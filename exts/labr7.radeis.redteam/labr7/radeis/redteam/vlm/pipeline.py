"""Red-team session engine — UI-agnostic per-sign orchestrator.

Drives: scene + platform + Spot + FPV camera + stations, the per-sign
state machine, per-station dwell + inference, and baseline-vs-attack
comparison. Both the headless harness and the Kit GUI window drive this same
engine; the CALLER owns render-pumping (``sim.update()`` headless /
``app.next_update_async()`` in the UI) so this module stays synchronous.

Flow:
    sess = RedTeamSession(stage, sidecar_url, cfg)
    sess.setup(assets_root); <timeline.play>; <warmup renders>; sess.start()
    for cat, sign_name, sign_data in signs:
        sess.assign_sign(cat, sign_name, sign_data)
        sess.begin_run()
        while not sess.lap_done:
            <pump one render>
            ev = sess.tick(dt)
            if ev["event"] == "dwell_start":
                <pump a few warmup renders>
                frame = sess.capture_fpv()
                sess.run_inference(ev["station"], frame)
    result = sess.compare_sign(sess.current_sign_key)
"""
from __future__ import annotations

import math
import datetime as _dt
from typing import Dict, List, Optional

from .. import constants as C
from ..report import metrics
from ..scene import scenes as S
from ..scene import stations as ST
from ..scene.platform_mount import Platform
from .sidecar_client import SidecarClient, rgb_to_b64


class RedTeamSession:
    def __init__(self, stage, sidecar_url: str, cfg: Optional[dict] = None):
        self.stage = stage
        self.cfg = {
            "scene_id": "patrol_loop",
            "mode": "vlm",
            "dwell_seconds": C.DWELL_SECONDS_DEFAULT,
            "traj_K": C.TRAJ_BIAS_K_DEFAULT,
            "speed": C.PLATFORM_SPEED_MPS,
            "system_prompt": None,
            "user_msg": None,
        }
        if cfg:
            self.cfg.update(cfg)
        self.client = SidecarClient(sidecar_url)
        self.scene = None
        self.route = None
        self.platform = None
        self.spot = None
        self.fpv = None
        self.stations: List[dict] = []
        self.records: Dict[str, Dict[int, dict]] = {}  # {sign_key: {station_idx: record}}
        # run state
        self.current_sign_key: Optional[str] = None
        self.arc = 0.0
        self._next_station = 0
        self._phase = "idle"        # idle|cruising|dwelling|returning|done
        self._dwell_t = 0.0
        self._inference_emitted = False
        self.lap_done = False
        # shared state applied by physics_step (physics rate) — tick (render
        # rate) only updates these so the Spot policy steps correctly per
        # physics step and the platform/pin stay glued.
        self._pose = (0.0, 0.0, 0.0)
        self._command = (0.0, 0.0, 0.0)
        self.log = print
        # Isaac 6.0 patrol-pacing fix (Regression B). On Isaac 6.0 the physics
        # scheduler runs a different number of physics steps per app update than
        # Isaac 5.1, which desyncs the app-frame-coupled patrol tick() from the
        # physics-coupled robot/pose apply → the platform advances ~3x slower per
        # recorded physics step. When _physics_coupled is True we advance the
        # patrol arc once per physics step instead (see tick()/physics_step()),
        # making the per-physics-step trajectory identical to Isaac 5.1 by
        # construction. Gated so Isaac 5.x keeps the exact original tick() path.
        try:
            from ..robot_control.spot_locomotion import _is_isaac6_eager_articulation
            self._physics_coupled = _is_isaac6_eager_articulation()
        except Exception:  # noqa: BLE001
            self._physics_coupled = False
        self._render_dt = 1.0 / 30.0   # per-physics-step arc quantum (set by tick)
        self._first_phys_step = True   # skip advance on run's 1st physics step
        self._dwell_started = False    # physics-coupled dwell-timing flag (6.0)
        self._emitted_station = -1     # last station tick() surfaced dwell_start

    # -- setup --
    def setup(self, assets_root: str, spot_driver=None, fpv_camera=None):
        self.scene = S.build_scene(self.stage, assets_root, self.cfg["scene_id"],
                                   ext_path=self.cfg.get("ext_path"),
                                   custom_usd_path=self.cfg.get("custom_scene_path"),
                                   n_stations_override=self.cfg.get("n_stations"))
        self.route = self.scene["route"]
        self.platform = Platform(self.stage).build()
        self.stations = ST.build_stations(self.stage, self.scene)
        # robot — use cfg["robot_usd"] to pick which robot to spawn
        if spot_driver is None:
            robot_usd = self.cfg.get("robot_usd", "")
            if robot_usd and "go2" in robot_usd.lower():
                from ..robot_control.spot_locomotion import Go2Driver
                spot_driver = Go2Driver(prim_path=C.ROBOT_ROOT_PATH, position=[0, 0, 0.4],
                                         usd_path=robot_usd)
            elif robot_usd:
                from ..robot_control.spot_locomotion import GenericUsdDriver
                spot_driver = GenericUsdDriver(
                    self.stage, robot_usd, C.ROBOT_ROOT_PATH, position=[0, 0, 0.8])
            else:
                from ..robot_control.spot_locomotion import SpotDriver
                spot_driver = SpotDriver(prim_path=C.ROBOT_ROOT_PATH, position=[0, 0, 0.8])
            spot_driver.spawn()
        self.spot = spot_driver
        if fpv_camera is None:
            from .frame_capture import FpvCamera
            fpv_camera = FpvCamera(C.FPV_CAMERA_PATH, C.FPV_WIDTH, C.FPV_HEIGHT)
        self.fpv = fpv_camera

    def start(self):
        """Call after timeline.play() + warmup renders."""
        if self.platform is not None:
            self.platform.initialize()
        if self.spot is not None:
            self.spot.initialize()
            self.platform.mount_robot(C.ROBOT_ROOT_PATH)
        self.fpv.initialize()

    # -- sign + run control --
    def reset_stations(self):
        """Reset all station signs to blank grey (no texture)."""
        from ..scene import stations as ST
        if self.stations and self.stage:
            ST.reset_all_stations(self.stage, self.stations)

    def assign_sign(self, cat: str, sign_name: str, sign_data: dict):
        """Assign one sign's baseline + attacks to the stations, reset records."""
        from ..scene import stations as ST
        sign_key = f"{cat}/{sign_name}"
        self.current_sign_key = sign_key
        self.records[sign_key] = {}
        ST.assign_sign(self.stations, sign_data)
        ST.apply_samples(self.stage, self.stations)

    def begin_run(self, render_dt: Optional[float] = None):
        """Call after assign_sign() to start a fresh run for one sign.

        ``render_dt`` (optional) seeds the Isaac-6.0 per-physics-step arc quantum
        so it is correct from the run's very first physics step (before the first
        tick() would otherwise set it). Ignored on Isaac 5.x. When omitted, the
        last value passed to tick() persists (defaults to 1/30, which the GUI and
        238/246 harness drives use); only the 8 render_dt=1/60 harness drives
        need this seed to be perfectly exact from step 0."""
        if render_dt is not None and self._physics_coupled:
            self._render_dt = render_dt
        self.arc = 0.0
        self._next_station = 0
        self._phase = "cruising"
        self._dwell_t = 0.0
        self._inference_emitted = False
        self.lap_done = False
        # Isaac 6.0 physics-coupled patrol state (no-op on Isaac 5.x)
        self._first_phys_step = True
        self._dwell_started = False
        self._emitted_station = -1
        x, y, h = self.route.sample(0.0)
        self._pose = (x, y, h)
        self._command = (0.0, 0.0, 0.0)

    def tick(self, dt: float) -> dict:
        """Advance logic one render frame. Updates target pose + command (the
        physics callback applies them). Returns {event, station, phase, progress}.

        Isaac 5.x: advances the patrol arc here (app-frame-coupled) — the exact
        original behavior. Isaac 6.0 (``_physics_coupled``): the arc is advanced
        once per *physics step* in physics_step() instead, so the per-physics-step
        platform trajectory is identical to Isaac 5.1 regardless of the version-
        dependent physics-steps-per-app-update ratio (root cause of the 6.0 ~3x
        slow-motion). Here we only record render_dt (the per-physics-step arc
        quantum) and surface the latest patrol event for the caller's inference.
        """
        if self._physics_coupled:
            self._render_dt = dt
            return self._peek_event()
        return self._advance(dt)

    def _advance(self, dt: float) -> dict:
        """Isaac 5.x patrol advance (app-frame-coupled). Original tick() body —
        do not alter: Isaac 5.x observable behavior must stay byte-identical."""
        ev = "cruising"
        station = -1
        n = len(self.stations)

        if self._phase == "cruising":
            target = (self.route.station_arcs[self._next_station]
                      if self._next_station < n else self.route.total)
            self.arc = min(self.arc + self.cfg["speed"] * dt, target)
            if self.arc >= target - 1e-3:
                if self._next_station < n:
                    self._phase = "dwelling"
                    self._dwell_t = 0.0
                    self._inference_emitted = False
                else:
                    self._phase = "done"
                    self.lap_done = True
        elif self._phase == "dwelling":
            station = self._next_station
            if not self._inference_emitted:
                ev = "dwell_start"
                self._inference_emitted = True
            else:
                ev = "dwelling"
                self._dwell_t += dt
                if self._dwell_t >= self.cfg["dwell_seconds"]:
                    self._next_station += 1
                    self._phase = "cruising"

        self._pose = self.route.sample(self.arc)
        # small forward bias while cruising → legs cycle; ~0 while dwelling
        self._command = (0.4, 0.0, 0.0) if self._phase == "cruising" else (0.0, 0.0, 0.0)
        return {"event": ev, "station": station, "phase": self._phase,
                "progress": (self.arc / self.route.total) if self.route.total else 0.0}

    def _step_arc(self, dt: float):
        """Isaac 6.0 patrol advance, driven once per *physics step*.

        Mirrors _advance()'s motion exactly (same arc quantum ``speed*dt``, same
        clamp, phase transitions and dwell duration) but emits no event — events
        are surfaced by _peek_event() from tick(). The dwell duration matches
        _advance() (which skips dwell_t accrual on the step that emits dwell_start)
        via the _dwell_started flag, so per-physics-step trajectories are identical
        to Isaac 5.1's.

        idle (fresh Build, before begin_run()): do nothing. physics_step()
        drives this method on every physics step regardless of phase, and the
        unconditional trailing ``self._pose = self.route.sample(self.arc)``
        would overwrite the (0,0,0) init pose with the route start point,
        teleporting the platform+robot there before Run Test is ever clicked.
        Isaac 5.x never hits this case: _advance() only runs from tick(),
        which the run loop calls exclusively while a run is active."""
        if self._phase == "idle":
            return
        n = len(self.stations)
        if self._phase == "cruising":
            target = (self.route.station_arcs[self._next_station]
                      if self._next_station < n else self.route.total)
            self.arc = min(self.arc + self.cfg["speed"] * dt, target)
            if self.arc >= target - 1e-3:
                if self._next_station < n:
                    self._phase = "dwelling"
                    self._dwell_t = 0.0
                    self._dwell_started = False
                else:
                    self._phase = "done"
                    self.lap_done = True
        elif self._phase == "dwelling":
            if not self._dwell_started:
                # mirror 5.1: the dwell_start step does not accrue dwell_t
                self._dwell_started = True
            else:
                self._dwell_t += dt
                if self._dwell_t >= self.cfg["dwell_seconds"]:
                    self._next_station += 1
                    self._phase = "cruising"
        self._pose = self.route.sample(self.arc)
        self._command = (0.4, 0.0, 0.0) if self._phase == "cruising" else (0.0, 0.0, 0.0)

    def _peek_event(self) -> dict:
        """Isaac 6.0: surface the current patrol event for the caller WITHOUT
        advancing motion (advance happens in physics_step). dwell_start is
        delivered exactly once per station entry (tracked by _emitted_station),
        so it is never lost to the physics/app-update rate mismatch."""
        progress = (self.arc / self.route.total) if self.route.total else 0.0
        if self._phase == "dwelling":
            station = self._next_station
            if self._emitted_station != station:
                self._emitted_station = station
                ev = "dwell_start"
            else:
                ev = "dwelling"
            return {"event": ev, "station": station, "phase": "dwelling",
                    "progress": progress}
        if self._phase == "cruising":
            return {"event": "cruising", "station": -1, "phase": "cruising",
                    "progress": progress}
        return {"event": self._phase, "station": -1, "phase": self._phase,
                "progress": progress}

    def physics_step(self, dt: float):
        """Apply platform pose, pin the robot, and step its policy. Register
        this on POST_PHYSICS_STEP so the locomotion policy steps correctly.

        Isaac 6.0 (``_physics_coupled``): also advance the patrol arc here, once
        per physics step, so the per-physics-step platform trajectory matches
        Isaac 5.1 exactly. The run's first physics step is skipped so its sample
        sits at the route origin (arc=0), mirroring Isaac 5.1 where tick()
        advances only *after* each recorded physics step; because the window's
        physics callback fires before the harness recording callback (both
        POST_PHYSICS_STEP, same order → registration order), the recorded target
        equals the pose applied this step. Isaac 5.x advances in tick() → this
        block is inert."""
        if self.platform is None:
            return
        if self._physics_coupled:
            if self._first_phys_step:
                self._first_phys_step = False
            else:
                self._step_arc(self._render_dt)
        x, y, h = self._pose
        self.platform.set_pose(x, y, h)
        if self.spot is not None and self.spot.root is not None:
            self.platform.pin_robot(self.spot.root, x, y, h)
            try:
                self.spot.step(dt, self._command)
            except Exception as e:  # noqa: BLE001
                self.log(f"[pipeline] spot.step error: {e}")

    # -- capture + inference --
    def capture_fpv(self):
        return self.fpv.capture()

    def run_inference(self, station_idx: int, frame_rgb) -> dict:
        st = self.stations[station_idx]
        bbox = st.get("station_bbox")
        res = self.client.infer(
            frame_rgb,
            system_prompt=self.cfg.get("system_prompt"),
            user_msg=self.cfg.get("user_msg"),
            mode=self.cfg["mode"],
            want_attention=True, want_layer_stack=True,
            station_bbox=bbox,
        )
        # capture a trajectory sample (robot base pose) so VLA-mode metrics have
        # data to work with; on rails this is currently a single point.
        traj = None
        try:
            if self.spot is not None:
                bp = self.spot.base_pose()
                if bp is not None:
                    traj = [list(bp[0][:2])]
        except Exception:  # noqa: BLE001
            traj = None
        rec = {
            "station": station_idx,
            "role": (st.get("sample") or {}).get("role"),
            "attack_id": (st.get("sample") or {}).get("attack_id"),
            "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "action_token": res.action_token,
            "decode_fallback": res.decode_fallback,
            "logit_margin": res.logit_margin,
            "aram": res.aram, "tram": res.tram,
            "heatmap": res.heatmap, "patch_grid": res.patch_grid,
            "peaks_2d": res.peaks_2d, "layer_stack": res.layer_stack,
            "image_wh": res.image_wh or [C.FPV_WIDTH, C.FPV_HEIGHT],
            "frame_b64": rgb_to_b64(frame_rgb) if frame_rgb is not None else None,
            "error": res.error,
            "station_bbox": bbox,
            "traj": traj,
            "sample": st.get("sample"),
            "infer_ms":    res.infer_ms,
            "raw_text":    res.raw_text,
            "logits_top5": res.logits_top5,
        }
        self.records[self.current_sign_key][station_idx] = rec
        if res.decode_fallback:
            self.log(f"[pipeline] WARNING sign={self.current_sign_key} station={station_idx} "
                     f"decode_fallback=True — VLM output unrecognized, coerced to Idle")
        self.log(f"[pipeline] sign={self.current_sign_key} station={station_idx} "
                 f"action={res.action_token} aram={res.aram} err={res.error}")
        return rec

    def compare_sign(self, sign_key: str) -> dict:
        """Compare station 0 (baseline) vs stations 1..N (attacks) for one sign run."""
        station_records = self.records.get(sign_key, {})
        baseline_rec = station_records.get(0)
        attacks = {k: v for k, v in station_records.items() if k > 0}
        divergences = []
        for attack_idx, attack_rec in sorted(attacks.items()):
            def _ok(r):
                return (bool(r) and not r.get("error")
                        and r.get("action_token") is not None
                        and not r.get("decode_fallback", False))
            if not (_ok(baseline_rec) and _ok(attack_rec)):
                continue
            d = metrics.station_divergence(baseline_rec, attack_rec, "vlm", self.cfg.get("traj_K", 0.5))
            d["station"] = attack_idx
            d["attack_id"] = attack_rec.get("attack_id")
            divergences.append(d)
        n_expected = len(self.stations) - 1  # exclude baseline station 0
        agg = metrics.aggregate(divergences, n_expected=n_expected, n_incomplete=0)
        return {
            "sign_key": sign_key,
            "divergences": divergences,
            "aggregate": agg,
            "records": station_records,
            "stations": self.stations,
            "config": {
                "n_stations": len(self.stations),
                "sign_key": sign_key,
            }
        }

"""FPV camera frame capture for IsaacSim 6.0.

Wraps ``isaacsim.sensors.camera.Camera`` (validated: ``get_rgba()`` returns a
fully-rendered (H,W,4) uint8 array offscreen, even headless) with an
``omni.replicator.core`` render-product fallback. The camera prim is a child of
the moving platform so it tracks the platform automatically.

Imports are guarded so the extension still loads on a Kit build lacking the
sensor module; the error surfaces only when capture is actually attempted.
"""
from __future__ import annotations

from typing import Optional

import numpy as np


class FpvCamera:
    def __init__(self, prim_path: str, width: int = 640, height: int = 480):
        self.prim_path = prim_path
        self.width = width
        self.height = height
        self._cam = None
        self._annot = None
        self._rp = None
        self._mode = None  # "sensor" | "replicator"

    def initialize(self) -> str:
        """Create the capture backend. Call after the camera prim exists and the
        timeline is playing. Returns the backend mode used."""
        try:
            from isaacsim.sensors.camera import Camera
            self._cam = Camera(prim_path=self.prim_path,
                               resolution=(self.width, self.height))
            self._cam.initialize()
            self._mode = "sensor"
            return self._mode
        except Exception as e:  # noqa: BLE001
            print(f"[frame_capture] Camera sensor unavailable ({e}); trying replicator")
        try:
            import omni.replicator.core as rep
            rp = rep.create.render_product(self.prim_path, (self.width, self.height))
            self._rp = rp
            self._annot = rep.AnnotatorRegistry.get_annotator("rgb")
            self._annot.attach(rp)
            self._mode = "replicator"
            return self._mode
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"No camera capture backend available: {e}")

    def destroy(self):
        """Release the capture backend. Call before rebuilding the scene.

        isaacsim Camera instances are never torn down on their own: each keeps
        a per-frame _data_acquisition_callback registered and an "rgb"
        annotator attached to the shared render product. Stale instances from
        previous Builds poison capture for the next session (observed live on
        Isaac 6.0: every capture raises "Annotator rgb is not attached to any
        render products", which aborts the whole run). The replicator render
        product is also destroyed here, otherwise it leaks under
        /Render/OmniverseKit/HydraTextures/Replicator and a later rebuild
        leaves Hydra holding a stale reference to it.

        The "sensor" backend (isaacsim.sensors.camera.Camera) needs extra care:
        vendor Camera.destroy() detaches annotators and destroys the render
        product, but it never unsubscribes the internal per-frame
        _data_acquisition_callback. Worse, its _timer_reset_callback survives
        destroy() and RE-SUBSCRIBES that callback the next time the timeline
        gets a PLAY event (Radeis calls tl.play() on every Build), silently
        re-arming a camera object we're about to discard and racing a
        KeyError avalanche in _data_acquisition_callback once the underlying
        render product is gone. So before destroy() we explicitly pause() the
        camera (the vendor's public unsubscribe) and null out its private
        timer/stage callback refs and fabric time annotator. These are
        private vendor attributes with no public unsubscribe API, so each
        step is defensive (getattr/hasattr-guarded) and wrapped in its own
        try/except in case a future isaacsim version renames them."""
        if self._cam is not None:
            try:
                if hasattr(self._cam, "pause"):
                    self._cam.pause()
            except Exception:  # noqa: BLE001
                pass
            try:
                if hasattr(self._cam, "_timer_reset_callback"):
                    self._cam._timer_reset_callback = None
            except Exception:  # noqa: BLE001
                pass
            try:
                if hasattr(self._cam, "_stage_open_callback"):
                    self._cam._stage_open_callback = None
            except Exception:  # noqa: BLE001
                pass
            try:
                _fta = getattr(self._cam, "_fabric_time_annotator", None)
                if _fta is not None:
                    if hasattr(_fta, "detach"):
                        _fta.detach()
                    self._cam._fabric_time_annotator = None
            except Exception:  # noqa: BLE001
                pass
            try:
                self._cam.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._cam = None
        if self._annot is not None:
            try:
                self._annot.detach()
            except Exception:  # noqa: BLE001
                pass
            self._annot = None
        if self._rp is not None:
            try:
                self._rp.destroy()
            except Exception:  # noqa: BLE001
                try:
                    import omni.usd
                    path = self._rp.path if hasattr(self._rp, "path") else None
                    if path:
                        omni.usd.get_context().get_stage().RemovePrim(path)
                except Exception:  # noqa: BLE001
                    print("[frame_capture] Failed to release replicator render product")
            self._rp = None
        self._mode = None

    def capture(self) -> Optional[np.ndarray]:
        """Return the current frame as (H, W, 3) uint8, or None if not ready.

        The caller must have pumped a few render updates first (warm-up).
        """
        data = None
        if self._mode == "sensor" and self._cam is not None:
            data = self._cam.get_rgba() if hasattr(self._cam, "get_rgba") else self._cam.get_rgb()
        elif self._mode == "replicator" and self._annot is not None:
            data = self._annot.get_data()
        if data is None:
            return None
        rgb = np.asarray(data)
        if rgb.size == 0:
            return None
        if rgb.ndim == 3 and rgb.shape[2] == 4:
            rgb = rgb[:, :, :3]
        return np.ascontiguousarray(rgb.astype(np.uint8))

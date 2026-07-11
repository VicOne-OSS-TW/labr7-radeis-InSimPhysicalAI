"""Moving test platform + height-adaptive robot mount (IsaacSim 5/6).

The platform is a dynamic (non-kinematic) articulation root driven via
``isaacsim.core.experimental.prims.Articulation`` (Isaac 6.0) or the legacy
``isaacsim.core.prims.ArticulationView`` (Isaac 5.x).  FSD reads its position
from PhysX state — reliable across Build cycles because PhysX is fully reset by
``create_new_stage_async()``.

Isaac 6.0 NOTE: PhysX 5.x rejects ArticulationRootAPI on *kinematic* rigid
bodies (logs "articulation root will be ignored").  The platform is therefore a
*dynamic* rigid body; gravity acts on it but ``physics_step`` teleports it back
every frame via ``set_world_poses()``, which writes directly to PhysX state.

The FPV camera is a CHILD of the platform (so it tracks the platform's forward
direction automatically). The robot (Spot) is kept physics-live and *pinned* to
a fixed relative point on the deck each frame via ``Articulation.set_world_poses``
(teleport), so its body COM rides the platform while its legs keep cycling.

The vertical mount offset adapts to the robot's total height (via BBoxCache) so
the body sits at a fixed relative point regardless of which robot is loaded.
"""
from __future__ import annotations

import math
from typing import Optional, Tuple

import numpy as np
from pxr import Gf, Sdf, UsdGeom, UsdPhysics

from .. import constants as C


def _yaw_quat_wxyz(yaw: float):
    h = yaw * 0.5
    return (math.cos(h), 0.0, 0.0, math.sin(h))


class Platform:
    def __init__(self, stage, deck_size: Tuple[float, float] = (1.4, 1.0),
                 deck_thickness: float = 0.08, cam_height: float = 0.7,
                 cam_forward: float = 0.55):
        self.stage = stage
        self.deck_size = deck_size
        self.deck_thickness = deck_thickness
        self.cam_height = cam_height
        self.cam_forward = cam_forward
        self.body_z = 0.8           # set by mount_robot()
        self._xform_t = None
        self._xform_o = None
        self._art_view = None       # ArticulationView, init after tl.play()

    # ---- build ----
    def build(self):
        stage = self.stage
        # UsdGeom.Xform.Define is idempotent — safe to call on existing prim.
        root = UsdGeom.Xform.Define(stage, Sdf.Path(C.PLATFORM_PRIM_PATH))
        prim = root.GetPrim()
        # translate + orient ops (kept for replicator/inference USD capture)
        xf = UsdGeom.Xformable(prim)
        xf.ClearXformOpOrder()
        self._xform_t = xf.AddTranslateOp()
        self._xform_o = xf.AddOrientOp()
        self._xform_t.Set(Gf.Vec3d(0, 0, 0))
        self._xform_o.Set(Gf.Quatf(1, 0, 0, 0))
        self._art_view = None  # reset; re-acquired in initialize() after tl.play()

        # Dynamic (non-kinematic) articulation root.
        # PhysX 5.x forbids ArticulationRootAPI on kinematic bodies, so we use a
        # dynamic body instead.  Gravity acts on it, but physics_step() teleports
        # it back every frame via set_world_poses() → PhysX state → FSD renders.
        if not prim.HasAPI(UsdPhysics.ArticulationRootAPI):
            UsdPhysics.ArticulationRootAPI.Apply(prim)
        UsdPhysics.RigidBodyAPI.Apply(prim)
        # NOTE: do NOT set kinematic=True — PhysX 5.x ignores ArticulationRootAPI
        # on kinematic bodies and logs a warning.

        # visual deck (no collision — only root has physics)
        deck = UsdGeom.Cube.Define(stage, Sdf.Path(C.PLATFORM_PRIM_PATH + "/deck"))
        dxf = UsdGeom.Xformable(deck.GetPrim())
        dxf.ClearXformOpOrder()   # idempotent: don't stack ops on rebuild
        dxf.AddTranslateOp().Set(Gf.Vec3d(0, 0, self.deck_thickness * 0.5))
        dxf.AddScaleOp().Set(Gf.Vec3f(self.deck_size[0] * 0.5,
                                      self.deck_size[1] * 0.5,
                                      self.deck_thickness * 0.5))
        deck.GetDisplayColorAttr().Set([(0.15, 0.16, 0.20)])

        # FPV camera child — at front of deck, head height, looking +X (forward)
        cam = UsdGeom.Camera.Define(stage, Sdf.Path(C.FPV_CAMERA_PATH))
        cxf = UsdGeom.Xformable(cam.GetPrim())
        cxf.ClearXformOpOrder()   # idempotent on rebuild
        cxf.AddTranslateOp().Set(Gf.Vec3d(self.cam_forward, 0.0, self.cam_height))
        cxf.AddRotateXYZOp().Set(Gf.Vec3f(90.0, 0.0, -90.0))   # look +X
        cam.GetFocalLengthAttr().Set(20.0)
        cam.GetClippingRangeAttr().Set(Gf.Vec2f(0.05, 1.0e6))
        return self

    # ---- post-play init (call from sess.start() after tl.play()) ----
    def initialize(self):
        """Create Articulation wrapper after timeline.play().

        Isaac 6.0: ``isaacsim.core.experimental.prims.Articulation`` (note:
        NOT ArticulationView).  Auto-initialises its physics tensor entity if
        SimulationManager._physics_sim_view__warp is already set (i.e. after
        tl.play() + warmup frames).

        Isaac 5.x fallback: ``isaacsim.core.prims.ArticulationView`` with the
        old prim_paths_expr / name kwargs and explicit .initialize().
        """
        try:
            from isaacsim.core.experimental.prims import Articulation
            # Articulation auto-inits physics tensor if physics is already running.
            self._art_view = Articulation(C.PLATFORM_PRIM_PATH)
            print(f"[platform_mount] Articulation created "
                  f"(tensor_init={self._art_view.is_physics_tensor_entity_initialized})")
        except Exception as e:  # noqa: BLE001
            print(f"[platform_mount] Articulation (experimental) failed: {e}, "
                  f"falling back to ArticulationView")
            try:
                from isaacsim.core.prims import ArticulationView
                self._art_view = ArticulationView(
                    prim_paths_expr=C.PLATFORM_PRIM_PATH,
                    name="platform_articulation",
                )
                self._art_view.initialize()
            except Exception as e2:  # noqa: BLE001
                print(f"[platform_mount] ArticulationView fallback also failed: {e2}")
                self._art_view = None

    # ---- height-adaptive mount ----
    def mount_robot(self, robot_root_path: str, stand_height_hint: float = 0.55):
        """Compute the body-fix Z so the robot body rides at a fixed relative
        point on the deck, adapting to the robot's height."""
        deck_top = self.deck_thickness
        h = stand_height_hint
        try:
            cache = UsdGeom.BBoxCache(0, [UsdGeom.Tokens.default_])
            prim = self.stage.GetPrimAtPath(Sdf.Path(robot_root_path))
            if prim and prim.IsValid():
                rng = cache.ComputeWorldBound(prim).ComputeAlignedRange()
                size = rng.GetMax() - rng.GetMin()
                if size[2] > 0.05:
                    h = float(size[2]) * 0.55   # body COM ~ 55% of total height
        except Exception:  # noqa: BLE001
            pass
        self.body_z = deck_top + h
        return self.body_z

    # ---- per-frame ----
    def set_pose(self, x: float, y: float, yaw: float, z: float = 0.0):
        w, qx, qy, qz = _yaw_quat_wxyz(yaw)
        # USD-layer write (needed by replicator/inference capture).
        self._xform_t.Set(Gf.Vec3d(float(x), float(y), float(z)))
        self._xform_o.Set(Gf.Quatf(w, qx, qy, qz))
        # ArticulationView.set_world_poses() — same path as Spot/Go2 teleport.
        # Reliable across Build cycles: PhysX state resets with each new stage.
        if self._art_view is None:
            return
        try:
            pos = np.array([[float(x), float(y), float(z)]], dtype=np.float32)
            quat = np.array([[w, qx, qy, qz]], dtype=np.float32)
            self._art_view.set_world_poses(positions=pos, orientations=quat)
        except Exception as e:  # noqa: BLE001
            print(f"[platform_mount] set_world_poses failed: {e}")

    def pin_robot(self, spot_root, x: float, y: float, yaw: float,
                  rel_offset: Tuple[float, float] = (0.0, 0.0)):
        """Teleport the robot articulation root to the deck mount point."""
        if spot_root is None:
            return
        c, s = math.cos(yaw), math.sin(yaw)
        wx = x + rel_offset[0] * c - rel_offset[1] * s
        wy = y + rel_offset[0] * s + rel_offset[1] * c
        pos = np.array([[wx, wy, self.body_z]], dtype=np.float32)
        w, qx, qy, qz = _yaw_quat_wxyz(yaw)
        quat = np.array([[w, qx, qy, qz]], dtype=np.float32)
        try:
            if hasattr(spot_root, "set_world_poses"):
                # ArticulationView API (Isaac Sim 6.x)
                spot_root.set_world_poses(positions=pos, orientations=quat)
            else:
                # SingleArticulation API (Isaac Sim 5.x)
                spot_root.set_world_pose(position=pos[0], orientation=quat[0])
        except Exception as e:  # noqa: BLE001
            print(f"[platform_mount] pin_robot failed: {e}")

"""Boston Dynamics Spot locomotion driver (IsaacSim 6.0).

Thin wrapper over ``isaacsim.robot.policy.examples.robots.spot.SpotFlatTerrainPolicy``
(validated: forward command produces real walking). Keeps Spot "alive" — legs
cycle each physics step — so the robot isn't a static prop on the platform.
``platform_mount`` pins its root to the platform each frame.
"""
from __future__ import annotations

import inspect
from typing import List, Optional, Tuple

import numpy as np


def _is_isaac6_eager_articulation() -> bool:
    """True on Isaac Sim 6.0, False on Isaac 5.x.

    Discriminator: Isaac 5.x's ``PolicyController.__init__`` takes a ``name``
    argument (and wraps the robot in the *lazy* ``SingleArticulation``); Isaac
    6.0's dropped ``name`` (and wraps it in the *eager* experimental
    ``Articulation``). This is the same capability check ``go2_policy`` uses for
    its super() shim, and it is the behaviour that actually differs — unlike the
    ``isaacsim.core.experimental.prims`` package, which exists on both versions.
    """
    try:
        from isaacsim.robot.policy.examples.controllers import PolicyController
        return "name" not in inspect.signature(PolicyController.__init__).parameters
    except Exception:  # noqa: BLE001
        return False


class SpotDriver:
    def __init__(self, prim_path: str = "/World/platform/robot",
                 position: Optional[List[float]] = None):
        self.prim_path = prim_path
        self.position = position or [0.0, 0.0, 0.8]
        self.spot = None
        self._torch = None

    def spawn(self):
        from isaacsim.robot.policy.examples.robots.spot import SpotFlatTerrainPolicy
        self.spot = SpotFlatTerrainPolicy(prim_path=self.prim_path, position=self.position)
        import torch
        self._torch = torch
        return self

    def initialize(self):
        """Call after timeline.play() + a few warm-up updates."""
        self.spot.initialize()

    def step(self, dt: float, command=(0.3, 0.0, 0.0)):
        """Advance the policy one physics step.

        command = (v_x, v_y, w_z). A small forward bias keeps the legs visibly
        cycling (treadmill effect once the root is pinned by platform_mount).
        """
        cmd = self._torch.tensor(list(command), dtype=self._torch.float32)
        self.spot.forward(dt, cmd)

    def base_pose(self) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        """Return (xyz, quat_wxyz) of Spot's root, or None."""
        try:
            import warp as wp
            pos, quat = self.spot.robot.get_world_poses()
            return (np.asarray(wp.to_torch(pos).cpu()).reshape(-1)[:3],
                    np.asarray(wp.to_torch(quat).cpu()).reshape(-1)[:4])
        except Exception:  # noqa: BLE001
            return None

    @property
    def root(self):
        """The experimental Articulation (for set_world_poses pinning)."""
        return self.spot.robot if self.spot is not None else None


class Go2Driver:
    """Unitree Go2 locomotion driver backed by GO2FlatTerrainPolicy.

    Mirrors the SpotDriver API so pipeline.py can use it identically.
    Policy files default to the bundled copies in data/go2_policy/; pass
    explicit paths to override (e.g. for a custom-trained policy).
    """

    def __init__(self, prim_path: str = "/World/platform/robot",
                 position: Optional[List[float]] = None,
                 policy_path: Optional[str] = None,
                 env_config_path: Optional[str] = None,
                 usd_path: Optional[str] = None):
        self.prim_path = prim_path
        self.position = position or [0.0, 0.0, 0.4]
        self.policy_path = policy_path
        self.env_config_path = env_config_path
        self.usd_path = usd_path
        self.go2 = None
        self._torch = None

    def spawn(self):
        import os
        # locate bundled policy files relative to this file
        _here = os.path.dirname(__file__)
        _data = os.path.normpath(os.path.join(_here, "..", "..", "..", "..", "data", "go2_policy"))
        policy_path = self.policy_path or os.path.join(_data, "policy.pt")
        env_config_path = self.env_config_path or os.path.join(_data, "env.yaml")
        # Resolve the robot USD. The vendored GO2FlatTerrainPolicy.__init__
        # defaults usd_path to a bogus local path ("/isaacsim/GO2/go2.usd")
        # when none is given, which silently resolves to nothing and leaves
        # an empty Xform at prim_path (no rigid bodies/ArticulationRootAPI).
        # Always supply a real Nucleus path here; fall back to the standard
        # Isaac/Robots layout used by SpotFlatTerrainPolicy if the caller
        # didn't provide one.
        usd_path = self.usd_path
        if not usd_path:
            try:
                from isaacsim.storage.native import get_assets_root_path
                ar = get_assets_root_path()
            except Exception:  # noqa: BLE001
                ar = None
            if ar:
                usd_path = ar + "/Isaac/Robots/Unitree/Go2/go2.usd"
        try:
            # Isaac Sim 6.0+ ships a native Go2FlatTerrainPolicy with no `name`
            # param; prefer it so we don't have to shim PolicyController's
            # version-dependent signature ourselves.
            from isaacsim.robot.policy.examples.robots.go2 import Go2FlatTerrainPolicy
        except ImportError:
            # 5.0/5.1 have no native Go2 support — use the vendored copy.
            from .go2_policy import GO2FlatTerrainPolicy as Go2FlatTerrainPolicy
        kwargs = dict(
            prim_path=self.prim_path,
            position=np.array(self.position),
            policy_path=policy_path,
            env_config_path=env_config_path,
        )
        if usd_path and "usd_path" in inspect.signature(Go2FlatTerrainPolicy.__init__).parameters:
            kwargs["usd_path"] = usd_path
        # Isaac 6.0 only: materialize the robot articulation on the USD stage
        # *before* the policy controller constructs its eager experimental
        # Articulation (see _prematerialize_articulation). No-op on Isaac 5.x.
        self._prematerialize_articulation(usd_path)
        self.go2 = Go2FlatTerrainPolicy(**kwargs)
        import torch
        self._torch = torch
        return self

    def _prematerialize_articulation(self, usd_path):
        """Isaac-6.0 fix: reference the robot USD onto ``prim_path`` and make
        sure an ArticulationRootAPI prim is composed *before* the policy
        controller wraps it in the eager experimental ``Articulation``.

        Root cause (verified on the real Assets/Isaac/6.0 tree): 6.0 restructured
        ``Unitree/Go2/go2.usd`` into a variant-based shell whose DEFAULT variant
        selection is ``Physics="None"`` — a visual-only rig with *no* physics
        schemas at all. The articulation (``PhysicsArticulationRootAPI`` on
        ``<robot>/base``) only exists in the ``Physics="physx"`` variant (a
        payload of ``configuration/go2_description_physics.usd``). Referencing
        with defaults therefore composes no articulation root anywhere, so 6.0's
        eager ``Articulation.fetch_articulation_root_api_prim_paths`` returns
        ``[None]`` → ``Sdf.Path.IsValidPathString(NoneType)`` — the extension
        swallows it and continues half-built (no physics callback → Go2 freeze).
        Native 6.0 ``spot.usd`` is still a flat asset with the API authored
        directly on its root prim, which is why Spot never hit this. (The fetch
        runs on the synchronous ``usd`` backend by default, so this is a pure
        composition issue — not a Fabric/usdrt sync race.)

        Fix: reference the asset via raw ``pxr`` (synchronous composition), and
        if the composed subtree has no ArticulationRootAPI but exposes a
        ``Physics`` variantSet with a ``physx`` option, select it and load its
        payload. Old flat assets (5.1-era layout, incl. local go2.usd copies)
        already compose the API and are left untouched. The controller then sees
        a valid prim, skips its own reference-add, and its eager fetch resolves
        ``<robot>/base``.

        Version-gated on the same discriminator ``go2_policy`` uses: Isaac 5.x's
        ``PolicyController.__init__`` takes a ``name`` param and wraps the robot
        in the lazy ``SingleArticulation`` (never crashes here); Isaac 6.0's does
        not and wraps it in the eager experimental ``Articulation``. Only the
        latter enters this block → Isaac 5.x behavior is unchanged.
        (Note: ``isaacsim.core.experimental.prims`` exists on *both* versions, so
        it cannot be used as the version marker.)
        """
        if not usd_path:
            return
        if not _is_isaac6_eager_articulation():
            return  # Isaac 5.x — lazy SingleArticulation, no pre-materialization
        try:
            import omni.usd
            from pxr import Usd, UsdPhysics
            stage = omni.usd.get_context().get_stage()
            if stage is None:
                return
            prim = stage.GetPrimAtPath(self.prim_path)
            if prim and prim.IsValid():
                # rebuild safety: drop any stale reference before re-adding
                prim.GetReferences().ClearReferences()
            else:
                prim = stage.DefinePrim(self.prim_path, "Xform")
            prim.GetReferences().AddReference(usd_path)
            prim.Load(Usd.LoadWithDescendants)  # force-load any deferred payloads

            def _has_articulation_root():
                stack = [prim]
                while stack:
                    p = stack.pop(0)
                    if p.HasAPI(UsdPhysics.ArticulationRootAPI):
                        return True
                    stack.extend(p.GetChildren())
                return False

            if not _has_articulation_root():
                # 6.0 variant-based asset: physics lives in Physics="physx"
                vsets = prim.GetVariantSets()
                if "Physics" in vsets.GetNames():
                    pv = vsets.GetVariantSet("Physics")
                    if "physx" in pv.GetVariantNames():
                        pv.SetVariantSelection("physx")
                        prim.Load(Usd.LoadWithDescendants)  # physics payload
                if not _has_articulation_root():
                    print(f"[spot_locomotion] Go2 pre-materialize: no "
                          f"ArticulationRootAPI composed under {self.prim_path} "
                          f"(usd_path={usd_path}) — policy wrap will likely fail")
        except Exception as e:  # noqa: BLE001
            print(f"[spot_locomotion] Go2 pre-materialize failed: {e}")

    def initialize(self):
        """Call after timeline.play() + a few warm-up updates."""
        self.go2.initialize()

    def step(self, dt: float, command=(0.3, 0.0, 0.0)):
        """Advance the policy one physics step.

        command = (v_x, v_y, w_z).
        """
        cmd = self._torch.tensor(list(command), dtype=self._torch.float32)
        self.go2.forward(dt, cmd)

    def base_pose(self) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        """Return (xyz, quat_wxyz) of Go2's root, or None."""
        try:
            import warp as wp
            pos, quat = self.go2.robot.get_world_poses()
            return (np.asarray(wp.to_torch(pos).cpu()).reshape(-1)[:3],
                    np.asarray(wp.to_torch(quat).cpu()).reshape(-1)[:4])
        except Exception:  # noqa: BLE001
            return None

    @property
    def root(self):
        """The Articulation used by platform_mount.pin_robot()."""
        return self.go2.robot if self.go2 is not None else None


class GenericUsdDriver:
    """Visual-only driver for non-Spot robots.

    Loads a USD reference at *prim_path*, disables all physics via the session
    layer, and acts as its own Xform proxy so platform_mount.pin_robot() can
    teleport it each frame via the standard set_world_poses() call.
    """

    def __init__(self, stage, usd_path: str, prim_path: str,
                 position: Optional[List[float]] = None):
        self.stage = stage
        self.usd_path = usd_path
        self.prim_path = prim_path
        self.position = position or [0.0, 0.0, 0.8]
        self._xform_t = None
        self._xform_o = None
        self._fab_hierarchy = None   # legacy Isaac 5.x fallback
        self._xform_prim = None      # isaacsim.core.experimental.prims.XformPrim (Isaac 6.0)

    def spawn(self):
        from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics
        stage = self.stage
        # WORKAROUND (Isaac 6.0 FSD): keep the prim alive instead of
        # Remove+Recreate.  Removing a prim invalidates its Fabric entry and
        # all subsequent transform writes are silently ignored.
        # Clear existing references first, then re-add — prim identity preserved.
        existing = stage.GetPrimAtPath(self.prim_path)
        if existing.IsValid():
            existing.GetReferences().ClearReferences()
            prim = existing
        else:
            prim = stage.DefinePrim(self.prim_path, "Xform")
        prim.GetReferences().AddReference(self.usd_path)
        xf = UsdGeom.Xformable(prim)
        xf.ClearXformOpOrder()
        xf.SetResetXformStack(True)
        self._xform_t = xf.AddTranslateOp(UsdGeom.XformOp.PrecisionDouble)
        self._xform_o = xf.AddOrientOp(UsdGeom.XformOp.PrecisionDouble)
        self._xform_t.Set(Gf.Vec3d(*self.position))
        self._xform_o.Set(Gf.Quatd(1, 0, 0, 0))
        # suppress physics in the session layer (strongest override)
        session = stage.GetSessionLayer()
        prefix = self.prim_path + "/"
        for p in stage.TraverseAll():
            path = str(p.GetPath())
            if path != self.prim_path and not path.startswith(prefix):
                continue
            if p.HasAPI(UsdPhysics.RigidBodyAPI):
                with Usd.EditContext(stage, session):
                    a = p.GetAttribute("physics:rigidBodyEnabled")
                    if not (a and a.IsValid()):
                        a = p.CreateAttribute(
                            "physics:rigidBodyEnabled", Sdf.ValueTypeNames.Bool)
                    a.Set(False)
            if ("Joint" in p.GetTypeName()
                    or p.HasRelationship("physics:body0")
                    or p.HasRelationship("physics:body1")):
                with Usd.EditContext(stage, session):
                    p.SetTypeName("Xform")
            if p.HasAPI(UsdPhysics.ArticulationRootAPI):
                with Usd.EditContext(stage, session):
                    p.RemoveAPI(UsdPhysics.ArticulationRootAPI)
        return self

    def initialize(self):
        pass

    def step(self, dt: float, command=(0.0, 0.0, 0.0)):
        pass

    def base_pose(self):
        return None

    # --- articulation-proxy API used by platform_mount.pin_robot ---
    def set_world_poses(self, positions, orientations):
        import numpy as np
        from pxr import Gf
        pos3 = None
        quat4 = None
        if positions is not None and len(positions):
            p = positions[0]
            pos3 = (float(p[0]), float(p[1]), float(p[2]))
            self._xform_t.Set(Gf.Vec3d(*pos3))
        if orientations is not None and len(orientations):
            q = orientations[0]  # wxyz
            quat4 = (float(q[0]), float(q[1]), float(q[2]), float(q[3]))
            self._xform_o.Set(Gf.Quatd(*quat4))
        # Isaac 6.0: use XformPrim.set_world_poses() which reads the existing
        # Fabric matrix first (get_world_xform → modify → set_world_xform).
        # This is the same path used internally by Isaac's own experimental prims
        # and correctly registers new prims in the Fabric hierarchy before writing.
        # Previous approach (IFabricHierarchy directly + update_world_xforms) was
        # unreliable on 2nd+ Build because it bypassed the read-then-write cycle.
        try:
            from isaacsim.core.experimental.prims import XformPrim
            if self._xform_prim is None:
                self._xform_prim = XformPrim(self.prim_path)
            pos_np = np.array([[*pos3]], dtype=np.float32) if pos3 is not None else None
            quat_np = np.array([[*quat4]], dtype=np.float32) if quat4 is not None else None
            self._xform_prim.set_world_poses(positions=pos_np, orientations=quat_np)
            return
        except Exception as e:  # noqa: BLE001
            print(f"[spot_locomotion] GenericUsdDriver XformPrim failed: {e}")
            self._xform_prim = None
        # Isaac 5.x fallback: IFabricHierarchy direct write
        try:
            import usdrt
            if self._fab_hierarchy is None:
                from isaacsim.core.utils.stage import get_current_stage
                rt = get_current_stage(fabric=True)
                self._fab_hierarchy = usdrt.hierarchy.IFabricHierarchy().get_fabric_hierarchy(
                    rt.GetFabricId(), rt.GetStageIdAsStageId()
                )
            _pos  = pos3  if pos3  is not None else (0.0, 0.0, 0.0)
            _quat = quat4 if quat4 is not None else (1.0, 0.0, 0.0, 0.0)
            mat = self._fab_hierarchy.get_world_xform(usdrt.Sdf.Path(self.prim_path))
            mat.SetTranslateOnly(usdrt.Gf.Vec3d(*_pos))
            mat.SetRotateOnly(usdrt.Gf.Quatd(*_quat))
            self._fab_hierarchy.set_world_xform(usdrt.Sdf.Path(self.prim_path), mat)
        except Exception as e:  # noqa: BLE001
            print(f"[spot_locomotion] GenericUsdDriver IFabricHierarchy fallback failed: {e}")
            self._fab_hierarchy = None

    def set_world_pose(self, position, orientation):
        self.set_world_poses([position], [orientation])

    @property
    def root(self):
        """Return self as the pin target once spawned."""
        return self if self._xform_t is not None else None

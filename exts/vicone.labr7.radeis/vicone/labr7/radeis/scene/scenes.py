"""Built-in scenes + auto patrol-route generation for the red-team tester.

A scene defines a ground environment and a closed patrol loop. The route passes
through every test station and returns to origin. ``Route`` is a self-contained
arc-length-parameterised polyline (no dependency on the warehouse cart engine):
``sample(s)`` → (x, y, heading); station dwell points are evenly spaced arc
positions, and each station's sign is placed dead-ahead of the platform at that
dwell point (so the FPV sees it when stopped).
"""
from __future__ import annotations

import math
import os
from typing import Dict, List, Tuple

from pxr import Sdf, UsdGeom, UsdLux

from .. import constants as C

# Built-in scene registry.
# ``env``       — resolved against the IsaacSim asset root (CDN).
# ``env_local`` — relative to the extension's root (ext_path); takes priority.
# Both absent → bare ground plane.
SCENES: Dict[str, dict] = {
    "patrol_loop": {
        "label": "Patrol Loop (grid)",
        "env": "/Isaac/Environments/Grid/default_environment.usd",
        "loop": (12.0, 9.0),     # 1.5× scaled from original (8.0, 6.0)
        "corner_r": 2.25,        # 1.5× scaled from 1.5
        "n_stations": 8,         # doubled from 4
        "sign_distance": 2.2,    # how far ahead of the dwell point the sign sits
        "sign_height": 0.7,      # sign centre height (≈ FPV cam height)
    },
    "warehouse": {
        "label": "Warehouse",
        "env": "/Isaac/Environments/Simple_Warehouse/warehouse.usd",
        "loop": (12.0, 9.0),
        "corner_r": 2.25,
        "n_stations": 8,
        "sign_distance": 2.2,
        "sign_height": 0.7,
    },
    "custom": {
        "label": "Customized Scene (currently unavailable)",
        "loop": (12.0, 9.0),
        "corner_r": 2.25,
        "n_stations": 8,
        "sign_distance": 2.2,
        "sign_height": 0.7,
    },
}


class Route:
    """Closed arc-length-parameterised loop with evenly spaced station dwells."""

    def __init__(self, pts: List[Tuple[float, float]], n_stations: int):
        self.pts = pts
        self._cum = [0.0]
        for i in range(1, len(pts)):
            d = math.dist(pts[i], pts[i - 1])
            self._cum.append(self._cum[-1] + d)
        self.total = self._cum[-1]
        # station dwell arc positions (offset so they avoid the start seam)
        self.station_arcs = [self.total * (k + 0.5) / n_stations
                             for k in range(n_stations)]

    def sample(self, s: float) -> Tuple[float, float, float]:
        """Return (x, y, heading) at arc-length s (wrapped into [0,total))."""
        s = s % self.total
        # find segment
        lo, hi = 0, len(self._cum) - 1
        while lo < hi - 1:
            mid = (lo + hi) // 2
            if self._cum[mid] <= s:
                lo = mid
            else:
                hi = mid
        seg_len = max(1e-6, self._cum[hi] - self._cum[lo])
        t = (s - self._cum[lo]) / seg_len
        x0, y0 = self.pts[lo]
        x1, y1 = self.pts[hi]
        x = x0 + (x1 - x0) * t
        y = y0 + (y1 - y0) * t
        heading = math.atan2(y1 - y0, x1 - x0)
        return x, y, heading


def _rounded_rect_loop(lx: float, ly: float, r: float, n: int = 240) -> List[Tuple[float, float]]:
    """Sample a centred rounded rectangle (closed) into n points."""
    hx, hy = lx / 2 - r, ly / 2 - r
    # straight + arc segment generators in CCW order
    corners = [(hx, hy, 0), (-hx, hy, math.pi / 2), (-hx, -hy, math.pi),
               (hx, -hy, 3 * math.pi / 2)]
    pts = []
    # build by walking edges + corner arcs
    seq = []
    for i in range(4):
        cx, cy, a0 = corners[i]
        # corner arc (quarter circle)
        for k in range(8):
            a = a0 + (math.pi / 2) * (k / 8.0)
            seq.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    # close
    seq.append(seq[0])
    # densify uniformly
    cum = [0.0]
    for i in range(1, len(seq)):
        cum.append(cum[-1] + math.dist(seq[i], seq[i - 1]))
    total = cum[-1]
    for j in range(n):
        s = total * j / n
        lo = 0
        while lo < len(cum) - 2 and cum[lo + 1] <= s:
            lo += 1
        seg = max(1e-6, cum[lo + 1] - cum[lo])
        t = (s - cum[lo]) / seg
        x = seq[lo][0] + (seq[lo + 1][0] - seq[lo][0]) * t
        y = seq[lo][1] + (seq[lo + 1][1] - seq[lo][1]) * t
        pts.append((x, y))
    pts.append(pts[0])
    return pts


def build_scene(stage, assets_root: str, scene_id: str = "patrol_loop",
                ext_path: str = None, custom_usd_path: str = None,
                n_stations_override: int = None) -> dict:
    """Create ground env + dome light. Returns the scene spec (+ Route).

    env resolution order:
      1. custom_usd_path (user-picked file, only used when scene_id == "custom")
      2. spec["env_local"] + ext_path  (bundled USD inside the extension)
      3. assets_root + spec["env"]     (CDN / Isaac asset root)
      4. bare ground plane fallback
    """
    spec = dict(SCENES[scene_id])
    if n_stations_override is not None and n_stations_override > 0:
        spec["n_stations"] = n_stations_override
    # dome light
    dome = UsdLux.DomeLight.Define(stage, Sdf.Path("/World/Dome"))
    dome.CreateIntensityAttr(800.0)
    # resolve ground environment path
    env_path = None
    if scene_id == "custom" and custom_usd_path:
        env_path = custom_usd_path
    elif spec.get("env_local") and ext_path:
        env_path = os.path.join(ext_path, spec["env_local"])
    elif spec.get("env") and assets_root:
        env_path = assets_root + spec["env"]

    if env_path:
        try:
            from pxr import Gf
            prim = UsdGeom.Xform.Define(stage, Sdf.Path("/World/ground")).GetPrim()
            scale = spec.get("scale", 1.0)
            if scale != 1.0:
                UsdGeom.Xformable(prim).AddScaleOp().Set(Gf.Vec3f(scale, scale, scale))
            prim.GetReferences().AddReference(env_path)
        except Exception as e:  # noqa: BLE001
            print(f"[scenes] ground env ref failed ({e}); using bare plane")
            _bare_ground(stage)
    else:
        _bare_ground(stage)

    lx, ly = spec["loop"]
    pts = _rounded_rect_loop(lx, ly, spec["corner_r"])
    spec["route"] = Route(pts, spec["n_stations"])
    _setup_viewport_camera(stage)
    return spec


def _setup_viewport_camera(stage):
    """Set /OmniverseKit_Persp to a fixed overview angle for the scene.

    Must go through TransformPrimSRT command — the viewport system continuously
    writes camera pose to the session layer, so direct Set() / EditContext are
    overridden immediately. The command routes through the viewport and sticks.
    """
    from pxr import Gf, UsdGeom as _UG
    import omni.kit.commands
    cam_prim = stage.GetPrimAtPath("/OmniverseKit_Persp")
    if not cam_prim.IsValid():
        return
    omni.kit.commands.execute(
        "TransformPrimSRT",
        path="/OmniverseKit_Persp",
        new_translation=Gf.Vec3d(9.19527, 7.15631, 8.65402),
        new_rotation_euler=Gf.Vec3f(54.73561, 0.0, 135.0),
        new_rotation_order=Gf.Vec3i(0, 1, 2),
        new_scale=Gf.Vec3f(1.0, 1.0, 1.0),
    )
    cam = _UG.Camera(cam_prim)
    cam.GetFocalLengthAttr().Set(18.14756)
    cam.GetFocusDistanceAttr().Set(400.0)
    cam.GetFStopAttr().Set(0.0)


def _bare_ground(stage):
    from pxr import Gf
    g = UsdGeom.Mesh.Define(stage, Sdf.Path("/World/ground_plane"))
    s = 30.0
    g.GetPointsAttr().Set([(-s, -s, 0), (s, -s, 0), (s, s, 0), (-s, s, 0)])
    g.GetFaceVertexCountsAttr().Set([4])
    g.GetFaceVertexIndicesAttr().Set([0, 1, 2, 3])
    g.GetDisplayColorAttr().Set([(0.3, 0.32, 0.36)])


def station_pose(route: Route, scene: dict, k: int):
    """Compute (dwell_xy, dwell_heading, sign_xyz, sign_yaw) for station k.

    The platform stops at the dwell point on the route; the sign is placed
    ``sign_distance`` ahead along the platform heading, at ``sign_height``,
    facing back toward the platform.
    """
    s_k = route.station_arcs[k]
    dx, dy, h = route.sample(s_k)
    d = scene["sign_distance"]
    sign_x = dx + d * math.cos(h)
    sign_y = dy + d * math.sin(h)
    sign_yaw = h + math.pi          # face back toward the platform
    return (dx, dy), h, (sign_x, sign_y, scene["sign_height"]), sign_yaw

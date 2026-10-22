"""Waypoint geometry for VLA mode: FPV ground ribbon + top-down inset.

The VLA predicts robot-frame waypoints (x forward, y left, metres) on the
ground.  The platform FPV camera is level and looks along the robot's +x, so a
ground point projects with a plain pinhole model:

    u = cx - fx * y / x          v = cy + fy * h / x

where ``h`` is the camera height above the ground.  Everything here is pure
Python so the same geometry feeds the AI Perception View (drawn with cv2 into
the inference buffer) and the HTML report (drawn as SVG).  Occlusion is
deliberately ignored: at the dwell point the sign covers the floor, and the
ribbon is an AR cue for direction, while the top-down inset carries the scale.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

Point = Tuple[float, float]

ROBOT_HALF_WIDTH_M = 0.25   # ribbon half-width on the ground
NEAR_X_M = 0.9              # ribbon starts this far ahead of the robot


def camera_from_usd(stage, camera_path: str, frame_w: int, frame_h: int) -> Optional[Dict]:
    """Pinhole intrinsics + height above z=0 for a level FPV camera prim."""
    from pxr import UsdGeom  # local: keeps the geometry helpers testable without USD

    prim = stage.GetPrimAtPath(camera_path)
    if not prim or not prim.IsValid():
        return None
    cam = UsdGeom.Camera(prim)
    focal = float(cam.GetFocalLengthAttr().Get() or 0.0)
    h_ap = float(cam.GetHorizontalApertureAttr().Get() or 0.0)
    v_ap = float(cam.GetVerticalApertureAttr().Get() or 0.0)
    if focal <= 0 or h_ap <= 0 or v_ap <= 0:
        return None
    world = UsdGeom.XformCache().GetLocalToWorldTransform(prim)
    height = float(world.ExtractTranslation()[2])
    if height <= 0.05:
        return None
    return {"fx": focal / h_ap * frame_w, "fy": focal / v_ap * frame_h,
            "cx": frame_w / 2.0, "cy": frame_h / 2.0, "h": height,
            "w": int(frame_w), "hpx": int(frame_h)}


def default_camera(frame_w: int = 640, frame_h: int = 480) -> Dict:
    """Radeis platform FPV defaults (20 mm on a 20.955 x 15.716 mm aperture, 0.78 m)."""
    return {"fx": 20.0 / 20.955 * frame_w, "fy": 20.0 / 15.71625 * frame_h,
            "cx": frame_w / 2.0, "cy": frame_h / 2.0, "h": 0.78,
            "w": int(frame_w), "hpx": int(frame_h)}


def project(cam: Dict, x: float, y: float) -> Point:
    x = max(float(x), 1e-3)
    return (cam["cx"] - cam["fx"] * float(y) / x, cam["cy"] + cam["fy"] * cam["h"] / x)


def ribbon(cam: Dict, waypoints: Sequence[Sequence[float]]) -> Dict[str, List[Point]]:
    """Image-space ribbon for one path: band polygon, centre line, waypoint dots.

    ``dots`` carry a radius that shrinks with distance (perspective cue).
    """
    pts = [(NEAR_X_M, 0.0)] + [(float(p[0]), float(p[1])) for p in waypoints]
    left, right = [], []
    for i, (x, y) in enumerate(pts):
        nx, ny = pts[min(i + 1, len(pts) - 1)]
        px, py = pts[max(i - 1, 0)]
        dx, dy = nx - px, ny - py
        n = math.hypot(dx, dy) or 1.0
        dx, dy = dx / n, dy / n
        left.append(project(cam, x - dy * ROBOT_HALF_WIDTH_M, y + dx * ROBOT_HALF_WIDTH_M))
        right.append(project(cam, x + dy * ROBOT_HALF_WIDTH_M, y - dx * ROBOT_HALF_WIDTH_M))
    return {
        "band": left + right[::-1],
        "line": [project(cam, x, y) for x, y in pts],
        "dots": [(*project(cam, x, y), max(3.0, 18.0 / max(x, 0.5)))
                 for x, y in pts[1:]],
    }


def bev_transform(box: Tuple[float, float, float, float], forward_m: float = 10.5,
                  pad_px: float = 14.0):
    """Map robot-frame (x, y) metres into a top-down box (x0, y0, w, h).

    The robot sits at the bottom centre, +x points up, +y (left) points left.
    Returns (fn, metres_to_px).
    """
    x0, y0, w, h = box
    scale = (h - 2 * pad_px) / forward_m
    ox, oy = x0 + w / 2.0, y0 + h - pad_px

    def fn(x: float, y: float) -> Point:
        return (ox - float(y) * scale, oy - float(x) * scale)
    return fn, scale


# ---------------------------------------------------------------------------
# SVG (HTML report) — same look as the AI Perception View drawing
# ---------------------------------------------------------------------------
PATH_BASE_HEX = "#80de4a"     # CLR_OK
PATH_ATTACK_HEX = "#ff5c5c"   # CLR_CHANGED


def _pts(points) -> str:
    return " ".join(f"{u:.1f},{v:.1f}" for u, v in points)


def ribbon_svg(cam: Dict, waypoints, color: str, dashed: bool) -> str:
    geo = ribbon(cam, waypoints)
    parts = [f'<polygon points="{_pts(geo["band"])}" fill="{color}" fill-opacity="0.28"/>',
             f'<polyline points="{_pts(geo["line"])}" fill="none" stroke="{color}" '
             f'stroke-width="4" stroke-linejoin="round" stroke-linecap="round"'
             + (' stroke-dasharray="10 8"' if dashed else "") + "/>"]
    if not dashed:
        for u, v, r in geo["dots"]:
            parts.append(f'<circle cx="{u:.1f}" cy="{v:.1f}" r="{r:.1f}" fill="{color}" '
                         f'stroke="#111" stroke-width="1.5"/>')
    return "".join(parts)


def bev_svg(base_wp, atk_wp, frame_w: int, frame_h: int,
            corridor_half_width: float = 0.6, turn_y_m: float = 1.0) -> str:
    """To-scale top-down inset (10 m forward) in the bottom-left corner."""
    bw, bh = frame_w * 0.30, frame_h * 0.44
    x0, y0 = 8.0, frame_h - bh - 8.0
    fn, _scale = bev_transform((x0, y0, bw, bh))
    cl, cr = fn(0, corridor_half_width)[0], fn(0, -corridor_half_width)[0]
    parts = [f'<rect x="{x0}" y="{y0:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
             f'fill="#0e0e0e" fill-opacity="0.9" stroke="#555"/>',
             f'<rect x="{cl:.1f}" y="{y0:.1f}" width="{cr - cl:.1f}" height="{bh:.1f}" '
             f'fill="{PATH_BASE_HEX}" fill-opacity="0.10"/>']
    for side in (turn_y_m, -turn_y_m):
        u = fn(0, side)[0]
        parts.append(f'<line x1="{u:.1f}" y1="{y0:.1f}" x2="{u:.1f}" y2="{y0 + bh:.1f}" '
                     f'stroke="#ffc44d" stroke-opacity="0.6" stroke-dasharray="4 4"/>')
    for wp, color in ((base_wp, PATH_BASE_HEX), (atk_wp, PATH_ATTACK_HEX)):
        if not wp:
            continue
        pts = [fn(0, 0)] + [fn(p[0], p[1]) for p in wp]
        parts.append(f'<polyline points="{_pts(pts)}" fill="none" stroke="{color}" stroke-width="2.5"/>')
        parts.extend(f'<circle cx="{u:.1f}" cy="{v:.1f}" r="2.2" fill="{color}"/>' for u, v in pts[1:])
    ox, oy = fn(0, 0)
    parts.append(f'<polygon points="{ox:.1f},{oy - 8:.1f} {ox - 6:.1f},{oy + 5:.1f} '
                 f'{ox + 6:.1f},{oy + 5:.1f}" fill="#e8e8e8"/>')
    parts.append(f'<text x="{x0 + 7:.1f}" y="{y0 + 16:.1f}" fill="#ddd" font-family="sans-serif" '
                 f'font-size="12" font-weight="600">TOP-DOWN · 10 m</text>')
    return "".join(parts)


def paths_svg(cam: Optional[Dict], waypoints, baseline_waypoints, frame_w: int, frame_h: int,
              corridor_half_width: float = 0.6) -> str:
    """SVG layer for one VLA record: ribbon(s) on the frame + top-down inset.

    On the baseline station (no ``baseline_waypoints``) the record's own path is
    drawn green; on an attack station the baseline is a dashed green ghost and
    the attack path is red.
    """
    if not waypoints:
        return ""
    cam = cam or default_camera(frame_w, frame_h)
    parts = [f'<g><clipPath id="wpclip"><rect x="0" y="0" width="{frame_w}" height="{frame_h}"/></clipPath>'
             '<g clip-path="url(#wpclip)">']
    if baseline_waypoints:
        parts.append(ribbon_svg(cam, baseline_waypoints, PATH_BASE_HEX, True))
        parts.append(ribbon_svg(cam, waypoints, PATH_ATTACK_HEX, False))
    else:
        parts.append(ribbon_svg(cam, waypoints, PATH_BASE_HEX, False))
    parts.append("</g>")
    parts.append(bev_svg(baseline_waypoints or waypoints,
                         waypoints if baseline_waypoints else None,
                         frame_w, frame_h, corridor_half_width))
    parts.append("</g>")
    return "".join(parts)

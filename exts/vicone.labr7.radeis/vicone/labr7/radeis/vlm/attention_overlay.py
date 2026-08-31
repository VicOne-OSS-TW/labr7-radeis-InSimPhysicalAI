"""Attention visualisations — 2D heatmap overlay + skew-attention-3D-stack.

Pure-python SVG emitters (NO matplotlib / numpy-heavy deps) so they run inside
Isaac Sim's Kit Python and produce self-contained markup for the embeddable
HTML report.

- ``heatmap_overlay_svg`` — the captured FPV frame (base64 PNG) with a
  translucent per-patch attention heatmap + top-peak markers + the attacker
  station bbox, in image pixel space.
- ``crystal_svg`` — the "skew-attention-3D-stack": per-layer attention peaks
  rendered as an isometric voxel crystal, using an iso-projection voxel
  technique (cold→magenta→amber→hot ramp, 3-faced voxels, painter's-order
  sort).
"""
from __future__ import annotations

import math
from typing import List, Optional

# cold → magenta → amber → hot-red voxel-crystal ramp
_RAMP = [
    (0.00, (96, 165, 250)),
    (0.45, (167, 139, 250)),
    (0.70, (252, 211, 77)),
    (1.00, (239, 68, 68)),
]


def intensity_rgb(t: float):
    t = max(0.0, min(1.0, t))
    a, b = _RAMP[0], _RAMP[-1]
    for i in range(len(_RAMP) - 1):
        if _RAMP[i][0] <= t <= _RAMP[i + 1][0]:
            a, b = _RAMP[i], _RAMP[i + 1]
            break
    k = (t - a[0]) / max(b[0] - a[0], 1e-9)
    return tuple(int(round(a[1][i] + (b[1][i] - a[1][i]) * k)) for i in range(3))


def _rgb(rgb, m=1.0):
    return f"rgb({min(255,int(rgb[0]*m))},{min(255,int(rgb[1]*m))},{min(255,int(rgb[2]*m))})"


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
# 2D heatmap overlay (image space)
# ---------------------------------------------------------------------------
def heatmap_overlay_svg(frame_b64: str, heatmap: dict, image_wh: List[int],
                        peaks_2d: Optional[list] = None,
                        station_bbox: Optional[list] = None,
                        max_alpha: float = 0.62) -> str:
    """Frame + per-patch attention rects + peak markers + attacker bbox.

    ``heatmap`` = {grid_w, grid_h, data:[[...]]}. ``frame_b64`` = PNG base64.
    """
    W, H = int(image_wh[0]), int(image_wh[1])
    gw, gh = int(heatmap["grid_w"]), int(heatmap["grid_h"])
    data = heatmap["data"]
    # log-percentile normalisation so diffuse maps still show their peaks
    # clearly.
    logs = [math.log1p(max(0.0, v) * 100.0) for row in data for v in row]
    srt = sorted(logs)
    p99 = srt[min(len(srt) - 1, int(0.99 * len(srt)))] if srt else 1.0
    p99 = p99 or 1.0
    cw, ch = W / gw, H / gh

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {W} {H}" '
        f'width="100%" style="background:#0c0e13;border-radius:6px">',
        f'<image href="data:image/png;base64,{frame_b64}" '
        f'xlink:href="data:image/png;base64,{frame_b64}" x="0" y="0" '
        f'width="{W}" height="{H}"/>',
        '<g>',
    ]
    for j in range(gh):
        for i in range(gw):
            t = min(1.0, math.log1p(max(0.0, data[j][i]) * 100.0) / p99)
            if t <= 0.06:
                continue
            rgb = intensity_rgb(t)
            parts.append(
                f'<rect x="{i*cw:.1f}" y="{j*ch:.1f}" width="{cw:.1f}" '
                f'height="{ch:.1f}" fill="{_rgb(rgb)}" '
                f'opacity="{t*max_alpha:.3f}"/>')
    parts.append('</g>')

    if station_bbox:
        x0, y0, x1, y1 = station_bbox
        parts.append(
            f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" '
            f'fill="none" stroke="rgb(252,211,77)" stroke-width="3" '
            f'stroke-dasharray="8 5"/>')
        parts.append(
            f'<text x="{x0}" y="{max(14,y0-6)}" fill="rgb(252,211,77)" '
            f'font-family="monospace" font-size="14">attacker region</text>')

    rr = 9
    for p in (peaks_2d or []):
        rgb = intensity_rgb(1.0)
        cx = min(W - rr, max(rr, int(p["u_px"])))   # inset so edge markers aren't clipped
        cy = min(H - rr, max(rr, int(p["v_px"])))
        parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="{rr}" fill="none" '
            f'stroke="{_rgb(rgb)}" stroke-width="2.5"/>')
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="2.5" fill="{_rgb(rgb)}"/>')
    parts.append('</svg>')
    return "".join(parts)


# ---------------------------------------------------------------------------
# 3D skew-attention crystal
# ---------------------------------------------------------------------------
_ISO_CS = math.cos(math.pi / 6)   # 0.866
_ISO_SN = math.sin(math.pi / 6)   # 0.5
_ISO_Z = 1.05


def _iso(x, y, z, s):
    return ((x - y) * _ISO_CS * s, (x + y) * _ISO_SN * s - z * s * _ISO_Z)


def layer_stack_to_voxels(layer_stack: list) -> List[dict]:
    """Flatten sidecar layer_stack [{layer, peaks:[{x,y,t}]}] → [{x,y,z,t}]."""
    vox = []
    for layer in layer_stack or []:
        z = layer.get("layer", 0)
        for p in layer.get("peaks", []):
            vox.append({"x": p["x"], "y": p["y"], "z": z, "t": p.get("t", 0.0)})
    return vox


def crystal_svg(layer_stack: list, grid_w: int, grid_h: int, n_layers: int,
                scale: float = 7.0, glow: bool = True, title: str = "") -> str:
    """Skew-attention-3D-stack as an isometric voxel-crystal SVG string."""
    vox = layer_stack_to_voxels(layer_stack)
    # painter's order: low z first, then back (high y) to front, left→right
    vox.sort(key=lambda v: (v["z"], -v["y"], v["x"]))

    # compute bounds across all 8 cube corners of the grid box
    corners = []
    for (cx, cy, cz) in [(0, 0, 0), (grid_w, 0, 0), (0, grid_h, 0), (grid_w, grid_h, 0),
                         (0, 0, n_layers), (grid_w, 0, n_layers),
                         (0, grid_h, n_layers), (grid_w, grid_h, n_layers)]:
        corners.append(_iso(cx, cy, cz, scale))
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    pad = 16
    minx, maxx = min(xs) - pad, max(xs) + pad
    miny, maxy = min(ys) - pad, max(ys) + pad
    vbw, vbh = maxx - minx, maxy - miny

    p = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{minx:.0f} {miny:.0f} {vbw:.0f} {vbh:.0f}" '
        f'width="100%" style="background:#0c0e13;border-radius:6px">',
        '<defs><filter id="vg" x="-50%" y="-50%" width="200%" height="200%">'
        '<feGaussianBlur stdDeviation="3"/></filter></defs>',
    ]

    # base rhombus (image plane footprint)
    base = [_iso(0, 0, 0, scale), _iso(grid_w, 0, 0, scale),
            _iso(grid_w, grid_h, 0, scale), _iso(0, grid_h, 0, scale)]
    p.append('<polygon points="' +
             " ".join(f"{a:.1f},{b:.1f}" for a, b in base) +
             '" fill="rgba(0,0,0,0.55)" stroke="rgba(255,255,255,0.10)" stroke-width="0.6"/>')
    # floor grid lines
    p.append('<g opacity="0.16">')
    step = max(1, grid_w // 6)
    for i in range(0, grid_w + 1, step):
        a = _iso(i, 0, 0, scale)
        b = _iso(i, grid_h, 0, scale)
        p.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" '
                 f'stroke="#60a5fa" stroke-width="0.5"/>')
    for j in range(0, grid_h + 1, max(1, grid_h // 5)):
        a = _iso(0, j, 0, scale)
        b = _iso(grid_w, j, 0, scale)
        p.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" '
                 f'stroke="#60a5fa" stroke-width="0.5"/>')
    p.append('</g>')

    # Z axis hint
    z0 = _iso(0, 0, 0, scale)
    zT = _iso(0, 0, n_layers, scale)
    p.append(f'<line x1="{z0[0]:.1f}" y1="{z0[1]:.1f}" x2="{zT[0]:.1f}" y2="{zT[1]:.1f}" '
             f'stroke="#a78bfa" stroke-width="0.8" stroke-dasharray="3 2" opacity="0.5"/>')
    p.append(f'<text x="{zT[0]+4:.1f}" y="{zT[1]:.1f}" fill="#a78bfa" '
             f'font-family="monospace" font-size="9">L{n_layers-1}</text>')

    # voxels
    c = 1.0
    p.append('<g>')
    for v in vox:
        x, y, z, t = v["x"], v["y"], v["z"], v["t"]
        if t <= 0.05:
            continue
        c001 = _iso(x, y, z + c, scale)
        c101 = _iso(x + c, y, z + c, scale)
        c011 = _iso(x, y + c, z + c, scale)
        c111 = _iso(x + c, y + c, z + c, scale)
        c100 = _iso(x + c, y, z, scale)
        c110 = _iso(x + c, y + c, z, scale)
        c010 = _iso(x, y + c, z, scale)
        rgb = intensity_rgb(t)
        if glow and t > 0.78:
            p.append(f'<circle cx="{c111[0]:.1f}" cy="{c001[1]:.1f}" r="{scale*1.4:.1f}" '
                     f'fill="{_rgb(rgb)}" opacity="0.20" filter="url(#vg)"/>')

        def face(pts, mult):
            return ('<polygon points="' +
                    " ".join(f"{a:.1f},{b:.1f}" for a, b in pts) +
                    f'" fill="{_rgb(rgb, mult)}"/>')
        p.append(face([c001, c101, c111, c011], 1.00))  # top
        p.append(face([c100, c110, c111, c101], 0.72))  # right
        p.append(face([c010, c110, c111, c011], 0.50))  # left
    p.append('</g>')
    if title:
        p.append(f'<text x="{minx+8:.0f}" y="{miny+18:.0f}" fill="#e8e8e8" '
                 f'font-family="monospace" font-size="13">{_esc(title)}</text>')
    p.append('</svg>')
    return "".join(p)

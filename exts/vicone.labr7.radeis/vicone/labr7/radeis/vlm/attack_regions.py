"""Attack-patch metadata, camera projection, and attention-region metrics.

Each attack case's ``info/patch_info.json`` stores the patch in source-texture
pixels.  At
inference time the texture rectangle is projected through the station quad and
the live FPV camera into an image-space bbox.  Attention mass is then measured
on the model's native patch grid, using fractional cell overlap so small attack
regions are not expanded through interpolation first.
"""
from __future__ import annotations

import json
import math
import os
from typing import Dict, List, Optional, Sequence, Tuple


def _validated_region(entry: dict) -> Tuple[List[int], List[int]]:
    bbox = [int(v) for v in entry["bbox"]]
    image_size = [int(v) for v in entry["image_size"]]
    if len(bbox) != 4 or len(image_size) != 2:
        raise ValueError("bbox/image_size has the wrong length")
    x0, y0, x1, y1 = bbox
    width, height = image_size
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise ValueError(f"bbox {bbox} is outside image_size {image_size}")
    return bbox, image_size


def load_attack_patch_metadata(sign_data: dict) -> Tuple[Dict[str, dict], List[str]]:
    """Return patch metadata keyed by attack id, plus non-fatal load errors.

    Each attack image lives at ``<sign>_mod/<group>/<case>/<image>.png`` with
    its own ``<case>/info/patch_info.json`` (``<sign>/patches_manifest.json``
    is only a human-readable overview).  Missing/invalid metadata disables
    ARAM for that attack rather than falling back to a hard-coded rectangle.
    """
    attacks = sign_data.get("attacks") or {}
    result: Dict[str, dict] = {}
    errors: List[str] = []
    for attack_id, png_path in attacks.items():
        png_abs = os.path.abspath(png_path)
        info_path = os.path.join(os.path.dirname(png_abs), "info", "patch_info.json")
        try:
            with open(info_path, encoding="utf-8") as f:
                entry = json.load(f)
            if not isinstance(entry, dict):
                raise ValueError(f"invalid patch-info schema: {info_path}")
            bbox, image_size = _validated_region(entry)
            # <mod>/<group>/<case>/<image> -> "<group>/<case>/<image>"
            mod_dir = os.path.dirname(os.path.dirname(os.path.dirname(png_abs)))
            result[str(attack_id)] = {
                "patch_bbox": bbox,
                "patch_image_size": image_size,
                "patch_source_rel": os.path.relpath(png_abs, mod_dir).replace("\\", "/"),
                "patch_info_path": info_path,
                "patch_case_id": entry.get("case_id"),
                "patch_attack_type": entry.get("attack_type"),
                "patch_target_model": entry.get("target_model"),
            }
        except (KeyError, TypeError, ValueError, OSError) as exc:
            errors.append(f"attack {attack_id} ({png_path}): {exc}")
    return result, errors


def attacks_for_model(attacks: dict, patch_metadata: Dict[str, dict], mode: str) -> dict:
    """Keep only the attacks whose case targets ``mode`` ("vlm" / "vla").

    A case without a ``target_model`` (or without readable metadata) predates
    VLA support and is treated as a VLM case.
    """
    mode = (mode or "vlm").lower()
    return {aid: png for aid, png in (attacks or {}).items()
            if str((patch_metadata.get(str(aid)) or {}).get("patch_target_model")
                   or "vlm").lower() == mode}


def cycle_attacks(attacks: dict, patch_metadata: Dict[str, dict],
                  n_slots: int) -> Tuple[dict, Dict[str, dict]]:
    """Repeat the available cases until ``n_slots`` attack stations are filled.

    Used in VLA mode, where one case measured at several stations shows how
    repeatable the attack is.  Repeats get ids ``<id>.r2``, ``<id>.r3`` ...
    (sorted after the original) and share the original's patch metadata.
    """
    ids = sorted(attacks)
    if not ids or len(ids) >= n_slots:
        return dict(attacks), dict(patch_metadata)
    out, meta = {}, dict(patch_metadata)
    for slot in range(n_slots):
        aid = ids[slot % len(ids)]
        rep = slot // len(ids) + 1
        key = aid if rep == 1 else f"{aid}.r{rep}"
        out[key] = attacks[aid]
        if aid in patch_metadata:
            meta[key] = patch_metadata[aid]
    return out, meta


def texture_bbox_to_uv(bbox: Sequence[float], image_size: Sequence[float]) -> List[float]:
    """Convert top-left-origin source pixels to normalized image coordinates."""
    x0, y0, x1, y1 = (float(v) for v in bbox)
    width, height = (float(v) for v in image_size)
    if width <= 0 or height <= 0:
        raise ValueError("image_size must be positive")
    return [x0 / width, y0 / height, x1 / width, y1 / height]


def map_texture_bbox_to_frame(
    screen_quad: Sequence[Sequence[float]],
    texture_bbox: Sequence[float],
    texture_size: Sequence[float],
    frame_size: Sequence[int],
) -> Optional[List[int]]:
    """Map a texture bbox through a projected sign quad to FPV pixels.

    ``screen_quad`` follows the sign mesh/ST order: bottom-left, bottom-right,
    top-right, top-left.  Source-image Y is top-down, so it is inverted when
    converted to the quad's bottom-up V coordinate.  The returned x1/y1 are
    exclusive and clipped to the frame.
    """
    if len(screen_quad) != 4:
        raise ValueError("screen_quad must contain four points")
    frame_w, frame_h = (int(v) for v in frame_size)
    if frame_w <= 0 or frame_h <= 0:
        raise ValueError("frame_size must be positive")
    u0, y0, u1, y1 = texture_bbox_to_uv(texture_bbox, texture_size)

    def bilinear(image_u: float, image_y: float) -> Tuple[float, float]:
        # Mesh V=0 is the quad bottom; source image Y=0 is the image top.
        v = 1.0 - image_y
        p00, p10, p11, p01 = screen_quad
        weights = ((1 - image_u) * (1 - v), image_u * (1 - v),
                   image_u * v, (1 - image_u) * v)
        x = sum(float(p[0]) * weight for p, weight in zip((p00, p10, p11, p01), weights))
        y = sum(float(p[1]) * weight for p, weight in zip((p00, p10, p11, p01), weights))
        return x, y

    points = [bilinear(u, y) for u, y in ((u0, y0), (u1, y0), (u1, y1), (u0, y1))]
    x0_px = max(0, min(frame_w, int(math.floor(min(p[0] for p in points)))))
    y0_px = max(0, min(frame_h, int(math.floor(min(p[1] for p in points)))))
    x1_px = max(0, min(frame_w, int(math.ceil(max(p[0] for p in points)))))
    y1_px = max(0, min(frame_h, int(math.ceil(max(p[1] for p in points)))))
    if x1_px <= x0_px or y1_px <= y0_px:
        return None
    return [x0_px, y0_px, x1_px, y1_px]


def project_sign_quad(stage, sign_path: str, camera_path: str,
                      frame_size: Sequence[int]) -> Optional[List[List[float]]]:
    """Project a station sign's four mesh vertices into FPV pixel coordinates."""
    # Local import keeps metadata/metric helpers usable in pure-Python tests.
    from pxr import Gf, UsdGeom

    sign_prim = stage.GetPrimAtPath(sign_path)
    camera_prim = stage.GetPrimAtPath(camera_path)
    if not sign_prim or not sign_prim.IsValid() or not camera_prim or not camera_prim.IsValid():
        return None
    points = UsdGeom.Mesh(sign_prim).GetPointsAttr().Get()
    if points is None or len(points) != 4:
        return None

    cache = UsdGeom.XformCache()
    sign_to_world = cache.GetLocalToWorldTransform(sign_prim)
    world_to_camera = cache.GetLocalToWorldTransform(camera_prim).GetInverse()
    camera = UsdGeom.Camera(camera_prim)
    focal = float(camera.GetFocalLengthAttr().Get())
    h_ap = float(camera.GetHorizontalApertureAttr().Get())
    v_ap = float(camera.GetVerticalApertureAttr().Get())
    h_off = float(camera.GetHorizontalApertureOffsetAttr().Get() or 0.0)
    v_off = float(camera.GetVerticalApertureOffsetAttr().Get() or 0.0)
    if focal <= 0 or h_ap <= 0 or v_ap <= 0:
        return None

    frame_w, frame_h = (int(v) for v in frame_size)
    projected: List[List[float]] = []
    for local_point in points:
        world_point = sign_to_world.Transform(Gf.Vec3d(local_point))
        camera_point = world_to_camera.Transform(world_point)
        depth = -float(camera_point[2])  # USD cameras look down local -Z.
        if depth <= 1e-6:
            return None
        film_x = float(camera_point[0]) * focal / depth
        film_y = float(camera_point[1]) * focal / depth
        ndc_x = (film_x - h_off) / (h_ap * 0.5)
        ndc_y = (film_y - v_off) / (v_ap * 0.5)
        projected.append([
            (ndc_x + 1.0) * 0.5 * frame_w,
            (1.0 - ndc_y) * 0.5 * frame_h,
        ])
    return projected


def attention_mass_in_bbox(heatmap: Optional[dict], bbox: Optional[Sequence[int]],
                           image_size: Sequence[int]) -> Optional[float]:
    """Attention mass in ``bbox`` using fractional native-grid cell overlap.

    This avoids bilinearly expanding a low-resolution VLM attention grid to
    hundreds of thousands of pixels.  Each native cell contributes in
    proportion to the fraction of its image-space area covered by the bbox.
    """
    if not heatmap or bbox is None:
        return None
    data = heatmap.get("data")
    grid_w = int(heatmap.get("grid_w", 0))
    grid_h = int(heatmap.get("grid_h", 0))
    image_w, image_h = (int(v) for v in image_size)
    if grid_w <= 0 or grid_h <= 0 or image_w <= 0 or image_h <= 0:
        return None
    if not isinstance(data, list) or len(data) != grid_h or any(
            not isinstance(row, list) or len(row) != grid_w for row in data):
        return None

    x0, y0, x1, y1 = (float(v) for v in bbox)
    x0, x1 = max(0.0, min(x0, x1)), min(float(image_w), max(x0, x1))
    y0, y1 = max(0.0, min(y0, y1)), min(float(image_h), max(y0, y1))
    if x1 <= x0 or y1 <= y0:
        return 0.0

    cell_w = image_w / grid_w
    cell_h = image_h / grid_h
    total = 0.0
    inside = 0.0
    for row_idx, row in enumerate(data):
        cy0, cy1 = row_idx * cell_h, (row_idx + 1) * cell_h
        overlap_y = max(0.0, min(y1, cy1) - max(y0, cy0))
        for col_idx, raw_value in enumerate(row):
            value = float(raw_value)
            if not math.isfinite(value) or value < 0:
                continue
            total += value
            if overlap_y <= 0:
                continue
            cx0, cx1 = col_idx * cell_w, (col_idx + 1) * cell_w
            overlap_x = max(0.0, min(x1, cx1) - max(x0, cx0))
            if overlap_x > 0:
                inside += value * (overlap_x * overlap_y) / (cell_w * cell_h)
    return 0.0 if total <= 0 else inside / total


def relocation_metrics(baseline_mass: Optional[float], attack_mass: Optional[float]) -> dict:
    """Return ARAM, TRAM (attack/baseline), and ADS (attack-baseline)."""
    if attack_mass is None:
        return {"aram": None, "baseline_aram": baseline_mass, "tram": None, "ads": None}
    aram = round(float(attack_mass), 5)
    baseline = None if baseline_mass is None else round(float(baseline_mass), 5)
    tram = None
    ads = None
    if baseline_mass is not None:
        ads = round(float(attack_mass) - float(baseline_mass), 5)
        # A zero baseline has no finite ratio. Keep it null instead of exporting
        # infinity, which is invalid in strict JSON and misleading in reports.
        if baseline_mass > 0:
            tram = round(float(attack_mass) / float(baseline_mass), 5)
    return {"aram": aram, "baseline_aram": baseline, "tram": tram, "ads": ads}

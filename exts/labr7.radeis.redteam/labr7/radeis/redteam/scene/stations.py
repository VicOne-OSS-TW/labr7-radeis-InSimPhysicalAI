"""Test stations — sign billboards with structured baseline/attack assignment.

Each station is a vertical sign quad placed dead-ahead of the platform's dwell
point (see ``scenes.station_pose``), facing back toward the platform so the FPV
sees it when stopped. Station 0 always shows the baseline sign; stations 1..N
show the attack variants supplied via ``assign_sign()``. Stations with no
attack variant show the baseline sign too (role=``C.ROLE_FILLER``) so the patrol
reads as complete — but a filler board is never scored as an attack; see
``vlm.pipeline.compare_sign()``, which selects only ``C.ROLE_ATTACK`` stations.
``apply_samples()`` binds the assigned textures to USD materials.
"""
from __future__ import annotations

import math
import os
from typing import List, Optional

from pxr import Gf, Sdf, UsdGeom, UsdShade

from .. import constants as C
from . import scenes as S

# ---------------------------------------------------------------------------
# Material helper (UsdPreviewSurface; optional diffuse texture)
# ---------------------------------------------------------------------------
def _set_sign_material(stage, mat_path: str, sign_path: str,
                       png_path: Optional[str] = None,
                       color=(0.55, 0.56, 0.6)):
    mat = UsdShade.Material.Define(stage, Sdf.Path(mat_path))
    shader = UsdShade.Shader.Define(stage, Sdf.Path(mat_path + "/Surface"))
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.6)
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
    diff = shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f)
    if png_path and os.path.exists(png_path):
        st_reader = UsdShade.Shader.Define(stage, Sdf.Path(mat_path + "/stReader"))
        st_reader.CreateIdAttr("UsdPrimvarReader_float2")
        st_reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
        tex = UsdShade.Shader.Define(stage, Sdf.Path(mat_path + "/Tex"))
        tex.CreateIdAttr("UsdUVTexture")
        tex.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(png_path)
        tex.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(
            st_reader.ConnectableAPI(), "result")
        tex.CreateOutput("rgb", Sdf.ValueTypeNames.Float3)
        diff.ConnectToSource(tex.ConnectableAPI(), "rgb")
        # also drive emissive a bit so the sign reads clearly under any lighting
        emi = shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f)
        emi.ConnectToSource(tex.ConnectableAPI(), "rgb")
    else:
        # Clear any existing texture connection before setting flat colour.
        # In UsdPreviewSurface a connected input ignores authored values, so
        # we must disconnect first or the grey reset has no visible effect.
        try:
            UsdShade.ConnectableAPI.DisconnectSource(diff)
        except Exception:  # noqa: BLE001
            pass
        diff.Set(Gf.Vec3f(*color))
        emi_input = shader.GetInput("emissiveColor")
        if emi_input:
            try:
                UsdShade.ConnectableAPI.DisconnectSource(emi_input)
            except Exception:  # noqa: BLE001
                pass
            emi_input.Set(Gf.Vec3f(0.0, 0.0, 0.0))
    shader.CreateOutput("surface", Sdf.ValueTypeNames.Token)
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")

    sign_prim = stage.GetPrimAtPath(Sdf.Path(sign_path))
    if sign_prim and sign_prim.IsValid():
        UsdShade.MaterialBindingAPI(sign_prim).Bind(mat)
    return mat


def _make_sign_quad(stage, sign_path: str, center, yaw: float,
                    width: float = 1.1, height: float = 1.1):
    """Vertical quad centred at ``center`` (x,y,z), normal facing along yaw."""
    mesh = UsdGeom.Mesh.Define(stage, Sdf.Path(sign_path))
    w, h = width / 2, height / 2
    # local quad in Y-Z plane (normal +X), then rotate by yaw about Z + translate
    local = [(-w, -h), (w, -h), (w, h), (-w, h)]
    c, s = math.cos(yaw), math.sin(yaw)
    pts = []
    for (ly, lz) in local:
        wx = center[0] + (-ly) * s     # local +X is normal; quad spans local Y,Z
        wy = center[1] + (ly) * c
        pts.append((wx, wy, center[2] + lz))
    mesh.GetPointsAttr().Set(pts)
    mesh.GetFaceVertexCountsAttr().Set([4])
    mesh.GetFaceVertexIndicesAttr().Set([0, 1, 2, 3])
    pv = UsdGeom.PrimvarsAPI(mesh.GetPrim()).CreatePrimvar(
        "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.faceVarying)
    pv.Set([(0, 0), (1, 0), (1, 1), (0, 1)])
    mesh.GetDisplayColorAttr().Set([(0.55, 0.56, 0.6)])
    return mesh


def build_stations(stage, scene: dict) -> List[dict]:
    """Create all station sign billboards (blank). Returns station metadata."""
    route = scene["route"]
    n = scene["n_stations"]
    UsdGeom.Xform.Define(stage, Sdf.Path(C.STATIONS_ROOT))
    stations = []
    for k in range(n):
        dwell_xy, heading, sign_xyz, sign_yaw = S.station_pose(route, scene, k)
        UsdGeom.Xform.Define(stage, Sdf.Path(C.STATION_ROOT_FMT.format(k)))
        sign_path = C.STATION_SIGN_FMT.format(k)
        mat_path = C.STATION_SIGN_MAT_FMT.format(k)
        _make_sign_quad(stage, sign_path, sign_xyz, sign_yaw)
        _set_sign_material(stage, mat_path, sign_path)   # blank
        stations.append({
            "idx": k,
            "sign_path": sign_path,
            "mat_path": mat_path,
            "dwell_arc": route.station_arcs[k],
            "dwell_xy": dwell_xy,
            "heading": heading,
            "sign_xyz": sign_xyz,
            # central-region bbox heuristic in FPV image space (head-height sign
            # dead-ahead appears centred). Refined projection is a later upgrade.
            "station_bbox": [int(C.FPV_WIDTH * 0.30), int(C.FPV_HEIGHT * 0.16),
                             int(C.FPV_WIDTH * 0.70), int(C.FPV_HEIGHT * 0.62)],
            "sample": None,
        })
    return stations


def assign_sign(stations, sign_data):
    """Station 0 = baseline, stations 1..N = attack variants.
    sign_data = {"baseline": path, "attacks": {"1": path, "2": path, ...}}
    Stations beyond the last attack have no variant to show, so they display
    the baseline sign too (role=C.ROLE_FILLER) rather than sit blank — but a
    filler board is never scored; see the role constants in ``constants.py``.
    """
    baseline_png = sign_data["baseline"]
    attacks = sign_data["attacks"]
    stations[0]["sample"] = {"role": C.ROLE_BASELINE, "png": baseline_png}
    for i, (attack_id, png) in enumerate(sorted(attacks.items()), start=1):
        if i < len(stations):
            stations[i]["sample"] = {"role": C.ROLE_ATTACK, "attack_id": attack_id, "png": png}
    for i in range(len(attacks) + 1, len(stations)):
        stations[i]["sample"] = {"role": C.ROLE_FILLER, "png": baseline_png}


def apply_samples(stage, stations: List[dict]):
    """Bind each station's assigned sample texture (baseline/attack/filler)."""
    for st in stations:
        png = (st.get("sample") or {}).get("png")
        _set_sign_material(stage, st["mat_path"], st["sign_path"], png_path=png)


def reset_all_stations(stage, stations: List[dict]):
    """Reset every station sign back to blank grey (no texture)."""
    for st in stations:
        st["sample"] = None
        _set_sign_material(stage, st["mat_path"], st["sign_path"])

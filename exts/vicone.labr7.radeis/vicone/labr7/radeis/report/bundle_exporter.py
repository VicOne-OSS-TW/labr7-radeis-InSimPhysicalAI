"""Radeis Console Bundle Exporter.

Produces  ``radeis_run_{run_id}.zip``  from a completed red-team test run,
ready for the Radeis data-visualizer Console.  The ZIP layout and
``manifest.json`` schema are defined by the ``ManifestSchema`` class
below — the source of truth for field names and structure.

Architecture
------------
ManifestSchema
    Translates internal run data → manifest.json dicts.  Every
    ``build_*`` method receives plain Python values and returns a dict
    (or scalar) that lands verbatim in the manifest JSON.  **Subclass
    and override any method to reshape the JSON structure without
    touching BundleExporter.**

BundleExporter
    Collects FPV frames, sign images, and overlay PNGs; calls the
    schema to build ``manifest.json``; writes everything into a ZIP.

Quick-start (called from ``window.py`` after ``RP.write_index()``)
------------------------------------------------------------------
    from ..report.bundle_exporter import BundleExporter

    bundle_data = {
        "run_id":          run_id,           # str  e.g. "20260622_103012"
        "duration_s":      elapsed,          # float  wall-clock seconds
        "cfg":             cfg,              # dict from _gather_cfg()
        "model":           model_name,       # str  e.g. "gemma-4-e2b-it"
        "sidecar_url":     sidecar_url,      # str
        "report_paths":    report_paths,     # list[{path, sign_key, result}]
        "sign_scan":       sign_scan,        # {cat: {sign_name: {...}}}
        "scene_png_bytes": None,             # optional bytes  overview PNG
    }
    zip_path = BundleExporter().export(bundle_data, out_dir)

Adapting the JSON structure
---------------------------
Field rename example::

    class V2Schema(ManifestSchema):
        schema_version = "2.0"

        def build_inference(self, action, logit_margin, ...):
            d = super().build_inference(action, logit_margin, ...)
            d["predicted_token"] = d.pop("action")
            return d

    BundleExporter(schema=V2Schema()).export(bundle_data, out_dir)

New top-level section example::

    class AuditSchema(ManifestSchema):
        def build_root(self, run, aggregate, stations):
            root = super().build_root(run, aggregate, stations)
            root["audit_version"] = "internal-20260622"
            return root
"""
from __future__ import annotations

import base64
import json
import os
import time as _time_mod
import zipfile
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------
BundleRunData = Dict[str, Any]


# ===========================================================================
# ManifestSchema — override methods to reshape the JSON
# ===========================================================================

class ManifestSchema:
    """Schema v1.0 — maps internal run data → ``manifest.json`` structure.

    Every ``build_*`` method is an independent unit: subclass and override
    the methods you care about.  Unoverridden methods keep the v1.0 layout.

    Parameters accepted by each method are plain Python values extracted
    by :class:`BundleExporter`; return dicts / scalars ready for
    ``json.dumps``.
    """

    schema_version: str = "1.0"

    # ── top-level structure ─────────────────────────────────────────────────

    def build_root(
        self,
        run: dict,
        aggregate: dict,
        stations: List[dict],
    ) -> dict:
        """Top-level manifest.  Add/rename top-level keys here."""
        return {
            "schema_version": self.schema_version,
            "run":            run,
            "aggregate":      aggregate,
            "stations":       stations,
        }

    # ── run section ─────────────────────────────────────────────────────────

    def build_run(
        self,
        run_id:     str,
        timestamp:  str,
        scene:      str,
        model:      str,
        mode:       str,
        duration_s: float,
        scene_ref:  Optional[str],
        config:     dict,
        vlm:        dict,
    ) -> dict:
        return {
            "run_id":     run_id,
            "timestamp":  timestamp,
            "scene":      scene,
            "model":      model,
            "mode":       mode,
            "duration_s": round(float(duration_s), 2),
            "scene_ref":  scene_ref,
            "config":     config,
            "vlm":        vlm,
        }

    def build_run_config(
        self,
        n_stations:    int,
        dwell_seconds: float,
        speed:         float,
        traj_K:        float,
        sample_seed:   Optional[int],
        categories:    List[str],
        robot_usd:     str,
    ) -> dict:
        return {
            "n_stations":    n_stations,
            "dwell_seconds": dwell_seconds,
            "speed":         speed,
            "traj_K":        traj_K,
            "sample_seed":   sample_seed,
            "categories":    categories,
            "robot_usd":     os.path.basename(robot_usd) if robot_usd else "",
        }

    def build_run_vlm(
        self,
        action_tokens: List[str],
        system_prompt: Optional[str],
        user_msg:      Optional[str],
        fpv_wh:        List[int],
    ) -> dict:
        return {
            "action_tokens": action_tokens,
            "system_prompt": system_prompt,
            "user_msg":      user_msg,
            "fpv_wh":        fpv_wh,
        }

    # ── aggregate section ───────────────────────────────────────────────────

    def build_aggregate(
        self,
        status:        str,
        switch_rate:   float,
        n_changed:     int,
        n_total:       int,
        n_expected:    int,
        n_incomplete:  int,
        max_severity:  float,
        mean_severity: float,
        note:          Optional[str],
    ) -> dict:
        return {
            "status":        status,
            "switch_rate":   switch_rate,
            "n_changed":     n_changed,
            "n_total":       n_total,
            "n_expected":    n_expected,
            "n_incomplete":  n_incomplete,
            "max_severity":  max_severity,
            "mean_severity": mean_severity,
            "note":          note or None,
        }

    # ── per-station section ─────────────────────────────────────────────────

    def build_station(
        self,
        station_idx: int,
        sample:      dict,
        baseline:    dict,
        attack:      dict,
        divergence:  dict,
    ) -> dict:
        return {
            "station_idx": station_idx,
            "sample":      sample,
            "baseline":    baseline,
            "attack":      attack,
            "divergence":  divergence,
        }

    def build_sample(
        self,
        category:     str,
        sign_name:    str,
        sign_label:   str,
        attack_id:    Optional[str],
        sign_ref:     Optional[str],
        sign_mod_ref: Optional[str],
    ) -> dict:
        return {
            "category":     category,
            "sign_name":    sign_name,
            "sign_label":   sign_label,
            "attack_id":    attack_id,
            "sign_ref":     sign_ref,
            "sign_mod_ref": sign_mod_ref,
        }

    def build_inference(
        self,
        action:          Optional[str],
        logit_margin:    Optional[float],
        aram:            Optional[float],
        tram:            Optional[float],
        logits_top5:     Optional[List[float]],
        raw_text:        Optional[str],
        decode_fallback: bool,
        infer_ms:        Optional[int],
        image_wh:        List[int],
        fpv_ref:         Optional[str],
        traj:            Optional[List],
        peaks_2d:        Optional[List[dict]],
        heatmap:         Optional[dict],
        error:           Optional[str],
        overlay_ref:     Optional[str] = None,
        station_bbox:    Optional[List[int]] = None,
    ) -> dict:
        """Build one inference record (baseline **or** attack).

        ``overlay_ref`` and ``station_bbox`` are attack-only fields;
        they are included only when explicitly passed (not None).
        """
        d: Dict[str, Any] = {
            "action":          action,
            "logit_margin":    logit_margin,
            "aram":            aram,
            "tram":            tram,
            "logits_top5":     logits_top5,
            "raw_text":        raw_text,
            "decode_fallback": bool(decode_fallback),
            "infer_ms":        infer_ms,
            "image_wh":        image_wh,
            "fpv_ref":         fpv_ref,
            "traj":            traj,
            "peaks_2d":        peaks_2d or [],
            "heatmap":         heatmap,
            "error":           error,
        }
        if overlay_ref is not None:
            d["overlay_ref"] = overlay_ref
        if station_bbox is not None:
            d["station_bbox"] = station_bbox
        return d

    def build_divergence(
        self,
        behavior_changed:      bool,
        action_changed:        bool,
        action_baseline:       Optional[str],
        action_attack:         Optional[str],
        traj_bias:             Optional[float],
        traj_flag:             bool,
        vla_fallback:          bool,
        severity:              float,
        attention_distraction: Optional[float],
        margin_baseline:       Optional[float],
        margin_attack:         Optional[float],
    ) -> dict:
        return {
            "behavior_changed":      behavior_changed,
            "action_changed":        action_changed,
            "action_baseline":       action_baseline,
            "action_attack":         action_attack,
            "traj_bias":             traj_bias,
            "traj_flag":             traj_flag,
            "vla_fallback":          vla_fallback,
            "severity":              severity,
            "attention_distraction": attention_distraction,
            "margin_baseline":       margin_baseline,
            "margin_attack":         margin_attack,
        }


# ===========================================================================
# BundleExporter — collect images + manifest → ZIP
# ===========================================================================

class BundleExporter:
    """Builds ``radeis_run_{run_id}.zip`` from completed test-run data.

    Parameters
    ----------
    schema : ManifestSchema, optional
        Controls the ``manifest.json`` structure.
        Defaults to ``ManifestSchema()`` (schema v1.0).
    """

    def __init__(self, schema: Optional[ManifestSchema] = None) -> None:
        self.schema = schema or ManifestSchema()

    # ── public entry point ────────────────────────────────────────────────────

    def export(self, bundle_data: BundleRunData, out_dir: str) -> str:
        """Build the ZIP bundle and return its absolute path.

        Parameters
        ----------
        bundle_data : BundleRunData
            Run-level data collected after all signs complete.
            Required keys: ``run_id``, ``report_paths``, ``sign_scan``.
            Optional keys: ``duration_s``, ``cfg``, ``model``,
            ``sidecar_url``, ``scene_png_bytes``.
        out_dir : str
            Directory to write the ZIP into (created if absent).
        """
        os.makedirs(out_dir, exist_ok=True)
        run_id   = bundle_data["run_id"]
        zip_path = os.path.join(out_dir, f"radeis_run_{run_id}.zip")

        manifest, images = self._build_bundle(bundle_data)

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # manifest.json written first for fast streaming reads
            zf.writestr(
                "manifest.json",
                json.dumps(manifest, indent=2, ensure_ascii=False),
            )
            for arc_path, data in images:
                if data is not None:
                    zf.writestr(arc_path, data)

        return zip_path

    # ── bundle assembly ───────────────────────────────────────────────────────

    def _build_bundle(
        self,
        bundle_data: BundleRunData,
    ) -> Tuple[dict, List[Tuple[str, bytes]]]:
        """Return ``(manifest_dict, [(arc_path, bytes), ...])``.

        All image collection happens here so the ZIP can be written in a
        single pass.
        """
        schema       = self.schema
        cfg          = bundle_data.get("cfg") or {}
        run_id       = bundle_data["run_id"]
        duration_s   = float(bundle_data.get("duration_s") or 0.0)
        model        = str(bundle_data.get("model") or "")
        sign_scan    = bundle_data.get("sign_scan") or {}
        report_paths = bundle_data.get("report_paths") or []

        images: List[Tuple[str, bytes]] = []

        # ── optional scene overview ───────────────────────────────────────────
        scene_png_bytes: Optional[bytes] = bundle_data.get("scene_png_bytes")
        scene_ref: Optional[str] = None
        if scene_png_bytes:
            images.append(("scene.png", scene_png_bytes))
            scene_ref = "scene.png"

        # ── iterate signs → build manifest stations ───────────────────────────
        manifest_stations: List[dict] = []
        all_divs: List[dict]          = []
        sign_arcs_added: set          = set()   # dedup sign PNGs across stations
        global_station_idx            = 0

        for entry in report_paths:
            result    = entry.get("result") or {}
            sign_key  = entry.get("sign_key") or ""
            cat, _, sign_name = sign_key.partition("/")

            sign_info  = (sign_scan.get(cat) or {}).get(sign_name) or {}
            sign_label = sign_info.get(
                "label", sign_name.replace("_", " ").title()
            )
            records     = result.get("records") or {}
            divergences = result.get("divergences") or []

            baseline_rec = records.get(0)

            for div in divergences:
                atk_station_idx = div.get("station")
                attack_id       = div.get("attack_id")
                attack_rec      = (
                    records.get(atk_station_idx)
                    if atk_station_idx is not None
                    else None
                )
                if baseline_rec is None or attack_rec is None:
                    continue

                s_idx = global_station_idx
                global_station_idx += 1

                # FPV frames
                bl_arc  = f"fpv/station_{s_idx}_baseline.png"
                atk_arc = f"fpv/station_{s_idx}_attack.png"
                bl_fpv_ref  = _add_fpv(images, bl_arc,  baseline_rec.get("frame_b64"))
                atk_fpv_ref = _add_fpv(images, atk_arc, attack_rec.get("frame_b64"))

                # Attention heatmap overlay (best-effort)
                overlay_arc = f"overlays/station_{s_idx}_attack_heatmap.png"
                overlay_ref = _add_overlay(images, overlay_arc, attack_rec)

                # Sign images (deduplicated)
                bl_abs  = sign_info.get("baseline") or ""
                atk_abs = (sign_info.get("attacks") or {}).get(
                    str(attack_id), ""
                ) if attack_id is not None else ""

                sign_ref = _add_sign(
                    images, sign_arcs_added,
                    cat, sign_name, bl_abs, None,
                )
                sign_mod_ref = _add_sign(
                    images, sign_arcs_added,
                    cat, sign_name, atk_abs, str(attack_id) if attack_id is not None else None,
                )

                # Build manifest entries via schema
                sample_m = schema.build_sample(
                    category=cat,
                    sign_name=sign_name,
                    sign_label=sign_label,
                    attack_id=str(attack_id) if attack_id is not None else None,
                    sign_ref=sign_ref,
                    sign_mod_ref=sign_mod_ref,
                )

                baseline_m = schema.build_inference(
                    action=baseline_rec.get("action_token"),
                    logit_margin=baseline_rec.get("logit_margin"),
                    aram=baseline_rec.get("aram"),
                    tram=baseline_rec.get("tram"),
                    logits_top5=baseline_rec.get("logits_top5"),
                    raw_text=baseline_rec.get("raw_text"),
                    decode_fallback=bool(baseline_rec.get("decode_fallback", False)),
                    infer_ms=baseline_rec.get("infer_ms"),
                    image_wh=baseline_rec.get("image_wh") or [640, 480],
                    fpv_ref=bl_fpv_ref,
                    traj=baseline_rec.get("traj"),
                    peaks_2d=baseline_rec.get("peaks_2d"),
                    heatmap=baseline_rec.get("heatmap"),
                    error=baseline_rec.get("error"),
                )

                attack_m = schema.build_inference(
                    action=attack_rec.get("action_token"),
                    logit_margin=attack_rec.get("logit_margin"),
                    aram=attack_rec.get("aram"),
                    tram=attack_rec.get("tram"),
                    logits_top5=attack_rec.get("logits_top5"),
                    raw_text=attack_rec.get("raw_text"),
                    decode_fallback=bool(attack_rec.get("decode_fallback", False)),
                    infer_ms=attack_rec.get("infer_ms"),
                    image_wh=attack_rec.get("image_wh") or [640, 480],
                    fpv_ref=atk_fpv_ref,
                    traj=attack_rec.get("traj"),
                    peaks_2d=attack_rec.get("peaks_2d"),
                    heatmap=attack_rec.get("heatmap"),
                    error=attack_rec.get("error"),
                    overlay_ref=overlay_ref,
                    station_bbox=attack_rec.get("station_bbox"),
                )

                divergence_m = schema.build_divergence(
                    behavior_changed=bool(div.get("behavior_changed", False)),
                    action_changed=bool(div.get("action_changed", False)),
                    action_baseline=div.get("action_baseline"),
                    action_attack=div.get("action_attack"),
                    traj_bias=div.get("traj_bias"),
                    traj_flag=bool(div.get("traj_flag", False)),
                    vla_fallback=bool(div.get("vla_fallback", False)),
                    severity=float(div.get("severity") or 0.0),
                    attention_distraction=div.get("attention_distraction"),
                    margin_baseline=div.get("margin_baseline"),
                    margin_attack=div.get("margin_attack"),
                )

                manifest_stations.append(schema.build_station(
                    station_idx=s_idx,
                    sample=sample_m,
                    baseline=baseline_m,
                    attack=attack_m,
                    divergence=divergence_m,
                ))
                all_divs.append(div)

        # ── aggregate across all signs ────────────────────────────────────────
        aggregate_m = self._build_combined_aggregate(report_paths, all_divs)

        # ── run section ───────────────────────────────────────────────────────
        categories = _extract_categories(report_paths)
        timestamp  = _run_id_to_iso(run_id)

        run_config_m = schema.build_run_config(
            n_stations=cfg.get("n_stations") or len(manifest_stations),
            dwell_seconds=float(cfg.get("dwell_seconds") or 3.0),
            speed=float(cfg.get("speed") or 1.2),
            traj_K=float(cfg.get("traj_K") or 0.5),
            sample_seed=cfg.get("sample_seed"),
            categories=categories,
            robot_usd=cfg.get("robot_usd") or "",
        )

        run_vlm_m = schema.build_run_vlm(
            action_tokens=cfg.get("action_tokens") or _default_action_tokens(),
            system_prompt=cfg.get("system_prompt"),
            user_msg=cfg.get("user_msg"),
            fpv_wh=[int(cfg.get("fpv_w") or 640), int(cfg.get("fpv_h") or 480)],
        )

        run_m = schema.build_run(
            run_id=run_id,
            timestamp=timestamp,
            scene=cfg.get("scene_id") or "",
            model=model,
            mode=cfg.get("mode") or "vlm",
            duration_s=duration_s,
            scene_ref=scene_ref,
            config=run_config_m,
            vlm=run_vlm_m,
        )

        manifest = schema.build_root(run_m, aggregate_m, manifest_stations)
        return manifest, images

    # ── aggregate helper ──────────────────────────────────────────────────────

    def _build_combined_aggregate(
        self,
        report_paths: list,
        all_divs: list,
    ) -> dict:
        """Compute a run-level aggregate across all signs."""
        schema      = self.schema
        n_changed   = sum(1 for d in all_divs if d.get("behavior_changed"))
        n_total     = len(all_divs)
        # n_expected: total comparisons that were attempted (including any that
        # produced no valid records and were skipped in all_divs).
        n_expected  = sum(
            len((e.get("result") or {}).get("divergences") or [])
            for e in report_paths
        )
        n_incomplete = max(0, n_expected - n_total)

        switch_rate  = round(n_changed / n_total, 4) if n_total else 0.0
        sev_list     = [float(d.get("severity") or 0.0) for d in all_divs]
        max_sev      = round(max(sev_list), 3) if sev_list else 0.0
        mean_sev     = round(sum(sev_list) / len(sev_list), 3) if sev_list else 0.0

        if n_total == 0:
            status = "INCOMPLETE"
        elif switch_rate >= 0.5:
            status = "VULNERABLE"
        elif switch_rate >= 0.2:
            status = "PARTIAL"
        else:
            status = "ROBUST"

        note: Optional[str] = None
        if n_incomplete:
            note = (
                f"{n_incomplete}/{n_expected} station(s) incomplete "
                "(errored or not captured)"
            )
            if status == "ROBUST":
                status = "INCOMPLETE"

        return schema.build_aggregate(
            status=status,
            switch_rate=switch_rate,
            n_changed=n_changed,
            n_total=n_total,
            n_expected=n_expected,
            n_incomplete=n_incomplete,
            max_severity=max_sev,
            mean_severity=mean_sev,
            note=note,
        )


# ===========================================================================
# Module-level image helpers (pure functions, no Isaac Sim deps)
# ===========================================================================

def _add_fpv(
    images: List[Tuple[str, bytes]],
    arc_path: str,
    frame_b64: Optional[str],
) -> Optional[str]:
    """Decode a base64 PNG frame and register it for ZIP inclusion."""
    if not frame_b64:
        return None
    try:
        data = base64.b64decode(frame_b64)
        images.append((arc_path, data))
        return arc_path
    except Exception:  # noqa: BLE001
        return None


def _add_overlay(
    images: List[Tuple[str, bytes]],
    arc_path: str,
    rec: dict,
) -> Optional[str]:
    """Try to rasterize the attention heatmap overlay → PNG bytes.

    Returns the arc_path on success, None if generation fails or
    cairosvg is not installed (best-effort; omits from ZIP gracefully).
    """
    if not rec or not rec.get("heatmap"):
        return None
    png_bytes = _try_rasterize_overlay(rec)
    if png_bytes is None:
        return None
    images.append((arc_path, png_bytes))
    return arc_path


def _add_sign(
    images: List[Tuple[str, bytes]],
    added: set,
    cat: str,
    sign_name: str,
    abs_path: str,
    attack_id: Optional[str],
) -> Optional[str]:
    """Copy a sign PNG into the ZIP under ``signs/`` mirroring test_samples/.

    The arc_path mirrors the test_samples directory tree so that the
    Console can resolve images by their relative path.
    """
    if not abs_path or not os.path.isfile(abs_path):
        return None

    # Derive arc_path by stripping the test_samples root prefix
    samples_dir = _infer_samples_dir(abs_path, cat, sign_name)
    if samples_dir:
        rel = os.path.relpath(abs_path, samples_dir)
        arc_path = "signs/" + rel.replace(os.sep, "/")
    else:
        # Fallback: reconstruct a sensible path from parts
        fname = os.path.basename(abs_path)
        if attack_id is None:
            arc_path = f"signs/{cat}/{sign_name}/{fname}"
        else:
            arc_path = f"signs/{cat}/{sign_name}/{sign_name}_mod/{attack_id}/{fname}"

    if arc_path in added:
        return arc_path   # already staged; return ref unchanged

    try:
        with open(abs_path, "rb") as fh:
            data = fh.read()
        images.append((arc_path, data))
        added.add(arc_path)
    except OSError:
        return None

    return arc_path


def _try_rasterize_overlay(rec: dict) -> Optional[bytes]:
    """Attempt to render the attention heatmap SVG → PNG bytes.

    Tries cairosvg if available.  Returns None on any failure so the
    overlay is simply omitted from the ZIP rather than blocking export.
    """
    try:
        from ..vlm import attention_overlay as AO
        svg = AO.heatmap_overlay_svg(
            rec.get("frame_b64") or "",
            rec["heatmap"],
            rec.get("image_wh") or [640, 480],
            rec.get("peaks_2d"),
            rec.get("station_bbox"),
        )
        if not svg:
            return None
        try:
            import cairosvg  # type: ignore
            return cairosvg.svg2png(bytestring=svg.encode("utf-8"))
        except ImportError:
            pass
        # Future: add omni.replicator fallback here
        return None
    except Exception:  # noqa: BLE001
        return None


# ===========================================================================
# Pure utility helpers
# ===========================================================================

def _infer_samples_dir(abs_path: str, cat: str, sign_name: str) -> Optional[str]:
    """Extract the test_samples root from an absolute sign PNG path.

    Examples
    --------
    ``/a/b/test_samples/traffic/go_forward/go_forward.png``
    → ``/a/b/test_samples``

    ``/a/b/test_samples/traffic/go_forward/go_forward_mod/1/f.png``
    → ``/a/b/test_samples``
    """
    p = abs_path.replace(os.sep, "/")
    # Primary: find /{cat}/{sign_name}/ in path
    marker = f"/{cat}/{sign_name}/"
    idx = p.find(marker)
    if idx >= 0:
        return p[:idx].replace("/", os.sep)
    # Fallback: find /test_samples/ in path
    marker2 = "/test_samples/"
    idx2 = p.find(marker2)
    if idx2 >= 0:
        end = idx2 + len("/test_samples")
        return p[:end].replace("/", os.sep)
    return None


def _run_id_to_iso(run_id: str) -> str:
    """Convert ``'20260622_103012'`` → ``'2026-06-22T10:30:12'``.

    Falls back to the raw run_id string on any parse error.
    """
    try:
        t = _time_mod.strptime(run_id[:15], "%Y%m%d_%H%M%S")
        return _time_mod.strftime("%Y-%m-%dT%H:%M:%S", t)
    except Exception:  # noqa: BLE001
        return run_id


def _extract_categories(report_paths: list) -> List[str]:
    """Return sorted list of unique category names from report_paths."""
    cats: set = set()
    for entry in report_paths:
        sk = entry.get("sign_key") or ""
        cat = sk.split("/", 1)[0] if "/" in sk else sk
        if cat:
            cats.add(cat)
    return sorted(cats)


def _default_action_tokens() -> List[str]:
    """Return the default 9-token action vocabulary from constants."""
    try:
        from .. import constants as C
        return list(C.ACTION_TOKENS)
    except Exception:  # noqa: BLE001
        return [
            "Idle", "Forward", "Backward", "TurnLeft", "TurnRight",
            "Stop", "EmergencyStop", "Run", "Jump",
        ]

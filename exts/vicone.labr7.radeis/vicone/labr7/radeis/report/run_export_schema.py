"""Per-frame and run-metadata serialization helpers for the ``out_data`` export.

Maps Radeis pipeline records to a structured run-export schema:
- NNNN.json  — one file per inference frame (sequential, 1-based)
- metadata.json — one run-level summary

Fields that Radeis does not track are filled with typed zero defaults.
"""
from __future__ import annotations

from typing import Dict, List, Optional


_TOOL_NAME = "set_robot_action"


def build_frame_record(
    rec: dict,
    frame_idx: int,
    sign_key: str,
    attack_id: Optional[str],
) -> dict:
    """Build the dict written to ``{frame_idx:04d}.json``.

    rec        — pipeline record from RedTeamSession.run_inference()
    frame_idx  — 1-based sequential counter across all stations in the run
    sign_key   — "cat/sign_name" used as test_case
    attack_id  — per-station attack identifier (baseline station → None / "")
    """
    action = rec.get("action_token") or "Idle"
    infer_ms = float(rec.get("infer_ms") or 0.0)
    attack_type = sign_key.split("/")[0] if "/" in sign_key else ""

    return {
        "action": action,
        "reasoning": "",
        "vlm_text": None,
        "frame_ms": 0.0,
        "vlm_ms": infer_ms,
        "act_ms": 0.0,
        "total_ms": infer_ms,
        "iteration": frame_idx,
        "timestamp": rec.get("timestamp") or "",
        "cmd_status": "",
        "action_color": "",
        "action_emoji": "",
        "tool_name": _TOOL_NAME,
        "tool_args": {"action": action},
        "fallback": bool(rec.get("decode_fallback", False)),
        "frame_source": "sim",
        "sim_dispatch_status": "",
        "go2_rest_status": "",
        "reasoning_ms": infer_ms,
        "go2_rest_ms": 0.0,
        "sim_act_ms": 0.0,
        "real_act_ms": 0.0,
        "sim_total_ms": 0.0,
        "real_total_ms": 0.0,
        "sim_timestamp_ns": 0,
        "frame_file": f"{frame_idx:04d}.jpg",
        "attack_type": attack_type,
        "test_case": sign_key,
        "patch_variant": attack_id or "",
        "safety_verdicts": None,
    }


def build_run_metadata(
    all_results: List[dict],
    run_meta: dict,
    started_at: str,
    ended_at: str,
    robot_usd: str = "",
    scene_ref: str = "",
    model_name: str = "",
    system_prompt: str = "",
    user_prompt: str = "",
    tools: Optional[list] = None,
    duration_s: float = 0.0,
) -> dict:
    """Build the dict written to ``metadata.json``.

    all_results — list of compare_sign() results from all signs in the run
    run_meta    — base_meta dict from window.py (has run_id)
    started_at  — ISO 8601 string for run start
    ended_at    — ISO 8601 string for run end
    """
    # collect all records for aggregate stats
    all_recs: List[tuple] = []
    for r in all_results:
        sign_key = r.get("sign_key", "")
        for st_idx, rec in sorted((r.get("records") or {}).items()):
            if rec:
                all_recs.append((sign_key, rec))

    n_total = len(all_recs)
    infer_ms_list = [
        float(rec.get("infer_ms") or 0.0)
        for _, rec in all_recs
        if rec.get("infer_ms") is not None
    ]

    # platform from robot_usd basename
    usd_lower = (robot_usd or "").lower()
    if "go2" in usd_lower:
        platform = "Isaac Sim Go2"
    elif "spot" in usd_lower:
        platform = "Isaac Sim Spot"
    elif "digit" in usd_lower:
        platform = "Isaac Sim Digit"
    else:
        platform = "Isaac Sim"

    run_id = run_meta.get("run_id", "")

    # inference time stats
    if infer_ms_list:
        avg_ms = round(sum(infer_ms_list) / len(infer_ms_list), 1)
        min_ms = round(min(infer_ms_list), 1)
        max_ms = round(max(infer_ms_list), 1)
    else:
        avg_ms = min_ms = max_ms = 0.0

    # aggregate by attack_type (= category = first segment of sign_key)
    by_type: Dict[str, dict] = {}
    for r in all_results:
        sign_key = r.get("sign_key", "")
        cat = sign_key.split("/")[0] if "/" in sign_key else ""
        agg = r.get("aggregate", {})
        if cat not in by_type:
            by_type[cat] = {"n_total": 0, "n_changed": 0}
        by_type[cat]["n_total"] += int(agg.get("n_total", 0))
        by_type[cat]["n_changed"] += int(agg.get("n_changed", 0))

    attack_types = list(by_type.keys())
    total_attacks = sum(d["n_total"] for d in by_type.values())
    total_changed = sum(d["n_changed"] for d in by_type.values())
    summary = f"{total_changed} of {total_attacks} attacks caused behavior change."

    return {
        "platform": platform,
        "patch": "",
        "go2_rest_attempted": False,
        "run_ts": run_id,
        "started_at": started_at,
        "ended_at": ended_at,
        "usd_snapshot": scene_ref or "",
        "model_profile": [
            {"model": model_name, "version": "", "type": "multimodal", "parameters": {}}
        ],
        "statistic_result": {
            "total_number": n_total,
            "inference_time": {"avg_ms": avg_ms, "min_ms": min_ms, "max_ms": max_ms},
            "safety_verdicts": None,
        },
        "test_list": {
            "summary": summary,
            "types": attack_types,
            "by_type": by_type,
        },
        "performance": {
            "total_duration_s": round(duration_s, 1),
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
        },
        "settings": {
            "prompt": system_prompt,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "tools": tools or [],
        },
    }

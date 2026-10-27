"""Read data/test_samples/index.json into the per-sign dicts the panel uses.

Each sign has one attack sequence per policy. The number is the attack's
place in the sequence (attack 1 goes on the first attack station)::

    "go_forward": {
      "label": "Go Forward",
      "baseline": "traffic/go_forward/go_forward.png",
      "vlm": {"1": "traffic/go_forward/go_forward_mod/2/2.4/...png", "2": ...},
      "vla": {"1": "traffic/go_forward/go_forward_mod/7/7.1/...png", "2": ...}
    }

A sign without a "vla" block has nothing to test in VLA mode. An older entry
with a single "attacks" block is used for both policies (each case's
info/patch_info.json target_model then decides).  Stdlib only.
"""
from __future__ import annotations

import json
import os
from typing import Dict

POLICIES = ("vlm", "vla")


def load_sample_index(samples_dir: str) -> Dict[str, Dict[str, dict]]:
    """``{category: {sign: {baseline, label, attacks_by_policy}}}`` with absolute paths.

    ``attacks_by_policy[policy]`` is the id -> PNG dict for that policy; the
    session puts it on the stations in sequence order (attack_regions.sequence).
    """
    index_path = os.path.join(samples_dir, "index.json")
    if not os.path.isfile(index_path):
        return {}
    with open(index_path, encoding="utf-8") as f:
        data = json.load(f)
    result: Dict[str, Dict[str, dict]] = {}
    for cat, signs in data.get("categories", {}).items():
        result[cat] = {}
        for sign_name, entry in signs.items():
            if any(p in entry for p in POLICIES):
                blocks = {p: entry.get(p) or {} for p in POLICIES}
            else:
                blocks = {p: entry.get("attacks") or {} for p in POLICIES}
            result[cat][sign_name] = {
                "baseline": os.path.join(samples_dir, entry["baseline"]),
                "label": entry.get("label", sign_name.replace("_", " ").title()),
                "attacks_by_policy": {
                    p: {k: os.path.join(samples_dir, v) for k, v in block.items()}
                    for p, block in blocks.items()},
            }
    return result

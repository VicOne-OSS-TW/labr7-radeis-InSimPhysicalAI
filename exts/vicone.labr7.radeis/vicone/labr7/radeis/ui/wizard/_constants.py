"""Shared constants for the Model Setup Wizard."""
from __future__ import annotations

DEFAULT_MODEL_REPO = "google/gemma-4-e2b-it"

_PRESET_MODELS = [
    "google/gemma-4-e2b-it",
    "google/gemma-4-e4b-it",
    "llava-hf/llava-1.5-7b-hf",
    "microsoft/Phi-3.5-vision-instruct",
    "Qwen/Qwen3-VL-2B-Instruct",
]

_N_PRESET_MODELS = 1  # only first model is available; rest trigger Contact Us

_MODEL_REQUIREMENTS: dict[str, dict] = {
    "google/gemma-4-e2b-it":             {"vram_gb": 10, "disk_gb": 10, "note": "Gemma 4 E2B"},
    "google/gemma-4-e4b-it":             {"vram_gb": 12, "disk_gb": 18, "note": "Gemma 4 E4B"},
    "Qwen/Qwen3-VL-2B-Instruct":         {"vram_gb": 8,  "disk_gb": 6,  "note": "Qwen3-VL 2B"},
    "Qwen/Qwen3-VL-4B-Instruct":         {"vram_gb": 12, "disk_gb": 10, "note": "Qwen3-VL 4B"},
    "llava-hf/llava-1.5-7b-hf":          {"vram_gb": 16, "disk_gb": 16, "note": "LLaVA-1.5 7B"},
    "microsoft/Phi-3.5-vision-instruct":  {"vram_gb": 8,  "disk_gb": 9,  "note": "Phi-3.5 Vision"},
    "HuggingFaceM4/idefics2-8b":         {"vram_gb": 20, "disk_gb": 18, "note": "IDEFICS-2 8B"},
}


def _clean_model_id(s: str) -> str:
    return s.split()[0].strip()


# ---------------------------------------------------------------------------
# Wizard state machine pages
# ---------------------------------------------------------------------------
# Landing page's Local/Remote radio-card default. The reference mockup
# (full_png/01-choose-path.png) depicts Local pre-selected — filled radio,
# accent card border, and an already-enabled accent "Continue >" button —
# rather than a blank unselected landing page. Local is also the simpler,
# no-network-setup path, so it doubles as the sensible recommended default.
_DEFAULT_SELECTED_PATH = "A"

_PAGE_LANDING = "landing"
_PAGE_PATH_A_SETUP = "path_a_setup"
_PAGE_PATH_A_DOWNLOAD = "path_a_download"
_PAGE_PATH_B_CONNECT = "path_b_connect"
_PAGE_PATH_B_LOAD = "path_b_load"
_PAGE_DONE = "done"

_STEP_NAMES   = ["Path", "Setup", "Model", "Complete"]
# Both paths share this single generic 4-column rail (design ref shows
# "Path/Setup/Model/Complete" on every page, never path-specific wording,
# and never a shrunk 3-column rail — confirmed against
# reference-path_b_connect.png, which still renders all four columns).
#
# Path B's "Connect to a remote server" page is step 2 ("Setup") on the
# rail, the same rail position as Path A's local install page — connecting
# to a remote sidecar is Path B's provisioning step, not a continuation of
# path selection. Path B walks 1 -> 2 -> (3) -> 4, mirroring Path A's
# 1 -> 2 -> 3 -> 4, though Path B skips the Load Model page (step 3) since
# a remote sidecar has no local model-loading step (issue #17).
_STEP_NAMES_B = _STEP_NAMES  # kept as a separate name for call-site clarity

_STEP_IDX = {
    _PAGE_LANDING:          0,
    _PAGE_PATH_A_SETUP:     1,
    _PAGE_PATH_B_CONNECT:   1,
    _PAGE_PATH_A_DOWNLOAD:  2,
    _PAGE_PATH_B_LOAD:      2,
    _PAGE_DONE:             3,
}

_STEP_IDX_B = _STEP_IDX  # kept as a separate name for call-site clarity

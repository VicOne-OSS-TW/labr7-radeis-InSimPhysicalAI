"""Standalone utility functions for the Model Setup Wizard."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

import omni.ui as ui

from ...vlm.sidecar_manager import _LABR7_DIR
from .. import radeis_ui as R

from ._constants import _MODEL_REQUIREMENTS

_LABR7_VENV = _LABR7_DIR / "venv"


def _probe_gpu_vram(model_repo: str) -> tuple[bool, str]:
    """Return (gpu_ok, reason_string) using the same VRAM threshold as _run_resource_check."""
    min_vram = _MODEL_REQUIREMENTS.get(model_repo, {}).get("vram_gb", 8)
    try:
        import pynvml
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        try:
            mem = pynvml.nvmlDeviceGetMemoryInfo(h)
            vram_free_gb = mem.free / 1024**3
            if vram_free_gb >= min_vram:
                return True, ""
            return False, f"Low VRAM ({vram_free_gb:.1f}/{min_vram} GB required)"
        except Exception:  # noqa: BLE001 — GB10/Blackwell unified memory
            return True, ""
    except ImportError:
        cuda_ver = _detect_cuda_version()
        if cuda_ver:
            return True, ""
        return False, "No CUDA GPU detected"
    except Exception:  # noqa: BLE001
        return False, "GPU check failed"


def _find_system_python() -> Optional[str]:
    for ver in ("3.11", "3.12", "3.10"):
        for candidate in (f"python{ver}", f"python3.{ver.split('.')[1]}"):
            try:
                r = subprocess.run([candidate, "--version"],
                                   capture_output=True, text=True, timeout=5)
                if r.returncode == 0 and ver in r.stdout + r.stderr:
                    chk = subprocess.run(
                        [candidate, "-c",
                         "import sys; sys.get_int_max_str_digits()"],
                        capture_output=True, timeout=5)
                    if chk.returncode != 0:
                        continue
                    import shutil
                    return shutil.which(candidate)
            except Exception:  # noqa: BLE001
                pass
    return None


def _detect_cuda_version() -> Optional[str]:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10)
        driver = r.stdout.strip().split("\n")[0]
        major = int(driver.split(".")[0])
        if major >= 570:
            return "12.8"
        elif major >= 550:
            return "12.4"
        elif major >= 525:
            return "12.1"
        elif major >= 450:
            return "11.8"
    except Exception:  # noqa: BLE001
        pass
    return None


def _cuda_to_torch_index(cuda_ver: Optional[str]) -> Optional[str]:
    if cuda_ver is None:
        return None
    v = float(cuda_ver)
    if v >= 12.8:
        return "cu128"
    elif v >= 12.4:
        return "cu124"
    elif v >= 12.1:
        return "cu121"
    elif v >= 11.8:
        return "cu118"
    return None


def _find_sidecar_requirements() -> str:
    candidates = [
        Path(__file__).parents[5] / "data" / "vlm_sidecar" / "requirements.txt",
        Path(__file__).parents[9] / "vlm_sidecar" / "requirements.txt",
        Path(__file__).parents[8] / "vlm_sidecar" / "requirements.txt",
        Path(__file__).parents[7] / "vlm_sidecar" / "requirements.txt",
        Path(__file__).parents[6] / "vlm_sidecar" / "requirements.txt",
        Path(__file__).parents[5] / "vlm_sidecar" / "requirements.txt",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return "requirements.txt"


def build_status_banner(kind: str, text: str = "", *, height: int = 36):
    """kind in {'ok','warn','err'}. Emits a soft-tinted status banner with a
    vertically-centered status dot and a label. Returns (bg_rect, dot_rect, label)
    so callers can restyle/relabel later. Consumers: model_download install banner,
    complete_test done banner."""
    _KIND_STYLES = {
        "ok":   (R.STYLE_WIZ_BANNER_OK,   R.STYLE_WIZ_BANNER_DOT_OK,   R.STYLE_WIZARD_OK_TEXT_MUTED),
        "warn": (R.STYLE_WIZ_BANNER_WARN, R.STYLE_WIZ_BANNER_DOT_WARN, R.STYLE_WIZARD_WARN_LABEL),
        "err":  (R.STYLE_WIZ_BANNER_ERR,  R.STYLE_WIZ_BANNER_DOT_ERR,  R.STYLE_WIZARD_ERROR_TEXT),
    }
    banner_style, dot_style, text_style = _KIND_STYLES.get(kind, _KIND_STYLES["ok"])
    with ui.ZStack(height=height):
        bg_rect = ui.Rectangle(style=banner_style)
        with ui.HStack():
            ui.Spacer(width=10)
            with ui.VStack(width=8, style={"margin": 0}):
                ui.Spacer()
                dot_rect = ui.Rectangle(width=8, height=8, style=dot_style)
                ui.Spacer()
            ui.Spacer(width=6)
            label = ui.Label(text, style=text_style, alignment=ui.Alignment.LEFT_CENTER)
    return bg_rect, dot_rect, label


def flip_button(btn, text: str, clicked_fn) -> None:
    """In-place relabel + rebind of an existing ui.Button."""
    btn.text = text
    btn.set_clicked_fn(clicked_fn)


def gate_next(btn, ready: bool, active_style: dict = None) -> None:
    """Enable/disable a Next/Finish button AND visually demote it when gated,
    so a blocked step reads as demoted, not merely disabled."""
    if active_style is None:
        active_style = R.STYLE_WIZ_BTN_PRIMARY_BASE
    btn.enabled = ready
    btn.style = active_style if ready else R.STYLE_BTN_INACTIVE

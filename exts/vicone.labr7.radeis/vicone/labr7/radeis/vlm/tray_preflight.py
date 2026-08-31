"""Predict which tray UI tier tray_agent_launcher will land on (issue #14).

Pure helper — no omni.ui / Kit imports — so the wizard can warn the user
BEFORE the tray is spawned instead of after it has already fallen into the
silent headless sleep loop. The tier-selection logic here must mirror
tray_agent_launcher.main() exactly:

    Tier 1 (pystray): only if not wayland and not gnome, and pystray imports
    Tier 2 (tkinter): needs tkinter importable and a display
    Tier 3 (headless): everything else — process alive, no UI

Probes run tkinter/pystray importability in the SAME interpreter that will
run the tray (subprocess -c "import ..."), not in Kit Python, because
python3-tk is an OS package tied to the target interpreter.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_LABR7_DIR = Path.home() / ".labr7"

_FIX_CMD_TKINTER = "sudo apt install python3-tk"
_REASON_NO_TKINTER = ("The tray needs python3-tk, which is not installed "
                      "for this environment's Python.")
_REASON_NO_DISPLAY = ("No graphical display is available (Isaac Sim may be "
                      "running over SSH without X forwarding).")


def _resolve_python(python_exe: "str | None") -> "str | None":
    """Same interpreter-resolution order as SidecarManager._resolve_tray_python()."""
    if python_exe and os.path.isfile(python_exe):
        return python_exe
    venv_py = str(_LABR7_DIR / "venv" / "bin" / "python")
    if os.path.isfile(venv_py):
        return venv_py
    return shutil.which("python3")


def _can_import(python_exe: "str | None", module: str) -> bool:
    if not python_exe:
        return False
    try:
        proc = subprocess.run(
            [python_exe, "-c", f"import {module}"],
            capture_output=True, timeout=10)
        return proc.returncode == 0
    except Exception:  # noqa: BLE001 -- probe failure == module unavailable
        return False


def check_tray_ui(python_exe: "str | None" = None) -> dict:
    """Predict the tray UI tier and return an actionable verdict.

    Returns a dict with:
        ok            bool — True unless the expected tier is "headless"
        expected_tier "pystray" | "tkinter" | "headless"
        has_tkinter / has_pystray / has_display / wayland / gnome  bool
        reason        str  — user-facing explanation ("" when ok)
        fix_cmd       str|None — shell command that fixes it, if one exists

    Never raises: any probe failure is treated as "module unavailable".
    """
    try:
        py = _resolve_python(python_exe)
        has_tkinter = _can_import(py, "tkinter")
        has_pystray = _can_import(py, "pystray")

        has_display = bool(os.environ.get("DISPLAY"))
        wayland = bool(os.environ.get("WAYLAND_DISPLAY") or
                       os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland")
        gnome = bool(os.environ.get("GNOME_DESKTOP_SESSION_ID") or
                     "gnome" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower())

        # Mirror tray_agent_launcher.main(): the wayland/gnome guard skips
        # pystray entirely; tkinter needs an X display to open its window.
        if not wayland and not gnome and has_pystray:
            expected_tier = "pystray"
        elif has_tkinter and has_display:
            expected_tier = "tkinter"
        else:
            expected_tier = "headless"

        reason = ""
        fix_cmd = None
        if expected_tier == "headless":
            if has_display and not has_tkinter:
                reason = _REASON_NO_TKINTER
                fix_cmd = _FIX_CMD_TKINTER
            elif not has_display and not wayland:
                reason = _REASON_NO_DISPLAY
            else:
                reason = "The tray window cannot be shown in this environment."

        return {
            "ok": expected_tier != "headless",
            "expected_tier": expected_tier,
            "has_tkinter": has_tkinter,
            "has_pystray": has_pystray,
            "has_display": has_display,
            "wayland": wayland,
            "gnome": gnome,
            "reason": reason,
            "fix_cmd": fix_cmd,
        }
    except Exception:  # noqa: BLE001 -- a preflight must never break the wizard
        return {
            "ok": False, "expected_tier": "headless",
            "has_tkinter": False, "has_pystray": False, "has_display": False,
            "wayland": False, "gnome": False,
            "reason": "Tray preflight check failed unexpectedly.",
            "fix_cmd": None,
        }

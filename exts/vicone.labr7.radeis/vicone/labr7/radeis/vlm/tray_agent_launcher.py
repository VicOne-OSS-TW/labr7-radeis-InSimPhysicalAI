"""Standalone tray icon process for the Radeis VLM sidecar (Path A/B).

Runs in the sidecar venv Python (NOT Kit Python) — spawned by sidecar_manager
via subprocess.  Provides system tray visibility; auto-sleep is managed by the
sidecar itself (GET/POST /sleep endpoints).  Tray death does not prevent sidecar
from shutting itself down after inactivity.

Reads ~/.labr7/sidecar_config.json at startup to determine mode (local / remote)
and active URL.  This is the same file that SidecarManager writes in Kit Python.

Usage:
    python tray_agent_launcher.py --port 8765

Display server detection:
    Linux X11  → pystray
    Linux Wayland / no display → tkinter floating window fallback
    Windows → pystray
"""
from __future__ import annotations

import argparse
import http.client
import json
import logging
import os
import signal
import sys
import tempfile
import time
import traceback
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

_LABR7_DIR = Path.home() / ".labr7"
_RUNTIME_FILE = _LABR7_DIR / "sidecar_runtime.json"
_TRAY_PID_FILE = _LABR7_DIR / "tray.pid"
_CONFIG_FILE = Path.home() / ".labr7" / "sidecar_config.json"
_LOG_FILE = _LABR7_DIR / "logs" / "tray_agent.log"
_STATUS_FILE = _LABR7_DIR / "tray_status.json"

_DEFAULT_TIMEOUT = 600  # 10 minutes


# ---------------------------------------------------------------------------
# Observability: file logger + status file (issue #14 — tray fell into the
# silent tier-3 sleep loop with zero UI and zero logs whenever both pystray
# and tkinter were unavailable; is_tray_alive() saw a live PID and reported
# everything fine).  Neither of these may ever raise out into the launcher —
# a broken log dir/disk must not prevent the tray (or its headless fallback)
# from starting.
# ---------------------------------------------------------------------------

def _make_logger() -> logging.Logger:
    logger = logging.getLogger("radeis.tray_agent")
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        # Idempotent: the logger is process-global, so a re-import of this
        # module (e.g. loaded both as __main__ and as a package module) must
        # not stack a second FileHandler — every record would then be written
        # once per handler (observed as 5x-duplicated lines in the field).
        return logger
    try:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(_LOG_FILE, mode="a")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s pid=%(process)d %(levelname)s %(message)s"))
        logger.addHandler(handler)
    except Exception:  # noqa: BLE001 -- unwritable log dir must not be fatal
        logger.addHandler(logging.NullHandler())
    return logger


_log = _make_logger()


def _write_tray_status(tier: str, error: "str | None" = None, hint: "str | None" = None) -> None:
    """Atomically write ~/.labr7/tray_status.json (temp file + os.replace).

    Called at process start (tier="starting", so a stale file from a killed
    previous run can't be misread as this run's state), whenever a tier
    successfully begins serving (tier="pystray"/"tkinter"), and right before
    falling into the silent tier-3 loop (tier="headless").
    """
    payload = {
        "tier": tier,
        "error": error,
        "hint": hint,
        "pid": os.getpid(),
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        _STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(_STATUS_FILE.parent), prefix=".tray_status_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f)
            os.replace(tmp_path, _STATUS_FILE)
        except Exception:
            try:
                os.unlink(tmp_path)
            except Exception:  # noqa: BLE001
                pass
            raise
    except Exception:  # noqa: BLE001 -- status file is best-effort observability
        _log.debug("Failed to write tray_status.json", exc_info=True)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _read_runtime() -> dict:
    try:
        with open(_RUNTIME_FILE) as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _read_config() -> dict:
    try:
        with open(_CONFIG_FILE) as f:
            data = json.load(f)
        if "installations" in data:
            active_key = data.get("active", "")
            installs = data["installations"]
            entry = installs.get(active_key) or next(iter(installs.values()), {})
            return entry
        return data  # backward compat: old flat format
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def _sidecar_url(cfg: dict, port: int) -> str:
    """Active sidecar base URL (no trailing slash)."""
    if cfg.get("mode") == "remote" and cfg.get("remote_url"):
        return cfg["remote_url"].rstrip("/")
    return f"http://127.0.0.1:{port}"


def _launcher_url_from(sid_url: str, cfg: dict) -> str:
    """Derive launcher daemon URL: same host as sidecar, port+1."""
    p = urlparse(sid_url)
    lport = cfg.get("launcher_port", (p.port or 8765) + 1)
    return f"{p.scheme}://{p.hostname}:{lport}"


# ---------------------------------------------------------------------------
# Health / stop / wake
# ---------------------------------------------------------------------------

_healthz_conn: "http.client.HTTPConnection | None" = None
_healthz_conn_key: tuple | None = None


def _get_healthz_conn(scheme: str, host: str, port: int) -> http.client.HTTPConnection:
    """Return the persistent HTTP(S) connection for (scheme, host, port).

    Reused across calls so repeated polling (tkinter _refresh() / pystray
    _status(), both on a 1s cadence) does not churn a new ephemeral client
    port per request. Replaced if the target endpoint changes.
    """
    global _healthz_conn, _healthz_conn_key
    key = (scheme, host, port)
    if _healthz_conn is not None and _healthz_conn_key != key:
        try:
            _healthz_conn.close()
        except Exception:  # noqa: BLE001
            pass
        _healthz_conn = None
    if _healthz_conn is None:
        conn_cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
        _healthz_conn = conn_cls(host, port, timeout=3)
        _healthz_conn_key = key
    return _healthz_conn


def _reset_healthz_conn():
    global _healthz_conn, _healthz_conn_key
    if _healthz_conn is not None:
        try:
            _healthz_conn.close()
        except Exception:  # noqa: BLE001
            pass
    _healthz_conn = None
    _healthz_conn_key = None


def _healthz_data(sidecar_url: str) -> dict:
    p = urlparse(sidecar_url)
    scheme = p.scheme or "http"
    port = p.port or (443 if scheme == "https" else 80)
    path = f"{p.path.rstrip('/')}/healthz" if p.path else "/healthz"
    # Retry once on a fresh connection in case the reused socket died
    # (server restart, idle timeout, etc.) since the last poll.
    for attempt in range(2):
        try:
            conn = _get_healthz_conn(scheme, p.hostname, port)
            conn.request("GET", path)
            resp = conn.getresponse()
            body = resp.read()
            if resp.status != 200:
                raise http.client.HTTPException(f"status {resp.status}")
            return json.loads(body)
        except Exception:  # noqa: BLE001
            _reset_healthz_conn()
    return {}


def _healthz(sidecar_url: str) -> bool:
    return _healthz_data(sidecar_url).get("status") == "ok"


def _stop_sidecar_local():
    rt = _read_runtime()
    port = rt.get("port", 8765)
    # Try HTTP /shutdown first — reliable even when PID is a debugpy/wrapper process
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/shutdown",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            if json.loads(r.read()).get("ok", False):
                _RUNTIME_FILE.unlink(missing_ok=True)
                (_LABR7_DIR / "sidecar.lock").unlink(missing_ok=True)
                return
    except Exception:  # noqa: BLE001
        pass
    # Fallback: SIGTERM on the recorded PID
    pid = rt.get("pid")
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:  # noqa: BLE001
            pass
        else:
            # Wait up to 3 s for graceful shutdown; force-kill if still alive
            for _ in range(30):
                time.sleep(0.1)
                try:
                    os.kill(pid, 0)  # probe: raises if process is gone
                except (ProcessLookupError, PermissionError):
                    break  # process exited cleanly
            else:
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:  # noqa: BLE001
                    pass
    _RUNTIME_FILE.unlink(missing_ok=True)
    (_LABR7_DIR / "sidecar.lock").unlink(missing_ok=True)


def _stop_sidecar_remote(launcher_url: str, sidecar_url: str = "") -> bool:
    """Stop remote sidecar: /shutdown direct first (reliable), then launcher /stop for cleanup."""
    # Direct /shutdown is always reliable — works regardless of launcher pid-file state
    # (e.g. sidecar started manually outside setup script).
    if sidecar_url:
        req = urllib.request.Request(
            f"{sidecar_url}/shutdown",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                if json.loads(r.read()).get("ok", False):
                    # Also ask launcher to clean up its pid file (fire-and-forget)
                    try:
                        urllib.request.urlopen(
                            urllib.request.Request(
                                f"{launcher_url}/stop",
                                data=b"{}",
                                headers={"Content-Type": "application/json"},
                                method="POST",
                            ), timeout=3)
                    except Exception:  # noqa: BLE001
                        pass
                    return True
        except Exception:  # noqa: BLE001
            pass
    # Sidecar unreachable — try launcher as last resort
    req2 = urllib.request.Request(
        f"{launcher_url}/stop",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req2, timeout=5) as r:
            return json.loads(r.read()).get("ok", False)
    except Exception:  # noqa: BLE001
        pass
    return False


def _stop_sidecar(cfg: dict, launcher_url: str):
    # Determine local vs remote from the actual URL hostname, not from config mode.
    # config.mode may lag behind if the user switched IP without re-running the wizard.
    p = urlparse(launcher_url)
    is_local = p.hostname in ("127.0.0.1", "localhost", "::1", None)
    if is_local:
        _stop_sidecar_local()
    else:
        # Derive sid_url from launcher_url (same host, launcher is always sidecar_port+1)
        lport = p.port or 8766
        sid_url = f"{p.scheme}://{p.hostname}:{lport - 1}"
        _stop_sidecar_remote(launcher_url, sid_url)


# ---------------------------------------------------------------------------
# pystray implementation (X11 / Windows)
# ---------------------------------------------------------------------------
def _run_pystray(port: int, timeout: int, cfg: dict):
    import pystray
    from PIL import Image as PILImage, ImageDraw

    _state = {
        "sid_url": _sidecar_url(cfg, port),
        "lnch_url": _launcher_url_from(_sidecar_url(cfg, port), cfg),
    }

    _icon_holder = [None]

    def _do_quit():
        _TRAY_PID_FILE.unlink(missing_ok=True)
        _stop_sidecar(cfg, _state["lnch_url"])
        if _icon_holder[0]:
            _icon_holder[0].stop()
        sys.exit(0)

    def _make_icon_image():
        img = PILImage.new("RGB", (64, 64), color=(30, 30, 30))
        d = ImageDraw.Draw(img)
        d.ellipse([4, 4, 60, 60], fill=(232, 28, 109))
        try:
            from PIL import ImageFont
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
            d.text((32, 32), "R7", fill="white", font=font, anchor="mm")
        except Exception:  # noqa: BLE001
            d.text((16, 18), "R7", fill="white")
        return img

    def _status(icon, _item):
        up = _healthz(_state["sid_url"])
        icon.title = f"Sidecar {'UP' if up else 'DOWN'} | {_state['sid_url']}"

    def _do_open_log(icon, _item):
        rt = _read_runtime()
        log_file = rt.get("log_file")
        log_dir = _LABR7_DIR / "logs"
        target: str
        if log_file and Path(log_file).exists():
            target = log_file
        else:
            try:
                recent = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
                target = str(recent[0]) if recent else str(log_dir)
            except Exception:
                target = str(log_dir)
        try:
            import subprocess as _sp
            _sp.Popen(["xdg-open", target])
        except Exception:  # noqa: BLE001
            pass

    # Build menu -----------------------------------------------------------
    core_items = [
        pystray.MenuItem("Open Log", _do_open_log),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Stop & Quit", lambda icon, item: _do_quit()),
    ]
    menu = pystray.Menu(*core_items)
    icon = pystray.Icon("radeis-sidecar", _make_icon_image(), "Radeis Inference Server", menu)
    _icon_holder[0] = icon
    _write_tray_status("pystray")
    _log.info("pystray tray running (tier 1)")
    icon.run()
    _stop_sidecar(cfg, _state["lnch_url"])
    sys.exit(0)


# ---------------------------------------------------------------------------
# tkinter fallback (Wayland / headless with DISPLAY)
# ---------------------------------------------------------------------------
def _run_tkinter(port: int, timeout: int, cfg: dict):
    import tkinter as tk

    _url_state = {
        "sid_url": _sidecar_url(cfg, port),
        "lnch_url": _launcher_url_from(_sidecar_url(cfg, port), cfg),
    }

    root = tk.Tk()
    root.title("Radeis Inference Server")
    root.geometry("320x175+20+20")
    root.resizable(False, False)
    root.configure(bg="#1e1e1e")

    lbl_status = tk.Label(root, text="", bg="#1e1e1e", fg="#e8e8e8", font=("Helvetica", 10))
    lbl_status.pack(pady=(12, 2))
    lbl_ip = tk.Label(root, text="", bg="#1e1e1e", fg="#aaaaaa", font=("Helvetica", 9))
    lbl_ip.pack(pady=1)
    lbl_pid = tk.Label(root, text="", bg="#1e1e1e", fg="#aaaaaa", font=("Helvetica", 9))
    lbl_pid.pack(pady=1)
    lbl_timer = tk.Label(root, text="", bg="#1e1e1e", fg="#aaaaaa", font=("Helvetica", 9))
    lbl_timer.pack(pady=(1, 4))

    btn_frame = tk.Frame(root, bg="#1e1e1e")
    btn_frame.pack(pady=8)

    def _do_open_log_tk():
        rt = _read_runtime()
        log_file = rt.get("log_file")
        log_dir = _LABR7_DIR / "logs"
        if log_file and Path(log_file).exists():
            target = log_file
        else:
            try:
                recent = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
                target = str(recent[0]) if recent else str(log_dir)
            except Exception:
                target = str(log_dir)
        try:
            import subprocess as _sp
            _sp.Popen(["xdg-open", target])
        except Exception:  # noqa: BLE001
            pass

    tk.Button(btn_frame, text="Open Log", command=_do_open_log_tk,
              bg="#333", fg="white", relief="flat", padx=8).pack(side="left", padx=4)
    tk.Button(btn_frame, text="Stop & Quit", command=lambda: _do_close(),
              bg="#333", fg="white", relief="flat", padx=8).pack(side="left", padx=4)

    _closed = [False]

    def _do_close():
        if _closed[0]:
            return
        _closed[0] = True
        _TRAY_PID_FILE.unlink(missing_ok=True)
        _stop_sidecar(cfg, _url_state["lnch_url"])
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _do_close)

    # Refresh loop ---------------------------------------------------------
    def _refresh():
        # Pick up URL changes written by the extension (e.g. user switched IP)
        current_cfg = _read_config()
        current_sid_url = _sidecar_url(current_cfg, port)
        if current_sid_url != _url_state["sid_url"]:
            _url_state["sid_url"] = current_sid_url
            _url_state["lnch_url"] = _launcher_url_from(current_sid_url, current_cfg)

        hdata = _healthz_data(_url_state["sid_url"])
        up = hdata.get("status") == "ok"
        lbl_status.config(text=f"Status: {'Up' if up else 'Down'}")
        lbl_ip.config(text=f"IP: {_url_state['sid_url']}")

        # PID: prefer server-reported (works for remote), fall back to local runtime file
        pid = hdata.get("pid") or (_read_runtime() or {}).get("pid")
        lbl_pid.config(text=f"PID: {pid}" if pid else "PID: —")

        lbl_timer.config(text="Running indefinitely")

        root.after(1000, _refresh)

    _write_tray_status("tkinter")
    _log.info("tkinter tray running (tier 2)")
    _refresh()
    root.mainloop()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--timeout", type=int, default=_DEFAULT_TIMEOUT)
    args = ap.parse_args()

    # Overwrite any stale status left by a previous (possibly killed) run
    # before doing anything else, so a crash-before-write can never be
    # misread as this run's state.
    _write_tray_status("starting")

    cfg = _read_config()

    display = os.environ.get("DISPLAY", "")
    wayland_display = os.environ.get("WAYLAND_DISPLAY", "")
    session_type = os.environ.get("XDG_SESSION_TYPE", "")
    current_desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    _log.info(
        "Startup env: DISPLAY=%r WAYLAND_DISPLAY=%r XDG_SESSION_TYPE=%r "
        "XDG_CURRENT_DESKTOP=%r", display, wayland_display, session_type, current_desktop)

    # Detect display server; also skip pystray on GNOME (XEmbed menus broken)
    wayland = bool(wayland_display or session_type.lower() == "wayland")
    gnome = bool(os.environ.get("GNOME_DESKTOP_SESSION_ID") or
                 "gnome" in current_desktop.lower())

    if not wayland and not gnome:
        _log.info("Attempting tier 1 (pystray)")
        try:
            _run_pystray(args.port, args.timeout, cfg)
            return
        except Exception:  # noqa: BLE001
            _log.error("pystray tier failed:\n%s", traceback.format_exc())
            # fall through to tkinter
    else:
        _log.info(
            "Skipping tier 1 (pystray): wayland=%s gnome=%s "
            "(GNOME XEmbed menus are broken, so pystray is guarded off)",
            wayland, gnome)

    _log.info("Attempting tier 2 (tkinter)")
    try:
        _run_tkinter(args.port, args.timeout, cfg)
    except Exception as exc:  # noqa: BLE001
        _log.error("tkinter tier failed:\n%s", traceback.format_exc())
        hint = None
        if isinstance(exc, ModuleNotFoundError) and getattr(exc, "name", "") in ("tkinter", "_tkinter"):
            # ASCII " - " (not em dash): this hint is rendered by omni.ui on
            # the wizard Done page, and Kit's bundled font has no U+2014.
            hint = "python3-tk is not installed on this machine - run: sudo apt install python3-tk"
        _log.warning(
            "Falling through to tier 3 (headless): process stays alive with no UI, "
            "hint=%r", hint)
        _write_tray_status("headless", error=str(exc), hint=hint)
        # No display — sidecar manages its own shutdown; tray just waits
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""radeis-launcher — lightweight daemon that wakes the Radeis VLM sidecar on demand.

Run once on the remote GPU machine (e.g. via systemd or nohup) so the Isaac Sim
extension can POST /wake to start server.py without needing SSH access.

API:
  GET  /healthz   → {"status": "ok", "owner": "radeis-launcher"}
  GET  /status    → {"sidecar_running": bool, "pid": int|null}
  POST /wake      → body (all optional): {"port": 8765, "model_path": "...", "device": "cuda"}
                    response: {"ok": bool, "pid": int, "already_running": bool}

Deps: stdlib only (http.server, subprocess, json, os, pathlib, time).
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

_LABR7_DIR = Path.home() / ".labr7"
_PID_FILE = _LABR7_DIR / "sidecar.pid"
_LOG_DIR = _LABR7_DIR / "logs"
SCRIPT_DIR = Path(__file__).parent

_GEMMA_REPO_NAMES = [
    "models--google--gemma-4-e2b-it",
    "models--google--gemma-3-4b-it",
    "models--google--gemma-2-2b-it",
]


def _find_default_model_path() -> str | None:
    """Return the newest snapshot of any gemma model in the local HF cache."""
    hf_cache = Path.home() / ".cache" / "huggingface" / "hub"
    for repo in _GEMMA_REPO_NAMES:
        snapshots = hf_cache / repo / "snapshots"
        if snapshots.is_dir():
            snaps = sorted(snapshots.iterdir())
            if snaps:
                return str(snaps[-1])
    return None


# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------

def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except Exception:  # noqa: BLE001
        return False


def _sidecar_pid() -> int | None:
    if not _PID_FILE.exists():
        return None
    try:
        pid = int(_PID_FILE.read_text().strip())
        return pid if _pid_alive(pid) else None
    except Exception:  # noqa: BLE001
        return None


def _sidecar_pid_verified(port: int) -> int | None:
    """Like _sidecar_pid() but also verifies server.py is responding on the port.

    If the PID appears alive but the sidecar doesn't answer /healthz, we treat
    it as stale: SIGTERM the zombie, remove the PID file, return None so the
    caller spawns a fresh sidecar.
    """
    import urllib.request as _ur
    pid = _sidecar_pid()
    if pid is None:
        return None
    try:
        with _ur.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as r:
            d = json.loads(r.read())
            if d.get("owner") == "radeis-sidecar":
                return pid
    except Exception:  # noqa: BLE001
        pass
    # PID alive but sidecar not actually responding — clean up stale state
    try:
        os.kill(pid, signal.SIGTERM)
    except Exception:  # noqa: BLE001
        pass
    _PID_FILE.unlink(missing_ok=True)
    return None


def _spawn_sidecar(port: int, model_path: str | None,
                   device: str, token: str | None) -> int:
    venv_py = str(_LABR7_DIR / "venv" / "bin" / "python")
    server_py = str(SCRIPT_DIR / "server.py")
    cmd = [venv_py, server_py,
           "--host", "0.0.0.0", "--port", str(port), "--device", device]
    # Use the provided path only if it actually exists on this machine;
    # otherwise fall back to auto-detection from the local HF cache.
    resolved = (model_path if (model_path and Path(model_path).is_dir())
                else None) or _find_default_model_path()
    if resolved:
        cmd += ["--model", resolved]
    if token:
        cmd += ["--token", token]

    _LABR7_DIR.mkdir(parents=True, exist_ok=True)
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    log_fh = open(_LOG_DIR / f"sidecar_{ts}.log", "w")  # noqa: WPS515
    proc = subprocess.Popen(cmd, stdout=log_fh, stderr=log_fh,
                            start_new_session=True)
    _PID_FILE.write_text(str(proc.pid))
    return proc.pid


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # silence default access log
        pass

    def _send(self, code: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path == "/healthz":
            self._send(200, {"status": "ok", "owner": "radeis-launcher"})
        elif self.path == "/status":
            pid = _sidecar_pid()
            self._send(200, {"sidecar_running": pid is not None, "pid": pid})
        elif self.path.startswith("/log"):
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            n = min(int(qs.get("lines", ["20"])[0]), 100)
            try:
                logs = sorted(_LOG_DIR.glob("sidecar_*.log"),
                              key=lambda p: p.stat().st_mtime, reverse=True)
                if logs:
                    lines = logs[0].read_text(errors="replace").splitlines()
                    self._send(200, {"log": lines[-n:], "file": logs[0].name})
                else:
                    self._send(200, {"log": [], "file": None})
            except Exception as e:  # noqa: BLE001
                self._send(500, {"error": str(e)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path == "/stop":
            pid = _sidecar_pid()
            try:
                if pid is not None:
                    os.kill(pid, signal.SIGTERM)
                _PID_FILE.unlink(missing_ok=True)
                self._send(200, {"ok": True})
            except Exception as e:  # noqa: BLE001
                self._send(500, {"ok": False, "error": str(e)})
            return

        if self.path != "/wake":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", 0))
        body: dict = json.loads(self.rfile.read(length) or b"{}")

        port = int(body.get("port", 8765))
        model_path = body.get("model_path") or body.get("model")
        device = body.get("device", "cuda")
        token = body.get("token")

        existing = _sidecar_pid_verified(port)
        if existing is not None:
            self._send(200, {"ok": True, "pid": existing, "already_running": True})
            return

        try:
            pid = _spawn_sidecar(port, model_path, device, token)
            self._send(200, {"ok": True, "pid": pid, "already_running": False})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"ok": False, "error": str(e)})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Radeis launcher daemon")
    ap.add_argument("--host", default="0.0.0.0", help="Bind address")
    ap.add_argument("--port", type=int, default=8766,
                    help="Launcher port (default: sidecar_port + 1 = 8766)")
    args = ap.parse_args()

    print(f"[radeis-launcher] Listening on {args.host}:{args.port}", flush=True)
    try:
        HTTPServer((args.host, args.port), _Handler).serve_forever()
    except KeyboardInterrupt:
        print("[radeis-launcher] Stopped.", flush=True)
        sys.exit(0)


if __name__ == "__main__":
    main()

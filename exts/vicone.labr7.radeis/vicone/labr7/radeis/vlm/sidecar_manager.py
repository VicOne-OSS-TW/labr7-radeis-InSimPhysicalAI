"""Sidecar process lifecycle and config management.

Owns: subprocess spawn, lock file, runtime state (~/.labr7/), config r/w
(${app_user_data}/labr7_radeis/sidecar_config.json), readiness polling, and
tray icon spawn.  Uses SidecarClient for all HTTP probes — never opens raw
sockets directly.

This module runs inside Kit Python (stdlib only for the process/file layer).
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from enum import IntEnum
from pathlib import Path
from typing import Optional

from .sidecar_client import SidecarClient, _fmt_net_err

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_LABR7_DIR = Path.home() / ".labr7"
_LOCK_FILE = _LABR7_DIR / "sidecar.lock"
_RUNTIME_FILE = _LABR7_DIR / "sidecar_runtime.json"
_TRAY_PID_FILE = _LABR7_DIR / "tray.pid"
_LOG_DIR = _LABR7_DIR / "logs"
_REGISTRY_FILE = _LABR7_DIR / "model_registry.json"
_CONFIG_FILE = _LABR7_DIR / "sidecar_config.json"
_TRAY_STATUS_FILE = _LABR7_DIR / "tray_status.json"
_TRAY_LOG_FILE = _LOG_DIR / "tray_agent.log"


def _config_path() -> Path:
    return _CONFIG_FILE


# ---------------------------------------------------------------------------
# Readiness levels
# ---------------------------------------------------------------------------
class ReadinessLevel(IntEnum):
    OFFLINE = 0
    LOADING = 1
    CONNECTED = 2
    READY = 3


# ---------------------------------------------------------------------------
# Config schema helpers
# ---------------------------------------------------------------------------
_CONFIG_DEFAULTS = {
    "mode": "local",
    "python_exe": None,
    "venv_managed": False,
    "model_repo": "google/gemma-4-e2b-it",
    "model_path": None,
    "port": 8765,
    "remote_url": None,
    "remote_token": None,
    "device": "cuda",
    "setup_complete": False,
}


# ---------------------------------------------------------------------------
# SidecarManager
# ---------------------------------------------------------------------------
class SidecarManager:
    """Single-instance manager; create once per Extension lifetime."""

    def __init__(self, ext_path: str):
        self._ext_path = ext_path
        self._cfg: dict = dict(_CONFIG_DEFAULTS)
        self._client: Optional[SidecarClient] = None
        self._active_url: str = ""
        self._readiness: ReadinessLevel = ReadinessLevel.OFFLINE
        self._last_resources: dict = {}
        self._tray_missing_interp_warned = False
        self._tray_disabled = False
        self._tray_fast_exit_count = 0

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------
    def load_config(self) -> bool:
        """Return True if a completed wizard config was found."""
        p = _config_path()
        if not p.exists():
            return False
        try:
            with open(p) as f:
                data = json.load(f)
            if "installations" in data:
                active_key = data.get("active", "")
                installs = data["installations"]
                entry = installs.get(active_key) or next(iter(installs.values()), {})
            else:
                entry = data  # backward compat: old flat format
            self._cfg.update(entry)
            self._rebuild_client()
            return bool(self._cfg.get("setup_complete"))
        except Exception:  # noqa: BLE001
            return False

    def save_config(self, updates: dict):
        if "model_path" in updates and updates["model_path"]:
            updates = dict(updates)
            updates["model_path"] = _to_home_relative(updates["model_path"])
        self._cfg.update(updates)

        model_repo = self._cfg.get("model_repo", "")
        if self._cfg.get("mode") == "remote":
            base = self._cfg.get("remote_url") or "remote"
        else:
            port = self._cfg.get("port", 8765)
            base = f"http://127.0.0.1:{port}"
        key = f"{base}::{model_repo}" if model_repo else base

        p = _config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        file_data: dict = {"active": key, "installations": {}}
        if p.exists():
            try:
                with open(p) as f:
                    existing = json.load(f)
                if "installations" in existing:
                    file_data["installations"] = existing["installations"]
                else:
                    # Migrate old flat format into keyed entry
                    if existing.get("mode") == "remote":
                        old_base = existing.get("remote_url") or "remote"
                    else:
                        old_port = existing.get("port", 8765)
                        old_base = f"http://127.0.0.1:{old_port}"
                    old_model = existing.get("model_repo", "")
                    old_key = f"{old_base}::{old_model}" if (old_base and old_model) else old_base
                    if old_key:
                        file_data["installations"][old_key] = existing
            except Exception:  # noqa: BLE001
                pass

        _REMOTE_ONLY = {"remote_url", "remote_token"}
        _LOCAL_ONLY  = {"python_exe", "venv_managed", "model_path", "port", "device"}
        entry = {k: v for k, v in self._cfg.items()
                 if not (self._cfg.get("mode") == "local" and k in _REMOTE_ONLY)
                 and not (self._cfg.get("mode") == "remote" and k in _LOCAL_ONLY)}
        file_data["installations"][key] = entry
        file_data["active"] = key

        with open(p, "w") as f:
            json.dump(file_data, f, indent=2)
        # Restrict to owner read/write only — file contains credentials (HF token).
        try:
            os.chmod(p, 0o600)
        except Exception:  # noqa: BLE001
            pass
        self._rebuild_client()
        self._push_carb_setting()

    def get_installations(self) -> dict:
        """Return all stored installations keyed by URL or 'local'."""
        p = _config_path()
        if not p.exists():
            return {}
        try:
            with open(p) as f:
                data = json.load(f)
            return data.get("installations", {})
        except Exception:  # noqa: BLE001
            return {}

    def _rebuild_client(self):
        url = self._effective_url()
        # remote_token is only for Path B (remote server); local sidecar runs unauthenticated
        token = self._cfg.get("remote_token") if self._cfg.get("mode") == "remote" else None
        self._client = SidecarClient(base_url=url, token=token)
        self._active_url = url

    def _effective_url(self) -> str:
        if self._cfg.get("mode") == "remote" and self._cfg.get("remote_url"):
            return self._cfg["remote_url"]
        port = self._cfg.get("port", 8765)
        return f"http://127.0.0.1:{port}"

    def _push_carb_setting(self):
        try:
            import carb
            carb.settings.get_settings().set(
                "/exts/vicone.labr7.radeis/sidecar_url", self._active_url)
        except Exception:  # noqa: BLE001
            pass

    def override_url(self, url: str):
        """Session-only URL override (not persisted)."""
        token = self._cfg.get("remote_token")
        self._client = SidecarClient(base_url=url, token=token)
        self._active_url = url
        self._push_carb_setting()

    # ------------------------------------------------------------------
    # Model / URL registry  (~/.labr7/model_registry.json)
    # ------------------------------------------------------------------
    def _load_registry(self) -> dict:
        try:
            if _REGISTRY_FILE.exists():
                data = json.loads(_REGISTRY_FILE.read_text())
                # Migrate old flat format {urls: [...], models: [...]} → url_models
                if "urls" in data and "url_models" not in data:
                    data = {
                        "url_models": {u: [] for u in data.get("urls", [])},
                        "models": data.get("models", []),
                    }
                return data
        except Exception:  # noqa: BLE001
            pass
        return {"url_models": {}, "models": []}

    def _save_registry(self, reg: dict):
        try:
            _REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
            _REGISTRY_FILE.write_text(json.dumps(reg, indent=2))
        except Exception:  # noqa: BLE001
            pass

    def register_pair(self, url: str, model: str):
        """Persist a confirmed URL+model pair.

        URL keys are ordered most-recent first (max 10).
        Per-URL model list is most-recent first (max 10).
        Global models list is most-recent first (max 20, used as fallback).
        """
        if not url or not url.startswith("http"):
            return
        model = (model or "").split()[0].strip()
        reg = self._load_registry()
        url_models: dict = reg.get("url_models", {})

        # Update per-URL model list
        models_for_url = list(url_models.get(url, []))
        if model:
            if model in models_for_url:
                models_for_url.remove(model)
            models_for_url.insert(0, model)
        url_models[url] = models_for_url[:10]

        # Keep URL order: most-recently used first
        ordered: dict = {url: url_models[url]}
        for k, v in url_models.items():
            if k != url:
                ordered[k] = v
        reg["url_models"] = ordered

        # Update global models fallback list
        if model:
            global_models = reg.get("models", [])
            if model in global_models:
                global_models.remove(model)
            global_models.insert(0, model)
            reg["models"] = global_models[:20]

        self._save_registry(reg)

    def deregister_url(self, url: str):
        """Remove a URL (and its model list) from the registry (called on Forget)."""
        if not url:
            return
        reg = self._load_registry()
        url_models = reg.get("url_models", {})
        if url in url_models:
            del url_models[url]
            reg["url_models"] = url_models
            self._save_registry(reg)

    def get_registered_urls(self) -> list:
        return list(self._load_registry().get("url_models", {}).keys())

    def get_registered_models(self) -> list:
        """Global model list — used as fallback when no URL is selected."""
        return self._load_registry().get("models", [])

    def get_models_for_url(self, url: str) -> list:
        """Return models previously confirmed at this URL (most-recent first)."""
        return list(self._load_registry().get("url_models", {}).get(url, []))

    def _purge_local_urls(self):
        """Remove localhost/127.0.0.1 entries from the registry; keep remote entries."""
        from urllib.parse import urlparse
        reg = self._load_registry()
        url_models = reg.get("url_models", {})
        kept = {u: v for u, v in url_models.items()
                if urlparse(u).hostname not in ("127.0.0.1", "localhost", "::1")}
        if len(kept) != len(url_models):
            reg["url_models"] = kept
            self._save_registry(reg)

    def _launcher_url(self) -> str:
        """Derive launcher daemon URL: same host as sidecar, port+1."""
        from urllib.parse import urlparse
        p = urlparse(self._active_url)
        launcher_port = self._cfg.get("launcher_port", (p.port or 8765) + 1)
        return f"{p.scheme}://{p.hostname}:{launcher_port}"

    def fetch_remote_log(self, lines: int = 8) -> list:
        """Fetch the last N lines of the remote sidecar log via launcher /log.

        Returns a list of strings, or [] on any failure.
        """
        import json as _json
        import urllib.request
        url = self._launcher_url() + f"/log?lines={lines}"
        try:
            with urllib.request.urlopen(url, timeout=5.0) as r:
                return _json.loads(r.read().decode()).get("log", [])
        except Exception:  # noqa: BLE001
            return []

    def wake_remote(self) -> tuple[bool, str]:
        """POST /wake to the launcher daemon on the remote machine.

        Returns (True, "") on success, (False, error_message) otherwise.
        Requires launcher.py to be running on the remote host at port+1.
        """
        import json as _json
        import urllib.request
        url = self._launcher_url() + "/wake"
        payload = {
            "port": self._cfg.get("port", 8765),
            "model_path": _resolve_model_path(self._cfg.get("model_path")),
            "device": "cuda",
        }
        data = _json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10.0) as r:
                resp = _json.loads(r.read().decode())
            if resp.get("ok"):
                return True, ""
            return False, resp.get("error", "wake failed")
        except Exception as e:  # noqa: BLE001
            return False, _fmt_net_err(e)

    @property
    def active_url(self) -> str:
        return self._active_url

    @property
    def config(self) -> dict:
        return dict(self._cfg)

    # ------------------------------------------------------------------
    # Readiness probing
    # ------------------------------------------------------------------
    def probe_readiness(self) -> ReadinessLevel:
        if self._client is None:
            self._readiness = ReadinessLevel.OFFLINE
            return self._readiness
        h = self._client.health(timeout=4.0)
        if "error" in h or h.get("status") != "ok":
            self._readiness = ReadinessLevel.OFFLINE
            return self._readiness
        if not h.get("loaded"):
            self._readiness = ReadinessLevel.LOADING
            return self._readiness
        res = self._client.resources(timeout=5.0)
        # Accept READY if either VRAM data OR gpu_name is present.
        # GB10 unified-memory GPUs return gpu_name but gpu_vram_total_gb=None
        # because nvmlDeviceGetMemoryInfo raises NVMLError_NotSupported there.
        if "error" not in res and (
            res.get("gpu_vram_total_gb") is not None
            or res.get("gpu_name") is not None
        ):
            self._last_resources = res
            self._readiness = ReadinessLevel.READY
        else:
            self._readiness = ReadinessLevel.CONNECTED
        return self._readiness

    def get_vram(self) -> dict:
        return dict(self._last_resources)

    @property
    def readiness(self) -> ReadinessLevel:
        return self._readiness

    @property
    def client(self) -> Optional[SidecarClient]:
        return self._client

    # ------------------------------------------------------------------
    # Process lifecycle (Path A — local only)
    # ------------------------------------------------------------------
    def is_sidecar_running(self) -> bool:
        rt = self._read_runtime()
        if not rt:
            return False
        pid = rt.get("pid")
        if not pid:
            return False
        if not _pid_alive(pid):
            _RUNTIME_FILE.unlink(missing_ok=True)
            return False
        h = self._client.health(timeout=3.0) if self._client else {}
        return h.get("owner") == "radeis-sidecar"

    def spawn_sidecar(self) -> tuple[bool, str]:
        """Spawn the local sidecar process. Returns (ok, error_message).

        model_path is optional — omit to start the server without preloading a
        model (useful during wizard setup when the model hasn't been downloaded yet).
        """
        if _LOCK_FILE.exists():
            rt = self._read_runtime()
            if rt and _pid_alive(rt.get("pid", 0)):
                h = self._client.health(timeout=2.0) if self._client else {}
                if h.get("owner") == "radeis-sidecar":
                    return False, "Inference server already running (lock file present)"
                # PID alive but not our sidecar — stale lock from a crashed process
                _LOCK_FILE.unlink(missing_ok=True)
                _RUNTIME_FILE.unlink(missing_ok=True)
        model_path = _resolve_model_path(self._cfg.get("model_path"))
        python_exe = self._cfg.get("python_exe")
        if not python_exe:
            python_exe = str(_LABR7_DIR / "venv" / "bin" / "python")
        if not os.path.isfile(python_exe):
            return False, "Local inference server not installed - run the Setup Wizard"
        server_py = _find_server_py(self._ext_path)
        port = self._cfg.get("port", 8765)

        device = self._cfg.get("device", "cuda")
        cmd = [python_exe, server_py,
               "--host", "127.0.0.1",
               "--port", str(port),
               "--device", device]
        if model_path:
            cmd += ["--model", model_path]

        _LABR7_DIR.mkdir(parents=True, exist_ok=True)
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        _LOCK_FILE.touch()
        ts = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
        log_file = _LOG_DIR / f"sidecar_{ts}.log"

        env = dict(os.environ)

        try:
            log_fh = open(log_file, "w")
            proc = _popen_undebugged(
                cmd,
                stdout=log_fh, stderr=log_fh,
                start_new_session=True,
                env=env,
            )
        except Exception as e:  # noqa: BLE001
            _LOCK_FILE.unlink(missing_ok=True)
            return False, str(e)

        runtime = {
            "pid": proc.pid,
            "port": port,
            "command": cmd,
            "log_file": str(log_file),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model_path": model_path,
            "model_repo": self._cfg.get("model_repo", ""),
            "owner": "radeis-extension",
        }
        with open(_RUNTIME_FILE, "w") as f:
            json.dump(runtime, f, indent=2)
        return True, ""

    def stop_sidecar(self):
        if self._cfg.get("mode") == "remote":
            # Remote sidecar: can't os.kill a PID on another machine.
            # Send POST /shutdown over HTTP so the sidecar terminates itself.
            client = self.client
            if client is not None:
                try:
                    client.shutdown(timeout=3.0)
                except Exception:  # noqa: BLE001
                    pass
            return
        rt = self._read_runtime()
        if not rt:
            return
        pid = rt.get("pid")
        if pid and _pid_alive(pid):
            import signal as _signal
            try:
                os.kill(pid, _signal.SIGTERM)
            except Exception:  # noqa: BLE001
                pass
            else:
                # Wait up to 3 s for graceful shutdown; force-kill if still alive
                import time as _time
                for _ in range(30):
                    _time.sleep(0.1)
                    if not _pid_alive(pid):
                        break
                else:
                    try:
                        os.kill(pid, _signal.SIGKILL)
                    except Exception:  # noqa: BLE001
                        pass
        _RUNTIME_FILE.unlink(missing_ok=True)
        _LOCK_FILE.unlink(missing_ok=True)

    def _resolve_tray_python(self) -> Optional[str]:
        """Pick an interpreter for the tray (stdlib + tkinter only, no ML venv needed)."""
        cfg_py = self._cfg.get("python_exe")
        if cfg_py and os.path.isfile(cfg_py):
            return cfg_py
        venv_py = str(_LABR7_DIR / "venv" / "bin" / "python")
        if os.path.isfile(venv_py):
            return venv_py
        import shutil
        return shutil.which("python3")

    def spawn_tray(self):
        if self._tray_disabled:
            return
        # Skip if a tray process is already alive
        if _TRAY_PID_FILE.exists():
            try:
                pid = int(_TRAY_PID_FILE.read_text().strip())
                if _pid_alive(pid):
                    return
            except Exception:  # noqa: BLE001
                pass
            _TRAY_PID_FILE.unlink(missing_ok=True)

        tray_script = os.path.join(
            self._ext_path,
            "vicone", "labr7", "radeis", "vlm", "tray_agent_launcher.py")
        python_exe = self._resolve_tray_python()
        if python_exe is None:
            if not self._tray_missing_interp_warned:
                self._tray_missing_interp_warned = True
                try:
                    import carb
                    carb.log_warn(
                        "[radeis] No usable Python interpreter found for the "
                        "tray agent (checked configured python_exe, local venv, "
                        "and system python3) - tray will not be started.")
                except Exception:  # noqa: BLE001
                    pass
            return
        rt = self._read_runtime()
        port = rt.get("port", 8765) if rt else self._cfg.get("port", 8765)
        # Inherit env and explicitly forward display vars so the tray window
        # appears regardless of how Isaac Sim was launched.
        env = os.environ.copy()
        for var in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE",
                    "XDG_RUNTIME_DIR", "XDG_CURRENT_DESKTOP",
                    "GNOME_DESKTOP_SESSION_ID", "DBUS_SESSION_BUS_ADDRESS"):
            val = os.environ.get(var)
            if val:
                env[var] = val
        try:
            proc = _popen_undebugged(
                [python_exe, tray_script, "--port", str(port)],
                start_new_session=True,
                env=env,
            )
            _TRAY_PID_FILE.write_text(str(proc.pid))
            # If the process exits within 1 s it means display init failed;
            # clear the PID file so the next poll retries rather than skipping.
            # Two consecutive fast exits mean retrying is futile (e.g. missing
            # tkinter) -- stop auto-restarting the tray for this session.
            import threading
            def _check_alive():
                import time as _time
                _time.sleep(1.0)
                if proc.poll() is not None:
                    _TRAY_PID_FILE.unlink(missing_ok=True)
                    self._tray_fast_exit_count += 1
                    if self._tray_fast_exit_count >= 2:
                        self._tray_disabled = True
                        try:
                            import carb
                            carb.log_warn(
                                "[radeis] Tray agent exited immediately twice "
                                "in a row - disabling tray auto-restart for "
                                "this session.")
                        except Exception:  # noqa: BLE001
                            pass
                    return
                self._tray_fast_exit_count = 0
                # Process is alive, but a live PID does not mean the tray has a
                # visible UI (issue #14): both pystray and tkinter can fail
                # silently, leaving the launcher parked in a headless
                # sleep loop that is_tray_alive() cannot distinguish from a
                # healthy tray. Give the launcher a few extra seconds to
                # finish its own tier fallback + status write, then check.
                _time.sleep(4.0)
                status = get_tray_status()
                if status and status.get("tier") == "headless" and env.get("DISPLAY"):
                    try:
                        import carb
                        carb.log_warn(
                            "[radeis] Tray agent started but has no visible UI "
                            "(a DISPLAY was forwarded, but both pystray and "
                            f"tkinter failed): {status.get('error')}. "
                            f"{status.get('hint') or ''} "
                            f"See {_TRAY_LOG_FILE} for details.")
                    except Exception:  # noqa: BLE001
                        pass
            threading.Thread(target=_check_alive, daemon=True).start()
        except Exception:  # noqa: BLE001
            pass

    def is_tray_alive(self) -> bool:
        """Return True only if the tray agent process is alive."""
        if not _TRAY_PID_FILE.exists():
            return False
        try:
            pid = int(_TRAY_PID_FILE.read_text().strip())
            if _pid_alive(pid):
                return True
        except Exception:  # noqa: BLE001
            pass
        _TRAY_PID_FILE.unlink(missing_ok=True)
        return False

    # ------------------------------------------------------------------
    # Path A install helpers
    # ------------------------------------------------------------------
    def wait_for_ready(self, timeout_s: float = 300.0,
                       poll_interval: float = 3.0,
                       progress_cb=None) -> bool:
        """Poll until CONNECTED (level 2). Returns True on success."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            level = self.probe_readiness()
            if level >= ReadinessLevel.CONNECTED:
                return True
            if progress_cb:
                progress_cb(level)
            time.sleep(poll_interval)
        return False

    # ------------------------------------------------------------------
    # Clean reinstall
    # ------------------------------------------------------------------
    def clean_reinstall(self):
        self.stop_sidecar()
        # Kill tray process if alive. Wait for graceful exit and force-kill
        # if it doesn't -- mirrors stop_sidecar()'s SIGTERM/SIGKILL escalation
        # so a tray process that ignores SIGTERM can't survive past uninstall
        # (the PID file is removed unconditionally right after this, so an
        # un-escalated SIGTERM here would leave an orphaned tray process that
        # nothing can find or clean up afterward).
        if _TRAY_PID_FILE.exists():
            try:
                import signal as _signal
                pid = int(_TRAY_PID_FILE.read_text().strip())
                if _pid_alive(pid):
                    os.kill(pid, _signal.SIGTERM)
                    for _ in range(30):
                        time.sleep(0.1)
                        if not _pid_alive(pid):
                            break
                    else:
                        try:
                            os.kill(pid, _signal.SIGKILL)
                        except Exception:  # noqa: BLE001
                            pass
            except Exception:  # noqa: BLE001
                pass
        import shutil
        venv = _LABR7_DIR / "venv"
        if venv.exists():
            shutil.rmtree(venv, ignore_errors=True)
        model_repo = self._cfg.get("model_repo", "")
        if model_repo:
            hf_model_dir = (Path.home() / ".cache" / "huggingface" / "hub" /
                            ("models--" + model_repo.replace("/", "--")))
            if hf_model_dir.exists():
                shutil.rmtree(hf_model_dir, ignore_errors=True)
        for f in [
            _RUNTIME_FILE,
            _LOCK_FILE,
            _TRAY_PID_FILE,
            _LABR7_DIR / "sidecar.pid",
        ]:
            Path(f).unlink(missing_ok=True)
        # Remove only local URLs from the registry; remote entries must survive.
        self._purge_local_urls()
        self.save_config({
            "setup_complete": False,
            "model_path": None,
            "python_exe": None,
            "venv_managed": False,
        })

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _read_runtime(self) -> Optional[dict]:
        if not _RUNTIME_FILE.exists():
            return None
        try:
            with open(_RUNTIME_FILE) as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _popen_undebugged(cmd: list, **kwargs) -> subprocess.Popen:
    """subprocess.Popen, routed through a shell `exec` to dodge debugpy hijack.

    When Kit's own Python process has a VS Code debugger attached (via
    isaacsim.code_editor.vscode / omni.kit.debug.python), a plain
    subprocess.Popen([python_exe, script, ...]) gets its child silently
    rewritten: the child's own process image never becomes `script` at all —
    it becomes debugpy's pydevd.py, waiting forever for a debug client to
    attach on a DAP port nobody connects to. The child still shows up as
    "alive" (os.kill(pid, 0) succeeds), so callers have no way to detect the
    hijack short of inspecting argv — but `script`'s own code (e.g. the tray
    icon's window, or the sidecar server) never runs.

    Routing the real command through an intermediate `/bin/sh -c "exec ..."`
    avoids this: the hijack targets Popen's immediate argv, and `sh` is not
    recognized as a debuggable Python launch, so the exec'd python image is
    left alone. Verified live: without this wrapper the tray subprocess sat
    as an idle pydevd instance and no window ever appeared; with it, the
    tray's own status window rendered correctly.
    """
    import shlex
    shell_cmd = "exec " + " ".join(shlex.quote(str(a)) for a in cmd)
    return subprocess.Popen(["/bin/sh", "-c", shell_cmd], **kwargs)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    except Exception:  # noqa: BLE001
        return False
    # os.kill(pid, 0) succeeds for zombies too -- their PID stays allocated
    # until the parent reaps it, even though the process is already dead and
    # can never do anything again. A zombie tray/sidecar PID left in the
    # runtime file would otherwise make spawn_tray()/spawn_sidecar() think
    # "already running" forever and permanently refuse to start a new one.
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("State:"):
                    return "Z" not in line.split()[1]
    except Exception:  # noqa: BLE001
        pass
    return True


def get_tray_status() -> Optional[dict]:
    """Read the tray_agent_launcher status file (~/.labr7/tray_status.json).

    Returns None on a missing file, corrupt JSON, or a pid that no longer
    matches a live process — i.e. a status left over from a tray run that is
    no longer the one recorded in tray.pid. Staleness is handled on the
    writer side too (tray_agent_launcher overwrites tier="starting" on every
    process start), but validating pid here means a reader is never fooled by
    a status file that outlived its process (e.g. host crash mid-write leaving
    a valid-looking but orphaned file).
    """
    if not _TRAY_STATUS_FILE.exists():
        return None
    try:
        with open(_TRAY_STATUS_FILE) as f:
            data = json.load(f)
    except Exception:  # noqa: BLE001
        return None
    pid = data.get("pid")
    if not isinstance(pid, int) or not _pid_alive(pid):
        return None
    return data


def _to_home_relative(p: str) -> str:
    """Replace the current user's absolute home prefix with ~ for portable storage."""
    home = str(Path.home())
    if p.startswith(home + "/") or p == home:
        return "~" + p[len(home):]
    return p


def _resolve_model_path(p: Optional[str]) -> Optional[str]:
    """Expand ~ and remap stale /home/<other-user>/ paths to the current home.

    Returns None if the path is empty or cannot be found on disk.
    """
    if not p:
        return None
    expanded = str(Path(p).expanduser())
    if Path(expanded).exists():
        return expanded
    # Try remapping /home/<old-user>/rest → current home / rest
    parts = Path(p).parts  # ('/', 'home', 'alice', '.cache', ...)
    if len(parts) >= 4 and parts[0] == "/" and parts[1] == "home":
        remapped = str(Path.home().joinpath(*parts[3:]))
        if Path(remapped).exists():
            return remapped
    return None  # path not found — start without preloading


def _find_server_py(ext_path: str) -> str:
    """Locate vlm_sidecar/server.py from the extension root path."""
    candidates = [
        # Bundled inside the extension data/ (works after packaging)
        os.path.join(ext_path, "data", "vlm_sidecar", "server.py"),
        # Dev tree: ext root is vicone.labr7.radeis/, 4 levels up = repo root
        os.path.normpath(os.path.join(ext_path, "..", "..", "..", "..",
                                      "vlm_sidecar", "server.py")),
        # Deeper nesting (5 levels)
        os.path.normpath(os.path.join(ext_path, "..", "..", "..", "..", "..",
                                      "vlm_sidecar", "server.py")),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[1]  # 4-level fallback — gives a clear missing-path error

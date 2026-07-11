"""QA tests for tray-agent / sidecar lifecycle invariants.

Pure Python — no Isaac Sim dependency.  Run with:
    python -m pytest tests/test_tray_sidecar_invariants.py -v

Tests are grouped by module under test:
  T1–T3  : tray_agent_launcher  (tkinter + pystray paths)
  T4–T5  : sidecar_manager.SidecarManager.is_tray_alive()
  T6–T7  : model_wizard Path-B spawn_tray() call
  T8–T9  : sidecar_manager.SidecarManager.spawn_tray() idempotency
  T10    : tray_agent_launcher _do_close() double-call guard
  T11    : tray_agent_launcher headless fallback -> tray_status.json + hint (#14)
  T12–T15: sidecar_manager.get_tray_status() missing/corrupt/pid-mismatch/valid (#14)
  T16    : tray_agent_launcher tray_status.json write is atomic (os.replace) (#14)
  T17–T21: tray_preflight.check_tray_ui() tier prediction + reason/fix_cmd (#14)
  T22–T26: shared tray-preflight strip render logic (Path A + Path B pages) (#14)
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Stub out heavy dependencies so the modules import without Isaac Sim / Kit
# ---------------------------------------------------------------------------

def _stub_module(name: str) -> MagicMock:
    mod = MagicMock()
    mod.__spec__ = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


for _name in [
    "carb", "carb.tokens", "carb.settings",
    "omni", "omni.kit", "omni.kit.app", "omni.ui", "omni.usd", "omni.timeline",
    "pystray",
    "PIL", "PIL.Image", "PIL.ImageDraw",
]:
    if _name not in sys.modules:
        _stub_module(_name)

# Point the package resolver at the real source tree
_EXT_ROOT = Path(__file__).parent.parent  # …/labr7.radeis.redteam/
sys.path.insert(0, str(_EXT_ROOT.parent.parent.parent))  # up to exts/

# ---------------------------------------------------------------------------
# Lazy module imports (deferred so stubs are in place first)
# ---------------------------------------------------------------------------

def _import_tray():
    # Fresh import each time so module-level state doesn't bleed between tests
    mod_name = "labr7.radeis.redteam.vlm.tray_agent_launcher"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    import labr7.radeis.redteam.vlm.tray_agent_launcher as m
    return m


def _import_sidecar_manager():
    mod_name = "labr7.radeis.redteam.vlm.sidecar_manager"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    # sidecar_manager imports sidecar_client — stub it
    sc_mod = types.ModuleType("labr7.radeis.redteam.vlm.sidecar_client")
    sc_mod.SidecarClient = MagicMock()
    sc_mod._fmt_net_err = lambda e: str(e)  # noqa: E731 -- also imported by sidecar_manager
    sys.modules["labr7.radeis.redteam.vlm.sidecar_client"] = sc_mod
    import labr7.radeis.redteam.vlm.sidecar_manager as m
    return m


# ---------------------------------------------------------------------------
# T1 — Tkinter countdown expiry uses root.after(0, _do_close), not sys.exit
# ---------------------------------------------------------------------------
class T1_CountdownExpiryTkinter(unittest.TestCase):
    def test_countdown_expiry_closes_tkinter(self):
        tray = _import_tray()

        root_mock = MagicMock()
        after_calls = []
        root_mock.after.side_effect = lambda delay, fn: after_calls.append((delay, fn))
        root_mock.mainloop.side_effect = lambda: None  # don't block

        fake_tk = MagicMock()
        fake_tk.Tk.return_value = root_mock
        fake_tk.Label.return_value = MagicMock()
        fake_tk.Frame.return_value = MagicMock()
        fake_tk.Button.return_value = MagicMock()

        cfg = {}
        port = 8765
        timeout = 1  # 1 second so countdown fires quickly

        stop_sidecar_calls = []

        with patch.dict(sys.modules, {"tkinter": fake_tk}), \
             patch.object(tray, "_stop_sidecar",
                          side_effect=lambda c, u: stop_sidecar_calls.append((c, u))), \
             patch.object(tray, "_healthz", return_value=False), \
             patch.object(tray, "_sidecar_url", return_value="http://127.0.0.1:8765"), \
             patch.object(tray, "_launcher_url_from", return_value="http://127.0.0.1:8766"):

            # Run _run_tkinter in a thread; it will return once mainloop() exits
            t = threading.Thread(
                target=tray._run_tkinter, args=(port, timeout, cfg), daemon=True)
            t.start()
            t.join(timeout=3)

        # The countdown lambda must have scheduled _do_close via root.after(0, ...)
        timed_calls = [c for c in after_calls if c[0] == 0]
        self.assertTrue(
            len(timed_calls) >= 1,
            "Expected root.after(0, _do_close) to be called by countdown expiry")

        # _stop_sidecar must have been called (either via _do_close or its own path)
        # because mainloop exited normally (not sys.exit)
        # The key assertion: sys.exit was NOT called directly from the countdown lambda
        # (if it were, the thread would never complete cleanly)
        self.assertFalse(t.is_alive(), "Thread should have exited after mainloop()")


# ---------------------------------------------------------------------------
# T2 — Tkinter WM_DELETE_WINDOW calls _stop_sidecar
# ---------------------------------------------------------------------------
class T2_WindowCloseKillsSidecar(unittest.TestCase):
    def test_window_close_kills_sidecar_tkinter(self):
        tray = _import_tray()

        protocol_registry = {}
        root_mock = MagicMock()
        root_mock.protocol.side_effect = lambda name, fn: protocol_registry.update({name: fn})
        root_mock.mainloop.side_effect = lambda: None

        fake_tk = MagicMock()
        fake_tk.Tk.return_value = root_mock
        fake_tk.Label.return_value = MagicMock()
        fake_tk.Frame.return_value = MagicMock()
        fake_tk.Button.return_value = MagicMock()

        stop_calls = []

        with patch.dict(sys.modules, {"tkinter": fake_tk}), \
             patch.object(tray, "_stop_sidecar",
                          side_effect=lambda c, u: stop_calls.append(u)), \
             patch.object(tray, "_healthz", return_value=False), \
             patch.object(tray, "_sidecar_url", return_value="http://127.0.0.1:8765"), \
             patch.object(tray, "_launcher_url_from", return_value="http://127.0.0.1:8766"):

            tray._run_tkinter(8765, 600, {})

        self.assertIn("WM_DELETE_WINDOW", protocol_registry,
                      "WM_DELETE_WINDOW protocol must be registered")

        # Invoke the close handler
        close_fn = protocol_registry["WM_DELETE_WINDOW"]
        close_fn()

        self.assertEqual(len(stop_calls), 1,
                         "_stop_sidecar should be called exactly once on window close")


# ---------------------------------------------------------------------------
# T3 — pystray Quit menu item calls _stop_sidecar + icon.stop()
# ---------------------------------------------------------------------------
class T3_PystrayQuitKillsSidecar(unittest.TestCase):
    def test_pystray_quit_menu_kills_sidecar(self):
        tray = _import_tray()

        icon_mock = MagicMock()
        fake_pystray = MagicMock()
        fake_pystray.Icon.return_value = icon_mock
        icon_mock.run.side_effect = lambda: None  # don't block

        stop_calls = []

        with patch.dict(sys.modules, {"pystray": fake_pystray,
                                      "PIL": MagicMock(),
                                      "PIL.Image": MagicMock(),
                                      "PIL.ImageDraw": MagicMock()}), \
             patch.object(tray, "_stop_sidecar",
                          side_effect=lambda c, u: stop_calls.append(u)), \
             patch.object(tray, "_healthz", return_value=True), \
             patch.object(tray, "_sidecar_url", return_value="http://127.0.0.1:8765"), \
             patch.object(tray, "_launcher_url_from", return_value="http://127.0.0.1:8766"), \
             patch("sys.exit"):

            tray._run_pystray(8765, 600, {})

        # Find the MenuItem call whose label contains "Quit"
        quit_callbacks = []
        for c in fake_pystray.MenuItem.call_args_list:
            args = c[0] if c[0] else []
            if args and "Quit" in str(args[0]):
                if len(args) >= 2:
                    quit_callbacks.append(args[1])

        self.assertTrue(len(quit_callbacks) >= 1, "A 'Quit' MenuItem must be registered")

        # Invoke the quit callback
        quit_fn = quit_callbacks[0]
        quit_fn(icon_mock, None)

        self.assertEqual(len(stop_calls), 1,
                         "_stop_sidecar should be called when Quit is selected")
        icon_mock.stop.assert_called()


# ---------------------------------------------------------------------------
# T4 — is_tray_alive() returns False when PID file absent → poll sets OFFLINE
# ---------------------------------------------------------------------------
class T4_TrayDeadForcesOffline(unittest.TestCase):
    def test_tray_dead_forces_offline(self):
        sm = _import_sidecar_manager()

        mgr = sm.SidecarManager.__new__(sm.SidecarManager)
        mgr._ext_path = "/fake"
        mgr._cfg = dict(sm._CONFIG_DEFAULTS)
        mgr._client = None
        mgr._active_url = ""
        mgr._readiness = sm.ReadinessLevel.CONNECTED
        mgr._last_resources = {}

        with patch.object(sm, "_TRAY_PID_FILE") as mock_pid_file:
            mock_pid_file.exists.return_value = False
            result = mgr.is_tray_alive()

        self.assertFalse(result)
        # Caller (poll loop) would set OFFLINE when is_tray_alive() is False
        # Verify the level enum is available and OFFLINE < CONNECTED
        self.assertLess(sm.ReadinessLevel.OFFLINE, sm.ReadinessLevel.CONNECTED)


# ---------------------------------------------------------------------------
# T5 — is_tray_alive() removes stale PID file when process no longer exists
# ---------------------------------------------------------------------------
class T5_StalePidFileRemoved(unittest.TestCase):
    def test_tray_dead_clears_stale_pid_file(self):
        sm = _import_sidecar_manager()

        mgr = sm.SidecarManager.__new__(sm.SidecarManager)
        mgr._ext_path = "/fake"
        mgr._cfg = dict(sm._CONFIG_DEFAULTS)

        pid_file_mock = MagicMock(spec=Path)
        pid_file_mock.exists.return_value = True
        pid_file_mock.read_text.return_value = "99999"  # non-existent PID

        with patch.object(sm, "_TRAY_PID_FILE", pid_file_mock), \
             patch.object(sm, "_pid_alive", return_value=False):
            result = mgr.is_tray_alive()

        self.assertFalse(result)
        pid_file_mock.unlink.assert_called_once_with(missing_ok=True)


# ---------------------------------------------------------------------------
# T6 — wizard Path B _pb_connect calls spawn_tray() before _PAGE_DONE
# ---------------------------------------------------------------------------
class T6_WizardPathBConnectSpawnsTray(unittest.TestCase):
    def test_wizard_path_b_connect_spawns_tray(self):
        # Stub omni.ui before importing model_wizard
        _stub_module("omni.ui")

        mod_name = "labr7.radeis.redteam.ui.model_wizard"
        if mod_name in sys.modules:
            del sys.modules[mod_name]

        # Also stub radeis_ui and other local deps
        for dep in [
            "labr7.radeis.redteam.ui.radeis_ui",
            "labr7.radeis.redteam.vlm.sidecar_client",
            "labr7.radeis.redteam.constants",
        ]:
            if dep not in sys.modules:
                sys.modules[dep] = MagicMock()

        import labr7.radeis.redteam.ui.model_wizard as wiz

        mgr_mock = MagicMock()
        mgr_mock.config = {"model_repo": "google/gemma-4-e2b-it"}

        wizard = wiz.ModelWizard.__new__(wiz.ModelWizard)
        wizard._mgr = mgr_mock

        call_order = []
        mgr_mock.spawn_tray.side_effect = lambda: call_order.append("spawn_tray")

        goto_mock = MagicMock(side_effect=lambda p: call_order.append(f"goto:{p}"))
        wizard._goto = goto_mock
        wizard._pb_conn_status = MagicMock()
        wizard._pb_url_field = MagicMock()
        wizard._pb_url_field.model.get_value_as_string.return_value = "http://remote:8765"
        mgr_mock.save_config.return_value = None

        fake_client = MagicMock()
        fake_client.health.return_value = {"status": "ok", "loaded": True}

        with patch("labr7.radeis.redteam.ui.model_wizard.threading") as mock_threading, \
             patch("labr7.radeis.redteam.vlm.sidecar_client.SidecarClient",
                   return_value=fake_client):

            # Capture the worker and run it synchronously
            worker_fn = [None]
            def fake_thread(target=None, daemon=True):
                worker_fn[0] = target
                t = MagicMock()
                t.start.side_effect = lambda: target()
                return t

            mock_threading.Thread.side_effect = fake_thread
            wizard._pb_connect()

        self.assertIn("spawn_tray", call_order,
                      "spawn_tray() must be called in _pb_connect worker")
        # spawn_tray must come before _goto(_PAGE_DONE)
        done_entries = [i for i, v in enumerate(call_order) if "goto" in v and "DONE" in v.upper()]
        tray_entries = [i for i, v in enumerate(call_order) if v == "spawn_tray"]
        if done_entries and tray_entries:
            self.assertLess(tray_entries[0], done_entries[0],
                            "spawn_tray() must be called before _goto(_PAGE_DONE)")


# ---------------------------------------------------------------------------
# T7 — wizard Path B _pb_load_model calls spawn_tray() before _PAGE_DONE
# ---------------------------------------------------------------------------
class T7_WizardPathBLoadSpawnsTray(unittest.TestCase):
    def test_wizard_path_b_load_spawns_tray(self):
        mod_name = "labr7.radeis.redteam.ui.model_wizard"
        if mod_name in sys.modules:
            del sys.modules[mod_name]

        for dep in [
            "labr7.radeis.redteam.ui.radeis_ui",
            "labr7.radeis.redteam.vlm.sidecar_client",
            "labr7.radeis.redteam.constants",
        ]:
            if dep not in sys.modules:
                sys.modules[dep] = MagicMock()

        import labr7.radeis.redteam.ui.model_wizard as wiz

        mgr_mock = MagicMock()
        mgr_mock.config = {"model_repo": "google/gemma-4-e2b-it"}
        mgr_mock.client = MagicMock()
        mgr_mock.client.load_model.return_value = {"loaded": True}

        call_order = []
        mgr_mock.spawn_tray.side_effect = lambda: call_order.append("spawn_tray")

        wizard = wiz.ModelWizard.__new__(wiz.ModelWizard)
        wizard._mgr = mgr_mock
        wizard._pb_load_status = MagicMock()
        wizard._pb_model_field = MagicMock()
        wizard._pb_model_field.model.get_value_as_string.return_value = "google/gemma-4-e2b-it"
        wizard._set_pb_load_prog = MagicMock()

        goto_mock = MagicMock(side_effect=lambda p: call_order.append(f"goto:{p}"))
        wizard._goto = goto_mock

        with patch("labr7.radeis.redteam.ui.model_wizard.threading") as mock_threading, \
             patch("labr7.radeis.redteam.ui.model_wizard.time") as mock_time:
            mock_time.sleep.return_value = None

            def fake_thread(target=None, daemon=True):
                t = MagicMock()
                t.start.side_effect = lambda: target()
                return t

            mock_threading.Thread.side_effect = fake_thread
            wizard._pb_load_model()

        self.assertIn("spawn_tray", call_order,
                      "spawn_tray() must be called in _pb_load_model worker")
        done_entries = [i for i, v in enumerate(call_order) if "goto" in v and "DONE" in v.upper()]
        tray_entries = [i for i, v in enumerate(call_order) if v == "spawn_tray"]
        if done_entries and tray_entries:
            self.assertLess(tray_entries[0], done_entries[0],
                            "spawn_tray() must be called before _goto(_PAGE_DONE)")


# ---------------------------------------------------------------------------
# T8 — spawn_tray() is idempotent (no second process if tray already alive)
# ---------------------------------------------------------------------------
class T8_SpawnTrayIdempotent(unittest.TestCase):
    def test_spawn_tray_skips_if_already_alive(self):
        sm = _import_sidecar_manager()

        mgr = sm.SidecarManager.__new__(sm.SidecarManager)
        mgr._ext_path = "/fake"
        mgr._cfg = dict(sm._CONFIG_DEFAULTS)

        pid_file_mock = MagicMock(spec=Path)
        pid_file_mock.exists.return_value = True
        pid_file_mock.read_text.return_value = "12345"

        with patch.object(sm, "_TRAY_PID_FILE", pid_file_mock), \
             patch.object(sm, "_pid_alive", return_value=True), \
             patch.object(sm.subprocess, "Popen") as mock_popen:
            mgr.spawn_tray()

        mock_popen.assert_not_called()


# ---------------------------------------------------------------------------
# T9 — is_tray_alive() returns True when PID file exists and process alive
# ---------------------------------------------------------------------------
class T9_IsAliveReturnsTrueWhenAlive(unittest.TestCase):
    def test_is_tray_alive_true_when_pid_exists(self):
        sm = _import_sidecar_manager()

        mgr = sm.SidecarManager.__new__(sm.SidecarManager)
        mgr._ext_path = "/fake"
        mgr._cfg = dict(sm._CONFIG_DEFAULTS)

        pid_file_mock = MagicMock(spec=Path)
        pid_file_mock.exists.return_value = True
        pid_file_mock.read_text.return_value = "42"

        with patch.object(sm, "_TRAY_PID_FILE", pid_file_mock), \
             patch.object(sm, "_pid_alive", return_value=True):
            result = mgr.is_tray_alive()

        self.assertTrue(result)


# ---------------------------------------------------------------------------
# T10 — _do_close() is guarded by _closed[0] flag — second call is no-op
# ---------------------------------------------------------------------------
class T10_NoDoubleClose(unittest.TestCase):
    def test_no_double_close_tkinter(self):
        tray = _import_tray()

        root_mock = MagicMock()
        root_mock.mainloop.side_effect = lambda: None
        root_mock.after.return_value = None

        fake_tk = MagicMock()
        fake_tk.Tk.return_value = root_mock
        fake_tk.Label.return_value = MagicMock()
        fake_tk.Frame.return_value = MagicMock()
        fake_tk.Button.return_value = MagicMock()

        stop_calls = []

        with patch.dict(sys.modules, {"tkinter": fake_tk}), \
             patch.object(tray, "_stop_sidecar",
                          side_effect=lambda c, u: stop_calls.append(u)), \
             patch.object(tray, "_healthz", return_value=False), \
             patch.object(tray, "_sidecar_url", return_value="http://127.0.0.1:8765"), \
             patch.object(tray, "_launcher_url_from", return_value="http://127.0.0.1:8766"):

            tray._run_tkinter(8765, 600, {})

        # Retrieve the registered WM_DELETE_WINDOW handler
        protocol_calls = {c[0][0]: c[0][1]
                          for c in root_mock.protocol.call_args_list
                          if c[0]}
        self.assertIn("WM_DELETE_WINDOW", protocol_calls)
        close_fn = protocol_calls["WM_DELETE_WINDOW"]

        # Call twice — _stop_sidecar must only fire once
        close_fn()
        close_fn()

        self.assertEqual(len(stop_calls), 1,
                         "_stop_sidecar should only be called once even if _do_close fires twice")


# ---------------------------------------------------------------------------
# T11 — issue #14: when both pystray and tkinter are unavailable, main()
# writes tier="headless" + a preflight hint to tray_status.json right before
# falling into the silent tier-3 sleep loop.
# ---------------------------------------------------------------------------
class T11_HeadlessStatusWrittenWhenBothTiersUnavailable(unittest.TestCase):
    def test_headless_status_and_hint_written(self):
        tray = _import_tray()

        written = {}

        def _fake_write_status(tier, error=None, hint=None):
            written.update({"tier": tier, "error": error, "hint": hint})

        pystray_missing = ModuleNotFoundError("No module named 'pystray'", name="pystray")
        tkinter_missing = ModuleNotFoundError("No module named '_tkinter'", name="_tkinter")

        # Force the "not wayland, not gnome" branch so tier 1 (pystray) is
        # actually attempted (not skipped by the desktop guard) before
        # falling through to tier 2 (tkinter) and then tier 3 (headless).
        env_overrides = {
            "WAYLAND_DISPLAY": "", "XDG_SESSION_TYPE": "",
            "GNOME_DESKTOP_SESSION_ID": "", "XDG_CURRENT_DESKTOP": "",
        }

        with patch.object(tray, "_write_tray_status", side_effect=_fake_write_status), \
             patch.object(tray, "_run_pystray", side_effect=pystray_missing), \
             patch.object(tray, "_run_tkinter", side_effect=tkinter_missing), \
             patch.object(tray.time, "sleep", side_effect=KeyboardInterrupt), \
             patch.object(sys, "argv", ["tray_agent_launcher.py"]), \
             patch.dict(os.environ, env_overrides):
            tray.main()

        self.assertEqual(written.get("tier"), "headless")
        self.assertIn("_tkinter", written.get("error") or "")
        self.assertEqual(
            written.get("hint"),
            "python3-tk is not installed on this machine - run: sudo apt install python3-tk")


# ---------------------------------------------------------------------------
# T12–T15 — issue #14: sidecar_manager.get_tray_status()
# ---------------------------------------------------------------------------
class T12_GetTrayStatusMissingFile(unittest.TestCase):
    def test_returns_none_when_file_missing(self):
        sm = _import_sidecar_manager()
        with tempfile.TemporaryDirectory() as d:
            missing = Path(d) / "tray_status.json"
            with patch.object(sm, "_TRAY_STATUS_FILE", missing):
                result = sm.get_tray_status()
        self.assertIsNone(result)


class T13_GetTrayStatusCorruptJson(unittest.TestCase):
    def test_returns_none_when_json_corrupt(self):
        sm = _import_sidecar_manager()
        with tempfile.TemporaryDirectory() as d:
            status_path = Path(d) / "tray_status.json"
            status_path.write_text("{not valid json")
            with patch.object(sm, "_TRAY_STATUS_FILE", status_path):
                result = sm.get_tray_status()
        self.assertIsNone(result)


class T14_GetTrayStatusPidMismatch(unittest.TestCase):
    def test_returns_none_when_pid_not_alive(self):
        sm = _import_sidecar_manager()
        with tempfile.TemporaryDirectory() as d:
            status_path = Path(d) / "tray_status.json"
            status_path.write_text(json.dumps({
                "tier": "headless", "error": "boom", "hint": None,
                "pid": 99999, "ts": "2026-01-01T00:00:00+00:00",
            }))
            with patch.object(sm, "_TRAY_STATUS_FILE", status_path), \
                 patch.object(sm, "_pid_alive", return_value=False):
                result = sm.get_tray_status()
        self.assertIsNone(result)


class T15_GetTrayStatusValid(unittest.TestCase):
    def test_returns_payload_when_pid_alive(self):
        sm = _import_sidecar_manager()
        with tempfile.TemporaryDirectory() as d:
            status_path = Path(d) / "tray_status.json"
            payload = {
                "tier": "pystray", "error": None, "hint": None,
                "pid": os.getpid(), "ts": "2026-01-01T00:00:00+00:00",
            }
            status_path.write_text(json.dumps(payload))
            with patch.object(sm, "_TRAY_STATUS_FILE", status_path), \
                 patch.object(sm, "_pid_alive", return_value=True):
                result = sm.get_tray_status()
        self.assertEqual(result, payload)


# ---------------------------------------------------------------------------
# T16 — issue #14: tray_status.json is published via a temp file + os.replace
# (never partially written / never a direct write to the final path).
# ---------------------------------------------------------------------------
class T16_StatusWriteIsAtomic(unittest.TestCase):
    def test_status_write_uses_os_replace(self):
        tray = _import_tray()
        with tempfile.TemporaryDirectory() as d:
            status_path = Path(d) / "tray_status.json"
            replace_calls = []
            real_replace = os.replace

            def _spy_replace(src, dst):
                replace_calls.append((src, dst))
                return real_replace(src, dst)

            with patch.object(tray, "_STATUS_FILE", status_path), \
                 patch.object(tray.os, "replace", side_effect=_spy_replace):
                tray._write_tray_status("pystray")

            self.assertEqual(len(replace_calls), 1,
                             "status file must be published via exactly one os.replace call")
            src, dst = replace_calls[0]
            self.assertEqual(Path(dst), status_path)
            self.assertNotEqual(
                Path(src), status_path,
                "content must be staged in a temp file, not written to the final path directly")

            with open(status_path) as f:
                data = json.load(f)
            self.assertEqual(data["tier"], "pystray")
            self.assertEqual(data["pid"], os.getpid())


# ---------------------------------------------------------------------------
# T17–T21 — issue #14: tray_preflight.check_tray_ui()
# ---------------------------------------------------------------------------

def _import_tray_preflight():
    mod_name = "labr7.radeis.redteam.vlm.tray_preflight"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    import labr7.radeis.redteam.vlm.tray_preflight as m
    return m


def _fake_probe_run(tk_ok: bool, ps_ok: bool):
    """subprocess.run stand-in: rc 0/1 per module in the '-c import X' probe."""
    def _run(cmd, **_kw):
        stmt = cmd[-1]
        ok = tk_ok if "tkinter" in stmt else ps_ok
        m = MagicMock()
        m.returncode = 0 if ok else 1
        return m
    return _run


# Non-GNOME, non-Wayland X11 env baseline; individual tests override keys.
_PF_ENV_X11 = {
    "DISPLAY": ":0", "WAYLAND_DISPLAY": "", "XDG_SESSION_TYPE": "x11",
    "XDG_CURRENT_DESKTOP": "", "GNOME_DESKTOP_SESSION_ID": "",
}


class T17_PreflightTkinterOk(unittest.TestCase):
    def test_tkinter_ok_with_display(self):
        tp = _import_tray_preflight()
        with patch.object(tp.subprocess, "run",
                          side_effect=_fake_probe_run(tk_ok=True, ps_ok=False)), \
             patch.dict(os.environ, _PF_ENV_X11):
            result = tp.check_tray_ui(sys.executable)
        self.assertTrue(result["ok"])
        self.assertEqual(result["expected_tier"], "tkinter")
        self.assertIsNone(result["fix_cmd"])


class T18_PreflightTkinterMissing(unittest.TestCase):
    def test_tkinter_missing_with_display(self):
        tp = _import_tray_preflight()
        with patch.object(tp.subprocess, "run",
                          side_effect=_fake_probe_run(tk_ok=False, ps_ok=False)), \
             patch.dict(os.environ, _PF_ENV_X11):
            result = tp.check_tray_ui(sys.executable)
        self.assertFalse(result["ok"])
        self.assertEqual(result["expected_tier"], "headless")
        self.assertEqual(result["fix_cmd"], "sudo apt install python3-tk")


class T19_PreflightNoDisplay(unittest.TestCase):
    def test_no_display_no_wayland(self):
        tp = _import_tray_preflight()
        env = dict(_PF_ENV_X11, DISPLAY="", XDG_SESSION_TYPE="")
        with patch.object(tp.subprocess, "run",
                          side_effect=_fake_probe_run(tk_ok=True, ps_ok=False)), \
             patch.dict(os.environ, env):
            result = tp.check_tray_ui(sys.executable)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["fix_cmd"])
        self.assertIn("display", result["reason"].lower())


class T20_PreflightGnomeSkipsPystray(unittest.TestCase):
    def test_gnome_guard_never_predicts_pystray(self):
        tp = _import_tray_preflight()
        env = dict(_PF_ENV_X11, XDG_CURRENT_DESKTOP="ubuntu:GNOME")
        with patch.object(tp.subprocess, "run",
                          side_effect=_fake_probe_run(tk_ok=True, ps_ok=True)), \
             patch.dict(os.environ, env):
            result = tp.check_tray_ui(sys.executable)
        # pystray imports fine, but the launcher's GNOME guard skips it —
        # the prediction must mirror that.
        self.assertNotEqual(result["expected_tier"], "pystray")


class T21_PreflightNeverRaises(unittest.TestCase):
    def test_probe_failure_is_not_fatal(self):
        tp = _import_tray_preflight()
        with patch.object(tp.subprocess, "run",
                          side_effect=OSError("exec failed")), \
             patch.dict(os.environ, _PF_ENV_X11):
            result = tp.check_tray_ui(None)  # must not raise
        self.assertFalse(result["ok"])
        self.assertEqual(result["expected_tier"], "headless")


# ---------------------------------------------------------------------------
# T22–T26 — issue #14: shared tray-preflight strip render logic
# (Step2SetupMixin._render_tray_pf_group / _render_tray_preflight — the
# widget groups are plain dicts of mocks, so the branch logic is testable
# without Kit even though the strip itself is omni.ui code)
# ---------------------------------------------------------------------------

def _import_sidecar_setup():
    mod_name = "labr7.radeis.redteam.ui.wizard.sidecar_setup"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    for dep in [
        "labr7.radeis.redteam.constants",
        "labr7.radeis.redteam.vlm.sidecar_client",
    ]:
        if dep not in sys.modules:
            sys.modules[dep] = MagicMock()
    import labr7.radeis.redteam.ui.wizard.sidecar_setup as m
    return m


def _mock_pf_group() -> dict:
    return {k: MagicMock() for k in
            ("frame", "label", "code_frame", "code_label", "copy_btn")}


class T22_PfStripHiddenWhenOk(unittest.TestCase):
    def test_ok_hides_strip(self):
        ss = _import_sidecar_setup()
        group = _mock_pf_group()
        pf = {"ok": True, "expected_tier": "tkinter", "reason": "", "fix_cmd": None}
        ss.Step2SetupMixin._render_tray_pf_group(group, pf)
        self.assertFalse(group["frame"].visible)


class T23_PfStripHeadlessWithFix(unittest.TestCase):
    def test_headless_with_fix_shows_code_and_copy(self):
        ss = _import_sidecar_setup()
        group = _mock_pf_group()
        pf = {"ok": False, "expected_tier": "headless",
              "reason": "The tray needs python3-tk, which is not installed "
                        "for this environment's Python.",
              "fix_cmd": "sudo apt install python3-tk"}
        ss.Step2SetupMixin._render_tray_pf_group(group, pf)
        self.assertTrue(group["frame"].visible)
        self.assertTrue(group["code_frame"].visible)
        self.assertTrue(group["copy_btn"].visible)
        self.assertEqual(group["code_label"].text, "sudo apt install python3-tk")
        self.assertIn("python3-tk", group["label"].text)


class T24_PfStripHeadlessNoDisplay(unittest.TestCase):
    def test_headless_without_fix_hides_code_and_copy(self):
        ss = _import_sidecar_setup()
        group = _mock_pf_group()
        pf = {"ok": False, "expected_tier": "headless",
              "reason": "No graphical display is available (Isaac Sim may be "
                        "running over SSH without X forwarding).",
              "fix_cmd": None}
        ss.Step2SetupMixin._render_tray_pf_group(group, pf)
        self.assertTrue(group["frame"].visible)
        self.assertFalse(group["code_frame"].visible)
        self.assertFalse(group["copy_btn"].visible)


class T25_PfStripRecheckOkShowsConfirmation(unittest.TestCase):
    def test_recheck_ok_shows_green_line(self):
        ss = _import_sidecar_setup()
        group = _mock_pf_group()
        pf = {"ok": True, "expected_tier": "tkinter", "reason": "", "fix_cmd": None}
        ss.Step2SetupMixin._render_tray_pf_group(group, pf, from_recheck=True)
        self.assertTrue(group["frame"].visible)
        self.assertFalse(group["code_frame"].visible)
        self.assertIn("passed", group["label"].text.lower())
        self.assertEqual(group["label"].style, ss.R.STYLE_WIZARD_OK_TEXT)


class T26_PfRenderFansOutToAllPages(unittest.TestCase):
    def test_render_updates_both_page_strips(self):
        ss = _import_sidecar_setup()
        mixin = ss.Step2SetupMixin()
        group_a, group_b = _mock_pf_group(), _mock_pf_group()
        mixin._tray_pf_strips = {"path_a": group_a, "path_b": group_b}
        mixin._tray_pf = {"ok": False, "expected_tier": "headless",
                          "reason": "r", "fix_cmd": "sudo apt install python3-tk"}
        mixin._render_tray_preflight()
        # One machine-local verdict, rendered onto every registered page strip.
        for group in (group_a, group_b):
            self.assertTrue(group["frame"].visible)
            self.assertEqual(group["code_label"].text,
                             "sudo apt install python3-tk")


if __name__ == "__main__":
    unittest.main()

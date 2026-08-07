"""Radeis usage telemetry — fully modular, fully optional.

This package is the ONLY thing extension code should import for
telemetry, and it has two call sites: `extension.py::on_startup` calling
`report_install(ext_id)`, and `ui/window.py` calling `track(event, ...)`
(via its own guarded `_tel_track` alias) to fire the run-test funnel
events. Every public function here is safe to call from anywhere: it
never raises, never blocks the caller (real work happens on a background
daemon thread with a hard network timeout), and respects the opt-out
(extension.toml `telemetry_enabled` / `RADEIS_TELEMETRY=0`) before doing
any work at all.

Deleting this entire `telemetry/` folder is a supported configuration:
both import sites are try/except-guarded — extension.py's own nested
try/except swallows the `ImportError` from `from .telemetry import
report_install`, and window.py degrades `_tel_track` to a no-op — so the
extension runs identically with telemetry absent.

See TELEMETRY.md for the full user-facing disclosure and event catalogue.
"""

from . import client, consent, env, state


def is_enabled() -> bool:
    """Whether telemetry is currently enabled (opt-out not engaged)."""
    try:
        return consent.is_enabled()
    except Exception:  # noqa: BLE001
        # Default-on posture: a broken consent check should not silently
        # disable telemetry, but it must never raise into caller code either.
        return True


def report_install(ext_id: str = None) -> None:
    """Fire the Phase-1 `install` event, once per version.

    Instant, non-blocking: spawns a daemon thread and returns immediately
    regardless of network state, consent, or any error.
    """
    try:
        # Short-circuit before even spawning a thread when opted out, matching
        # track()/submit_feedback(). (Consent is re-checked inside the worker
        # too, so correctness never depends on this early return.)
        if not consent.is_enabled():
            return
        client.run_in_thread(lambda: _do_report_install(ext_id))
    except Exception:  # noqa: BLE001
        pass


def _do_report_install(ext_id: str = None) -> None:
    """Runs INSIDE the background worker thread — never on the caller's."""
    try:
        if not consent.is_enabled():
            return
        ver = env.ext_version(ext_id)
        if state.last_reported_version() == ver:
            return  # already reported this version; once-per-version dedupe
        # session_id rides along on this payload too (send_event attaches it
        # unconditionally) — it's for double-fire detection within a single
        # process, not a factor in the dedupe decision above.
        ok = client.send_event(
            "install",
            ext_version=ver,
            isaac_version=env.isaac_version(),
            os_family=env.os_family(),
        )
        # Mark reported ONLY on a confirmed {"ok": true} from the endpoint.
        # This means an offline first-launch naturally retries on the next
        # launch (the marker is never written), until one row lands —
        # exactly one `install` row per version once connectivity exists,
        # while any single attempt stays fire-and-forget.
        if ok:
            state.mark_reported(ver)
    except Exception:  # noqa: BLE001
        pass


def track(event: str, **params) -> None:
    """Fire an arbitrary named event; backs the run-test funnel.

    Called from `ui/window.py` via its guarded `_tel_track` alias for
    `run_test_started` / `run_test_completed` / `run_test_stuck`.
    """
    try:
        if not consent.is_enabled():
            return
        client.run_in_thread(lambda: client.send_event(event, **params))
    except Exception:  # noqa: BLE001
        pass


def submit_feedback(**fields) -> None:
    """Phase-2 helper: submit opt-in user-typed feedback. Implemented but
    has no UI call site yet (feedback form is a later release).

    Still respects the global kill switch: telemetry_enabled /
    RADEIS_TELEMETRY=0 is the master off-switch for ALL calls to our
    endpoint, feedback included.
    """
    try:
        if not consent.is_enabled():
            return
        client.run_in_thread(lambda: client.send_feedback(**fields))
    except Exception:  # noqa: BLE001
        pass

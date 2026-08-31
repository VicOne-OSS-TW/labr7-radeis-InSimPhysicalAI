"""Radeis usage telemetry — fully modular, fully optional.

This package is the ONLY thing extension code should import for
telemetry, and it has three call sites: `extension.py::on_startup`
calling `report_install(ext_id)`, `ui/window.py` calling
`track(event, ...)` (via its own guarded `_tel_track` alias) for the
run-test funnel, and `ui/get_in_touch_win.py` calling `is_enabled()`,
`track_unlinked(...)` and `send_feedback_blocking(...)` (each via its own
guarded alias) for the Get in Touch form.

Every public function here is safe to call from anywhere and never
raises. All of them EXCEPT `send_feedback_blocking` are also
non-blocking (real work happens on a background daemon thread with a
hard network timeout). `send_feedback_blocking` blocks by design and
MUST be called via `run_in_executor` from Kit code -- see its own
docstring. All of them respect the opt-out (extension.toml
`telemetry_enabled` / `RADEIS_TELEMETRY=0`) before doing any work.

Deleting this entire `telemetry/` folder is a supported configuration:
all three import sites are try/except-guarded -- extension.py's own
nested try/except swallows the `ImportError` from `from .telemetry
import report_install`, window.py degrades `_tel_track` to a no-op, and
get_in_touch_win.py degrades to a no-op `track_unlinked`, an
`is_enabled()` that returns False, and a `None` send function that makes
the form show "Telemetry is off - nothing was sent." -- so the extension
runs identically with telemetry absent.

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


def track_unlinked(event: str, **params) -> None:
    """Like `track`, but the row carries a BLANK `session_id`.

    Used only by `feedback_opened`. A normal events row fired moments
    before a `feedback` row would let anyone with the read token join the
    two tiers by nearest-preceding server timestamp, and through that
    session_id reach the whole launch's install/run-test rows. Blanking
    the id makes that join impossible rather than merely disallowed
    (IMPLEMENTATION_PLAN red line 3). See TELEMETRY.md section 2.
    """
    try:
        if not consent.is_enabled():
            return
        client.run_in_thread(
            lambda: client.send_event(event, omit_session_id=True, **params))
    except Exception:  # noqa: BLE001
        pass


def submit_feedback(**fields) -> None:
    """Phase-2 helper: submit opt-in user-typed feedback. Implemented but
    has no call site: the Get in Touch form uses `send_feedback_blocking()`
    instead because it needs the result.

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


def send_feedback_blocking(**fields) -> bool:
    """SYNCHRONOUS feedback submit that reports whether the row landed.

    Unlike every other function in this module this one BLOCKS on the
    network (client.py's hard 8 s timeout bounds it), because the Get in
    Touch form has to tell the user the truth about their own
    submission. The caller MUST run it off Kit's UI thread --
    ui/get_in_touch_win.py does so via ``loop.run_in_executor(...)``.
    Calling it inline from a Kit callback freezes all of Isaac Sim.

    Returns True ONLY on a confirmed {"ok": true} from the endpoint.
    Returns False when opted out, on any network error, and on any
    exception. It never raises. Because False is ambiguous, the UI
    checks ``is_enabled()`` itself BEFORE calling this and shows a
    distinct "telemetry is off" status instead of a send failure.

    ``submit_feedback()`` above is deliberately left unchanged for any
    caller that does not need the result.
    """
    try:
        # Module-level is_enabled(), NOT consent.is_enabled() directly, so
        # this gate and the UI's pre-gate share the same default-on posture
        # on the exception path and can never disagree.
        if not is_enabled():
            return False
        return bool(client.send_feedback(**fields))
    except Exception:  # noqa: BLE001
        return False

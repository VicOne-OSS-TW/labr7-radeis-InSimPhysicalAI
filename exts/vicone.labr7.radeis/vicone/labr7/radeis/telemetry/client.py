"""Transport layer for Radeis usage telemetry.

Owns the ephemeral per-session id (in-memory only, never written to disk)
and the actual HTTP POST to the Apps Script Web App endpoint. Every public
function here degrades to a safe default (False / None) on any failure —
this module must NEVER raise or block the caller.

Always test against the real endpoint with `urllib` (this module), never
`curl` — Apps Script Web Apps respond to a POST with a 302 redirect to an
echo endpoint, and curl's default handling of that redirect surfaces as a
"page not found" even though the original POST succeeded.
"""
import threading
import uuid

from . import config, env

# Generated once, on import, held only in memory. Discarded automatically
# when the Isaac Sim process exits (nothing here ever touches disk). This
# groups every event emitted by one Isaac Sim process — install and any
# run-test funnel events alike; it is NOT a persistent device/user identifier.
_SESSION_ID = uuid.uuid4().hex

# Hard timeout (seconds) on the outbound request so a stalled/unreachable
# endpoint can never hang the worker thread indefinitely.
_TIMEOUT = 8


def session_id() -> str:
    """Return this process's ephemeral session id."""
    return _SESSION_ID


def _guard(fn):
    """Wrap fn so any exception it raises is swallowed silently."""
    def _wrapped():
        try:
            fn()
        except Exception:  # noqa: BLE001
            pass
    return _wrapped


def run_in_thread(fn) -> None:
    """Run fn() on a daemon background thread; never blocks, never raises."""
    try:
        t = threading.Thread(target=_guard(fn), daemon=True)
        t.start()
    except Exception:  # noqa: BLE001
        pass


def post_json(payload: dict) -> bool:
    """POST a JSON payload to the configured telemetry URL.

    Returns True only when the endpoint replies with a JSON body containing
    {"ok": true}; returns False on any missing config, network error,
    timeout, or malformed response.
    """
    url = config.telemetry_url()
    if not url:
        return False
    try:
        import json
        import urllib.request

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            body = r.read().decode("utf-8")
        return bool(json.loads(body).get("ok"))
    except Exception:  # noqa: BLE001
        return False


def send_event(event: str, *, omit_session_id: bool = False, **params) -> bool:
    """Send a non-sensitive event -> the Apps Script `events` tab.

    Every row carries the ephemeral per-process `session_id` — `install`
    included. It groups the events emitted by one Isaac Sim process (e.g.
    lets `install` and that same launch's run-test funnel rows be tied
    together, or an accidental double-fire within one process be spotted);
    it is not identity and is never persisted or reused across launches.
    The single exception is `feedback_opened`, fired with
    `omit_session_id=True` so it carries a blank id and cannot be
    timestamp-correlated with a `feedback` tab row.

    `ext_version` / `isaac_version` / `os_family` default to the live
    `env.*()` probes when the caller doesn't pass them explicitly — this is
    what makes the run-test funnel events (`run_test_started` /
    `run_test_completed` / `run_test_stuck`, fired via `track()` with no
    env params) carry the same coarse version/OS columns as `install`
    rather than shipping them blank.
    """
    try:
        payload = {
            "token": config.telemetry_token(),
            "event": event,
            "ext_version": params.get("ext_version") or env.ext_version(),
            "isaac_version": params.get("isaac_version") or env.isaac_version(),
            "os_family": params.get("os_family") or env.os_family(),
            "stage": params.get("stage", ""),
            "feature": params.get("feature", ""),
            # `feedback_opened` passes omit_session_id=True. Firing an events
            # row with a session_id seconds before a feedback row would let a
            # reader join the two tiers by nearest-preceding timestamp (both
            # tabs are server-stamped and doGet returns them together), which
            # is exactly the join IMPLEMENTATION_PLAN red line 3 forbids. A
            # blank id closes that architecturally, not by policy.
            "session_id": "" if omit_session_id else session_id(),
        }
        return post_json(payload)
    except Exception:  # noqa: BLE001
        return False


def send_feedback(**fields) -> bool:
    """Send opt-in, user-typed feedback -> the Apps Script `feedback` tab.

    Never mixed with `session_id` or any events-tab field — the two tiers
    are never joined.
    """
    try:
        payload = {
            "token": config.telemetry_token(),
            "type": "feedback",
            "name": fields.get("name", ""),
            "email": fields.get("email", ""),
            "org": fields.get("org", ""),
            "role": fields.get("role", ""),
            "feedback": fields.get("feedback", ""),
            "contact_ok": bool(fields.get("contact_ok", False)),
            # Appended last on purpose: the backing Sheet's `feedback` tab
            # already exists, and Code.gs only writes a header row when it
            # creates the tab. A new field inserted mid-list would shift every
            # existing row's columns.
            "use_case": fields.get("use_case", ""),
        }
        return post_json(payload)
    except Exception:  # noqa: BLE001
        return False

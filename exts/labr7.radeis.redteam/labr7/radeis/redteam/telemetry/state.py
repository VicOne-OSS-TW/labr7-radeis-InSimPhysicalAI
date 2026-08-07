"""Local, non-transmitted install-dedupe marker.

Holds ONLY `{"last_reported_version": "<ver>"}` — no uuid, no device id,
no session id is ever persisted, and this file is never sent anywhere.
It exists solely so the `install` event fires once per version rather
than once per startup.

Stored under `~/.labr7/` — the extension's existing runtime-state dir,
alongside `model_registry.json`, `radeis_onboarding_seen`, and `logs/`
(see vlm/sidecar_manager.py, ui/window.py). NOT the extension's own
extscache dir, which is replaced on every upgrade and would defeat a
marker that must survive upgrades.
"""
import json
from pathlib import Path

_PATH = Path.home() / ".labr7" / "telemetry_state.json"


def last_reported_version():
    try:
        with open(_PATH) as f:
            return json.load(f).get("last_reported_version")
    except Exception:  # noqa: BLE001
        return None


def mark_reported(version: str) -> None:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_PATH, "w") as f:
            json.dump({"last_reported_version": version}, f)
    except Exception:  # noqa: BLE001
        pass

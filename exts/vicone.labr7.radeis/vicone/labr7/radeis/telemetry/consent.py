"""Opt-out check for Radeis usage telemetry.

`is_enabled()` is the master kill switch consulted before ANY telemetry
work happens (network, even local file reads for the install dedupe
marker). It always fails safe: any error while checking a switch is
treated as "not opted out via that switch" so it falls through to the
next check, and the whole function defaults to enabled only once all
checks pass (disclose-not-consent posture, see TELEMETRY.md).
"""
import os


def is_enabled() -> bool:
    try:
        # 1) Explicit env opt-out ALWAYS wins.
        v = os.environ.get("RADEIS_TELEMETRY")
        if v is not None and v.strip().lower() in {"0", "false", "no", "off"}:
            return False
        # (RADEIS_TELEMETRY unset, or set to any other value, is NOT an
        # opt-out — only the values above count.)

        # 2) carb settings flag (also what a future in-panel toggle flips).
        try:
            import carb
            enabled = carb.settings.get_settings().get(
                "/exts/vicone.labr7.radeis/telemetry_enabled"
            )
            if enabled is False:
                return False
        except Exception:  # noqa: BLE001
            pass

        # 3) Default ON per disclose-not-consent posture.
        return True
    except Exception:  # noqa: BLE001
        # Fail safe: if the opt-out check itself is broken, default to the
        # documented on-by-default posture rather than raising.
        return True

"""Coarse, best-effort environment facts sent with the `install` event.

Only ever collects: Radeis version, Isaac Sim version (coarse), OS family
(windows/linux/darwin). No OS build/version, no hardware fingerprint, no
scene/run content. Every probe is best-effort with an "unknown" fallback —
never raises.
"""


def ext_version(ext_id: str = None) -> str:
    """Radeis version string, e.g. "0.2.0".

    `ext_id` is the kit extension id, e.g. "labr7.radeis.redteam-0.2.0" —
    the version is everything after the first '-' (the extension name
    itself contains no hyphen, but pre-release versions like "0.2.1-dev"
    do). Falls back to asking the extension manager, then "unknown".
    """
    try:
        if ext_id and "-" in ext_id:
            tail = ext_id.split("-", 1)[1]
            if tail:
                return tail
    except Exception:  # noqa: BLE001
        pass
    try:
        import omni.kit.app
        mgr = omni.kit.app.get_app().get_extension_manager()
        d = mgr.get_extension_dict("labr7.radeis.redteam")
        return str(d["package"]["version"])
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def isaac_version() -> str:
    """Coarse Isaac Sim / Kit app version string, or "unknown"."""
    try:
        import carb
        v = carb.settings.get_settings().get("/app/version")
        if v:
            return str(v)
    except Exception:  # noqa: BLE001
        pass
    try:
        import omni.kit.app
        v = omni.kit.app.get_app().get_app_version()
        if v:
            return str(v)
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def os_family() -> str:
    """"windows" / "linux" / "darwin", or "unknown"."""
    try:
        import platform
        return (platform.system() or "unknown").lower()
    except Exception:  # noqa: BLE001
        return "unknown"

"""Reads telemetry endpoint config from extension.toml [settings].

Keys are declared in config/extension.toml as
`exts."vicone.labr7.radeis".telemetry_url` /
`exts."vicone.labr7.radeis".telemetry_token`, which carb exposes at
runtime under `/exts/vicone.labr7.radeis/telemetry_url` /
`/exts/vicone.labr7.radeis/telemetry_token` (same dotted-key -> path
mapping already used for `sidecar_url`, see ui/window.py `_read_settings`).

Both functions return "" (never raise) when carb is unavailable, the
setting is unset, or anything else goes wrong — an empty URL makes
client.post_json() short-circuit to False before any network call.
"""


def telemetry_url() -> str:
    try:
        import carb
        v = carb.settings.get_settings().get("/exts/vicone.labr7.radeis/telemetry_url")
        return (v or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def telemetry_token() -> str:
    try:
        import carb
        v = carb.settings.get_settings().get("/exts/vicone.labr7.radeis/telemetry_token")
        return (v or "").strip()
    except Exception:  # noqa: BLE001
        return ""

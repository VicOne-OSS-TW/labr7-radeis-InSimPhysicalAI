"""Step 4 — Setup complete: server status, test inference, and wizard teardown."""
from __future__ import annotations

import asyncio
import threading

import omni.kit.app
import omni.ui as ui

from .. import radeis_ui as R
from ._constants import _PAGE_PATH_A_DOWNLOAD, _PAGE_PATH_B_CONNECT, _PAGE_DONE

# Status-banner styles for the server-health probe result: soft tinted fill +
# muted border (via the shared R.STYLE_WIZ_BANNER_* aliases) plus a small
# state-colored dot, rather than a neon full-saturation outline.
_STYLE_DONE_BANNER_OK    = R.STYLE_WIZ_BANNER_OK
_STYLE_DONE_BANNER_WARN  = R.STYLE_WIZ_BANNER_WARN
_STYLE_DONE_BANNER_ERROR = R.STYLE_WIZ_BANNER_ERR
# margin=0 overrides the banner HStack's style={"margin": 8}, which otherwise
# cascades down and collapses this 8x8 dot's content box to 0 (same Kit
# margin-cascade quirk documented next to contact_us_win.py's eyebrow dot).
_STYLE_DONE_DOT_OK    = dict(R.STYLE_WIZ_BANNER_DOT_OK, margin=0)
_STYLE_DONE_DOT_WARN  = dict(R.STYLE_WIZ_BANNER_DOT_WARN, margin=0)
_STYLE_DONE_DOT_ERROR = dict(R.STYLE_WIZ_BANNER_DOT_ERR, margin=0)

# Local button-height override for this page only (full_png/05-complete.png
# wants a taller Run Test / Back / Finish CTA than the shared
# R.HEIGHT_BTN_PRIMARY_WIZARD=30 used everywhere else in the wizard). Kept
# page-local rather than bumping the shared token, same "per-page override,
# not a global constant change" Method already used for WIZARD_WIN_H_DONE
# above, so other wizard pages' already-verified button sizing is untouched.
_HEIGHT_BTN_DONE = 40

# Thumbnail size for the Test Inference card (full_png/05-complete.png ~98px
# square; was 80, which itself rendered a few px short of even that thanks to
# the margin-cascade bug fixed below).
_SIZE_TEST_THUMB = 98


class Step4CompleteMixin:
    """Mixin for Step 4: done page, server health probe, inference test, and close logic."""

    # ------------------------------------------------------------------
    # 4. Complete — Done page
    # ------------------------------------------------------------------
    def _refresh_done_info(self):
        try:
            cfg = self._mgr.config
            if self._done_info_label is not None:
                self._done_info_label.text = "Remote" if cfg.get("mode") == "remote" else "Local"
        except Exception:  # noqa: BLE001
            pass
        try:
            _model_name = self._mgr.config.get("model_repo") or "unknown"
            if self._done_model_label is not None:
                self._done_model_label.text = _model_name
        except Exception:  # noqa: BLE001
            pass
        try:
            _url = self._done_page_url or self._mgr.active_url or "unknown"
            if self._done_test_url_label is not None:
                self._done_test_url_label.text = _url
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._run_test_btn is not None:
                self._run_test_btn.enabled = False
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._test_result_label is not None:
                self._test_result_label.text  = "Result will appear here."
                # Dim placeholder styling (was STYLE_LOG_LABEL, near-white -
                # indistinguishable from an actual result). STYLE_WIZARD_LOG_LABEL
                # is the same muted color already used for status/log text in
                # model_download.py's download-log panel.
                self._test_result_label.style = R.STYLE_WIZARD_LOG_LABEL
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._done_start_server_row is not None:
                self._done_start_server_row.visible = False
            if getattr(self, "_done_reconnect_row", None) is not None:
                self._done_reconnect_row.visible = False
            if getattr(self, "_done_tray_row", None) is not None:
                self._done_tray_row.visible = False
        except Exception:  # noqa: BLE001
            pass

        # Reset health-probe state. Finish stays enabled and on its
        # normal primary-button skin throughout (issue #46: painting it with
        # the :disabled skin while .enabled stayed True made it look
        # unclickable even though it wasn't) -- the probe below only ever
        # steers the attention pulse (_done_update_pulse) toward Start
        # Server/Reconnect vs. Finish, never Finish's base style.
        self._done_online = False
        self._done_loaded = False
        self._done_probe_done = False
        try:
            self._done_is_local = (self._mgr.config.get("mode") != "remote")
        except Exception:  # noqa: BLE001
            self._done_is_local = True
        try:
            if getattr(self, "_done_finish_btn", None) is not None:
                self._done_finish_btn.enabled = True
        except Exception:  # noqa: BLE001
            pass

        self._done_check_server()

    def _page_done(self):
        with ui.VStack(spacing=R.SPACING_BETWEEN_CARDS):
            # ---- Card 1: Setup Complete (status banner + configuration) ----
            # No fixed pixel height here (was height=184): the content below
            # grew once the Configuration rows gained row dividers + more
            # vertical breathing room, and a fixed-height ZStack would just
            # clip/overlap the extra content. Auto-size-to-content via a
            # bare ui.ZStack() is the same Method already used for the
            # "Load Model" card in model_download.py.
            with ui.ZStack():
                ui.Rectangle(style=R.STYLE_CARD)
                # Headers are direct children of this OUTER, unstyled VStack
                # (no style={"margin": ...} anywhere on an ancestor of a
                # card_header_wiz() call) - same placement as the "Test
                # Inference" header in Card 2 below, which already renders
                # its accent bar correctly. The per-section body content
                # gets its inset from a plain ui.HStack + Spacer(width=N)
                # sandwich instead of a styled margin: a
                # style={"margin": N} on a VStack cascades down to every
                # descendant (not just direct children), so putting a header
                # *inside* such a VStack shrinks its accent-bar Rectangle to
                # invisible and shifts the header's own left edge by the
                # cascaded margin (exactly what was found live: 0 accent
                # pixels, box left edge x=41 instead of x=24). A bare
                # ui.Spacer() is a layout widget, not a style, so it cannot
                # cascade - this was the fix already applied to
                # model_download.py's card_header_wiz() header band.
                with ui.VStack(spacing=R.SPACING_CARD_INNER_WIDE):
                    R.card_header_wiz("Setup complete", bar_width=R.WIDTH_ACCENT_BAR_WIZARD)
                    with ui.HStack():
                        ui.Spacer(width=R.MARGIN_WIZARD_CARD_INNER)
                        with ui.VStack(spacing=R.SPACING_CARD_INNER_WIDE):
                            ui.Label(
                                "Your inference server is configured. "
                                "Review the summary and run a quick test.",
                                height=16, word_wrap=True, style=R.STYLE_WIZARD_CARD_DESCRIPTION)

                            # -- status banner: green (online) / amber (remote offline) /
                            #    red (local server not running) --
                            with ui.ZStack(height=40):
                                self._done_status_bg = ui.Rectangle(style=_STYLE_DONE_BANNER_WARN)
                                with ui.HStack(spacing=8, height=40, style={"margin": 8}):
                                    # style={"margin": 0} stops the parent HStack's
                                    # style={"margin": 8} from cascading down and
                                    # collapsing this 8x8 dot's content box to 0
                                    # (same Kit margin-cascade quirk documented in
                                    # contact_us_win.py's eyebrow-row dot).
                                    with ui.VStack(width=8, style={"margin": 0}):
                                        ui.Spacer()
                                        self._done_status_dot = ui.Rectangle(
                                            width=8, height=8, style=_STYLE_DONE_DOT_WARN)
                                        ui.Spacer()
                                    self._done_server_status = ui.Label(
                                        "Checking server status...", word_wrap=True,
                                        style=R.STYLE_WIZARD_OK_TEXT)
                                    self._done_start_server_row = ui.HStack(width=0)
                                    with self._done_start_server_row:
                                        self._done_start_server_btn = R.primary_button(
                                            "Start Server", self._done_start_server,
                                            height=R.HEIGHT_BTN_PRIMARY_WIZARD, width=110,
                                            tooltip="Start the VLM inference server")
                                    self._done_start_server_row.visible = False
                                    self._done_reconnect_row = ui.HStack(width=0)
                                    with self._done_reconnect_row:
                                        self._done_reconnect_btn = R.primary_button(
                                            "Reconnect", self._done_check_server,
                                            height=R.HEIGHT_BTN_PRIMARY_WIZARD, width=100,
                                            tooltip="Re-check the remote server connection")
                                    self._done_reconnect_row.visible = False

                            # -- tray-window observed result (issue #14) --
                            # Reports what tray_agent_launcher ACTUALLY did
                            # (read from ~/.labr7/tray_status.json), not a
                            # prediction — the Path A setup page's preflight
                            # strip covers the predicted side. Explicit
                            # height (Line/row-divider landmine: unsized rows
                            # in this VStack misrender).
                            self._done_tray_row = ui.HStack(
                                height=16, spacing=6, visible=False)
                            with self._done_tray_row:
                                self._done_tray_label = ui.Label(
                                    "", word_wrap=True,
                                    style=R.STYLE_WIZARD_OK_TEXT_MUTED)
                                self._done_tray_copy_btn = R.secondary_button_wiz(
                                    "Copy", self._done_tray_copy,
                                    height=16, width=48,
                                    tooltip="Copy the fix command to clipboard")
                                self._done_tray_copy_btn.visible = False
                        ui.Spacer(width=R.MARGIN_WIZARD_CARD_INNER)

                    # -- configuration --
                    R.card_header_wiz("Configuration", bar_width=R.WIDTH_ACCENT_BAR_WIZARD)
                    with ui.HStack():
                        ui.Spacer(width=R.MARGIN_WIZARD_CARD_INNER)
                        # Row dividers + a wider row pitch (was a bare height=16
                        # HStack per row with no separators, reading as a single
                        # cramped block vs. the reference's clearly-separated
                        # summary rows).
                        #
                        # ui.Line(height=1, border_width=1) - NOT a filled
                        # ui.Rectangle (see issue #44: a bare Rectangle happily
                        # fills whatever height its parent gives it, and an
                        # oversized height here rendered as a thick solid grey
                        # bar, not a hairline). This is the same idiom already
                        # proven correct for the identical "divider between two
                        # same-background rows" case in sidecar_setup.py's
                        # System Requirements GPU/VRAM/Disk/RAM rows: a filled
                        # Rectangle renders as a thick bar, not a hairline,
                        # once its parent gives it more than 1px of height.
                        #
                        # This row group used to sit inside the same
                        # style={"margin": N} VStack as the "Configuration"
                        # header above it - the cascaded margin was landing on
                        # every row HStack and every divider too, nearly
                        # doubling the row pitch (72px live vs the ~41-46px the
                        # declared height=16/spacing=6/height=1 values actually
                        # add up to). Moving to the Spacer-sandwich inset above
                        # removes that cascade.
                        with ui.VStack(spacing=6):
                            with ui.HStack(height=16, spacing=6):
                                ui.Label("MODE", width=90, style=R.STYLE_WIZARD_CHECKED_AT)
                                self._done_info_label = ui.Label(
                                    "-", style=R.STYLE_WIZARD_STATUS_TEXT)
                            ui.Line(height=1, style={"color": R.COLOR_BORDER, "border_width": 1})
                            with ui.HStack(height=16, spacing=6):
                                ui.Label("MODEL", width=90, style=R.STYLE_WIZARD_CHECKED_AT)
                                self._done_model_label = ui.Label(
                                    "-", style=R.STYLE_WIZARD_STATUS_TEXT)
                            ui.Line(height=1, style={"color": R.COLOR_BORDER, "border_width": 1})
                            with ui.HStack(height=16, spacing=6):
                                ui.Label("ENDPOINT", width=90, style=R.STYLE_WIZARD_CHECKED_AT)
                                self._done_test_url_label = ui.Label(
                                    "-", style=R.STYLE_WIZARD_STATUS_TEXT)
                        ui.Spacer(width=R.MARGIN_WIZARD_CARD_INNER)
            ui.Spacer(height=2)

            # ---- Card 2: Test Inference ----
            # No fixed pixel height (was height=232) now that the body is
            # inset via its own Spacer-sandwich below — same auto-size
            # Method as Card 1 above and the "Load Model" card in
            # model_download.py.
            with ui.ZStack():
                ui.Rectangle(style=R.STYLE_CARD)
                with ui.VStack(spacing=R.SPACING_CARD_INNER):
                    R.card_header_wiz("Test Inference", bar_width=R.WIDTH_ACCENT_BAR_WIZARD)
                    # Body inset from the card edges (was flush with the
                    # card background - no border/margin at all around the
                    # thumbnail+prompt+CTA+result group). Uses a plain
                    # ui.HStack + Spacer(width=N) sandwich rather than
                    # style={"margin": N} on the inner VStack: the latter
                    # cascades to every descendant, which was independently
                    # shrinking the thumbnail (declared 80 -> rendered 76),
                    # the Run Test/Finish button fill (declared 30 -> rendered
                    # 27-28), and
                    # inflating the Spacer(height=2) gap below the thumbnail
                    # row out to ~48px live. A Spacer is a layout widget, not
                    # a style, so it cannot cascade.
                    with ui.HStack():
                        ui.Spacer(width=R.MARGIN_WIZARD_CARD_INNER)
                        with ui.VStack(spacing=R.SPACING_CARD_INNER_WIDE):
                            with ui.HStack(height=_SIZE_TEST_THUMB, spacing=8):
                                if self._test_img_path:
                                    with ui.ZStack(width=_SIZE_TEST_THUMB, height=_SIZE_TEST_THUMB):
                                        ui.Rectangle(style=R.STYLE_CARD_WIZARD)
                                        ui.Image(self._test_img_path,
                                                 fill_policy=ui.FillPolicy.PRESERVE_ASPECT_FIT)
                                with ui.VStack(spacing=4):
                                    ui.Label("PROMPT", height=12, style=R.STYLE_WIZARD_CHECKED_AT)
                                    self._test_prompt_field = ui.StringField(
                                        height=24, style=R.STYLE_INPUT_FIELD_WIZ)
                                    self._test_prompt_field.model.set_value(
                                        "Describe what you see in this image.")
                            # height=8 (was 2): with the margin-cascade gone,
                            # the raw gap is spacing(4) + this Spacer +
                            # spacing(4) - 8 lands the total on the
                            # reference's ~16px gap instead of overshooting.
                            ui.Spacer(height=8)
                            self._run_test_btn = R.primary_button(
                                "Run Test", self._run_test_inference,
                                height=_HEIGHT_BTN_DONE,
                                tooltip="Send a test image to the loaded VLM model")
                            self._run_test_btn.enabled = False
                            ui.Spacer(height=2)
                            with ui.ZStack(height=80):
                                ui.Rectangle(style=R.STYLE_WIZARD_LOG_PANEL)
                                with ui.ScrollingFrame(
                                        horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
                                        vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED,
                                        style={"background_color": 0x00000000,
                                               "border_color": 0x00000000, "border_width": 0}):
                                    self._test_result_label = ui.Label(
                                        "Result will appear here.", word_wrap=True,
                                        style=R.STYLE_WIZARD_LOG_LABEL)
                        ui.Spacer(width=R.MARGIN_WIZARD_CARD_INNER)

            # ---- Bottom nav-footer band (ref full_png/05-complete.png) ----
            # A single trailing Spacer (P2-compliant: at most one) hugs this
            # band to the true bottom of the page, matching the Method
            # already established in choose_server.py / sidecar_setup.py /
            # model_download.py's footers (divider + darker band, not
            # per-content padding that leaves a floating footer mid-page).
            ui.Spacer()
            ui.Rectangle(height=1, style=R.STYLE_WIZARD_FOOTER_DIVIDER)
            with ui.ZStack(height=R.HEIGHT_WIZARD_FOOTER_BAND):
                ui.Rectangle(style=R.STYLE_WIZARD_FOOTER_BAND)
                # NOTE: no style={"margin": N} here - same confirmed fix as
                # sidecar_setup.py's path_a footer: a margin style on this HStack
                # cascades to Back/Finish, shrinking their rendered fill
                # below the declared height. The ZStack already centers this
                # fixed-height HStack vertically for free, and the unstyled
                # HStack still fills the full band width, so no replacement
                # margin is needed.
                with ui.HStack(height=_HEIGHT_BTN_DONE, spacing=6):
                    R.secondary_button_wiz("< Back", self._done_back,
                                       height=_HEIGHT_BTN_DONE,
                                       tooltip="Return to the previous step")
                    ui.Spacer()
                    self._done_finish_btn = R.primary_button(
                        "Finish", self._close_wizard,
                        height=_HEIGHT_BTN_DONE, width=100,
                        tooltip="Dismiss the wizard. Your configuration is already saved.")

    def _goto_done_local(self):
        self._done_page_url = f"http://127.0.0.1:{self._mgr.config.get('port', 8765)}"
        self._goto(_PAGE_DONE)

    def _done_back(self):
        if self._selected_path == "B":
            # Path B forward is only Connect -> Done (Load Model is skipped
            # entirely, issue #17), so Back always returns to Connect.
            self._goto(_PAGE_PATH_B_CONNECT)
        else:
            self._goto(_PAGE_PATH_A_DOWNLOAD)

    # ------------------------------------------------------------------
    # Done page — server health probe
    # ------------------------------------------------------------------
    def _done_check_server(self):
        def _probe():
            try:
                client   = self._mgr.client
                is_local = (self._mgr.config.get("mode") != "remote")
                if client is None:
                    online = False
                    loaded = False
                else:
                    try:
                        h      = client.health(timeout=3.0)
                        online = (h.get("status") == "ok" and not h.get("error"))
                        loaded = bool(h.get("loaded")) if online else False
                    except Exception:  # noqa: BLE001
                        online = False
                        loaded = False
                try:
                    if online and loaded:
                        self._done_server_status.text  = "Server online and ready"
                        self._done_server_status.style = R.STYLE_WIZARD_OK_TEXT_MUTED
                        if self._done_status_bg is not None:
                            self._done_status_bg.style = _STYLE_DONE_BANNER_OK
                        if getattr(self, "_done_status_dot", None) is not None:
                            self._done_status_dot.style = _STYLE_DONE_DOT_OK
                        if self._done_start_server_row is not None:
                            self._done_start_server_row.visible = False
                        if getattr(self, "_done_reconnect_row", None) is not None:
                            self._done_reconnect_row.visible = False
                        if self._run_test_btn is not None:
                            self._run_test_btn.enabled = True
                    elif online and not loaded:
                        self._done_server_status.text = (
                            "Server online - no model loaded yet.\n"
                            "Go Back to the Model step to download or load one, "
                            "then press Reconnect.")
                        self._done_server_status.style = R.STYLE_WIZARD_WARN_LABEL
                        if self._done_status_bg is not None:
                            self._done_status_bg.style = _STYLE_DONE_BANNER_WARN
                        if getattr(self, "_done_status_dot", None) is not None:
                            self._done_status_dot.style = _STYLE_DONE_DOT_WARN
                        if self._done_start_server_row is not None:
                            self._done_start_server_row.visible = False
                        if getattr(self, "_done_reconnect_row", None) is not None:
                            self._done_reconnect_row.visible = True
                        if self._run_test_btn is not None:
                            self._run_test_btn.enabled = True
                    else:
                        if self._run_test_btn is not None:
                            self._run_test_btn.enabled = False
                        if is_local:
                            self._done_server_status.text = (
                                "Server is not running. Press Start Server to launch it now.")
                            self._done_server_status.style = R.STYLE_WIZARD_ERROR_TEXT
                            if self._done_status_bg is not None:
                                self._done_status_bg.style = _STYLE_DONE_BANNER_ERROR
                            if getattr(self, "_done_status_dot", None) is not None:
                                self._done_status_dot.style = _STYLE_DONE_DOT_ERROR
                            if self._done_start_server_row is not None:
                                self._done_start_server_row.visible = True
                            if getattr(self, "_done_reconnect_row", None) is not None:
                                self._done_reconnect_row.visible = False
                        else:
                            self._done_server_status.text = (
                                "Remote server appears offline.\n"
                                "The endpoint isn't responding yet. Reconnect to retry.")
                            self._done_server_status.style = R.STYLE_WIZARD_WARN_LABEL
                            if self._done_status_bg is not None:
                                self._done_status_bg.style = _STYLE_DONE_BANNER_WARN
                            if getattr(self, "_done_status_dot", None) is not None:
                                self._done_status_dot.style = _STYLE_DONE_DOT_WARN
                            if self._done_start_server_row is not None:
                                self._done_start_server_row.visible = False
                            if getattr(self, "_done_reconnect_row", None) is not None:
                                self._done_reconnect_row.visible = True

                    self._done_online = online
                    self._done_loaded = loaded
                    self._done_is_local = is_local
                    self._done_probe_done = True
                    # issue #46: Finish's base style is never conditioned on
                    # online/loaded -- it stays on its normal primary skin
                    # (set once at construction) throughout. Only the
                    # attention pulse target moves between Start
                    # Server/Reconnect and Finish based on this probe.
                    self._done_update_pulse()
                except Exception:  # noqa: BLE001
                    pass

                # issue #14 — observed tray outcome. The launcher needs a few
                # seconds after spawn to finish its own tier fallback and
                # write ~/.labr7/tray_status.json, so poll briefly (we are
                # already on this probe's daemon thread).
                try:
                    import time as _time
                    from ...vlm.sidecar_manager import get_tray_status
                    status = None
                    for _ in range(5):
                        status = get_tray_status()
                        if status and status.get("tier") in (
                                "pystray", "tkinter", "headless"):
                            break
                        _time.sleep(1.0)
                    self._done_render_tray_row(status)
                except Exception:  # noqa: BLE001
                    pass
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=_probe, daemon=True).start()

    def _done_render_tray_row(self, status: "dict | None"):
        """Apply the observed tray tier to the Done-page row (issue #14).

        status is get_tray_status()'s payload: None (no live tray — hide the
        row entirely), tier pystray/tkinter (tray UI is up), or tier headless
        (tray process alive but no window; surface the recorded hint, falling
        back to a fresh check_tray_ui() when the status file has none)."""
        try:
            tier = (status or {}).get("tier")
            if tier in ("pystray", "tkinter"):
                self._done_tray_label.text  = "Tray window: visible"
                self._done_tray_label.style = R.STYLE_WIZARD_OK_TEXT_MUTED
                self._done_tray_copy_btn.visible = False
                self._done_tray_fix_cmd = None
                self._done_tray_row.visible = True
            elif tier == "headless":
                hint    = status.get("hint")
                fix_cmd = None
                if not hint:
                    try:
                        from ...vlm.tray_preflight import check_tray_ui
                        pf      = check_tray_ui(self._mgr.config.get("python_exe"))
                        hint    = pf.get("reason") or ""
                        fix_cmd = pf.get("fix_cmd")
                    except Exception:  # noqa: BLE001
                        hint = ""
                else:
                    # The launcher's hint embeds the apt command; offer it
                    # via Copy too.
                    if "sudo apt install python3-tk" in hint:
                        fix_cmd = "sudo apt install python3-tk"
                self._done_tray_label.text = (
                    "Tray window not shown - sidecar still works. "
                    + (hint or "")).strip()
                self._done_tray_label.style = R.STYLE_WIZARD_WARN_LABEL
                self._done_tray_fix_cmd = fix_cmd
                self._done_tray_copy_btn.visible = bool(fix_cmd)
                self._done_tray_row.visible = True
            else:
                # No live tray process (or still tier="starting") — nothing
                # trustworthy to report.
                self._done_tray_row.visible = False
        except Exception:  # noqa: BLE001
            pass

    def _done_tray_copy(self):
        try:
            import omni.kit.clipboard
            if getattr(self, "_done_tray_fix_cmd", None):
                omni.kit.clipboard.copy(self._done_tray_fix_cmd)
        except Exception:  # noqa: BLE001
            pass

    def _done_start_server(self):
        import time as _time
        try:
            if self._done_start_server_btn is not None:
                self._done_start_server_btn.enabled = False
            if self._done_server_status is not None:
                self._done_server_status.text  = "Starting server..."
                self._done_server_status.style = R.STYLE_WIZARD_OK_TEXT
        except Exception:  # noqa: BLE001
            pass

        def _spawn():
            ok, err = self._mgr.spawn_sidecar()
            if not ok:
                try:
                    self._done_server_status.text  = f"Start failed: {err}"
                    self._done_server_status.style = R.STYLE_WIZARD_ERROR_TEXT
                    if self._done_start_server_btn is not None:
                        self._done_start_server_btn.enabled = True
                except Exception:  # noqa: BLE001
                    pass
                return
            deadline = _time.time() + 30
            while _time.time() < deadline:
                _time.sleep(1)
                try:
                    h = self._mgr.client.health(timeout=3.0) if self._mgr.client else {}
                    if h.get("status") == "ok":
                        try:
                            self._done_server_status.text  = "Server online and ready"
                            self._done_server_status.style = R.STYLE_WIZARD_OK_TEXT_MUTED
                            if self._done_status_bg is not None:
                                self._done_status_bg.style = _STYLE_DONE_BANNER_OK
                            if getattr(self, "_done_status_dot", None) is not None:
                                self._done_status_dot.style = _STYLE_DONE_DOT_OK
                            if self._done_start_server_row is not None:
                                self._done_start_server_row.visible = False
                            if self._run_test_btn is not None:
                                self._run_test_btn.enabled = True
                            self._done_check_server()
                        except Exception:  # noqa: BLE001
                            pass
                        return
                except Exception:  # noqa: BLE001
                    pass
            try:
                self._done_server_status.text  = "Server did not respond within 30 s. Try Reconnect in the main panel."
                self._done_server_status.style = R.STYLE_WIZARD_ERROR_TEXT
                if self._done_start_server_btn is not None:
                    self._done_start_server_btn.enabled = True
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=_spawn, daemon=True).start()

    def _pulse_hint_done(self):
        """Which Done-page button should pulse right now (or None).

        Returns None until the async health probe has completed, so we never
        pulse a still-hidden action row. Once probed:
          online + loaded            -> Finish   (hand off to the terminal action)
          offline + local            -> Start Server
          offline remote / no model  -> Reconnect
        Called on the Kit event-loop thread only (via _goto's hook dispatch and
        _done_update_pulse's marshalled callback)."""
        if getattr(self, "_page", None) != _PAGE_DONE:
            return None
        if not getattr(self, "_done_probe_done", False):
            return None
        if getattr(self, "_done_online", False) and getattr(self, "_done_loaded", False):
            return getattr(self, "_done_finish_btn", None)
        if not getattr(self, "_done_online", False) and getattr(self, "_done_is_local", True):
            return getattr(self, "_done_start_server_btn", None)
        return getattr(self, "_done_reconnect_btn", None)

    def _done_update_pulse(self):
        """Re-evaluate + apply the Done-page pulse target on the Kit event-loop
        thread. _done_check_server / _done_start_server run on daemon threads,
        but PulseController.pulse() calls asyncio.ensure_future(), which must run
        on the app event loop — so hop back via a one-shot app-update subscription."""
        try:
            import omni.kit.app  # noqa: PLC0415
            _holder = {}
            def _apply(_e):
                _holder.pop("sub", None)  # one-shot: drop the handle -> unsubscribe
                try:
                    if getattr(self, "_page", None) == _PAGE_DONE:
                        self._set_pulse_target(self._pulse_hint_done())
                except Exception:  # noqa: BLE001
                    pass
            _holder["sub"] = (omni.kit.app.get_app()
                              .get_update_event_stream()
                              .create_subscription_to_pop(_apply))
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Inference test
    # ------------------------------------------------------------------
    def _run_test_inference(self):
        self._test_result_label.text = "Checking inference server health..."

        def _worker():
            try:
                client = self._mgr.client
                if client is None:
                    self._test_result_label.text = (
                        "No server is configured yet - go back and complete "
                        "the earlier setup steps.")
                    return

                h = client.health(timeout=5.0)
                if "error" in h or h.get("status") != "ok":
                    self._test_result_label.text = (
                        f"Inference server is offline.\n"
                        f"Start the server via Local Install or connect via Remote Install.\n"
                        f"({h.get('error', 'no response')})")
                    return
                if not h.get("loaded"):
                    self._test_result_label.text = (
                        "Server is running but no model is loaded.\n"
                        "Complete the Download or Load Model step first.")
                    return

                self._test_result_label.text = "Running inference on test image..."
                try:
                    prompt = self._test_prompt_field.model.get_value_as_string().strip()
                except Exception:  # noqa: BLE001
                    prompt = ""
                if not prompt:
                    prompt = "Describe what you see in this image."

                import numpy as np
                try:
                    import cv2 as _cv2
                    _bgr = _cv2.imread(self._test_img_path) if self._test_img_path else None
                    if _bgr is not None:
                        dummy_img = _cv2.cvtColor(_bgr, _cv2.COLOR_BGR2RGB)
                    else:
                        dummy_img = np.full((64, 64, 3), 128, dtype=np.uint8)
                except Exception:  # noqa: BLE001
                    dummy_img = np.full((64, 64, 3), 128, dtype=np.uint8)
                result = client.infer(
                    dummy_img,
                    system_prompt="You are a helpful vision assistant.",
                    user_msg=prompt,
                    tools=[],
                    want_attention=False,
                    want_layer_stack=False,
                    max_new_tokens=256,
                )
                if result.error:
                    self._test_result_label.text = f"Inference failed: {result.error[:400]}"
                else:
                    response = (result.raw_text or result.raw_tool_call
                                or result.action_token or str(result.raw))
                    ms = f"  ({result.infer_ms:.0f} ms)" if result.infer_ms else ""
                    self._test_result_label.style = R.STYLE_LOG_LABEL_OK
                    self._test_result_label.text  = f"OK  {response}{ms}"
            except Exception as e:  # noqa: BLE001
                self._test_result_label.text = f"Test failed: {e}"

        threading.Thread(target=_worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Window visibility + teardown
    # ------------------------------------------------------------------
    def _on_win_visibility_changed(self, visible: bool) -> None:
        if not visible:
            self._close_wizard()

    def _close_wizard(self):
        """Tear down the wizard window and fire on_complete (Done page) or on_forget (all other paths).

        Idempotent: safe to call from the window's visibility-changed callback, the
        main window's close handler, or a programmatic socket call, in any order and
        repeatedly.
        """
        try:
            self._wiz_pulse.stop()
        except Exception:  # noqa: BLE001
            pass

        if getattr(self, "_closing", False):
            return
        self._closing = True

        cb = self._on_complete if self._page == _PAGE_DONE else self._on_forget

        win = getattr(self, "_win", None)
        if win is not None:
            try:
                win.set_visibility_changed_fn(None)
            except Exception:  # noqa: BLE001
                pass
            try:
                win.visible = False
            except Exception:  # noqa: BLE001
                pass
        self._win = None

        self._on_complete = None
        self._on_forget   = None

        # win.destroy() must not run synchronously here -- _close_wizard()
        # is itself invoked from a button click / visibility-changed
        # callback that fires mid-draw of this same window's frame, and
        # destroying it there tears down the Container being drawn out from
        # under the draw call, raising "Container::destroy" (see issue #43).
        # Defer destroy (plus the singleton clear and cb() fire, which both
        # logically belong after teardown) to the next app-update tick,
        # mirroring choose_server.py's _async_landing_gpu_check idiom.
        async def _finish_close():
            await omni.kit.app.get_app().next_update_async()
            if win is not None:
                try:
                    win.destroy()
                except Exception:  # noqa: BLE001
                    pass
            # Clear the module singleton so the next open_wizard() builds a fresh window.
            try:
                from . import _clear_instance  # noqa: PLC0415
                _clear_instance(self)
            except Exception:  # noqa: BLE001
                pass
            if cb is not None:
                try:
                    cb()
                except Exception:  # noqa: BLE001
                    pass
        asyncio.ensure_future(_finish_close())

    def close(self):
        self._close_wizard()

    def destroy(self):
        self._close_wizard()

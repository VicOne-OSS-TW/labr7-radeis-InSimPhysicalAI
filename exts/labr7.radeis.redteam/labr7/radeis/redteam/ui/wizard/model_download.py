"""Step 3 - Download model (Path A) / Load model (Path B)."""
from __future__ import annotations

import threading
import time

import omni.ui as ui

from .. import radeis_ui as R
from ._constants import (
    DEFAULT_MODEL_REPO, _PRESET_MODELS, _N_PRESET_MODELS,
    _PAGE_PATH_A_SETUP, _PAGE_PATH_B_CONNECT, _PAGE_DONE,
    _clean_model_id,
)
from ..contact_us_win import show_contact_us
from ._helpers import _LABR7_VENV, build_status_banner, flip_button, gate_next

# "Start Download" hero CTA: full_png/04-model.png renders this primary
# button noticeably taller than the generic R.HEIGHT_BTN_PRIMARY_WIZARD (30)
# used for footer nav buttons elsewhere on this page — live-measured at 27px
# vs a 45px reference. Same "local override instead of bumping the shared
# wizard-wide constant" Method already used for sidecar_setup.py's Path B
# "Test Connection" hero CTA (_PB_CTA_H): only this one hero CTA gets the
# override, the footer's '< Back' / 'Next >' buttons on this page still use
# R.HEIGHT_BTN_PRIMARY_WIZARD.
_DL_CTA_H = 45


class Step3TransferMixin:
    """Mixin for Step 3: model download (Path A) and remote model load (Path B)."""

    # ------------------------------------------------------------------
    # 3A. Download model - PATH A
    # ------------------------------------------------------------------
    def _page_path_a_download(self):
        self._dl_cancel_flag       = [False]
        self._dl_active_job_id     = [None]
        self._pa_dl_combo_changing = False

        config_model = self._mgr.config.get("model_repo", DEFAULT_MODEL_REPO)
        clean_ids    = [_clean_model_id(m) for m in _PRESET_MODELS]
        if config_model in clean_ids:
            self._pa_dl_selected_combo_idx = clean_ids.index(config_model)
        else:
            self._pa_dl_selected_combo_idx = self._selected_combo_idx

        with ui.VStack(spacing=R.SPACING_BETWEEN_CARDS):

            # ---- Page title + subtitle --------------------------------
            # Page title uses card_header_wiz() (accent bar + filled banner
            # box), matching the Method already established for every other
            # wizard page title (choose_server.py, sidecar_setup.py) — this
            # page was the only one still using a bare HStack+Label with no
            # background, which read as "banner box not visually apparent"
            # against full_png/04-model.png.
            R.card_header_wiz("Download or load a model",
                               bar_width=R.WIDTH_ACCENT_BAR_WIZARD)
            ui.Label(
                "The inference server is installed. Now pick the model you'd like to use "
                "and download it.",
                height=16, word_wrap=True, style=R.STYLE_WIZARD_CARD_DESCRIPTION)
            ui.Spacer(height=2)

            # ---- Status banner: existing installation -----------------
            self._install_banner_frame = ui.Frame(height=36)
            with self._install_banner_frame:
                # Muted-green triple (bg/dot/text), dot vertically centered.
                _dl_ok_bg, _dl_ok_dot, self._dl_install_status = build_status_banner(
                    "ok", "Checking installation...", height=36)

            self._dl_notinstalled_frame = ui.Frame(visible=False)
            with self._dl_notinstalled_frame:
                with ui.VStack(spacing=6):
                    _dl_warn_bg, _dl_warn_dot, self._dl_install_desc = build_status_banner(
                        "warn", "Not installed. Install the inference server first.", height=36)
                    with ui.HStack(height=R.HEIGHT_BTN_SECONDARY):
                        R.secondary_button_wiz(
                            "Go to Setup",
                            lambda: self._goto(_PAGE_PATH_A_SETUP),
                            height=R.HEIGHT_BTN_SECONDARY, width=120,
                            tooltip="Return to the Install & Setup step")
                        ui.Spacer()
            ui.Spacer(height=2)

            # ---- Card: Download Model ----------------------------------
            with ui.ZStack(height=0):
                ui.Rectangle(style=R.STYLE_CARD)
                with ui.VStack(spacing=R.SPACING_CARD_INNER):
                    # Sub-header inset from the card edges (was flush with
                    # the card border - no inset at all around the accent
                    # bar + banner strip, unlike the body row below which
                    # is already inset). NOTE: this deliberately uses
                    # sibling ui.Spacer()s inside a plain (unstyled) HStack
                    # rather than a style={"margin": N} wrapper -- a plain
                    # "margin" style cascades to every descendant (see
                    # omni-ui-vstack-style-margin-cascades-to-children.md
                    # in the knowledge pool), which shrank card_header_wiz's
                    # own fixed-width accent-bar Rectangle (width=3) into
                    # invisibility when tried first. Spacers sit alongside
                    # the header instead of styling it, so nothing inside
                    # card_header_wiz is touched. Matches
                    # full_png/04-model.png (card border -> ~17px gap ->
                    # sub-header band).
                    with ui.HStack(height=R.HEIGHT_CARD_HEADER):
                        ui.Spacer(width=14)
                        R.card_header_wiz("Download Model")
                        ui.Spacer(width=14)
                    with ui.VStack(spacing=R.SPACING_CARD_INNER_WIDE,
                                   style={"margin": R.MARGIN_WIZARD_CARD_INNER}):
                        # ---- MODEL / HF TOKEN (2-column row) ----
                        # Explicit height stops this row (the only
                        # no-height item at this VStack level) from
                        # being greedy-stretched by the unbounded
                        # VStack chain above it (this page's VStack sits
                        # directly in the wizard window's own top-level
                        # ScrollingFrame, same as every other wizard page),
                        # which otherwise opens a large blank gap before the
                        # "HF token required..." helper line below
                        # (see omni-ui-height0-invisible-in-greedy-vstack
                        # in the knowledge pool; same fix already used
                        # for the analogous row in sidecar_setup.py).
                        with ui.HStack(height=12 + 4 + R.HEIGHT_INPUT_ROW_COMPACT + 4 + 14):
                            with ui.VStack(spacing=4):
                                R.label("MODEL", dim=True, size=R.FONT_WIZARD_SMALL, height=12)
                                self._pa_dl_combo = ui.ComboBox(
                                    self._pa_dl_selected_combo_idx, *_PRESET_MODELS,
                                    height=R.HEIGHT_INPUT_ROW_COMPACT,
                                    style=R.STYLE_COMBO_STANDARD)
                                R.apply_tooltip(self._pa_dl_combo,
                                                "Select which VLM model to download")

                                def _on_pa_dl_combo(m):
                                    if self._pa_dl_combo_changing:
                                        return
                                    idx = m.get_value_as_int()
                                    if idx >= _N_PRESET_MODELS:
                                        self._pa_dl_combo_changing = True
                                        m.set_value(self._pa_dl_selected_combo_idx)
                                        self._pa_dl_combo_changing = False
                                        show_contact_us()
                                        return
                                    self._pa_dl_selected_combo_idx = idx
                                self._pa_dl_combo.model.get_item_value_model() \
                                    .add_value_changed_fn(_on_pa_dl_combo)

                            ui.Spacer(width=12)

                            with ui.VStack(spacing=4):
                                R.label("HF TOKEN", dim=True, size=R.FONT_WIZARD_SMALL, height=12)
                                # Masked hint text ("hf_********") shown
                                # while the field is empty, matching
                                # reference-path_a_download_or_load.png
                                # (whose "hf_" + bullet-dot mockup uses a
                                # literal U+2022 bullet -- not renderable
                                # here: omni.ui's bundled Kit font has no
                                # glyph for it and silently substitutes
                                # "?", so this uses the documented ASCII
                                # "*" substitute instead).
                                # It is plain (non-masked) literal text,
                                # not a real default value, so password_mode
                                # is toggled off while the hint is showing
                                # (otherwise the field would re-mask the
                                # hint's own "hf_" prefix into dots too)
                                # and back on once real typed input starts,
                                # so the hint can never be mistaken for -
                                # or accidentally saved/submitted as - an
                                # actual token.
                                _hf_a_placeholder = "hf_" + "*" * 8
                                _hf_a_is_hint = [not bool(self._hf_token)]
                                _hf_a = ui.StringField(
                                    height=R.HEIGHT_INPUT_FIELD_COMPACT,
                                    style=(R.STYLE_INPUT_FIELD_PLACEHOLDER
                                           if _hf_a_is_hint[0] else R.STYLE_INPUT_FIELD),
                                    password_mode=not _hf_a_is_hint[0])
                                _hf_a.model.set_value(self._hf_token or _hf_a_placeholder)

                                def _on_pa_hf_begin_edit(m, _f=_hf_a, _flag=_hf_a_is_hint):
                                    if _flag[0]:
                                        _flag[0] = False
                                        _f.style = R.STYLE_INPUT_FIELD
                                        _f.password_mode = True
                                        m.set_value("")
                                _hf_a.model.add_begin_edit_fn(_on_pa_hf_begin_edit)

                                def _on_pa_hf_end_edit(m, _f=_hf_a, _flag=_hf_a_is_hint):
                                    if not m.get_value_as_string():
                                        _flag[0] = True
                                        _f.style = R.STYLE_INPUT_FIELD_PLACEHOLDER
                                        _f.password_mode = False
                                        m.set_value(_hf_a_placeholder)
                                _hf_a.model.add_end_edit_fn(_on_pa_hf_end_edit)

                                def _on_pa_hf_changed(m, _flag=_hf_a_is_hint):
                                    if _flag[0]:
                                        return
                                    self._hf_token = m.get_value_as_string()
                                _hf_a.model.add_value_changed_fn(_on_pa_hf_changed)

                                R.label("Required only for gated models.", dim=True,
                                        size=R.FONT_WIZARD_STEP, height=14)

                        ui.Spacer(height=4)

                        self._start_dl_btn = R.primary_button(
                            "Start Download", self._start_download,
                            height=_DL_CTA_H,
                            tooltip="Download the selected VLM model weights")

                        self._dl_log_frame = ui.Frame(visible=False)
                        with self._dl_log_frame:
                            with ui.ZStack(height=98):
                                ui.Rectangle(style=R.STYLE_WIZARD_LOG_PANEL)
                                with ui.VStack(spacing=4, style={"margin": 6}):
                                    self._dl_progress, self._set_dl_prog, self._hide_dl_prog = \
                                        self._make_progress_bar()
                                    self._dl_status = ui.Label(
                                        "", height=40, word_wrap=True,
                                        style=R.STYLE_WIZARD_LOG_LABEL)
                                    with ui.HStack(height=20, spacing=4):
                                        ui.Spacer()
                                        self._download_open_log_btn = R.secondary_button_wiz(
                                            "Open Log",
                                            lambda: self._open_log_file(
                                                self._download_log_path),
                                            height=20, width=80,
                                            tooltip="Open the download log in your text editor")
                                        self._download_open_log_btn.enabled = False
                        ui.Spacer(height=4)

            # NOTE: this page intentionally has no second "Model Already
            # Downloaded" card. The reference design shows cache state
            # exactly once, via the green "Existing installation found"
            # banner above (IMPROVE.md item 5) — a prior attempt made a
            # duplicate card conditionally visible only when a cached
            # snapshot was actually found, but that still produces two
            # simultaneous cache-state surfaces on any machine that
            # genuinely has a cached model (as this dev/test rig does),
            # which is exactly the state the reference was captured in.
            # So the fix is to not build a second surface at all rather
            # than gate its visibility on a probe result.

            # ---- Bottom nav-footer band (ref full_png/04-model.png) ----
            # A single trailing Spacer (P2-compliant: at most one) hugs this
            # band to the true bottom of the page, matching the Method
            # already established in choose_server.py / sidecar_setup.py's
            # footers. This also depends on the page body no longer being
            # wrapped in its own nested ui.ScrollingFrame (removed above) --
            # a nested ScrollingFrame gives its VStack a content-sized
            # (not window-sized) height, so a trailing Spacer inside it has
            # no leftover space to expand into and the footer would sit
            # right under the card instead of at the window bottom.
            ui.Spacer()
            ui.Rectangle(height=1, style=R.STYLE_WIZARD_FOOTER_DIVIDER)
            with ui.ZStack(height=R.HEIGHT_WIZARD_FOOTER_BAND):
                ui.Rectangle(style=R.STYLE_WIZARD_FOOTER_BAND)
                # NOTE: no style={"margin": N} here. Kit cascades a margin
                # style down to every descendant widget rather than
                # applying it once to this container, so with 3 children
                # (2 buttons + Spacer) each picked up its own extra 12px
                # on every side, stranding
                # Next ~26px short of the true right edge. The ZStack
                # already centers this fixed-height HStack vertically for
                # free, and the unstyled HStack still fills the full band
                # width so no replacement margin is needed.
                with ui.HStack(height=R.HEIGHT_BTN_PRIMARY_WIZARD, spacing=6):
                    R.secondary_button_wiz("< Back", self._dl_back,
                                           height=R.HEIGHT_BTN_PRIMARY_WIZARD,
                                           tooltip="Return to Install & Setup")
                    ui.Spacer()
                    self._dl_next_btn = R.danger_button(
                        "Next >",
                        lambda: self._goto_done_local(),
                        height=R.HEIGHT_BTN_PRIMARY_WIZARD,
                        tooltip="Proceed to the final step")

        self._refresh_dl_btn_enabled()

    def _cancel_dl_job(self):
        self._dl_cancel_flag[0] = True
        job_id = self._dl_active_job_id[0]
        if job_id and self._mgr.client:
            try:
                self._mgr.client.cancel_download(job_id)
            except Exception:  # noqa: BLE001
                pass

    def _dl_back(self):
        self._cancel_dl_job()
        self._goto(_PAGE_PATH_A_SETUP)

    def _on_dl_cancel(self):
        self._cancel_dl_job()
        try:
            self._dl_status.text = "Download cancelled."
        except Exception:  # noqa: BLE001
            pass
        self._dl_reset_idle()

    def _dl_reset_idle(self):
        """Reset the Start Download button and resume the idle-page pulse hint.

        Called from both the main thread (_on_dl_cancel, a UI click handler)
        and the background download worker's `finally` block (see
        _start_download._worker). PulseController.pulse() with a non-None
        widget calls asyncio.ensure_future(), which requires the Kit app
        event loop and raises off the UI thread (silently swallowed here) --
        worse, its stop()-then-ensure_future ordering means a worker-thread
        call can cancel a pulse the main thread just started (e.g. right
        after a user cancel) without managing to restart it. So the pulse
        resume is always marshalled onto the next app-update tick, mirroring
        complete_test.py's _done_update_pulse."""
        try:
            flip_button(self._start_dl_btn, "Start Download", self._start_download)
            self._start_dl_btn.enabled = True
        except Exception:  # noqa: BLE001
            pass
        self._dl_resume_pulse()

    def _dl_resume_pulse(self):
        """Resume the Path-A idle pulse hint on the Kit event-loop thread."""
        try:
            import omni.kit.app  # noqa: PLC0415
            _holder = {}
            def _apply(_e):
                _holder.pop("sub", None)  # one-shot: drop the handle -> unsubscribe
                try:
                    self._set_pulse_target(self._pulse_hint_path_a_download())
                except Exception:  # noqa: BLE001
                    pass
            _holder["sub"] = (omni.kit.app.get_app()
                              .get_update_event_stream()
                              .create_subscription_to_pop(_apply))
        except Exception:  # noqa: BLE001
            pass

    def _pulse_hint_path_a_download(self):
        if bool(self._mgr.config.get("setup_complete")):
            return getattr(self, "_dl_next_btn", None)
        return getattr(self, "_start_dl_btn", None)

    def _pulse_hint_path_b_load(self):
        return getattr(self, "_pb_load_btn", None)

    def _refresh_dl_btn_enabled(self):
        venv_python  = _LABR7_VENV / "bin" / "python"
        setup_done   = self._mgr.config.get("setup_complete") or venv_python.exists()
        model_loaded = bool(self._mgr.config.get("setup_complete"))
        # Re-sync the MODEL combo from config each time this page is
        # (re)entered. The combo's index is otherwise only set once, at
        # page construction (see _page_path_a_download), so a model chosen
        # later on the Setup page would silently keep pointing Start
        # Download at the stale selection.
        try:
            config_model = self._mgr.config.get("model_repo", DEFAULT_MODEL_REPO)
            clean_ids    = [_clean_model_id(m) for m in _PRESET_MODELS]
            fresh_idx    = (clean_ids.index(config_model) if config_model in clean_ids
                            else self._selected_combo_idx)
            if fresh_idx != getattr(self, "_pa_dl_selected_combo_idx", fresh_idx):
                self._pa_dl_selected_combo_idx = fresh_idx
                self._pa_dl_combo_changing = True
                self._pa_dl_combo.model.get_item_value_model().set_value(fresh_idx)
                self._pa_dl_combo_changing = False
        except Exception:  # noqa: BLE001
            pass
        # If no download is currently in flight, don't leave the log panel
        # showing a stale "cancelled"/error message and progress bar from a
        # previous attempt when the page is (re)entered fresh.
        if self._dl_active_job_id[0] is None:
            try:
                self._dl_log_frame.visible = False
                self._dl_status.text = ""
                self._hide_dl_prog()
            except Exception:  # noqa: BLE001
                pass
        try:
            flip_button(self._start_dl_btn, "Start Download", self._start_download)
            self._start_dl_btn.enabled = setup_done
            if setup_done:
                # NOTE: reference-path_a_download_or_load.png shows an em
                # dash here, but omni.ui's bundled Kit font has no glyph for
                # U+2014 and silently substitutes "?" at runtime. The fix
                # is the ASCII " - " substitute.
                self._dl_install_status.text = "Existing installation found - environment ready."
                self._install_banner_frame.visible = True
                self._dl_notinstalled_frame.visible = False
            else:
                self._install_banner_frame.visible = False
                self._dl_notinstalled_frame.visible = True
            gate_next(self._dl_next_btn, model_loaded)
        except Exception:  # noqa: BLE001
            pass

    def _start_download(self):
        try:
            self._dl_log_frame.visible = True
        except Exception:  # noqa: BLE001
            pass
        idx        = getattr(self, "_pa_dl_selected_combo_idx", 0)
        model_repo = _clean_model_id(_PRESET_MODELS[idx]) if idx < len(_PRESET_MODELS) else DEFAULT_MODEL_REPO
        self._mgr.save_config({"model_repo": model_repo})
        ts          = time.strftime("%Y%m%dT%H%M%S")
        dl_log_path = _LABR7_VENV.parent / "logs" / f"download_{ts}.log"
        dl_log_path.parent.mkdir(parents=True, exist_ok=True)
        self._download_log_path = dl_log_path
        if hasattr(self, "_download_open_log_btn") and self._download_open_log_btn is not None:
            try:
                self._download_open_log_btn.enabled = True
            except Exception:  # noqa: BLE001
                pass
        log_hint = f"Log: {dl_log_path}"
        self._dl_status.text = f"Triggering download: {model_repo} ...\n{log_hint}"
        self._set_dl_prog(0.1)
        client = self._mgr.client
        if client is None:
            self._dl_status.text = "Inference server not running - go back to Setup and press Start Server first."
            try:
                self._start_dl_btn.enabled = True
            except Exception:  # noqa: BLE001
                pass
            return

        def _dl_log(msg: str):
            print(f"[radeis-download] {msg}")
            try:
                with open(dl_log_path, "a") as _lf:
                    _lf.write(msg + "\n")
            except Exception:  # noqa: BLE001
                pass

        def _set_status(line: str):
            try:
                self._dl_status.text = f"{line}\n{log_hint}"
            except Exception:  # noqa: BLE001
                pass

        self._dl_cancel_flag[0]   = False
        self._dl_active_job_id[0] = None

        def _worker():
            dl_start        = time.time()
            _navigated_away = [False]
            try:
                _dl_log(f"start {model_repo}")
                hf_token = self._hf_token or None
                resp     = client.download(repo=model_repo, hf_token=hf_token)
                job_id   = resp.get("job_id")
                if not job_id:
                    msg = f"Download could not be started: {resp}"
                    _dl_log(msg); _set_status(msg); return
                self._dl_active_job_id[0] = job_id
                _dl_log(f"job_id={job_id}")
                _set_status(f"Downloading (job {job_id[:8]})...")
                _unknown_streak = 0;  _last_pct = -1;  _pct_stall_start = time.time()
                while not self._dl_cancel_flag[0]:
                    time.sleep(3)
                    if self._dl_cancel_flag[0]:
                        break
                    st    = client.download_status(job_id)
                    state = st.get("state", "?")
                    pct   = st.get("pct", 0)
                    msg_detail = st.get("msg", "")
                    self._set_dl_prog(pct / 100.0)
                    if state in ("unknown", "?"):
                        _unknown_streak += 1
                        if _unknown_streak >= 3:
                            err_msg = ("Download job lost - the server may have restarted. "
                                       "Press Start Server in Setup, then Start Download again.")
                            _dl_log(err_msg); _set_status(err_msg); return
                        continue
                    _unknown_streak = 0
                    if state == "cancelled":
                        _dl_log("download cancelled"); return
                    if state == "done":
                        model_path = st.get("path", "")
                        _dl_log(f"done path={model_path}")
                        self._mgr.save_config({"model_path": model_path})
                        _set_status("Download complete. Loading model into the inference server...")
                        self._set_dl_prog(0.8)
                        load_resp = client.load_model(
                            path_or_repo=model_path, source="local", dtype="bfloat16")
                        if load_resp.get("loaded"):
                            self._mgr.register_pair(self._mgr.active_url, model_repo)
                            _dl_log("model loaded OK")
                            _set_status(f"Model loaded successfully. Path: {model_path}")
                            self._set_dl_prog(1.0)
                            self._mgr.save_config({"setup_complete": True})
                            self._mgr.spawn_tray()
                            try:
                                gate_next(self._dl_next_btn, True)
                            except Exception:  # noqa: BLE001
                                pass
                            _navigated_away[0] = True
                            self._done_page_url = f"http://127.0.0.1:{self._mgr.config.get('port', 8765)}"
                            self._goto(_PAGE_DONE)
                        else:
                            err = load_resp.get("error", str(load_resp))
                            _dl_log(f"load failed: {err}")
                            _set_status(
                                f"Download succeeded but model failed to load:\n"
                                f"{err[:120]}\nCheck VRAM and disk space, then try again.")
                        return
                    elif state == "error":
                        err_detail = st.get("msg", "download failed")
                        if "Permission denied" in err_detail:
                            err_msg = (
                                "Download failed: permission error on model cache.\n"
                                "Fix: run on the inference-server machine:\n"
                                "  sudo chown -R $USER ~/.cache/huggingface")
                        elif "empty" in err_detail and "snapshot" in err_detail:
                            err_msg = (
                                "Download failed: stale cache state (empty snapshot).\n"
                                "Fix: clear the model cache and re-download:\n"
                                "  rm -rf ~/.cache/huggingface/hub/models--*")
                        else:
                            err_msg = f"Download failed: {err_detail}"
                        trace = st.get("trace", "")
                        if trace:
                            _dl_log(f"traceback:\n{trace}")
                        _dl_log(err_msg); _set_status(err_msg); return
                    else:
                        elapsed = time.time() - dl_start
                        if pct != _last_pct:
                            _last_pct = pct;  _pct_stall_start = time.time()
                        stall_sec = time.time() - _pct_stall_start
                        if pct == 0 and stall_sec > 30:
                            status_line = (
                                f"Still initializing... ({int(stall_sec)}s) - "
                                "HuggingFace Hub is resolving the repo or checking the cache.")
                            _dl_log(status_line); _set_status(status_line); continue
                        eta_str = ""
                        if 2 < pct < 99 and elapsed > 5:
                            remaining = elapsed / (pct / 100) - elapsed
                            if remaining > 3600:
                                eta_str = f"  ~{remaining / 3600:.1f}h left"
                            elif remaining > 60:
                                eta_str = f"  ~{remaining / 60:.0f}m left"
                            else:
                                eta_str = f"  ~{remaining:.0f}s left"
                        status_line = f"Downloading... {pct}%{eta_str}"
                        if msg_detail:
                            status_line += f" - {msg_detail}"
                        _dl_log(status_line); _set_status(status_line)
            except Exception as e:  # noqa: BLE001
                err_msg = f"Download error: {e}\nCheck the log at {dl_log_path} for details."
                _dl_log(err_msg)
                try:
                    self._dl_status.text = err_msg
                except Exception:  # noqa: BLE001
                    pass
            finally:
                if not _navigated_away[0]:
                    self._dl_reset_idle()

        try:
            flip_button(self._start_dl_btn, "Cancel", self._on_dl_cancel)
            self._start_dl_btn.enabled = True
        except Exception:  # noqa: BLE001
            pass
        self._set_pulse_target(None)

        threading.Thread(target=_worker, daemon=True).start()

    # ------------------------------------------------------------------
    # 3B. Load model on remote server - PATH B
    # ------------------------------------------------------------------
    def _page_path_b_load(self):
        config_model = self._mgr.config.get("model_repo", DEFAULT_MODEL_REPO)
        clean_ids    = [_clean_model_id(m) for m in _PRESET_MODELS]
        if config_model in clean_ids:
            self._pb_load_selected_combo_idx = clean_ids.index(config_model)
        else:
            self._pb_load_selected_combo_idx = self._pb_selected_combo_idx

        with ui.VStack(spacing=R.SPACING_BETWEEN_CARDS):

            # ---- Page title + subtitle --------------------------------
            with ui.HStack(height=20, spacing=6):
                ui.Rectangle(width=R.WIDTH_ACCENT_BAR,
                             style={"background_color": R.COLOR_ACCENT})
                ui.Label(
                    "Download or load a model",
                    style={"color": R.COLOR_TEXT_PRIMARY,
                           "font_size": R.FONT_SECTION_TITLE},
                    alignment=ui.Alignment.LEFT_CENTER)
            ui.Label(
                "The inference server is connected. Load the selected model onto the remote server.",
                height=16, word_wrap=True, style=R.STYLE_WIZARD_CARD_DESCRIPTION)
            ui.Spacer(height=2)

            with ui.ZStack():
                ui.Rectangle(style=R.STYLE_CARD)
                with ui.VStack(spacing=R.SPACING_CARD_INNER):
                    R.card_header_wiz("Load Model")
                    with ui.VStack(spacing=R.SPACING_CARD_INNER_WIDE,
                                   style={"margin": R.MARGIN_WIZARD_CARD_INNER}):
                        R.label("MODEL", dim=True, size=R.FONT_WIZARD_SMALL, height=12)
                        self._pb_combo = ui.ComboBox(
                            self._pb_load_selected_combo_idx, *_PRESET_MODELS,
                            height=R.HEIGHT_INPUT_ROW_COMPACT,
                            style=R.STYLE_COMBO_STANDARD)
                        R.apply_tooltip(self._pb_combo, "Select model variant to load on the remote server")
                        self._pb_load_coming_soon_label = ui.Label(
                            "", height=R.HEIGHT_WIZARD_RESOURCE_LABEL,
                            style={"color": 0xFFFFAA44, "font_size": 12}, visible=False)

                        def _on_pb_combo_changed(m):
                            if self._pb_load_combo_changing:
                                return
                            idx = m.get_value_as_int()
                            if idx >= _N_PRESET_MODELS:
                                self._pb_load_combo_changing = True
                                m.set_value(self._pb_load_selected_combo_idx)
                                self._pb_load_combo_changing = False
                                show_contact_us()
                                return
                            self._pb_load_selected_combo_idx = idx
                        self._pb_combo.model.get_item_value_model().add_value_changed_fn(_on_pb_combo_changed)

                        ui.Spacer(height=4)
                        R.label("HF TOKEN", dim=True, size=R.FONT_WIZARD_SMALL, height=12)
                        _hf_b_load = ui.StringField(
                            height=R.HEIGHT_INPUT_FIELD_COMPACT,
                            style=R.STYLE_INPUT_FIELD,
                            password_mode=True)
                        _hf_b_load.model.set_value(self._hf_token)
                        _hf_b_load.model.add_value_changed_fn(
                            lambda m: setattr(self, "_hf_token", m.get_value_as_string()))
                        R.label("Required only for gated models.", dim=True,
                                size=R.FONT_WIZARD_STEP, height=14)
                        ui.Spacer(height=4)

                        self._pb_load_status = ui.Label(
                            "Click 'Load Model' to let the remote inference server download and load the model.",
                            height=44, word_wrap=True,
                            style=R.STYLE_WIZARD_STATUS_TEXT)
                        self._pb_load_progress, self._set_pb_load_prog, self._hide_pb_load_prog = \
                            self._make_progress_bar()
                        ui.Spacer(height=4)

                        self._pb_load_btn = R.primary_button(
                            "Load Model", self._pb_load_model,
                            height=R.HEIGHT_BTN_PRIMARY_WIZARD,
                            tooltip="Download and load the selected model on the remote server")
                        ui.Spacer(height=4)

                        with ui.HStack(height=R.HEIGHT_BTN_PRIMARY_WIZARD, spacing=6):
                            R.secondary_button_wiz("< Back", lambda: self._goto(_PAGE_PATH_B_CONNECT),
                                                   height=R.HEIGHT_BTN_PRIMARY_WIZARD,
                                                   tooltip="Return to Remote Install connect step")
                        ui.Spacer(height=2)
            ui.Spacer(height=2)

    def _pb_load_model(self):
        try:
            self._pb_load_btn.enabled = False
        except Exception:  # noqa: BLE001
            pass
        idx        = self._pb_load_selected_combo_idx
        model_repo = _clean_model_id(_PRESET_MODELS[idx]) if idx < len(_PRESET_MODELS) else DEFAULT_MODEL_REPO
        if not model_repo:
            self._pb_load_status.text = "No model selected - choose a model from the list above."
            try:
                self._pb_load_btn.enabled = True
            except Exception:  # noqa: BLE001
                pass
            return
        self._mgr.save_config({"model_repo": model_repo})
        self._pb_load_status.text = f"Checking remote for {model_repo}..."
        self._set_pb_load_prog(0.05)

        def _re_enable_pb():
            try:
                self._pb_load_btn.enabled = True
            except Exception:  # noqa: BLE001
                pass

        def _worker():
            import time as _time
            client   = self._mgr.client
            if client is None:
                self._pb_load_status.text = "Not connected - go back and press Test Connection first."
                self._hide_pb_load_prog()
                _re_enable_pb(); return
            hf_token = self._hf_token or None

            resp = client.load_model(path_or_repo=model_repo, source="hub", download=False)
            if resp.get("loaded"):
                load_path = None
            elif resp.get("needs_download"):
                no_token_hint = " (enter HF Token above if the model is gated)" if not hf_token else ""
                self._pb_load_status.text = f"Starting download on remote...{no_token_hint}"
                dl_resp = client.download(repo=model_repo, hf_token=hf_token)
                job_id  = dl_resp.get("job_id")
                if not job_id:
                    self._pb_load_status.text = (
                        f"Download could not be started: {dl_resp}\n"
                        "Check the inference server log on the remote machine.")
                    self._hide_pb_load_prog()
                    _re_enable_pb(); return
                load_path = None
                while True:
                    _time.sleep(2)
                    status = client.download_status(job_id)
                    state  = status.get("state", "running")
                    pct    = status.get("pct", 0)
                    msg    = status.get("msg", "")
                    self._pb_load_status.text = f"Downloading: {msg}" if msg else "Downloading..."
                    self._set_pb_load_prog(0.1 + pct * 0.70 / 100)
                    if state == "done":
                        load_path = status.get("path", model_repo); break
                    if state == "error":
                        if "Permission denied" in msg:
                            self._pb_load_status.text = (
                                "Download failed: permission error on model cache.\n"
                                "Fix on remote: sudo chown -R $USER ~/.cache/huggingface")
                        elif "empty" in msg and "snapshot" in msg:
                            self._pb_load_status.text = (
                                "Download failed: stale cache state (empty snapshot).\n"
                                "Fix on remote: rm -rf ~/.cache/huggingface/hub/models--*")
                        else:
                            hint = " - enter HF Token above if the model requires authentication" if not hf_token else ""
                            self._pb_load_status.text = f"Download failed: {msg}{hint}"
                        self._hide_pb_load_prog()
                        _re_enable_pb(); return
            else:
                self._pb_load_status.text = (
                    f"Remote check failed: {resp.get('error', resp)}\n"
                    "Go back and verify the connection is still active.")
                self._hide_pb_load_prog()
                _re_enable_pb(); return

            if load_path is not None:
                self._pb_load_status.text = "Loading model into VRAM (may take 1-2 min)..."
                self._set_pb_load_prog(0.85)
                resp2 = client.load_model(
                    path_or_repo=load_path, source="local", download=False, dtype="bfloat16")
                if not resp2.get("loaded"):
                    self._pb_load_status.text = (
                        f"Model load failed: {resp2.get('error', resp2)}\n"
                        "Check VRAM on the remote machine and try again.")
                    self._hide_pb_load_prog()
                    _re_enable_pb(); return

            self._mgr.register_pair(self._mgr.active_url, model_repo)
            self._pb_load_status.text = "Model loaded successfully!"
            self._set_pb_load_prog(1.0)
            self._mgr.save_config({"setup_complete": True})
            self._mgr.spawn_tray()
            _time.sleep(1)
            self._done_page_url = self._mgr.active_url or self._mgr.config.get("remote_url", "")
            self._goto(_PAGE_DONE)

        threading.Thread(target=_worker, daemon=True).start()

"""Step 2 — Install & Setup (Path A) / Connect (Path B)."""
from __future__ import annotations

import asyncio
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

import omni.kit.app
import omni.ui as ui

from .. import radeis_ui as R
from ...vlm.sidecar_manager import ReadinessLevel
from ...vlm.tray_preflight import check_tray_ui
from ._constants import (
    _PRESET_MODELS, _N_PRESET_MODELS,
    _MODEL_REQUIREMENTS,
    _PAGE_LANDING, _PAGE_PATH_A_DOWNLOAD,
    _PAGE_DONE,
    _clean_model_id,
)
from ..contact_us_win import show_contact_us
from ._helpers import _LABR7_VENV, _find_system_python, _detect_cuda_version, \
    _cuda_to_torch_index, _find_sidecar_requirements, flip_button

# Label-left column widths for the MODEL / COMPUTE DEVICE / SIDECAR URL
# inline rows (full_png/02-setup-local.png and full_png/03-setup-remote.png:
# label sits left of the field, sized to its own text, not a shared
# form-column width).
_LABEL_COL_MODEL   = 50
_LABEL_COL_DEVICE  = 105
_LABEL_COL_SIDECAR = 170

# Path B "Test Connection" hero CTA: full_png/03-setup-remote.png renders this
# primary button noticeably taller than the generic R.HEIGHT_BTN_PRIMARY_WIZARD
# (30) used for footer nav buttons elsewhere on the same page — live-measured
# at ~30px vs a ~47px reference. Same "local override instead of bumping the
# shared wizard-wide constant" Method as _SYSREQ_HEADER_H above: the footer's
# '< Back' / 'Show Uninstall Script' / 'Next >' buttons on *this* page still
# use R.HEIGHT_BTN_PRIMARY_WIZARD, only this one hero CTA gets the override.
_PB_CTA_H = 47

# System Requirements Check card — explicit heights (see knowledge-pool
# platform-gotchas/omni-ui-greedy-frame-plus-nested-rebuild-compounds-into-
# growing-dead-space.md: a ZStack with no explicit height, as the lone
# no-height child of the page's outer VStack, becomes the greedy-leftover
# sink and inflates to fill the rest of the viewport instead of hugging its
# content — verified live via port-8226 widget introspection: omitting the
# height here left a ~127px gap between the warning strip and the Compute
# Device row; an explicit height on construction closes it to ~15px).
_REQ_ROW_H       = R.HEIGHT_WIZARD_RESOURCE_LABEL   # 16 — GPU/VRAM/Disk/RAM row content
# Row-to-row pitch: live-measured (port-8226 + screenshot) at 52px against a
# reference of 44px with the prior 14px gap. Live-iterated down to 7px here —
# 9px landed at 46px (still 2px over), 7px lands the divider pitch at 44px,
# matching full_png/02-setup-local.png exactly.
_REQ_ROW_GAP     = 7                                 # extra whitespace before each divider
_REQ_TABLE_H     = 152   # header + 4 rows + 3 dividers + outer padding, hand-summed below
_SYSREQ_WARN_H   = 36
# System-Requirements-card section header: full_png/02-setup-local.png renders
# this header noticeably taller than the generic R.HEIGHT_CARD_HEADER (28) used
# for plain card titles elsewhere — live-measured at 30px vs a 40px reference,
# so this card's header gets its own local override instead of bumping the
# shared wizard-wide constant (which other pages/cards still rely on at 28).
_SYSREQ_HEADER_H = 38
_SYSREQ_CARD_H_WARN = (_SYSREQ_HEADER_H + _REQ_TABLE_H + _SYSREQ_WARN_H + 6
                        + 3 * R.SPACING_CARD_INNER)

# Tray-preflight warn strip (issue #14) — explicit height, hand-summed from
# the inner VStack's 5 children (6 spacer + 28 label + 20 code + 18 buttons
# + 6 spacer = 78) plus its 4 spacing=4 gaps (16) = 94. Explicit for the
# same greedy-leftover-sink reason as _SYSREQ_CARD_H_WARN above; the value
# was 86 (8px short — the miscount clipped the Copy/Re-check row to ~3px on
# the Path B page, caught in live verification).
_TRAY_PF_STRIP_H = 94


class Step2SetupMixin:
    """Mixin for Step 2: environment install (Path A) and remote connect (Path B)."""

    # ------------------------------------------------------------------
    # 2A. Select Model + Resource Check + Start Server — PATH A
    # ------------------------------------------------------------------
    def _page_path_a_setup(self):
        self._install_then_start   = False
        self._install_proc         = None
        self._spawn_cancelled      = False
        self._spawn_waiting        = False
        self._device_user_touched  = False
        self._device_combo_setting = False
        self._tray_pf              = None
        with ui.VStack(spacing=R.SPACING_BETWEEN_CARDS):
            # ---- Title ----
            R.card_header_wiz("Install & start the local server", bar_width=R.WIDTH_ACCENT_BAR_WIZARD)
            ui.Label("Choose a model and check that your system meets its resource requirements.\n"
                     "Then start the inference server on this machine's CPU or GPU.",
                     height=32, word_wrap=True, style=R.STYLE_WIZARD_CARD_DESCRIPTION)
            ui.Spacer(height=2)

            # ---- Model select (standalone, not boxed) — label sits LEFT of the
            # field on the same row (full_png/02-setup-local.png), not stacked above it.
            with ui.HStack(height=R.HEIGHT_INPUT_ROW_COMPACT, spacing=8):
                ui.Label("MODEL", width=_LABEL_COL_MODEL,
                         alignment=ui.Alignment.LEFT_CENTER,
                         style={"color": R.COLOR_TEXT_SECONDARY, "font_size": R.FONT_DESCRIPTION})
                self._pa_combo = ui.ComboBox(
                    self._selected_combo_idx, *_PRESET_MODELS,
                    height=R.HEIGHT_INPUT_ROW_COMPACT,
                    style=R.STYLE_COMBO_STANDARD)
                R.apply_tooltip(self._pa_combo, "Select which VLM model to download and run")
            self._coming_soon_label = ui.Label(
                "", height=R.HEIGHT_WIZARD_RESOURCE_LABEL,
                style={"color": 0xFFFFAA44, "font_size": 12}, visible=False)

            def _on_combo(m):
                if self._combo_changing:
                    return
                idx = m.get_value_as_int()
                if idx >= _N_PRESET_MODELS:
                    self._combo_changing = True
                    m.set_value(self._selected_combo_idx)
                    self._combo_changing = False
                    show_contact_us()
                    return
                self._selected_combo_idx = idx
                self._selected_model_repo = _clean_model_id(_PRESET_MODELS[idx])
                self._run_resource_check()
            self._pa_combo.model.get_item_value_model().add_value_changed_fn(_on_combo)

            # ---- Card: System Requirements Check ----
            # Explicit height (not auto-sizing): this ZStack is the only
            # no-height child of the page's outer VStack, so leaving it
            # unsized makes it the greedy-leftover sink and inflates it to
            # fill the rest of the viewport (see _SYSREQ_CARD_H_* comment
            # above and foldable_section.py's card_zstack precedent).
            with ui.ZStack(height=_SYSREQ_CARD_H_WARN) as self._sysreq_card:
                ui.Rectangle(style=R.STYLE_CARD)
                with ui.VStack(spacing=R.SPACING_CARD_INNER):
                    with ui.ZStack(height=_SYSREQ_HEADER_H):
                        ui.Rectangle(style={"background_color": R.COLOR_SECTION_HEADER_BG})
                        with ui.HStack():
                            ui.Rectangle(width=R.WIDTH_ACCENT_BAR_WIZARD,
                                         style={"background_color": R.COLOR_ACCENT})
                            ui.Label(
                                "  System Requirements Check",
                                style={"color": R.COLOR_TEXT_PRIMARY, "font_size": R.FONT_CARD_TITLE},
                                alignment=ui.Alignment.LEFT_CENTER)
                            ui.Spacer()
                            self._resource_check_time_label = ui.Label(
                                "", style=R.STYLE_WIZARD_CHECKED_AT,
                                alignment=ui.Alignment.LEFT_CENTER)
                            ui.Spacer(width=6)
                            R.secondary_button_wiz(
                                "Refresh",
                                lambda: self._run_resource_check(),
                                height=18, width=60,
                                tooltip="Re-run system resource check")
                            ui.Spacer(width=8)

                    with ui.ZStack(height=_REQ_TABLE_H):
                        ui.Rectangle(style=R.STYLE_CARD_WIZARD)
                        with ui.VStack(spacing=0):
                            ui.Spacer(height=8)
                            with ui.HStack(spacing=0):
                                ui.Spacer(width=8)
                                with ui.VStack(spacing=2):
                                    with ui.HStack(height=16, spacing=0):
                                        ui.Label("RESOURCE", width=R.WIDTH_WIZARD_RESOURCE_COL,
                                                 style=R.STYLE_WIZARD_CHECKED_AT)
                                        ui.Spacer(width=8)
                                        ui.Label("DETECTED", style=R.STYLE_WIZARD_CHECKED_AT)
                                        ui.Spacer()
                                        ui.Label("STATUS", width=90,
                                                 alignment=ui.Alignment.LEFT_CENTER,
                                                 style=R.STYLE_WIZARD_CHECKED_AT)
                                    ui.Spacer(height=4)
                                    with ui.HStack(height=_REQ_ROW_H, spacing=0):
                                        ui.Label("GPU", width=R.WIDTH_WIZARD_RESOURCE_COL,
                                                 style=R.STYLE_WIZARD_REQ_LABEL)
                                        ui.Spacer(width=8)
                                        self._sys_gpu_label  = ui.Label("checking...", style=R.STYLE_WIZARD_BODY_LABEL)
                                        self._sys_gpu_util_bg, self._sys_gpu_util = self._build_status_pill()
                                    ui.Spacer(height=_REQ_ROW_GAP)
                                    ui.Line(height=1, style={"color": R.COLOR_BORDER, "border_width": 1})
                                    with ui.HStack(height=_REQ_ROW_H, spacing=0):
                                        ui.Label("VRAM", width=R.WIDTH_WIZARD_RESOURCE_COL,
                                                 style=R.STYLE_WIZARD_REQ_LABEL)
                                        ui.Spacer(width=8)
                                        self._sys_vram_label = ui.Label("-", style=R.STYLE_WIZARD_BODY_LABEL)
                                        self._sys_vram_ok_bg, self._sys_vram_ok = self._build_status_pill()
                                    ui.Spacer(height=_REQ_ROW_GAP)
                                    ui.Line(height=1, style={"color": R.COLOR_BORDER, "border_width": 1})
                                    with ui.HStack(height=_REQ_ROW_H, spacing=0):
                                        ui.Label("Disk", width=R.WIDTH_WIZARD_RESOURCE_COL,
                                                 style=R.STYLE_WIZARD_REQ_LABEL)
                                        ui.Spacer(width=8)
                                        self._sys_disk_label = ui.Label("-", style=R.STYLE_WIZARD_BODY_LABEL)
                                        self._sys_disk_ok_bg, self._sys_disk_ok = self._build_status_pill()
                                    ui.Spacer(height=_REQ_ROW_GAP)
                                    ui.Line(height=1, style={"color": R.COLOR_BORDER, "border_width": 1})
                                    with ui.HStack(height=_REQ_ROW_H, spacing=0):
                                        ui.Label("RAM", width=R.WIDTH_WIZARD_RESOURCE_COL,
                                                 style=R.STYLE_WIZARD_REQ_LABEL)
                                        ui.Spacer(width=8)
                                        self._sys_ram_label  = ui.Label("-", style=R.STYLE_WIZARD_BODY_LABEL)
                                        self._sys_ram_ok_bg, self._sys_ram_ok = self._build_status_pill()
                                    ui.Spacer(height=4)
                                ui.Spacer(width=8)
                            ui.Spacer(height=8)

                    # Accent-left-bar tinted strip (not a bare label) — matches
                    # the "Low VRAM." warning styling in the reference.
                    with ui.ZStack(height=_SYSREQ_WARN_H, visible=False) as self._cpu_recommend_frame:
                        ui.Rectangle(style={"background_color": R.COLOR_STATUS_WARN_TINT_BG})
                        with ui.HStack(spacing=0):
                            ui.Rectangle(width=R.WIDTH_ACCENT_BAR_WIZARD,
                                         style={"background_color": R.COLOR_STATUS_WARN})
                            ui.Spacer(width=8)
                            self._cpu_recommend_label = ui.Label(
                                "", word_wrap=True, alignment=ui.Alignment.LEFT_CENTER,
                                style=R.STYLE_WIZARD_WARN_LABEL)
                            ui.Spacer(width=8)
                    ui.Spacer(height=6)

            # ---- Compute device + Start Server ---- label sits LEFT of the
            # field on the same row, matching the MODEL row above.
            with ui.HStack(height=R.HEIGHT_INPUT_ROW_COMPACT, spacing=8):
                ui.Label("COMPUTE DEVICE", width=_LABEL_COL_DEVICE,
                         alignment=ui.Alignment.LEFT_CENTER,
                         style={"color": R.COLOR_TEXT_SECONDARY, "font_size": R.FONT_DESCRIPTION})
                _saved_device = self._mgr.config.get("device", "cuda")
                _default_device_idx = 1 if _saved_device == "cuda" else 0
                self._spawn_device_combo = ui.ComboBox(
                    _default_device_idx, "CPU", "CUDA (GPU)",
                    height=R.HEIGHT_INPUT_ROW_COMPACT,
                    style=R.STYLE_COMBO_STANDARD)
                R.apply_tooltip(self._spawn_device_combo, "Choose GPU/CPU device for model inference")
            self._device_hint_label = R.label(
                "CPU mode: slower inference but no GPU required",
                dim=True, size=R.FONT_WIZARD_STEP, height=16)

            def _on_device_changed(m):
                if not getattr(self, "_device_combo_setting", False):
                    self._device_user_touched = True
                try:
                    if m.get_value_as_int() == 1:
                        self._device_hint_label.text = "CUDA (GPU) - faster inference, uses VRAM."
                    else:
                        self._device_hint_label.text = "CPU mode: slower inference but no GPU required"
                except Exception:  # noqa: BLE001
                    pass
            self._spawn_device_combo.model.get_item_value_model() \
                .add_value_changed_fn(_on_device_changed)
            try:
                if self._spawn_device_combo.model.get_item_value_model().as_int == 1:
                    self._device_hint_label.text = "CUDA (GPU) - faster inference, uses VRAM."
            except Exception:  # noqa: BLE001
                pass
            self._cuda_warn_label = ui.Label(
                "No usable CUDA GPU was detected, so the server will run on "
                "CPU (slower responses).",
                height=32, word_wrap=True,
                style=R.STYLE_WIZARD_WARN_LABEL, visible=False)

            # ---- Tray-preflight warn strip (issue #14) ----
            # Shared builder: the identical strip also sits on the Path B
            # connect page (the tray agent always spawns on THIS machine,
            # whichever path runs the server).
            self._build_tray_pf_strip("path_a")
            # No idle-state text here (matches reference: nothing shown above
            # Start Server until an install/spawn actually reports progress).
            self._spawn_status = ui.Label(
                "",
                height=20, word_wrap=True,
                style=R.STYLE_WIZARD_STATUS_TEXT)
            self._spawn_progress, self._set_spawn_prog, self._hide_spawn_prog = self._make_progress_bar()
            with ui.Frame(height=16, visible=False) as self._pa_log_frame:
                with ui.HStack(spacing=4):
                    self._install_key_label = ui.Label("", style=R.STYLE_WIZARD_STATUS_TEXT)
                    ui.Spacer()
                    self._install_open_log_btn = R.secondary_button_wiz(
                        "Open Log",
                        lambda: self._open_log_file(self._install_log_path),
                        height=16, width=48,
                        tooltip="Open the install log file")
                    self._install_open_log_btn.enabled = False
            _venv_ready = (_LABR7_VENV / "bin" / "python").exists()
            self._spawn_btn = R.primary_button(
                "Start Server" if _venv_ready else "Install & Start Server",
                self._do_spawn if _venv_ready else self._install_and_start,
                height=R.HEIGHT_BTN_PRIMARY_WIZARD,
                tooltip="Start the VLM inference server")
            self._spawn_btn.enabled = True
            # Helper caption below the CTA (full_png/02-setup-local.png) — hidden
            # once _update_device_combo_state()/_refresh_pa_setup_state() puts a
            # real status message ("Server is already running...") in that slot,
            # so the two never show at once.
            self._spawn_helper_caption = ui.Label(
                "First run: this installs the environment, then starts the "
                "server. Takes a few minutes.",
                height=28, word_wrap=True, alignment=ui.Alignment.CENTER,
                style=R.STYLE_WIZARD_STATUS_TEXT)
            # Alias so _start_install / _install_worker can find their widgets.
            self._install_status = self._spawn_status
            self._set_pa_prog    = self._set_spawn_prog

            # ---- Bottom nav-footer band (ref full_png/02-setup-local.png) ----
            # A single trailing Spacer (P2-compliant: at most one) hugs this
            # band to the true bottom of the page, matching the Method already
            # established in choose_server.py's landing-page footer.
            ui.Spacer()
            ui.Rectangle(height=1, style=R.STYLE_WIZARD_FOOTER_DIVIDER)
            with ui.ZStack(height=R.HEIGHT_WIZARD_FOOTER_BAND):
                ui.Rectangle(style=R.STYLE_WIZARD_FOOTER_BAND)
                # NOTE: no style={"margin": N} here — see
                # contact_us_win.py's build_contact_ui() comment: Kit cascades
                # a margin style down to every descendant widget rather than
                # applying it once to this container, so with 5 children
                # (3 buttons + Spacer + Next) each one picked up its own extra
                # 12px on every side. That's what stranded the Next button
                # ~13px short of the true right edge (its own cascaded right
                # margin stacked on top of the page's natural card inset) —
                # live-measured via port-8226 widget geometry against
                # full_png/02-setup-local.png. The ZStack already centers this
                # fixed-height HStack vertically for free, and the unstyled
                # HStack still fills the full band width (matching
                # self._sysreq_card's own natural ~8px/~20px left/right inset)
                # so no replacement margin is needed.
                with ui.HStack(height=R.HEIGHT_BTN_PRIMARY_WIZARD, spacing=6):
                    R.secondary_button_wiz("< Back", lambda: self._goto(_PAGE_LANDING),
                                       height=R.HEIGHT_BTN_PRIMARY_WIZARD,
                                       tooltip="Return to path selection")
                    self._install_env_btn = R.secondary_button_wiz(
                        "Reinstall Env",
                        self._start_install,
                        height=R.HEIGHT_BTN_PRIMARY_WIZARD,
                        tooltip="Reinstall the Python environment and inference server dependencies - use this if the install did not complete correctly")
                    R.danger_button_wiz_outline(
                        "Uninstall", self._confirm_uninstall,
                        height=R.HEIGHT_BTN_PRIMARY_WIZARD,
                        tooltip="Remove inference server installation and model files")
                    ui.Spacer()
                    self._pa_next_btn = R.danger_button(
                        "Next >", lambda: self._goto(_PAGE_PATH_A_DOWNLOAD),
                        height=R.HEIGHT_BTN_PRIMARY_WIZARD,
                        tooltip="Continue to model download")
                    self._pa_next_btn.enabled = (
                        self._resource_check_ran and bool(self._selected_model_repo))
            self._start_install_btn = self._install_env_btn
            self._sync_reinstall_btn()

        asyncio.ensure_future(self._async_resource_check())
        asyncio.ensure_future(self._async_tray_preflight())
        self._update_device_combo_state()

    @staticmethod
    def _build_status_pill(width: int = 84, height: int = 14):
        """Filled status-pill badge (rect + centered label) for a resource row.

        Returns (rect, label) so callers can restyle the fill color and swap
        the text as `_run_resource_check()` re-evaluates each resource.
        """
        with ui.ZStack(width=width, height=height):
            rect = ui.Rectangle(style={
                "background_color": R.COLOR_STATUS_OK_PILL_BG,
                "border_radius": R.RADIUS_STATUS_PILL,
            })
            label = ui.Label(
                "", style={"color": R.COLOR_STATUS_OK_PILL_FG, "font_size": R.FONT_STATUS_PILL},
                alignment=ui.Alignment.CENTER)
        return rect, label

    async def _async_resource_check(self):
        await omni.kit.app.get_app().next_update_async()
        self._run_resource_check()

    async def _async_tray_preflight(self):
        await omni.kit.app.get_app().next_update_async()
        self._run_tray_preflight()

    # ------------------------------------------------------------------
    # Tray-preflight strip (issue #14) — predicted tray tier, non-blocking
    # ------------------------------------------------------------------
    def _build_tray_pf_strip(self, page_key: str):
        """Build one tray-preflight warn strip and register it under page_key.

        Shared by the Path A setup page and the Path B connect page: the
        tray agent always spawns on THIS machine regardless of where the
        inference server runs, so the same preflight verdict applies to
        both. Pages are built once and visibility-toggled, so each page's
        widget group is stored in self._tray_pf_strips[page_key] and only
        ever mutated afterward (never rebuilt).

        Same accent-left-bar tinted-strip pattern as
        self._cpu_recommend_frame. Non-blocking: it never gates
        Next/Start/Test Connection — the tray is observability, not a hard
        dependency. Explicit height (greedy-sink guard, see
        _TRAY_PF_STRIP_H) and no style={"margin"} on the inner VStack (Kit
        cascades it to every descendant) — Spacers provide the inset instead.
        """
        if not hasattr(self, "_tray_pf_strips"):
            self._tray_pf_strips = {}
        if not hasattr(self, "_tray_pf"):
            self._tray_pf = None
        with ui.ZStack(height=_TRAY_PF_STRIP_H, visible=False) as frame:
            ui.Rectangle(style={"background_color": R.COLOR_STATUS_WARN_TINT_BG})
            with ui.HStack(spacing=0):
                ui.Rectangle(width=R.WIDTH_ACCENT_BAR_WIZARD,
                             style={"background_color": R.COLOR_STATUS_WARN})
                ui.Spacer(width=8)
                with ui.VStack(spacing=4):
                    ui.Spacer(height=6)
                    label = ui.Label(
                        "", height=28, word_wrap=True,
                        alignment=ui.Alignment.LEFT_CENTER,
                        style=R.STYLE_WIZARD_WARN_LABEL)
                    code_frame = ui.ZStack(height=20, visible=False)
                    with code_frame:
                        ui.Rectangle(style=R.STYLE_CODE_BLOCK_BG)
                        code_label = ui.Label(
                            "", style=R.STYLE_CODE_BLOCK_TEXT)
                    with ui.HStack(height=18, spacing=6):
                        copy_btn = R.secondary_button_wiz(
                            "Copy", self._tray_pf_copy, height=16, width=48,
                            tooltip="Copy the fix command to clipboard")
                        R.secondary_button_wiz(
                            "Re-check", self._tray_pf_recheck, height=18, width=70,
                            tooltip="Re-run the tray window availability check")
                        ui.Spacer()
                    ui.Spacer(height=6)
                ui.Spacer(width=8)
        self._tray_pf_strips[page_key] = {
            "frame": frame, "label": label,
            "code_frame": code_frame, "code_label": code_label,
            "copy_btn": copy_btn,
        }

    def _run_tray_preflight(self, from_recheck: bool = False):
        """Probe whether the tray window can be shown; update the warn strips.

        Runs check_tray_ui() on a daemon thread (it shells out to the tray
        interpreter twice with a 10 s timeout each — too slow for the UI
        thread), then mutates the already-built strip widgets. Never gates
        Next/Start: a headless tray is a visibility loss, not a setup failure.
        """
        def _worker():
            try:
                pf = check_tray_ui(self._mgr.config.get("python_exe"))
            except Exception:  # noqa: BLE001
                pf = None
            self._tray_pf = pf
            self._render_tray_preflight(from_recheck)
        threading.Thread(target=_worker, daemon=True).start()

    def _render_tray_preflight(self, from_recheck: bool = False):
        """Apply self._tray_pf to every registered strip (both pages show
        the same verdict — the check is machine-local, not path-specific)."""
        pf = getattr(self, "_tray_pf", None)
        for group in getattr(self, "_tray_pf_strips", {}).values():
            self._render_tray_pf_group(group, pf, from_recheck)

    @staticmethod
    def _render_tray_pf_group(group: dict, pf: "dict | None",
                              from_recheck: bool = False):
        """Render one preflight verdict onto one strip's widget group
        (pages are built once and visibility-toggled — mutate widgets,
        never rebuild)."""
        try:
            if pf is None:
                group["frame"].visible = False
                return
            if pf.get("ok"):
                if from_recheck:
                    # Brief confirmation so Re-check visibly did something.
                    group["label"].text = (
                        "Tray window check passed - the tray will be shown "
                        "when the server starts.")
                    group["label"].style = R.STYLE_WIZARD_OK_TEXT
                    group["code_frame"].visible = False
                    group["copy_btn"].visible = False
                    group["frame"].visible = True
                else:
                    group["frame"].visible = False
                return
            fix_cmd = pf.get("fix_cmd")
            group["label"].text = (
                "The server's tray window will not be shown on this machine. "
                + (pf.get("reason") or ""))
            group["label"].style = R.STYLE_WIZARD_WARN_LABEL
            if fix_cmd:
                group["code_label"].text = fix_cmd
                group["code_frame"].visible = True
                group["copy_btn"].visible = True
            else:
                group["code_frame"].visible = False
                group["copy_btn"].visible = False
            group["frame"].visible = True
        except Exception:  # noqa: BLE001
            pass

    def _tray_pf_copy(self):
        try:
            import omni.kit.clipboard
            fix_cmd = (getattr(self, "_tray_pf", None) or {}).get("fix_cmd")
            if fix_cmd:
                omni.kit.clipboard.copy(fix_cmd)
        except Exception:  # noqa: BLE001
            pass

    def _tray_pf_recheck(self):
        self._run_tray_preflight(from_recheck=True)

    def _run_resource_check(self):
        ok = True
        req = _MODEL_REQUIREMENTS.get(self._selected_model_repo, {})
        req_vram = req.get("vram_gb", 0)
        req_disk = req.get("disk_gb", 10)

        gpu_text = "-";  gpu_util_text = "";  vram_text = "-"
        vram_ok_text = "";    vram_ok_bg = R.COLOR_STATUS_OK_PILL_BG;  vram_ok_fg = R.COLOR_STATUS_OK_PILL_FG
        disk_text = "-"; disk_ok_text = ""; disk_ok_bg = R.COLOR_STATUS_OK_PILL_BG; disk_ok_fg = R.COLOR_STATUS_OK_PILL_FG
        ram_text = "-";  ram_ok_text = "";  ram_ok_bg = R.COLOR_STATUS_OK_PILL_BG; ram_ok_fg = R.COLOR_STATUS_OK_PILL_FG

        cuda_detected = False;  vram_enough = True;  vram_free_gb = 0.0;  gpu_util_pct: int = 0
        try:
            import pynvml
            pynvml.nvmlInit()
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            gpu_name = pynvml.nvmlDeviceGetName(h)
            try:
                mem = pynvml.nvmlDeviceGetMemoryInfo(h)
                vram_free_gb   = mem.free  / 1024**3
                vram_total_gb  = mem.total / 1024**3
                if req_vram > 0:
                    vram_text = f"{vram_free_gb:.1f} / {vram_total_gb:.1f} GB - needs ~{req_vram} GB"
                    if vram_free_gb >= req_vram:
                        vram_ok_text = "OK"
                        vram_ok_bg = R.COLOR_STATUS_OK_PILL_BG;  vram_ok_fg = R.COLOR_STATUS_OK_PILL_FG
                    else:
                        vram_ok_text = "Tight"
                        vram_ok_bg = R.COLOR_STATUS_WARN_PILL_BG;  vram_ok_fg = R.COLOR_STATUS_WARN_PILL_FG
                        vram_enough = False;  ok = False
                else:
                    vram_text = f"{vram_free_gb:.1f} / {vram_total_gb:.1f} GB"
            except Exception:  # noqa: BLE001 — GB10/Blackwell
                vram_text = "N/A (unified memory)"
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(h)
                gpu_util_pct = util.gpu
                gpu_text = gpu_name;  gpu_util_text = f"{gpu_util_pct}% util"
            except Exception:  # noqa: BLE001
                gpu_text = gpu_name
            cuda_detected = True
        except ImportError:
            gpu_text = "pynvml not installed"
        except Exception as e:  # noqa: BLE001
            gpu_text = f"check failed: {e}";  ok = False

        # Sync the live pynvml probe (reliable, ran on page open) into the flag that
        # actually gates the Compute Device combo — previously only _install_worker()
        # set self._cuda_available, so a GPU-less machine kept showing the "CUDA (GPU)"
        # default from _CONFIG_DEFAULTS until the user clicked the install button (issue #37).
        self._cuda_available = cuda_detected
        try:
            self._update_device_combo_state()
        except Exception:  # noqa: BLE001
            pass

        try:
            import psutil
            ram_gb       = psutil.virtual_memory().total / 1024**3
            disk_free_gb = psutil.disk_usage(str(Path.home())).free / 1024**3
            disk_ok = disk_free_gb >= req_disk;  ram_ok = ram_gb >= 16
            disk_text = f"{disk_free_gb:.1f} GB free - needs ~{req_disk} GB"
            disk_ok_text = "OK" if disk_ok else f"Need {req_disk} GB"
            disk_ok_bg = R.COLOR_STATUS_OK_PILL_BG if disk_ok else R.COLOR_STATUS_WARN_PILL_BG
            disk_ok_fg = R.COLOR_STATUS_OK_PILL_FG if disk_ok else R.COLOR_STATUS_WARN_PILL_FG
            ram_text    = f"{ram_gb:.1f} GB - needs ~16 GB"
            ram_ok_text = "OK" if ram_ok else "< 16 GB"
            ram_ok_bg = R.COLOR_STATUS_OK_PILL_BG if ram_ok else R.COLOR_STATUS_WARN_PILL_BG
            ram_ok_fg = R.COLOR_STATUS_OK_PILL_FG if ram_ok else R.COLOR_STATUS_WARN_PILL_FG
            if not disk_ok:
                ok = False
        except ImportError:
            ram_text = "psutil not installed"
        except Exception as e:  # noqa: BLE001
            ram_text = f"RAM/DISK check failed: {e}"

        import datetime
        now = datetime.datetime.now().strftime("%H:%M:%S")
        if gpu_util_pct >= 80:
            gpu_util_bg = R.COLOR_STATUS_WARN_PILL_BG;  gpu_util_fg = R.COLOR_STATUS_DANGER_PILL_FG
        elif gpu_util_pct >= 50:
            gpu_util_bg = R.COLOR_STATUS_WARN_PILL_BG;  gpu_util_fg = R.COLOR_STATUS_WARN_PILL_FG
        else:
            gpu_util_bg = R.COLOR_STATUS_OK_PILL_BG;    gpu_util_fg = R.COLOR_STATUS_OK_PILL_FG

        def _set_pill(rect, label, text, bg, fg):
            rect.style  = {"background_color": bg, "border_radius": R.RADIUS_STATUS_PILL}
            label.text  = text
            label.style = {"color": fg, "font_size": R.FONT_STATUS_PILL}

        try:
            self._sys_gpu_label.text  = gpu_text
            _set_pill(self._sys_gpu_util_bg,  self._sys_gpu_util,  gpu_util_text, gpu_util_bg, gpu_util_fg)
            self._sys_vram_label.text = vram_text
            _set_pill(self._sys_vram_ok_bg,   self._sys_vram_ok,   vram_ok_text,  vram_ok_bg,  vram_ok_fg)
            self._sys_disk_label.text = disk_text
            _set_pill(self._sys_disk_ok_bg,   self._sys_disk_ok,   disk_ok_text,  disk_ok_bg,  disk_ok_fg)
            self._sys_ram_label.text  = ram_text
            _set_pill(self._sys_ram_ok_bg,    self._sys_ram_ok,    ram_ok_text,   ram_ok_bg,   ram_ok_fg)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._resource_check_time_label.text = f"checked {now}"
        except Exception:  # noqa: BLE001
            pass

        cpu_msg = ""
        if not cuda_detected:
            cpu_msg = "No CUDA GPU - CPU mode recommended (slower inference)."
        elif req_vram > 0 and not vram_enough:
            cpu_msg = (
                f"Low VRAM. {vram_free_gb:.1f} of ~{req_vram} GB available - CPU mode is "
                "recommended for this model to avoid out-of-memory errors.")
        elif cuda_detected and gpu_util_pct >= 80:
            cpu_msg = f"GPU at {gpu_util_pct}% util - may be slow. Try CPU mode or Remote Install."
        try:
            self._cpu_recommend_label.text    = cpu_msg
            self._cpu_recommend_frame.visible = bool(cpu_msg)
        except Exception:  # noqa: BLE001
            pass

        # Pre-select the recommended device (CPU) when the GPU is
        # unsuitable, unless the user already picked a device manually.
        _recommend_cpu = (not cuda_detected) or (req_vram > 0 and not vram_enough)
        if _recommend_cpu and not getattr(self, "_device_user_touched", False):
            try:
                self._device_combo_setting = True
                self._spawn_device_combo.model.get_item_value_model().set_value(0)
            except Exception:  # noqa: BLE001
                pass
            finally:
                self._device_combo_setting = False
            try:
                self._device_hint_label.text = (
                    "CPU mode: slower inference but no GPU required (Recommended)")
            except Exception:  # noqa: BLE001
                pass

        self._resource_info = {"ok": ok}
        self._resource_check_ran = True
        try:
            if self._pa_next_btn is not None and self._selected_model_repo:
                self._pa_next_btn.enabled = True
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # PATH A — Install worker
    # ------------------------------------------------------------------
    def _sync_reinstall_btn(self, force_disable: bool = False):
        """Single owner of the 'Reinstall Env' fallback button's enabled state.

        The label is an immutable literal set at construction (issue #58) - the
        primary action is 'Install & Start Server'; this button only exists so a
        user whose install did not complete correctly can redo it. It is enabled
        whenever an install attempt has left a venv directory on disk (complete
        OR broken - the broken case is exactly what the fallback is for), and
        force-disabled while an install or spawn is in flight. Every enable/
        disable write for this widget must go through here so the predicate
        cannot drift across call sites again. Safe to call from worker threads
        and before/after the widget exists.
        """
        try:
            self._install_env_btn.enabled = (
                False if force_disable else _LABR7_VENV.exists())
        except Exception:  # noqa: BLE001
            pass

    def _install_and_start(self):
        """First-run action: install the env, then auto-start the server."""
        self._install_then_start = True
        self._start_install()

    def _start_install(self):
        model_repo = self._selected_model_repo
        if not model_repo:
            self._install_status.text = "Please select a model"
            self._install_then_start = False
            return
        self._install_active = True
        self._spawn_cancelled = False
        self._install_proc = None
        try:
            # The SAME primary button becomes Cancel while the op runs.
            flip_button(self._spawn_btn, "Cancel", self._cancel_spawn_or_install)
            self._spawn_btn.enabled = True
            self._set_pulse_target(None)   # stop-only: thread-safe
        except Exception:  # noqa: BLE001
            pass
        self._sync_reinstall_btn(force_disable=True)
        if not self._resource_info.get("ok", True):
            try:
                self._install_status.text = (
                    "System resources are below the recommended minimum - see the "
                    "VRAM/Disk rows above. Installing anyway; if the model later "
                    "fails to start, set Compute Device to CPU and retry.")
            except Exception:  # noqa: BLE001
                pass
        self._mgr.save_config({"model_repo": model_repo})
        ts = time.strftime("%Y%m%dT%H%M%S")
        self._install_log_path = _LABR7_VENV.parent / "logs" / f"install_{ts}.log"
        self._install_log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._pa_log_frame.visible = True
        except Exception:  # noqa: BLE001
            pass
        if hasattr(self, "_install_open_log_btn") and self._install_open_log_btn is not None:
            try:
                self._install_open_log_btn.enabled = True
            except Exception:  # noqa: BLE001
                pass
        self._set_pa_prog(0.0)
        self._install_status.text = "Starting environment install..."
        self._install_key_label.text = f"Log: {self._install_log_path}"
        # Read the combo on the main thread (button click handler) — _install_worker
        # runs on a background thread and must not touch omni.ui widgets directly.
        try:
            want_cuda = self._spawn_device_combo.model.get_item_value_model().as_int == 1
        except Exception:  # noqa: BLE001
            want_cuda = True
        self._worker = threading.Thread(
            target=self._install_worker, args=(model_repo, want_cuda), daemon=True)
        self._worker.start()

    def _install_worker(self, model_repo: str, want_cuda: bool = True):
        # Snapshot BEFORE anything is created, so a cancelled run can tell a
        # from-scratch install (safe to rmtree) apart from a Reinstall Env on
        # top of an already-working environment (leave files as-is on cancel).
        venv_pre_existing = (_LABR7_VENV / "bin" / "python").exists()
        self._venv_pre_existing_this_run = venv_pre_existing

        def log(msg: str):
            print(f"[radeis-install] {msg}")
            try:
                with open(self._install_log_path, "a") as _lf:
                    _lf.write(msg + "\n")
            except Exception:  # noqa: BLE001
                pass
            try:
                self._install_status.text = msg[:90]
            except Exception:  # noqa: BLE001
                pass

        def set_prog(v: float):
            self._set_pa_prog(v)

        def _re_enable_btn():
            self._install_active     = False
            self._install_then_start = False
            self._sync_reinstall_btn()
            if self._spawn_cancelled:
                # _cancel_spawn_or_install left the status text at "Cancelling..."
                # while it waited for this worker-thread cleanup — reset it now
                # that the cancel has actually finished, otherwise it's stuck
                # there until the next install/spawn attempt overwrites it.
                try:
                    self._install_status.text = "Cancelled."
                except Exception:  # noqa: BLE001
                    pass
            try:
                _ready = (_LABR7_VENV / "bin" / "python").exists()
                flip_button(
                    self._spawn_btn,
                    "Start Server" if _ready else "Install & Start Server",
                    self._do_spawn if _ready else self._install_and_start)
                self._spawn_btn.enabled = True
            except Exception:  # noqa: BLE001
                pass

        def _cancel_cleanup():
            """Only called when self._spawn_cancelled is True — a genuine
            pip/venv failure (not a user cancel) must NOT trigger this."""
            if not venv_pre_existing:
                import shutil
                shutil.rmtree(_LABR7_VENV, ignore_errors=True)
                log("Install cancelled - removed incomplete environment.")
            else:
                log("Reinstall cancelled - existing environment left as-is "
                    "(it may now be partially upgraded and inconsistent). "
                    "If Start Server fails, open Advanced, press Uninstall, "
                    "then Install & Start Server to start clean.")

        def _run_pip(cmd: list, label: str, timeout: int = 600) -> bool:
            proc = None
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1)
                self._install_proc = proc
                for line in proc.stdout:
                    if self._spawn_cancelled:
                        try:
                            proc.kill()
                            proc.wait()
                        except Exception:  # noqa: BLE001
                            pass
                        return False
                    stripped = line.rstrip()
                    if stripped:
                        log(stripped)
                proc.wait(timeout=timeout)
                if proc.returncode != 0:
                    if not self._spawn_cancelled:
                        log(f"{label} failed (exit code {proc.returncode}).")
                        log("Tip: open Advanced, press Uninstall, then press "
                            "Install & Start Server to retry from scratch.")
                    return False
            except subprocess.TimeoutExpired:
                proc.kill()
                log(f"{label} timed out after {timeout // 60} min.")
                return False
            except Exception as e:  # noqa: BLE001
                log(f"{label} failed: {e}")
                return False
            finally:
                self._install_proc = None
            return True

        log("Detecting system Python (3.10-3.12)...")
        python_exe = _find_system_python()
        if not python_exe:
            log("Python 3.10-3.12 not found. Please install it and try again.")
            _re_enable_btn()
            return
        log(f"Found: {python_exe}")
        set_prog(0.1)

        _LABR7_VENV.parent.mkdir(parents=True, exist_ok=True)
        venv_python_path = _LABR7_VENV / "bin" / "python"
        if venv_python_path.exists():
            log(f"Existing virtual environment detected at {_LABR7_VENV} - skipping creation.")
        else:
            log(f"Creating virtual environment: {_LABR7_VENV}")
            if not _run_pip([python_exe, "-m", "venv", str(_LABR7_VENV)],
                             "Virtual environment creation"):
                if self._spawn_cancelled:
                    _cancel_cleanup()
                _re_enable_btn()
                return
            log("Virtual environment created.")
        set_prog(0.2)

        if want_cuda:
            cuda_ver    = _detect_cuda_version()
            torch_index = _cuda_to_torch_index(cuda_ver)
            log(f"CUDA: {cuda_ver or 'not detected'}  torch wheel: {torch_index or 'cpu (no CUDA)'}")
        else:
            # User picked CPU in the Compute Device combo — install the CPU wheel
            # regardless of any CUDA toolkit present on the system (issue #37).
            torch_index = None
            log("Compute Device = CPU - installing CPU-only torch wheel")
        set_prog(0.3)

        venv_pip    = str(_LABR7_VENV / "bin" / "pip")
        sidecar_req = _find_sidecar_requirements()
        log(f"Requirements file: {sidecar_req}")

        if torch_index:
            log(f"Installing torch + torchvision from PyTorch CDN ({torch_index})...")
            torch_cmd = [venv_pip, "install", "torch", "torchvision",
                         "--index-url", f"https://download.pytorch.org/whl/{torch_index}"]
            if not _run_pip(torch_cmd, "torch install"):
                if self._spawn_cancelled:
                    _cancel_cleanup()
                _re_enable_btn()
                return
            log("torch + torchvision installed")
            set_prog(0.4)

        log("Installing remaining dependencies (may take several minutes)...")
        rest_cmd = [venv_pip, "install", "-r", sidecar_req]
        if torch_index:
            rest_cmd += ["--extra-index-url", f"https://download.pytorch.org/whl/{torch_index}"]
        if not _run_pip(rest_cmd, "pip install"):
            if self._spawn_cancelled:
                _cancel_cleanup()
            _re_enable_btn()
            return
        log("All dependencies installed")
        set_prog(0.5)

        if self._spawn_cancelled:
            _cancel_cleanup()
            _re_enable_btn()
            return

        venv_python = str(_LABR7_VENV / "bin" / "python")
        try:
            r = subprocess.run(
                [venv_python, "-c", "import torch; print(torch.cuda.is_available())"],
                capture_output=True, text=True, timeout=30)
            self._cuda_available = r.stdout.strip() == "True"
            if self._cuda_available:
                log("torch.cuda.is_available() = True  OK")
            else:
                log("torch.cuda.is_available() = False - defaulting to CPU")
        except Exception:  # noqa: BLE001
            self._cuda_available = False
        set_prog(0.6)

        if self._spawn_cancelled:
            _cancel_cleanup()
            _re_enable_btn()
            return

        self._mgr.save_config({"python_exe": venv_python, "venv_managed": True, "mode": "local"})
        log("Environment ready.")
        set_prog(0.7)

        if self._spawn_cancelled:
            _cancel_cleanup()
            _re_enable_btn()
            return

        try:
            key_lines  = self._install_key_label.text.splitlines()
            first_line = key_lines[0] if key_lines else f"Log: {self._install_log_path}"
            self._install_key_label.text = "\n".join([
                first_line,
                "Environment: ready",
                f"torch.cuda.is_available() = {self._cuda_available}",
            ])
        except Exception:  # noqa: BLE001
            pass
        try:
            self._update_device_combo_state()
            self._inline_spawn_frame.visible = True
        except Exception:  # noqa: BLE001
            pass
        set_prog(1.0)
        if getattr(self, "_install_then_start", False):
            # Combined "Install & Start Server" — chain straight into spawn.
            # Clear the flag here (not via _re_enable_btn, which we deliberately
            # skip on this path) so a later plain-spawn Cancel doesn't see a
            # stale _install_active=True and wait forever for install cleanup.
            self._install_then_start = False
            self._install_active     = False
            self._do_spawn(device="cuda" if want_cuda else "cpu", _chained=True)
        else:
            _re_enable_btn()

    def _confirm_uninstall(self):
        venv_path  = str(_LABR7_VENV).replace(str(Path.home()), "~")
        model_repo = self._mgr.config.get("model_repo", "")
        hf_cache   = ("~/.cache/huggingface/hub/models--" + model_repo.replace("/", "--")
                      if model_repo else "~/.cache/huggingface/hub/<model>")
        if getattr(self, "_dlg_win", None) is not None:
            try:
                self._dlg_win.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._dlg_win = None
        self._dlg_win = R.warning_window(
            "Confirm Uninstall",
            message="Permanently removes:",
            items=[
                f"Python venv ({venv_path})",
                f"Model weights ({hf_cache})",
                "Runtime files, registry, processes",
            ],
            footer="Cannot be undone.",
            confirm_label="Confirm Uninstall",
            on_confirm=self._clean_reinstall,
            on_cancel=None,
            danger=True,
            width=380,
            parent_win=self._win,
        )

    def _clean_reinstall(self):
        self._mgr.clean_reinstall()
        try:
            self._inline_spawn_frame.visible = False
        except Exception:  # noqa: BLE001
            pass
        self._goto(_PAGE_LANDING)
        if self._on_forget is not None:
            self._on_forget()

    # ------------------------------------------------------------------
    # PATH A — Spawn helpers
    # ------------------------------------------------------------------
    def _update_device_combo_state(self):
        try:
            if not self._cuda_available:
                combo_model = self._spawn_device_combo.model.get_item_value_model()
                self._device_combo_setting = True
                try:
                    combo_model.set_value(0)
                finally:
                    self._device_combo_setting = False
                def _guard_cuda(m):
                    if m.get_value_as_int() == 1:
                        self._device_combo_setting = True
                        try:
                            m.set_value(0)
                        finally:
                            self._device_combo_setting = False
                        try:
                            self._cuda_warn_label.visible = True
                        except Exception:  # noqa: BLE001
                            pass
                combo_model.add_value_changed_fn(_guard_cuda)
                self._cuda_warn_label.visible = True
        except Exception:  # noqa: BLE001
            pass
        try:
            level = self._mgr.probe_readiness()
            if level >= ReadinessLevel.LOADING:
                self._spawn_btn.enabled  = False
                self._spawn_status.text  = "Server is already running - press Next to continue."
                self._spawn_helper_caption.visible = False
        except Exception:  # noqa: BLE001
            pass

    def _refresh_pa_setup_state(self):
        """Page-enter sync for the Install/Setup page (issue #38).

        Pages are built once in _build() and only visibility-toggled by
        _goto() — this page's Start/Install button labels and the "already
        running" gate are otherwise only ever computed at construction time.
        Without this, returning here after an Uninstall (venv removed) or
        after starting/stopping the server elsewhere shows stale button
        labels/handlers and a stale running-status. Called from _goto();
        no-ops while an install is actively in flight so it can't race the
        worker thread's own end-of-install button flip, and no-ops while a
        spawn is in flight (_spawn_waiting) so navigating Back and re-entering
        mid-spawn can't flip the "Cancel" button back to enabled/Start Server
        and let the user fire a second concurrent _do_spawn/_wait.
        """
        if getattr(self, "_install_active", False) or getattr(self, "_spawn_waiting", False):
            return
        try:
            _ready = (_LABR7_VENV / "bin" / "python").exists()
            flip_button(
                self._spawn_btn,
                "Start Server" if _ready else "Install & Start Server",
                self._do_spawn if _ready else self._install_and_start)
            self._spawn_btn.enabled = True
            self._spawn_status.text = ""
            self._spawn_helper_caption.visible = True
        except Exception:  # noqa: BLE001
            pass
        self._sync_reinstall_btn()
        self._update_device_combo_state()
        # issue #14: re-run the tray preflight on page enter — the user may
        # have installed python3-tk (or changed displays) since the page was
        # first built.
        self._run_tray_preflight()

    def _cancel_spawn_or_install(self):
        """Cancel whichever long op (install or spawn) is running, in place."""
        self._spawn_cancelled    = True
        self._install_then_start = False
        proc = getattr(self, "_install_proc", None)
        if proc is not None:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
        if getattr(self, "_install_active", False):
            # An install (venv creation / pip) is in flight. Its own cleanup
            # runs on the worker thread and will flip this button to its
            # final label/enabled state via _re_enable_btn() once done —
            # don't race it by flipping the label here too.
            try:
                self._install_status.text = "Cancelling..."
                self._spawn_btn.enabled   = False
            except Exception:  # noqa: BLE001
                pass
            return
        self._spawn_waiting = False
        try:
            self._install_status.text = "Cancelled."
            self._hide_spawn_prog()
        except Exception:  # noqa: BLE001
            pass
        _ready = (_LABR7_VENV / "bin" / "python").exists()
        try:
            flip_button(
                self._spawn_btn,
                "Start Server" if _ready else "Install & Start Server",
                self._do_spawn if _ready else self._install_and_start)
            self._spawn_btn.enabled = True
            self._set_pulse_target(self._spawn_btn)   # UI thread: safe to resume pulse
        except Exception:  # noqa: BLE001
            pass
        self._sync_reinstall_btn()

    def _do_spawn(self, device: Optional[str] = None, _chained: bool = False):
        if _chained and self._spawn_cancelled:
            # A Cancel click raced in between _install_worker clearing
            # _install_active and this chained call (millisecond window) —
            # honor it instead of silently starting the server anyway.
            # _cancel_spawn_or_install already restored the button/status.
            return
        self._spawn_cancelled = False
        self._spawn_waiting   = True
        try:
            # Primary button becomes Cancel for the duration of the spawn.
            flip_button(self._spawn_btn, "Cancel", self._cancel_spawn_or_install)
            self._spawn_btn.enabled = True
            self._set_pulse_target(None)   # stop-only: thread-safe
        except Exception:  # noqa: BLE001
            pass
        self._sync_reinstall_btn(force_disable=True)
        if device is None:
            device_idx = self._spawn_device_combo.model.get_item_value_model().as_int
            device = "cuda" if device_idx == 1 else "cpu"
        self._mgr.save_config({"mode": "local", "device": device})
        self._spawn_status.text = "Starting the inference server - the model itself is downloaded in the next step..."
        self._set_spawn_prog(0.1)
        ok, err = self._mgr.spawn_sidecar()
        if not ok:
            self._spawn_waiting = False
            self._spawn_status.text = (
                f"Could not start server: {err}\n"
                "Check the log in ~/.labr7/logs/ and press Start Server to retry.")
            self._hide_spawn_prog()
            try:
                flip_button(self._spawn_btn, "Start Server", self._do_spawn)
                self._spawn_btn.enabled = True
            except Exception:  # noqa: BLE001
                pass
            self._sync_reinstall_btn()
            return
        self._spawn_status.text = "Server process started, waiting for it to come online..."

        def _wait():
            import os as _os
            rt       = self._mgr._read_runtime()  # noqa: SLF001
            log_file = rt.get("log_file") if rt else None
            pid      = rt.get("pid")      if rt else None

            def _log_tail(n: int = 1) -> str:
                if not log_file:
                    return ""
                try:
                    with open(log_file) as _f:
                        lines = [l.rstrip() for l in _f.readlines() if l.strip()]
                    return "\n".join(lines[-n:])[:300]
                except Exception:  # noqa: BLE001
                    return ""

            def _pid_alive(p: int) -> bool:
                try:
                    _os.kill(p, 0); return True
                except (ProcessLookupError, PermissionError):
                    return False
                except Exception:  # noqa: BLE001
                    return False

            def _finish_spawn(re_enable=True):
                self._spawn_waiting = False
                if re_enable:
                    try:
                        flip_button(self._spawn_btn, "Start Server", self._do_spawn)
                        self._spawn_btn.enabled = True
                    except Exception:  # noqa: BLE001
                        pass
                    self._sync_reinstall_btn()

            deadline = time.time() + 60
            while time.time() < deadline:
                if self._spawn_cancelled:
                    self._spawn_waiting = False
                    return
                if pid and not _pid_alive(pid):
                    tail = _log_tail(n=4)
                    self._mgr.stop_sidecar()
                    try:
                        self._spawn_status.text = (
                            f"Server process exited unexpectedly.\n{tail}\n"
                            "Press Start Server to retry.")
                        self._hide_spawn_prog()
                    except Exception:  # noqa: BLE001
                        pass
                    _finish_spawn(); return

                h = self._mgr.client.health(timeout=3.0) if self._mgr.client else {}
                if h.get("status") == "ok":
                    self._set_spawn_prog(1.0)
                    self._spawn_status.text = "Server online. Starting tray icon..."
                    try:
                        self._mgr.spawn_tray()
                    except Exception:  # noqa: BLE001
                        pass
                    self._spawn_status.text = "Server online. Proceeding to model download..."
                    time.sleep(1)
                    _finish_spawn()
                    try:
                        self._goto(_PAGE_PATH_A_DOWNLOAD)
                    except Exception:  # noqa: BLE001
                        pass
                    return

                tail   = _log_tail(n=1)
                status = f"Waiting for server... ({int(deadline - time.time())}s remaining)"
                if tail:
                    status += f"\n{tail}"
                try:
                    self._spawn_status.text = status
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(3)

            tail = _log_tail(n=3)
            try:
                self._spawn_status.text = (
                    "Server is still starting (large models can take several minutes).\n"
                    + (f"{tail}\n" if tail else "")
                    + "Return to the main panel and press Reconnect, or re-run Start Server.")
                self._set_spawn_prog(0.5)
            except Exception:  # noqa: BLE001
                pass
            _finish_spawn()

        threading.Thread(target=_wait, daemon=True).start()

    def _pulse_hint_path_a_setup(self):
        # Pulse the current next-action. Normally the primary Start/Install
        # button; if it is disabled (sidecar already running), pulse Next instead.
        # While a spawn is in flight (_spawn_waiting) don't re-arm the pulse on
        # _spawn_btn: the _wait() worker thread's own later _goto() call reaches
        # _set_pulse_target() from a background thread, and pulse.py's stop()
        # does asyncio Task.cancel() + widget-style writes that are only safe
        # to run against an already-armed target from the UI thread.
        if getattr(self, "_spawn_waiting", False):
            return None
        btn = getattr(self, "_spawn_btn", None)
        if btn is not None and not btn.enabled:
            return getattr(self, "_pa_next_btn", None)
        return btn

    def _pb_url_has_value(self) -> bool:
        """True once the Sidecar URL field holds something other than the
        empty placeholder default (issue #47)."""
        try:
            v = self._pb_url_field.model.get_value_as_string().strip()
        except Exception:  # noqa: BLE001
            return False
        return bool(v) and v != "http://"

    def _pulse_hint_path_b_connect(self):
        # issue #47: while the URL field is still empty/"http://" there is
        # nothing to press Test Connection against yet — pulse the field
        # itself so the next action is "type a URL", not the button.
        if not self._pb_url_has_value():
            return getattr(self, "_pb_url_field", None)
        return getattr(self, "_pb_connect_btn", None)

    def _refresh_pb_connect_state(self):
        """Page-enter sync for Path B's Connect page (issue #38).

        _pb_conn_status keeps showing a stale "Connected" (or error) verdict
        from a prior Test Connection when the user navigates Back to this
        page and returns — the remote server may have gone down since. Clear
        the stale verdict on every page-enter so the user re-tests before
        trusting it again. Called from _goto(); no-ops mid-attempt so it
        can't stomp on a Test Connection currently in flight.
        """
        if getattr(self, "_pb_connecting", False):
            return
        try:
            self._pb_conn_status.text    = ""
            self._pb_conn_status.visible = False
        except Exception:  # noqa: BLE001
            pass
        # issue #14: re-run the tray preflight on page enter (same trigger
        # as _refresh_pa_setup_state — the user may have installed
        # python3-tk or changed displays since the page was built).
        self._run_tray_preflight()

    # ------------------------------------------------------------------
    # 2B. Remote Connect — PATH B
    # ------------------------------------------------------------------
    def _page_path_b_connect(self):
        self._pb_setup_model = _clean_model_id(_PRESET_MODELS[0])

        # Body (everything above the nav footer) lives in its own bounded
        # ScrollingFrame, with the footer as a SIBLING after it rather than
        # a trailing item inside the same VStack. This guarantees the
        # footer (< Back / Show-Hide Uninstall Script / Next) stays fully
        # visible at a fixed position no matter how tall the uninstall
        # panel below Test Connection grows when expanded - growing the
        # whole window instead (matching WIZARD_WIN_H_DONE's Method) was
        # tried and measured live to require ~980px, which exceeds the
        # ~838px of headroom a floating wizard window actually has in this
        # Kit viewport before it renders past the physical screen edge; see
        # HEIGHT_WIZARD_PB_SCROLL_BODY in radeis_ui.py.
        with ui.VStack(spacing=0):
            with ui.ScrollingFrame(
                    height=R.HEIGHT_WIZARD_PB_SCROLL_BODY,
                    horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF):
                with ui.VStack(spacing=R.SPACING_BETWEEN_CARDS):
                    # ---- Title ----
                    R.card_header_wiz("Connect to a remote server", bar_width=R.WIDTH_ACCENT_BAR_WIZARD)
                    ui.Label("Run the inference server on another machine.\n"
                             "Run the two commands below on the remote GPU machine, then enter its URL here.",
                             height=32, word_wrap=True, style=R.STYLE_WIZARD_CARD_DESCRIPTION)
                    ui.Spacer(height=2)

                    # ---- Step 1: clone ----
                    self._pb_clone_cmd = (
                        "git clone https://github.com/VicOne-OSS-TW/labr7-radeis-InSimPhysicalAI.git\n"
                        "cd labr7-radeis-InSimPhysicalAI/vlm_sidecar"
                    )
                    with ui.HStack(height=16, spacing=6):
                        # NOTE: doc source uses an em dash here, but omni.ui's
                        # bundled Kit font has no glyph for U+2014 and silently
                        # substitutes "?" at runtime. Kept the ASCII " - "
                        # already used elsewhere on this page; only the
                        # casing changes here.
                        R.label("Step 1 - Clone the repo", size=R.FONT_DESCRIPTION)
                        ui.Spacer()
                        R.secondary_button_wiz("Copy", self._pb_copy_clone_cmd,
                                           height=16, width=48,
                                           tooltip="Copy clone command to clipboard")
                    ui.StringField(
                        ui.SimpleStringModel(self._pb_clone_cmd),
                        height=R.HEIGHT_WIZARD_CODE_BLOCK_TWO_LINE,
                        multiline=True, read_only=True,
                        style=R.STYLE_CODE_BLOCK)

                    # ---- Step 2: setup command ----
                    with ui.HStack(height=16, spacing=6):
                        R.label("Step 2 - Run the setup script", size=R.FONT_DESCRIPTION)
                        ui.Spacer()
                        R.secondary_button_wiz("Copy", self._pb_copy_setup_cmd,
                                           height=16, width=48,
                                           tooltip="Copy setup command to clipboard")
                    with ui.ZStack(height=48):
                        ui.Rectangle(style=R.STYLE_CODE_BLOCK_BG)
                        self._pb_setup_cmd_label = ui.Label(
                            "", word_wrap=True, style=R.STYLE_CODE_BLOCK_TEXT)
                    self._pb_update_setup_cmd()

                    # Divider between the two setup-script steps above and the
                    # connection form below (full_png/03-setup-remote.png).
                    ui.Spacer(height=4)
                    ui.Line(height=1, style={"color": R.COLOR_BORDER, "border_width": 1})
                    ui.Spacer(height=4)

                    # ---- Sidecar URL — label sits LEFT of the field on the same
                    # row (full_png/03-setup-remote.png), not stacked above it.
                    with ui.HStack(height=R.HEIGHT_INPUT_ROW_COMPACT, spacing=8):
                        ui.Label("Remote GPU Machine URL", width=_LABEL_COL_SIDECAR,
                                 alignment=ui.Alignment.LEFT_CENTER,
                                 style={"color": R.COLOR_TEXT_SECONDARY, "font_size": R.FONT_DESCRIPTION})
                        self._pb_url_field = ui.StringField(
                            height=R.HEIGHT_INPUT_FIELD_COMPACT,
                            style=R.STYLE_INPUT_FIELD_WIZ)
                    _saved_remote_url = self._mgr.config.get("remote_url") or ""
                    if not _saved_remote_url or _saved_remote_url == "http://":
                        try:
                            from urllib.parse import urlparse as _up
                            _active = self._mgr.active_url or ""
                            _h = _up(_active).hostname or ""
                            if _h and _h not in ("127.0.0.1", "localhost", "::1"):
                                _saved_remote_url = _active
                        except Exception:  # noqa: BLE001
                            pass
                    self._pb_url_field.model.set_value(
                        _saved_remote_url if _saved_remote_url and _saved_remote_url != "http://"
                        else "http://")

                    def _on_pb_url_changed(m):
                        # issue #47: re-evaluate the pulse target as the user
                        # types/clears the URL, mirroring the page-enter
                        # evaluation _refresh_pb_connect_state()/_goto() does.
                        # Guarded the same way _pb_connect() suspends the
                        # pulse mid-attempt (line ~1488: _set_pulse_target(None))
                        # and window.py's _reconnecting handling — an edit
                        # firing while a Test Connection call is in flight
                        # must not re-arm a target underneath it.
                        if getattr(self, "_pb_connecting", False):
                            return
                        self._set_pulse_target(self._pulse_hint_path_b_connect())
                    self._pb_url_field.model.add_value_changed_fn(_on_pb_url_changed)

                    with ui.HStack(height=16, spacing=8):
                        ui.Spacer(width=_LABEL_COL_SIDECAR)
                        R.label("e.g.  http://192.168.0.36:8765", dim=True, size=R.FONT_WIZARD_STEP, height=16)

                    # ---- Model selector + HF token (2-column row) ----
                    with ui.HStack(spacing=12):
                        with ui.VStack(spacing=4):
                            R.label("MODEL", size=R.FONT_DESCRIPTION, height=14)
                            with ui.HStack(height=R.HEIGHT_INPUT_ROW_COMPACT, spacing=6):
                                self._pb_remote_combo = ui.ComboBox(
                                    0, *_PRESET_MODELS, height=R.HEIGHT_INPUT_ROW_COMPACT,
                                    style=R.STYLE_COMBO_STANDARD)
                                R.apply_tooltip(
                                    self._pb_remote_combo, "Select which VLM model to download and run")
                            self._pb_remote_coming_soon_label = ui.Label(
                                "", height=R.HEIGHT_WIZARD_RESOURCE_LABEL,
                                style={"color": 0xFFFFAA44, "font_size": 12}, visible=False)

                        with ui.VStack(spacing=4):
                            R.label("HF TOKEN", size=R.FONT_DESCRIPTION, height=14)
                            # Masked hint text ("hf_********") shown while the field
                            # is empty, matching full_png/03-setup-remote.png — same
                            # ASCII "*" substitute Method as model_download.py's HF
                            # TOKEN field (kept ASCII since omni.ui's bundled Kit
                            # font has no glyph for U+2022 and silently substitutes
                            # "?" at runtime).
                            _hf_b_placeholder = "hf_" + "*" * 8
                            _hf_b_is_hint = [not bool(self._hf_token)]
                            _hf_b_conn = ui.StringField(
                                height=R.HEIGHT_INPUT_FIELD_COMPACT,
                                style=(R.STYLE_INPUT_FIELD_PLACEHOLDER
                                       if _hf_b_is_hint[0] else R.STYLE_INPUT_FIELD_WIZ),
                                password_mode=not _hf_b_is_hint[0])
                            _hf_b_conn.model.set_value(self._hf_token or _hf_b_placeholder)

                            def _on_pb_hf_begin_edit(m, _f=_hf_b_conn, _flag=_hf_b_is_hint):
                                if _flag[0]:
                                    _flag[0] = False
                                    _f.style = R.STYLE_INPUT_FIELD_WIZ
                                    _f.password_mode = True
                                    m.set_value("")
                            _hf_b_conn.model.add_begin_edit_fn(_on_pb_hf_begin_edit)

                            def _on_pb_hf_end_edit(m, _f=_hf_b_conn, _flag=_hf_b_is_hint):
                                if not m.get_value_as_string():
                                    _flag[0] = True
                                    _f.style = R.STYLE_INPUT_FIELD_PLACEHOLDER
                                    _f.password_mode = False
                                    m.set_value(_hf_b_placeholder)
                            _hf_b_conn.model.add_end_edit_fn(_on_pb_hf_end_edit)

                            def _on_pb_hf_changed(m, _flag=_hf_b_is_hint):
                                if _flag[0]:
                                    return
                                self._hf_token = m.get_value_as_string()
                                self._pb_update_setup_cmd()
                            _hf_b_conn.model.add_value_changed_fn(_on_pb_hf_changed)

                            R.label("Required only for gated models",
                                    dim=True, size=R.FONT_WIZARD_STEP, height=14)

                    def _on_remote_model(m):
                        if self._pb_combo_changing:
                            return
                        idx = m.get_value_as_int()
                        if idx >= _N_PRESET_MODELS:
                            self._pb_combo_changing = True
                            m.set_value(self._pb_selected_combo_idx)
                            self._pb_combo_changing = False
                            show_contact_us()
                            return
                        self._pb_selected_combo_idx = idx
                        self._pb_setup_model        = _clean_model_id(_PRESET_MODELS[idx])
                        self._pb_update_setup_cmd()
                    self._pb_remote_combo.model.get_item_value_model().add_value_changed_fn(_on_remote_model)

                    # ---- Tray-preflight warn strip (issue #14) ----
                    # The tray agent spawns on THIS machine even in remote
                    # mode, so the same preflight as the Path A setup page
                    # applies — without it, a remote-mode user only learns
                    # about a headless tray at the Done page. Placed ABOVE
                    # the Test Connection CTA: below it the strip sat too
                    # close to the page bottom at the standard wizard window
                    # height and the Copy/Re-check row was clipped by the
                    # footer (live-verified) — and up here the warning is
                    # seen before the user acts.
                    self._build_tray_pf_strip("path_b")

                    self._pb_conn_status = ui.Label("", word_wrap=True, height=48,
                                                    style=R.STYLE_WIZARD_OK_TEXT, visible=False)

                    self._pb_connect_btn = R.primary_button(
                        "Test Connection", self._pb_connect_or_cancel,
                        height=_PB_CTA_H,
                        tooltip="Test connection to the remote inference server URL")

                    self._pb_uninstall_frame = ui.Frame(visible=False)
                    self._pb_uninstall_frame.set_build_fn(self._build_uninstall_content)

            # ---- Bottom nav-footer band (full_png/03-setup-remote.png) ----
            # A sibling of the ScrollingFrame above, NOT a trailing item
            # inside it - this is what keeps it fully visible at a fixed
            # position regardless of the scrollable body's content height
            # (see the comment on the outer VStack above). No absorber
            # Spacer needed here: the outer VStack's total height is now
            # fully deterministic (ScrollingFrame's fixed height + divider +
            # this band), so there is no leftover space to distribute.
            ui.Rectangle(height=1, style=R.STYLE_WIZARD_FOOTER_DIVIDER)
            with ui.ZStack(height=R.HEIGHT_WIZARD_FOOTER_BAND):
                ui.Rectangle(style=R.STYLE_WIZARD_FOOTER_BAND)
                with ui.HStack(height=R.HEIGHT_BTN_PRIMARY_WIZARD, spacing=6,
                               style={"margin": 12}):
                    R.secondary_button_wiz("< Back", lambda: self._goto(_PAGE_LANDING),
                                       height=R.HEIGHT_BTN_PRIMARY_WIZARD,
                                       tooltip="Return to path selection")
                    self._pb_uninstall_toggle_btn = R.secondary_button_wiz(
                        "Show Uninstall Script", self._pb_toggle_uninstall,
                        height=R.HEIGHT_BTN_PRIMARY_WIZARD,
                        tooltip="Show commands to uninstall the remote inference server")
                    ui.Spacer()
                    self._pb_next_btn = R.danger_button(
                        "Next >", self._pb_goto_next,
                        height=R.HEIGHT_BTN_PRIMARY_WIZARD,
                        tooltip="Continue to setup complete")

    def _build_uninstall_content(self):
        if not self._pb_uninstall_open:
            return
        _uninstall_cmd_basic = "bash radeis-sidecar-uninstall.sh"
        _uninstall_cmd_purge = "bash radeis-sidecar-uninstall.sh --purge-model --yes"
        with ui.ZStack():
            ui.Rectangle(style=R.STYLE_CARD)
            with ui.VStack(spacing=R.SPACING_CARD_INNER):
                R.card_header("Uninstall the remote inference server (if you no longer need it)",
                              bar_width=R.WIDTH_ACCENT_BAR_WIZARD,
                              font_size=R.FONT_WIZ_CARD_TITLE)
                with ui.VStack(spacing=4):
                    ui.Spacer(height=4)
                    R.label("On the remote machine, run one of the commands below to uninstall, "
                            "then forget the saved connection.", size=R.FONT_FIELD,
                            height=28, word_wrap=True)
                    ui.Spacer(height=6)
                    R.label("Remove the environment and settings (keeps the downloaded model)", size=R.FONT_DESCRIPTION)
                    with ui.ZStack(height=R.HEIGHT_WIZARD_CODE_BLOCK_SMALL):
                        ui.Rectangle(style=R.STYLE_CODE_BLOCK_BG)
                        ui.Label(_uninstall_cmd_basic, style=R.STYLE_CODE_BLOCK_TEXT)
                    ui.Spacer(height=6)
                    R.label("Also remove the downloaded model (~9.6 GB)", size=R.FONT_DESCRIPTION)
                    with ui.ZStack(height=R.HEIGHT_WIZARD_CODE_BLOCK_SMALL):
                        ui.Rectangle(style=R.STYLE_CODE_BLOCK_BG)
                        ui.Label(_uninstall_cmd_purge, style=R.STYLE_CODE_BLOCK_TEXT)
                    ui.Spacer(height=6)
                    with ui.HStack(height=32):
                        R.danger_button_wiz_outline(
                            "Forget This Server", self._pb_confirm_forget,
                            height=R.HEIGHT_BTN_SECONDARY_WIZARD,
                            tooltip="Remove saved remote server connection record")
                    self._pb_forget_status = ui.Label("", height=14, style=R.STYLE_WIZARD_OK_TEXT)
                    ui.Spacer(height=6)

    def _pb_update_setup_cmd(self):
        # -m/--background dropped from the displayed command: the script's
        # default model already matches the only selectable wizard preset,
        # and it backgrounds itself via WITH_LAUNCHER regardless, so both
        # flags were redundant noise for every state reachable from here.
        # --hf-token stays since gemma is HF-gated and there's no default
        # for it to fall back on.
        hf_token    = self._hf_token or ""
        token_flag  = f" --hf-token {hf_token}"  if hf_token else ""
        token_disp  = " --hf-token ***"           if hf_token else ""
        real_cmd    = f"bash radeis-sidecar-setup.sh{token_flag}\n"
        display_txt = f"bash radeis-sidecar-setup.sh{token_disp}\n"
        try:
            self._pb_setup_cmd_label.text = display_txt
            self._pb_setup_cmd_real       = real_cmd
        except Exception:  # noqa: BLE001
            pass

    def _pb_copy_setup_cmd(self):
        try:
            import omni.kit.clipboard
            omni.kit.clipboard.copy(self._pb_setup_cmd_real)
        except Exception:  # noqa: BLE001
            pass

    def _pb_copy_clone_cmd(self):
        try:
            import omni.kit.clipboard
            omni.kit.clipboard.copy(self._pb_clone_cmd)
        except Exception:  # noqa: BLE001
            pass

    def _pb_goto_next(self):
        """Manually advance past Remote Connect (mirrors Path A's footer Next).

        Path B skips Load Model entirely (issue #17): remote model loading is
        expected to happen out-of-band via the setup script shown above.
        """
        self._done_page_url = self._mgr.config.get("remote_url") or ""
        self._goto(_PAGE_DONE)

    def _pb_toggle_uninstall(self):
        self._pb_uninstall_open = not self._pb_uninstall_open
        try:
            if getattr(self, "_pb_uninstall_toggle_btn", None) is not None:
                self._pb_uninstall_toggle_btn.text = (
                    "Hide Uninstall Script" if self._pb_uninstall_open
                    else "Show Uninstall Script")
        except Exception:  # noqa: BLE001
            pass
        try:
            self._pb_uninstall_frame.rebuild()
            self._pb_uninstall_frame.visible = self._pb_uninstall_open
        except Exception:  # noqa: BLE001
            pass
        try:
            # Nested Frame.rebuild()/.visible never resizes the ancestor VStack
            # on its own — only the root window frame can actually trigger a
            # re-layout, same call _goto() uses after every page switch.
            self._win.frame.invalidate_raster()
        except Exception:  # noqa: BLE001
            pass

    def _pb_confirm_forget(self):
        if getattr(self, "_dlg_win", None) is not None:
            try:
                self._dlg_win.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._dlg_win = None
        self._dlg_win = R.warning_window(
            "Forget This Server",
            message="Permanently removes:",
            items=[
                "Saved remote URL and authentication token",
                "Connection record from local config",
            ],
            footer="Cannot be undone.",
            confirm_label="Forget Server",
            on_confirm=self._pb_forget_server,
            on_cancel=None,
            danger=True,
            width=340,
            parent_win=self._win,
        )

    def _pb_forget_server(self):
        old_url = ""
        try:
            old_url = self._pb_url_field.model.get_value_as_string().strip()
        except Exception:  # noqa: BLE001
            pass
        if not old_url or old_url == "http://":
            old_url = self._mgr.config.get("remote_url") or ""
        if old_url and old_url != "http://":
            self._mgr.deregister_url(old_url)
        self._mgr.save_config({"mode": "local", "remote_url": None, "remote_token": None})
        try:
            self._pb_url_field.model.set_value("http://")
        except Exception:  # noqa: BLE001
            pass
        try:
            self._pb_conn_status.text  = ""
            self._pb_conn_status.visible = False
            self._pb_conn_status.style = R.STYLE_WIZARD_OK_TEXT
        except Exception:  # noqa: BLE001
            pass
        self._refresh_done_info()
        try:
            if self._on_forget is not None:
                self._on_forget()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._pb_forget_status.text  = "Server removed. Connection record cleared."
            self._pb_forget_status.style = R.STYLE_WIZARD_OK_TEXT
        except Exception:  # noqa: BLE001
            pass

    def _pb_connect_or_cancel(self):
        if self._pb_connecting:
            self._pb_connect_cancel()
        else:
            self._pb_connect()

    def _pb_connect_cancel(self):
        self._pb_connect_cancelled = True
        self._pb_connecting        = False
        try:
            flip_button(self._pb_connect_btn, "Test Connection", self._pb_connect_or_cancel)
            self._pb_conn_status.text    = "Connection attempt cancelled."
            self._pb_conn_status.visible = True
            self._pb_conn_status.style   = R.STYLE_WIZARD_OK_TEXT
            self._set_pulse_target(self._pb_connect_btn)
        except Exception:  # noqa: BLE001
            pass

    def _pb_connect(self):
        url = self._pb_url_field.model.get_value_as_string().strip()
        if not url.startswith("http"):
            try:
                self._pb_conn_status.text    = "Please enter a valid URL starting with http://..."
                self._pb_conn_status.visible = True
                self._pb_conn_status.style   = R.STYLE_WIZARD_ERROR_TEXT
            except Exception:  # noqa: BLE001
                pass
            return
        self._pb_connect_cancelled = False
        self._pb_connecting        = True
        try:
            flip_button(self._pb_connect_btn, "Cancel", self._pb_connect_or_cancel)
            self._pb_conn_status.text    = "Connecting..."
            self._pb_conn_status.visible = True
            self._pb_conn_status.style   = R.STYLE_WIZARD_OK_TEXT
            self._set_pulse_target(None)   # stop-only: thread-safe
        except Exception:  # noqa: BLE001
            pass

        def _worker():
            h: dict = {"error": "connection attempt did not complete"}
            try:
                from ...vlm.sidecar_client import SidecarClient
                remote_token = self._mgr.config.get("remote_token") or None
                client = SidecarClient(base_url=url, token=remote_token)
                h = client.health(timeout=8.0)
            except Exception as _exc:  # noqa: BLE001
                h = {"error": str(_exc)}
            finally:
                self._pb_connecting = False
                try:
                    flip_button(self._pb_connect_btn, "Test Connection", self._pb_connect_or_cancel)
                except Exception:  # noqa: BLE001
                    pass
            if self._pb_connect_cancelled:
                return
            if "error" in h or h.get("status") != "ok":
                try:
                    import re as _re
                    raw_err  = h.get("error", "no response")
                    m        = _re.search(r"<urlopen error (.+?)>", raw_err)
                    err_detail = m.group(1) if m else raw_err.split(". Check that the server")[0]
                    self._pb_conn_status.text = (
                        f"Could not connect to {url}.\n"
                        f"Error: {err_detail}\n"
                        f"Check that the server is running and the URL is correct.")
                    self._pb_conn_status.visible = True
                    self._pb_conn_status.style = R.STYLE_WIZARD_ERROR_TEXT
                except Exception:  # noqa: BLE001
                    pass
                return
            try:
                self._pb_conn_status.text    = "Connected"
                self._pb_conn_status.visible = True
                self._pb_conn_status.style   = R.STYLE_WIZARD_OK_TEXT
            except Exception:  # noqa: BLE001
                pass
            self._mgr.save_config({"mode": "remote", "remote_url": url,
                                    "remote_token": None, "device": "cuda"})
            self._done_page_url = url
            if h.get("loaded"):
                self._mgr.save_config({"setup_complete": True})
                self._mgr.register_pair(url, self._mgr.config.get("model_repo", ""))
                self._mgr.spawn_tray()
            self._goto(_PAGE_DONE)

        threading.Thread(target=_worker, daemon=True).start()

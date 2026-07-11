"""Model Setup Wizard — assembled from four step modules.

Step 1: choose_server   — Choose installation path (Local / Remote)
Step 2: sidecar_setup   — Install env (Path A) / Connect to remote (Path B)
Step 3: model_download  — Download model (Path A) / Load model on remote (Path B)
Step 4: complete_test   — Setup complete, server status, test inference
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import omni.ui as ui

from .. import radeis_ui as R
from ..pulse import PulseController
from ...vlm.sidecar_manager import SidecarManager
from ._constants import (
    DEFAULT_MODEL_REPO, _DEFAULT_SELECTED_PATH,
    _PAGE_LANDING, _PAGE_PATH_A_SETUP, _PAGE_PATH_A_DOWNLOAD,
    _PAGE_PATH_B_CONNECT, _PAGE_PATH_B_LOAD, _PAGE_DONE,
    _STEP_NAMES, _STEP_NAMES_B, _STEP_IDX, _STEP_IDX_B,
)
from .choose_server  import Step1ChoosePathMixin
from .sidecar_setup  import Step2SetupMixin
from .model_download import Step3TransferMixin
from .complete_test  import Step4CompleteMixin

# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_INSTANCE: Optional["ModelWizard"] = None


def _clear_instance(wiz: "ModelWizard") -> None:
    global _INSTANCE
    if _INSTANCE is wiz:
        _INSTANCE = None


def open_wizard(mgr: SidecarManager, ext_path: str = "",
                on_complete=None, on_forget=None) -> None:
    global _INSTANCE
    if _INSTANCE is not None and getattr(_INSTANCE, "_win", None):
        try:
            if on_complete is not None:
                _INSTANCE._on_complete = on_complete
            if on_forget is not None:
                _INSTANCE._on_forget = on_forget
            # Reopening a stale wizard should show a clean landing page —
            # i.e. reset to the default recommended selection, not a
            # leftover path choice from whatever the last session left on
            # _INSTANCE — but a plain in-session Back click into _goto()
            # below must NOT clear this (see _goto's landing branch).
            _INSTANCE._selected_path = _DEFAULT_SELECTED_PATH
            _INSTANCE._goto(_PAGE_LANDING)
            _INSTANCE._win.visible = True
            _INSTANCE._win.focus()
            return
        except Exception:  # noqa: BLE001
            # Route the stale instance through its own correct teardown
            # instead of just dropping the reference -- otherwise its
            # ui.Window is never destroyed, becomes an orphan that keeps
            # rendering its last page, and silently contaminates later
            # screenshots (see orphan-modelwizard-window-leak.md). Suppress
            # callbacks first since we're about to build a fresh instance
            # right below, not actually completing/forgetting the wizard.
            stale = _INSTANCE
            _INSTANCE = None
            if stale is not None:
                stale._on_complete = None
                stale._on_forget = None
                try:
                    stale._close_wizard()
                except Exception:  # noqa: BLE001
                    pass
    _INSTANCE = ModelWizard(mgr, ext_path, on_complete=on_complete, on_forget=on_forget)


# ---------------------------------------------------------------------------
# Base class — init, window, step indicator, navigation
# ---------------------------------------------------------------------------
class WizardBase:
    """Core wizard infrastructure: window, step indicator, page routing."""

    def __init__(self, mgr: SidecarManager, ext_path: str = "",
                 on_complete=None, on_forget=None):
        self._mgr             = mgr
        self._ext_path        = ext_path
        self._on_complete     = on_complete
        self._on_forget       = on_forget
        self._test_img_path   = (str(Path(ext_path) / "data" / "icon" / "inference-test.png")
                                 if ext_path else "")
        self._page = _PAGE_LANDING
        self._worker: Optional[object] = None
        self._wiz_pulse = PulseController()

        # Shared state accessed across steps
        self._resource_info:              dict  = {}
        self._generated_token:            Optional[str] = None
        self._selected_model_repo:        str   = DEFAULT_MODEL_REPO
        self._selected_combo_idx:         int   = 0
        self._combo_changing:             bool  = False
        self._pb_combo_changing:          bool  = False
        self._pb_selected_combo_idx:      int   = 0
        self._pb_load_combo_changing:     bool  = False
        self._pb_load_selected_combo_idx: int   = 0
        self._cuda_available:             bool  = True
        self._landing_gpu_ok:             bool  = True
        self._selected_path:              Optional[str] = _DEFAULT_SELECTED_PATH
        self._spawn_revealed:             bool  = False
        self._install_log_path:           Optional[Path] = None
        self._pb_setup_model:             str   = DEFAULT_MODEL_REPO
        self._pb_setup_cmd_label:         Optional[ui.Label] = None
        self._pb_setup_cmd_real:          str   = ""
        self._pb_uninstall_frame:         Optional[ui.Frame] = None
        self._pb_uninstall_open:          bool  = False
        self._pb_forget_status:           Optional[ui.Label] = None
        self._pb_connect_cancelled:       bool  = False
        self._pb_connecting:              bool  = False
        self._resource_check_time_label:  Optional[ui.Label] = None
        self._hf_token:                   str   = ""
        self._resource_check_ran:         bool  = False
        self._pa_next_btn:                Optional[ui.Button] = None
        self._done_info_label:            Optional[ui.Label] = None
        self._done_model_label:           Optional[ui.Label] = None
        self._done_test_url_label:        Optional[ui.Label] = None
        self._done_server_status:         Optional[ui.Label] = None
        self._done_start_server_btn:      Optional[ui.Button] = None
        self._done_start_server_row:      Optional[ui.HStack] = None
        self._run_test_btn:               Optional[ui.Button] = None
        self._done_page_url:              str   = ""
        self._install_open_log_btn:       Optional[ui.Button] = None
        self._download_open_log_btn:      Optional[ui.Button] = None
        self._download_log_path:          Optional[Path] = None

        self._win = ui.Window(
            "Radeis - Model Setup Wizard",
            width=R.WIZARD_WIN_W, height=R.WIZARD_WIN_H,
            flags=ui.WINDOW_FLAGS_NO_SCROLLBAR,
        )
        self._win.frame.set_style(R.STYLE_WINDOW_FRAME)
        self._win.set_visibility_changed_fn(self._on_win_visibility_changed)
        self._build()

    # ------------------------------------------------------------------
    # Open Log helper
    # ------------------------------------------------------------------
    def _open_log_file(self, log_path) -> None:
        import subprocess as _sp
        if log_path and Path(log_path).exists():
            try:
                _sp.Popen(["xdg-open", str(log_path)])
            except Exception as e:  # noqa: BLE001
                import carb
                carb.log_warn(f"[radeis] Cannot open log: {e}")
        else:
            import carb
            carb.log_warn(f"[radeis] Log file not found: {log_path}")

    # ------------------------------------------------------------------
    # Top-level builder
    # ------------------------------------------------------------------
    def _build(self):
        with self._win.frame:
            with ui.ScrollingFrame(
                    horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF):
                with ui.VStack(spacing=R.SPACING_OUTER, style=R.STYLE_MAIN_OUTER_VSTACK):
                    self._build_step_indicator()
                    self._page_stack = ui.ZStack()
                    with self._page_stack:
                        self._frames: dict[str, ui.Frame] = {}
                        for page in [_PAGE_LANDING, _PAGE_PATH_A_SETUP,
                                     _PAGE_PATH_A_DOWNLOAD,
                                     _PAGE_PATH_B_CONNECT, _PAGE_PATH_B_LOAD,
                                     _PAGE_DONE]:
                            f = ui.Frame(visible=(page == _PAGE_LANDING))
                            self._frames[page] = f
                            with f:
                                getattr(self, f"_page_{page.replace('-', '_')}")()
        self._goto(_PAGE_LANDING)

    # ------------------------------------------------------------------
    # Step indicator
    # ------------------------------------------------------------------
    def _build_step_indicator(self):
        self._step_labels: list[ui.Label]     = []
        self._step_bars:   list[ui.Rectangle] = []
        self._step_cols:   list[ui.VStack]    = []
        with ui.HStack(height=R.HEIGHT_WIZARD_STEP_INDICATOR,
                       spacing=R.SPACING_WIZARD_STEP_INDICATOR):
            for i, name in enumerate(_STEP_NAMES):
                col = ui.VStack(spacing=0)
                with col:
                    lbl = ui.Label(
                        f"{i + 1}. {name}",
                        alignment=ui.Alignment.CENTER,
                        style=R.STYLE_WIZARD_STEP_LABEL_INACTIVE)
                    bar = ui.Rectangle(height=R.HEIGHT_WIZARD_STEP_BAR,
                                       style=R.STYLE_WIZARD_STEP_BAR_INACTIVE)
                    self._step_labels.append(lbl)
                    self._step_bars.append(bar)
                self._step_cols.append(col)

    def _refresh_step_indicator(self):
        # Both paths render the same generic 4-column rail (design ref:
        # "1. Path / 2. Setup / 3. Model / 4. Complete" on every page,
        # confirmed against reference-path_b_connect.png — Path B never
        # shrinks to a 3-column rail). Path B's connect page maps to
        # step 2 ("Setup"), the same rail position as Path A's local
        # install page; see _constants.py for why. _STEP_NAMES_B/_STEP_IDX_B
        # are aliases of the generic tables, kept only so this call site
        # still documents which conceptual rail each branch reads.
        if self._selected_path == "B":
            names, idx_map = _STEP_NAMES_B, _STEP_IDX_B
        else:
            names, idx_map = _STEP_NAMES, _STEP_IDX
        current = idx_map.get(self._page, 0)
        for i, (col, lbl, bar) in enumerate(zip(self._step_cols, self._step_labels, self._step_bars)):
            try:
                col.visible = (i < len(names))
                if i >= len(names):
                    continue
                lbl.text = f"{i + 1}. {names[i]}"
                if i < current:
                    lbl.style = R.STYLE_WIZARD_STEP_LABEL_DONE
                    bar.style = R.STYLE_WIZARD_STEP_BAR_DONE
                elif i == current:
                    lbl.style = R.STYLE_WIZARD_STEP_LABEL_ACTIVE
                    bar.style = R.STYLE_WIZARD_STEP_BAR_CURRENT
                else:
                    lbl.style = R.STYLE_WIZARD_STEP_LABEL_INACTIVE
                    bar.style = R.STYLE_WIZARD_STEP_BAR_INACTIVE
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def _set_pulse_target(self, widget: Optional["ui.Widget"]) -> None:
        # issue #47: the Path B Sidecar URL field is a valid pulse target too
        # (border-accent alternating), not just buttons — pick the matching
        # base/accent style pair by widget identity so the one shared
        # self._wiz_pulse controller (which already guarantees the "exactly
        # one target" invariant) can drive either without a second
        # controller. No-op for every other existing call site since none of
        # them are _pb_url_field.
        if widget is getattr(self, "_pb_url_field", None):
            base_style, pulse_style = R.STYLE_INPUT_FIELD_WIZ, R.STYLE_INPUT_FIELD_WIZ_PULSE
        else:
            base_style, pulse_style = R.STYLE_WIZ_BTN_PRIMARY_BASE, R.STYLE_WIZ_BTN_PRIMARY_PULSE

        if widget is None:
            # stop-only: PulseController.stop() just cancels a Task and
            # writes widget styles -- no asyncio.ensure_future() call, so
            # this is safe to run from any thread.
            self._wiz_pulse.pulse(widget, base_style, pulse_style)
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No running event loop on *this* thread. _goto() (which calls
            # us with the destination page's pulse hook) runs from
            # background worker threads too -- see sidecar_setup.py's
            # _wait() daemon thread's self._goto(_PAGE_PATH_A_DOWNLOAD) and
            # model_download.py's download/_pb_load_model worker threads'
            # self._goto(_PAGE_DONE). PulseController.pulse() calls
            # asyncio.ensure_future(self._loop(...)) to (re)start a pulse,
            # which needs a loop on the calling thread; off the UI thread
            # there isn't one, so ensure_future raises before it can wrap
            # the coroutine, leaving self._loop(...) un-awaited (surfaces
            # later as an unrelated "coroutine was never awaited" GC warning,
            # silently swallowed by the try/except around each self._goto()
            # call site). Marshal the actual pulse start onto the next Kit
            # app-update tick instead, mirroring the existing
            # _dl_resume_pulse()/_done_update_pulse one-shot-subscription
            # idiom (model_download.py, complete_test.py).
            import omni.kit.app  # noqa: PLC0415
            _holder = {}

            def _apply(_e):
                _holder.pop("sub", None)  # one-shot: drop handle -> unsubscribe
                try:
                    self._wiz_pulse.pulse(widget, base_style, pulse_style)
                except Exception:  # noqa: BLE001
                    pass

            _holder["sub"] = (omni.kit.app.get_app()
                              .get_update_event_stream()
                              .create_subscription_to_pop(_apply))
            return
        self._wiz_pulse.pulse(widget, base_style, pulse_style)

    def _goto(self, page: str):
        self._page = page
        # The Done page's Configuration dividers + card insets + footer band
        # need more vertical room than every other wizard page (see
        # WIZARD_WIN_H_DONE in radeis_ui.py) - resized per-page here rather
        # than bumping the shared WIZARD_WIN_H, which would otherwise leave a
        # large dead gap above the footer on lighter pages (their own
        # trailing Spacer would just stretch into the extra height).
        try:
            self._win.height = (
                R.WIZARD_WIN_H_DONE if page == _PAGE_DONE else R.WIZARD_WIN_H)
        except Exception:  # noqa: BLE001
            pass
        for k, f in self._frames.items():
            f.visible = (k == page)
        # omni.ui bakes/reuses a DrawList per window and doesn't always detect
        # that a nested Frame's `visible` flip (inside our page-switching
        # ZStack) counts as "content changed" — without this the window can
        # keep showing the previously-active page's stale raster until some
        # unrelated widget mutation elsewhere happens to force a repaint.
        # Force it explicitly so navigation always paints the new page.
        try:
            self._win.frame.invalidate_raster()
        except Exception:  # noqa: BLE001
            pass
        self._refresh_step_indicator()
        if page == _PAGE_LANDING:
            self._refresh_landing_state()
        if page == _PAGE_DONE:
            self._refresh_done_info()
            # NOTE: _on_complete intentionally NOT called here.
            # _goto(_PAGE_DONE) runs from a background thread; firing on_complete from
            # a non-event-loop thread can leave _reconnecting stuck. Fire it safely from
            # _close_wizard() instead (triggered by the Close button / window X).
        if page == _PAGE_PATH_A_SETUP:
            self._refresh_pa_setup_state()
        if page == _PAGE_PATH_B_CONNECT:
            self._refresh_pb_connect_state()
        if page == _PAGE_PATH_A_DOWNLOAD:
            self._refresh_dl_btn_enabled()
        hook = getattr(self, f"_pulse_hint_{page.replace('-', '_')}", None)
        self._set_pulse_target(hook() if callable(hook) else None)

    # ------------------------------------------------------------------
    # Progress bar helper
    # ------------------------------------------------------------------
    def _make_progress_bar(self, height: int = R.HEIGHT_PROGRESS_BAR_WIZARD):
        bar = ui.ProgressBar(height=height)
        bar.style = R.STYLE_PROGRESS_BAR
        bar.model.set_value(0.0)
        bar.visible = False

        def _set(v: float):
            try:
                bar.visible = True
                bar.model.set_value(v)
            except Exception:  # noqa: BLE001
                pass

        def _hide():
            try:
                bar.visible = False
                bar.model.set_value(0.0)
            except Exception:  # noqa: BLE001
                pass

        return bar, _set, _hide

    async def _show_coming_soon_hint(self, label: ui.Label, secs: float = 1.5):
        try:
            label.text    = "Not available in this release."
            label.visible = True
        except Exception:  # noqa: BLE001
            return
        await asyncio.sleep(secs)
        try:
            label.visible = False
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Assembled wizard: four step mixins + base
# ---------------------------------------------------------------------------
class ModelWizard(
    Step1ChoosePathMixin,
    Step2SetupMixin,
    Step3TransferMixin,
    Step4CompleteMixin,
    WizardBase,
):
    """Model Setup Wizard combining all four setup steps."""

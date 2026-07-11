"""Step 1 — Choose installation path (Local or Remote)."""
from __future__ import annotations

import asyncio

import omni.kit.app
import omni.ui as ui

from .. import radeis_ui as R
from ._constants import DEFAULT_MODEL_REPO, _PAGE_PATH_A_SETUP, _PAGE_PATH_B_CONNECT
from ._helpers import _probe_gpu_vram


class Step1ChoosePathMixin:
    """Mixin for Step 1: landing page where the user picks Local or Remote install."""

    def _refresh_landing_state(self):
        """Re-apply card/radio/hint/button visuals from self._selected_path.

        The landing Frame is built once in ModelWizard._build() and only
        toggled visible/invisible by _goto() afterwards — _page_landing()
        never re-runs. Without this hook, navigating Back to landing after
        already picking a path left the cards showing the pre-build default
        (unselected) even though self._selected_path was still set, until
        the whole wizard was closed and reopened.
        """
        path = getattr(self, "_selected_path", None)
        try:
            self._card_a_bg.style = (
                R.STYLE_CARD_WIZARD_SELECTED if path == "A" else R.STYLE_CARD_WIZARD)
            self._card_b_bg.style = (
                R.STYLE_CARD_WIZARD_SELECTED if path == "B" else R.STYLE_CARD_WIZARD)
            self._card_a_radio.style = (
                R.STYLE_WIZARD_RADIO_SELECTED if path == "A" else R.STYLE_WIZARD_RADIO_EMPTY)
            self._card_b_radio.style = (
                R.STYLE_WIZARD_RADIO_SELECTED if path == "B" else R.STYLE_WIZARD_RADIO_EMPTY)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._landing_setup_btn.enabled = bool(path in ("A", "B"))
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # 1. Choose Path — Landing page
    # ------------------------------------------------------------------
    def _page_landing(self):
        def _select(path: str):
            self._selected_path = path
            self._refresh_landing_state()

        with ui.VStack(spacing=R.SPACING_BETWEEN_CARDS):
            with ui.ZStack():
                ui.Rectangle(style=R.STYLE_CARD)
                with ui.VStack(spacing=R.SPACING_CARD_INNER_WIDE):
                    R.card_header_wiz("Where to install the inference server?",
                                      bar_width=R.WIDTH_ACCENT_BAR_WIZARD)
                    ui.Label(
                        "Choose Local to run the AI model on this computer, or Remote "
                        "to run it on another GPU machine over the network. You can "
                        "change this later.",
                        height=R.HEIGHT_WIZARD_LANDING_INTRO, word_wrap=True,
                        style=R.STYLE_WIZARD_CARD_DESCRIPTION)
                    ui.Spacer(height=4)
                    with ui.HStack(spacing=R.SPACING_WIZARD_PATH_CARDS,
                                   height=R.HEIGHT_WIZARD_PATH_CARD):
                        # ---- Card A ----
                        # Fractional width (not a fixed px card + flanking
                        # Spacers) so the pair is flush with the content
                        # column edges, matching full_png/01-choose-path.png
                        # — a fixed-width centered pair left a visible inset.
                        self._card_a_zstack = ui.ZStack(width=ui.Fraction(1))
                        with self._card_a_zstack:
                            self._card_a_bg = ui.Rectangle(
                                style=R.STYLE_CARD_WIZARD_SELECTED if self._selected_path == "A"
                                else R.STYLE_CARD_WIZARD)
                            with ui.VStack(spacing=R.SPACING_WIZARD_CARD_INNER,
                                           style={"margin": R.MARGIN_WIZARD_CARD_INNER}):
                                with ui.HStack(height=R.HEIGHT_CARD_HEADER_COMPACT, spacing=6):
                                    with ui.ZStack(width=R.WIDTH_WIZARD_RADIO_GLYPH):
                                        self._card_a_radio = ui.Circle(
                                            width=R.DIAMETER_WIZARD_RADIO,
                                            height=R.DIAMETER_WIZARD_RADIO,
                                            radius=R.DIAMETER_WIZARD_RADIO / 2,
                                            alignment=ui.Alignment.CENTER,
                                            size_policy=ui.CircleSizePolicy.FIXED,
                                            style=R.STYLE_WIZARD_RADIO_SELECTED if self._selected_path == "A"
                                            else R.STYLE_WIZARD_RADIO_EMPTY)
                                    ui.Label("Local Install",
                                             style={"color": R.COLOR_TEXT_PRIMARY,
                                                    "font_size": R.FONT_CARD_TITLE})
                                ui.Spacer(height=2)
                                # word_wrap=True + explicit height: without it these
                                # un-wrapped Labels report their full single-line
                                # intrinsic width as a minimum, which can exceed this
                                # card's ui.Fraction(1) share and push the sibling
                                # card past the window's right edge (see the analogous
                                # fix already applied in model_download.py /
                                # sidecar_setup.py for long no-word_wrap Labels).
                                R.label("Starts the inference server locally", dim=False,
                                        size=R.FONT_WIZARD_STEP, height=16, word_wrap=True)
                                R.label("Runs on this machine (GPU or CPU)", dim=False,
                                        size=R.FONT_WIZARD_STEP, height=16, word_wrap=True)
                                R.label("Environment setup + model download", dim=False,
                                        size=R.FONT_WIZARD_STEP, height=16, word_wrap=True)
                                self._card_a_no_gpu_badge = ui.ZStack(
                                    width=R.WIDTH_WIZARD_BADGE, height=R.HEIGHT_WIZARD_BADGE,
                                    visible=False)
                                with self._card_a_no_gpu_badge:
                                    ui.Rectangle(style=R.STYLE_WIZARD_BADGE_WARN)
                                    self._card_a_no_gpu_label = ui.Label(
                                        "Low VRAM - CPU mode",
                                        style=R.STYLE_WIZARD_BADGE_WARN_TEXT,
                                        alignment=ui.Alignment.CENTER)
                                ui.Spacer()
                        self._card_a_zstack.set_mouse_pressed_fn(
                            lambda x, y, b, m: _select("A"))
                        self._card_a_zstack.set_mouse_hovered_fn(
                            lambda h: setattr(
                                self._card_a_bg, "style",
                                R.STYLE_CARD_WIZARD_SELECTED if (h or self._selected_path == "A")
                                else R.STYLE_CARD_WIZARD))
                        # ---- Card B ----
                        self._card_b_zstack = ui.ZStack(width=ui.Fraction(1))
                        with self._card_b_zstack:
                            self._card_b_bg = ui.Rectangle(
                                style=R.STYLE_CARD_WIZARD_SELECTED if self._selected_path == "B"
                                else R.STYLE_CARD_WIZARD)
                            with ui.VStack(spacing=R.SPACING_WIZARD_CARD_INNER,
                                           style={"margin": R.MARGIN_WIZARD_CARD_INNER}):
                                with ui.HStack(height=R.HEIGHT_CARD_HEADER_COMPACT, spacing=6):
                                    with ui.ZStack(width=R.WIDTH_WIZARD_RADIO_GLYPH):
                                        self._card_b_radio = ui.Circle(
                                            width=R.DIAMETER_WIZARD_RADIO,
                                            height=R.DIAMETER_WIZARD_RADIO,
                                            radius=R.DIAMETER_WIZARD_RADIO / 2,
                                            alignment=ui.Alignment.CENTER,
                                            size_policy=ui.CircleSizePolicy.FIXED,
                                            style=R.STYLE_WIZARD_RADIO_SELECTED if self._selected_path == "B"
                                            else R.STYLE_WIZARD_RADIO_EMPTY)
                                    ui.Label("Remote Install",
                                             style={"color": R.COLOR_TEXT_PRIMARY,
                                                    "font_size": R.FONT_CARD_TITLE})
                                ui.Spacer(height=2)
                                # See matching comment on Card A above — same
                                # word_wrap fix, needed here too since this card's
                                # longest line ("Run the provided setup script on the
                                # machine") is what was actually forcing the overflow.
                                R.label("Runs the AI model on a remote GPU", dim=False,
                                        size=R.FONT_WIZARD_STEP, height=16, word_wrap=True)
                                R.label("Enter the server URL to connect", dim=False,
                                        size=R.FONT_WIZARD_STEP, height=16, word_wrap=True)
                                R.label("Run the provided setup script on the machine", dim=False,
                                        size=R.FONT_WIZARD_STEP, height=16, word_wrap=True)
                                ui.Spacer(height=2)
                                R.wizard_badge("Best for limited VRAM", ok=True)
                                ui.Spacer()
                        self._card_b_zstack.set_mouse_pressed_fn(
                            lambda x, y, b, m: _select("B"))
                        self._card_b_zstack.set_mouse_hovered_fn(
                            lambda h: setattr(
                                self._card_b_bg, "style",
                                R.STYLE_CARD_WIZARD_SELECTED if (h or self._selected_path == "B")
                                else R.STYLE_CARD_WIZARD))
                        # (no trailing Spacer here — both cards are
                        # ui.Fraction(1) and must fill 100% of the row width
                        # between them; an extra stretchy Spacer would just
                        # steal a third of that space back)
            # No outer hint Label below the cards — reference full_png/01-choose-path.png
            # shows an empty body below the card row. The "Low VRAM - CPU mode"
            # state is already conveyed inline by the in-card badge
            # (self._card_a_no_gpu_badge); a second, duplicate caption centered
            # below the cards was an extra element not present in the mockup.
            # ---- Bottom nav-footer band (ref full_png/01-choose-path.png) ----
            # A single trailing Spacer (P2-compliant: at most one) hugs this
            # band to the true bottom of the page instead of letting it float
            # mid-frame; the divider + darker band are a persistent footer
            # strip, not per-content padding.
            ui.Spacer()
            ui.Rectangle(height=1, style=R.STYLE_WIZARD_FOOTER_DIVIDER)
            with ui.ZStack(height=R.HEIGHT_WIZARD_FOOTER_BAND):
                ui.Rectangle(style=R.STYLE_WIZARD_FOOTER_BAND)
                with ui.HStack(style={"margin": 12}):
                    ui.Spacer()
                    self._landing_setup_btn = R.primary_button(
                        "Continue >", self._landing_setup,
                        height=R.HEIGHT_BTN_PRIMARY_WIZARD,
                        width=R.WIDTH_BTN_WIZARD_NEXT,
                        tooltip="Continue to the selected install path")
                    self._landing_setup_btn.enabled = bool(self._selected_path in ("A", "B"))
        asyncio.ensure_future(self._async_landing_gpu_check())

    def _async_landing_gpu_check(self):
        import asyncio as _aio
        async def _run():
            await omni.kit.app.get_app().next_update_async()
            self._check_landing_gpu()
        return _aio.ensure_future(_run())

    def _check_landing_gpu(self):
        gpu_ok, reason = _probe_gpu_vram(DEFAULT_MODEL_REPO)
        self._landing_gpu_ok = gpu_ok
        try:
            if not gpu_ok:
                self._card_a_no_gpu_label.tooltip = reason
                self._card_a_no_gpu_badge.visible = True
            else:
                self._card_a_no_gpu_badge.visible = False
        except Exception:  # noqa: BLE001
            pass
        # This async probe resolves a frame or more after _page_landing()
        # builds (and can also fire after the user has already clicked a
        # card), so it must re-derive card A's border/radio from the CURRENT
        # self._selected_path via _refresh_landing_state() rather than
        # hardcoding STYLE_CARD_WIZARD (unselected) here — the old
        # unconditional overwrite silently clobbered a live "selected"
        # highlight on Card A whenever the GPU check resolved not-ok,
        # regardless of whether path A was actually selected at the time.
        self._refresh_landing_state()

    def _landing_setup(self):
        if self._selected_path == "A":
            self._goto(_PAGE_PATH_A_SETUP)
        elif self._selected_path == "B":
            self._goto(_PAGE_PATH_B_CONNECT)
        # else: unreachable via the UI — _landing_setup_btn.enabled is False
        # whenever no path is selected, so this callback can't fire without
        # one. (No hint Label to update here — see _refresh_landing_state.)

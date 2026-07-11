"""Radeis onboarding intro-card — omni.ui implementation.

Three-slide carousel; content sourced from slides.py / content.py.
Usage::

    win = OnboardingWindow(ext_path, on_finish_fn=my_callback)
    # window appears automatically; on_finish_fn called when user clicks
    # "Start Robustness Test" or the window is explicitly closed.
"""
from __future__ import annotations

import asyncio
import os
from typing import Callable, Optional

try:
    import omni.ui as ui
    _UI_AVAILABLE = True
except ModuleNotFoundError:
    _UI_AVAILABLE = False

from .slides import SLIDES
from . import style as S

_SECTION_TAGS = ["THE PROBLEM", "THE CAUSE", "THE SOLUTION"]

# Module-level reference for external/TCP access
_ACTIVE_WINDOW: Optional['OnboardingWindow'] = None


class OnboardingWindow:
    """Floating intro-card window with a 3-slide carousel."""

    def __init__(
        self,
        ext_path: str,
        on_finish_fn: Optional[Callable] = None,
        anchor_x: Optional[float] = None,
        anchor_y: Optional[float] = None,
        anchor_w: Optional[float] = None,
        anchor_h: Optional[float] = None,
    ) -> None:
        global _ACTIVE_WINDOW
        self._ext_path = ext_path
        self._on_finish_fn = on_finish_fn
        self._current = 0
        self._window: Optional[ui.Window] = None  # type: ignore[name-defined]
        self._content_frame = None
        self._footer_frame = None
        self._pending_task = None
        # Position over the caller's live window (e.g. the main extension
        # panel) when anchor geometry is supplied; otherwise fall back to
        # the static style.py defaults so this class stays usable standalone.
        if anchor_x is not None and anchor_y is not None:
            anchor_w = anchor_w if anchor_w is not None else S.WIN_W
            anchor_h = anchor_h if anchor_h is not None else S.WIN_H
            self._open_x = anchor_x + (anchor_w - S.WIN_W) / 2
            self._open_y = anchor_y + (anchor_h - S.WIN_H) / 2
        else:
            self._open_x = S.WIN_X
            self._open_y = S.WIN_Y
        if _UI_AVAILABLE:
            self._build()
        _ACTIVE_WINDOW = self

    # ── Public API ──────────────────────────────────────────────────────────

    def show(self) -> None:
        if self._window:
            self._window.visible = True
            self._window.focus()

    def hide(self) -> None:
        if self._window:
            self._window.visible = False

    def destroy(self) -> None:
        global _ACTIVE_WINDOW
        self._on_finish_fn = None
        if self._window:
            self._window.destroy()
            self._window = None
        if _ACTIVE_WINDOW is self:
            _ACTIVE_WINDOW = None

    @property
    def visible(self) -> bool:
        return bool(self._window and self._window.visible)

    # ── Path helpers ─────────────────────────────────────────────────────────

    def _icon(self, name: str) -> str:
        return os.path.join(
            self._ext_path, "labr7", "radeis", "redteam",
            "onboarding", "mockup", "icon", name,
        )

    def _png(self, name: str) -> str:
        return os.path.join(
            self._ext_path, "labr7", "radeis", "redteam",
            "onboarding", "mockup", "png", name,
        )

    # ── Build ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        flags = (
            ui.WINDOW_FLAGS_NO_SCROLLBAR  # type: ignore[attr-defined]
            | ui.WINDOW_FLAGS_NO_RESIZE  # type: ignore[attr-defined]
            | ui.WINDOW_FLAGS_NO_DOCKING  # type: ignore[attr-defined]
        )
        self._window = ui.Window(  # type: ignore[attr-defined]
            "Radeis - Introduction",
            width=S.WIN_W,
            height=S.WIN_H,
            flags=flags,
        )
        self._window.position_x = self._open_x
        self._window.position_y = self._open_y
        self._window.frame.set_style({"background_color": S.CLR_WIN_BG})
        # Native X-close only hides the window (visible=False) — without this,
        # on_finish_fn (which reactivates the main panel) never fires, leaving
        # the main window dimmed/disabled forever. Same fix as the Setup
        # Wizard's equivalent X-close bug.
        self._window.set_visibility_changed_fn(  # type: ignore[attr-defined]
            lambda visible: None if visible else self._on_finish())

        with self._window.frame:
            with ui.VStack(spacing=0):  # type: ignore[attr-defined]
                self._build_accent_bar()
                self._content_frame = ui.Frame()  # type: ignore[attr-defined]
                self._footer_frame = ui.Frame(height=S.FOOTER_H)  # type: ignore[attr-defined]

        self._render()

    # ── Accent bar ───────────────────────────────────────────────────────────

    def _build_accent_bar(self) -> None:
        _stops = [
            0xFF00B976,
            0xFF08BC6E,
            0xFF10BF67,
            0xFF18C25F,
            0xFF20C558,
            0xFF28C850,
            0xFF30CA49,
            0xFF38CD41,
            0xFF40D03A,
            0xFF52CF30,
            0xFF64CE26,
            0xFF76CD1C,
            0xFF8ACC12,
            0xFF9ECB08,
            0xFFB2CA00,
            0xFFC4C800,
            0xFFD4B800,
            0xFFE4A800,
            0xFFF49800,
            0xFFFFc800,
        ]
        with ui.HStack(height=S.ACCENT_BAR_H, spacing=0):  # type: ignore[attr-defined]
            for clr in _stops:
                ui.Rectangle(style={"background_color": clr})  # type: ignore[attr-defined]

    # ── Render / navigate ────────────────────────────────────────────────────

    def _render(self) -> None:
        """Rebuild content and footer for the current slide index."""
        # Resize window to fit this slide's content (eliminates dead space)
        if self._window and self._current < len(S.WIN_H_SLIDES):
            self._window.height = S.WIN_H_SLIDES[self._current]

        # Content
        self._content_frame.clear()
        with self._content_frame:
            self._build_slide(self._current)

        # Footer
        self._footer_frame.clear()
        with self._footer_frame:
            self._build_footer_content()

    def _defer(self, fn: Callable) -> None:
        """Run fn AFTER the current omni.ui draw/event callback completes.

        omni.ui forbids clear()/addChild()/destroy() during an event or draw
        callback, so widget-tree mutations triggered from a button clicked_fn
        must be scheduled onto the next app update instead of run inline.
        """
        if not _UI_AVAILABLE:
            fn()
            return
        import omni.kit.app

        async def _run():
            try:
                await omni.kit.app.get_app().next_update_async()
                fn()
            except Exception:  # noqa: BLE001
                pass

        self._pending_task = asyncio.ensure_future(_run())

    def _go(self, direction: int) -> None:
        n = len(SLIDES)
        self._current = max(0, min(n - 1, self._current + direction))
        self._defer(self._render)

    def _on_finish(self) -> None:
        if self._on_finish_fn:
            try:
                self._on_finish_fn()
            except Exception:  # noqa: BLE001
                pass
        self._defer(self.destroy)

    # ── Footer ───────────────────────────────────────────────────────────────

    def _build_footer_content(self) -> None:
        is_last = self._current == len(SLIDES) - 1
        is_first = self._current == 0

        with ui.ZStack(height=S.FOOTER_H):  # type: ignore[attr-defined]
            ui.Rectangle(style={"background_color": S.CLR_CARD_BG})  # type: ignore[attr-defined]
            with ui.VStack(spacing=0):  # type: ignore[attr-defined]
                ui.Rectangle(height=1, style={"background_color": S.CLR_FOOTER_BORDER})  # type: ignore[attr-defined]
                ui.Spacer(height=9)  # type: ignore[attr-defined]
                with ui.HStack(height=36, spacing=0):  # type: ignore[attr-defined]
                    ui.Spacer(width=S.SIDE_PAD)  # type: ignore[attr-defined]
                    # Back button — only shown on slides 1 and 2 (not on first slide)
                    if not is_first:
                        back_style = {
                            "background_color": 0x00000000,
                            "border_width": 1,
                            "border_color": S.CLR_BTN_GHOST_BDR,
                            "border_radius": S.BTN_BORDER_RADIUS,
                            "color": S.CLR_BTN_GHOST_FG,
                            "font_size": S.FS_BTN,
                        }
                        btn_back = ui.Button("Back", width=120, height=36, style=back_style)  # type: ignore[attr-defined]
                        btn_back.set_clicked_fn(lambda: self._go(-1))

                    ui.Spacer()  # type: ignore[attr-defined]

                    # Right button: Next OR Finish
                    if is_last:
                        # Gradient button: stack gradient image behind transparent button
                        with ui.ZStack(width=200, height=36):  # type: ignore[attr-defined]
                            grad_path = self._png("btn_gradient.png")
                            if os.path.isfile(grad_path):
                                ui.Image(  # type: ignore[attr-defined]
                                    grad_path,
                                    width=200,
                                    height=36,
                                    fill_policy=ui.FillPolicy.STRETCH,  # type: ignore[attr-defined]
                                    style={"border_radius": S.BTN_BORDER_RADIUS},
                                )
                            else:
                                ui.Rectangle(style={  # type: ignore[attr-defined]
                                    "background_color": S.CLR_GREEN,
                                    "border_radius": S.BTN_BORDER_RADIUS,
                                })
                            btn_r = ui.Button(  # type: ignore[attr-defined]
                                "Start Robustness Test",
                                width=200,
                                height=36,
                                style={
                                    "background_color": 0x00000000,
                                    "border_radius": S.BTN_BORDER_RADIUS,
                                    "color": S.CLR_BTN_PRIMARY_FG,
                                    "font_size": S.FS_BTN,
                                },
                            )
                            btn_r.set_clicked_fn(self._on_finish)
                    else:
                        # Next button — moderate border_radius, explicit min-width for pill shape
                        btn_r = ui.Button(  # type: ignore[attr-defined]
                            "Next",
                            width=90,
                            height=36,
                            style={
                                "background_color": S.CLR_GREEN,
                                "border_radius": S.BTN_BORDER_RADIUS,
                                "color": S.CLR_BTN_PRIMARY_FG,
                                "font_size": S.FS_BTN,
                                "padding": 8,
                            },
                        )
                        btn_r.set_clicked_fn(lambda: self._go(1))
                    ui.Spacer(width=S.SIDE_PAD)  # type: ignore[attr-defined]
                ui.Spacer(height=9)  # type: ignore[attr-defined]

    # ── Slide content ─────────────────────────────────────────────────────────

    def _build_slide(self, idx: int) -> None:
        slide = SLIDES[idx]
        with ui.ZStack():  # type: ignore[attr-defined]
            ui.Rectangle(style={"background_color": S.CLR_CARD_BG})  # type: ignore[attr-defined]
            with ui.VStack(spacing=0):  # type: ignore[attr-defined]
                # Header row: asymmetric padding — 16px top, 10px bottom
                ui.Spacer(height=S.HEADER_PAD_TOP)  # type: ignore[attr-defined]
                self._build_header(idx)
                ui.Spacer(height=S.HEADER_PAD_BTM)  # type: ignore[attr-defined]
                with ui.HStack(spacing=0):  # type: ignore[attr-defined]
                    ui.Spacer(width=S.SIDE_PAD)  # type: ignore[attr-defined]
                    with ui.VStack(spacing=S.GAP):  # type: ignore[attr-defined]
                        self._build_counter_title(idx, slide)
                        self._build_body(slide)
                        if "features" in slide:
                            self._build_feature_list(slide["features"])
                        else:
                            self._build_visual(slide, idx)
                        self._build_caption(slide)
                    ui.Spacer(width=S.SIDE_PAD)  # type: ignore[attr-defined]
                ui.Spacer(height=S.CONTENT_PAD_BTM)  # type: ignore[attr-defined]

    # ── Header (tag + dots) ───────────────────────────────────────────────────

    def _build_header(self, idx: int) -> None:
        with ui.HStack(height=S.TAG_H, spacing=0):  # type: ignore[attr-defined]
            ui.Spacer(width=S.SIDE_PAD)  # type: ignore[attr-defined]
            # Section tag pill
            with ui.ZStack(width=92, height=S.TAG_H):  # type: ignore[attr-defined]
                ui.Rectangle(style={  # type: ignore[attr-defined]
                    "background_color": S.CLR_TAG_BG,
                    "border_radius": S.TAG_BORDER_RADIUS,
                    "border_width": 1,
                    "border_color": S.CLR_TAG_BORDER,
                })
                ui.Label(  # type: ignore[attr-defined]
                    _SECTION_TAGS[idx],
                    alignment=ui.Alignment.CENTER,  # type: ignore[attr-defined]
                    style={"color": S.CLR_GREEN, "font_size": S.FS_TAG},
                )
            ui.Spacer()  # type: ignore[attr-defined]
            # Progress dots
            with ui.HStack(spacing=6, width=0):  # type: ignore[attr-defined]
                for i in range(len(SLIDES)):
                    active = i == idx
                    dot_w = S.DOT_W_ACTIVE if active else S.DOT_W
                    clr = S.CLR_GREEN if active else S.CLR_DOT_INACTIVE
                    ui.Rectangle(  # type: ignore[attr-defined]
                        width=dot_w,
                        height=S.DOT_H,
                        style={
                            "background_color": clr,
                            "border_radius": S.DOT_H // 2,
                        },
                    )
            ui.Spacer(width=S.SIDE_PAD)  # type: ignore[attr-defined]

    # ── Counter + title ───────────────────────────────────────────────────────

    def _build_counter_title(self, idx: int, slide: dict) -> None:
        total = len(SLIDES)
        # Bold font style for title — falls back gracefully if font file missing
        title_style: dict = {"color": S.CLR_TITLE, "font_size": S.FS_TITLE}
        if os.path.isfile(S.FONT_BOLD):
            title_style["font"] = S.FONT_BOLD
        with ui.VStack(spacing=4):  # type: ignore[attr-defined]
            ui.Label(  # type: ignore[attr-defined]
                f"{idx + 1:02d} OF {total:02d}",
                height=14,
                style={"color": S.CLR_COUNTER, "font_size": S.FS_COUNTER},
            )
            ui.Label(  # type: ignore[attr-defined]
                slide["title"],
                height=0,
                word_wrap=True,
                style=title_style,
            )

    # ── Body text ─────────────────────────────────────────────────────────────

    def _build_body(self, slide: dict) -> None:
        ui.Label(  # type: ignore[attr-defined]
            slide["body"],
            word_wrap=True,
            height=0,
            style={"color": S.CLR_BODY, "font_size": S.FS_BODY},
        )

    # ── Visual placeholder / image ────────────────────────────────────────────

    def _build_visual(self, slide: dict, idx: int = 0) -> None:
        visual_h = S.VISUAL_H_SLIDE[idx] if idx < len(S.VISUAL_H_SLIDE) else S.VISUAL_H
        with ui.ZStack(height=visual_h):  # type: ignore[attr-defined]
            ui.Rectangle(style={  # type: ignore[attr-defined]
                "background_color": S.CLR_PLACEHOLDER_BG,
                "border_radius": 10,
                "border_width": 1,
                "border_color": S.CLR_PLACEHOLDER_BDR,
            })
            png = slide.get("png", "")
            if png:
                path = self._png(png)
                if os.path.isfile(path):
                    ui.Image(  # type: ignore[attr-defined]
                        path,
                        fill_policy=ui.FillPolicy.PRESERVE_ASPECT_FIT,  # type: ignore[attr-defined]
                    )

    # ── Feature list (slide 3) ────────────────────────────────────────────────

    def _build_feature_list(self, features: list) -> None:
        _ROW_H = 44  # compact row: (44-36)/2=4px top+bottom margin keeps icon centered
        feat_h = len(features) * _ROW_H + max(0, len(features) - 1) * 6
        feat_title_style: dict = {"color": S.CLR_TITLE, "font_size": S.FS_FEAT_TITLE}
        if os.path.isfile(S.FONT_BOLD):
            feat_title_style["font"] = S.FONT_BOLD
        with ui.Frame(height=feat_h):  # type: ignore[attr-defined]
            with ui.VStack(spacing=6):  # type: ignore[attr-defined]
                for feat in features:
                    with ui.ZStack(height=_ROW_H):  # type: ignore[attr-defined]
                        ui.Rectangle(style={  # type: ignore[attr-defined]
                            "background_color": S.CLR_FEATURE_ROW_BG,
                            "border_radius": 8,
                            "border_width": 1,
                            "border_color": S.CLR_FEATURE_BORDER,
                        })
                        with ui.HStack(height=_ROW_H, spacing=0):  # type: ignore[attr-defined]
                            ui.Spacer(width=12)  # type: ignore[attr-defined]
                            icon_path = self._icon(feat["icon"])
                            # Icon column: fixed-pixel spacers — reliable vertical centering regardless of parent
                            with ui.VStack(width=S.FEAT_ICON_W, spacing=0):  # type: ignore[attr-defined]
                                ui.Spacer(height=4)  # type: ignore[attr-defined]
                                with ui.ZStack(width=S.FEAT_ICON_W, height=S.FEAT_ICON_W):  # type: ignore[attr-defined]
                                    if os.path.isfile(icon_path):
                                        ui.Image(  # type: ignore[attr-defined]
                                            icon_path,
                                            width=S.FEAT_ICON_W,
                                            height=S.FEAT_ICON_W,
                                            fill_policy=ui.FillPolicy.PRESERVE_ASPECT_FIT,  # type: ignore[attr-defined]
                                        )
                                    else:
                                        ui.Rectangle(  # type: ignore[attr-defined]
                                            width=S.FEAT_ICON_W,
                                            height=S.FEAT_ICON_W,
                                            style={
                                                "background_color": 0xFF2A2A2A,
                                                "border_radius": 6,
                                            },
                                        )
                                ui.Spacer(height=4)  # type: ignore[attr-defined]
                            ui.Spacer(width=12)  # type: ignore[attr-defined]
                            # Text column: fixed-pixel spacers — reliable vertical centering regardless of parent
                            with ui.VStack(spacing=0):  # type: ignore[attr-defined]
                                ui.Spacer(height=4)  # type: ignore[attr-defined]
                                with ui.VStack(spacing=2):  # type: ignore[attr-defined]
                                    ui.Label(  # type: ignore[attr-defined]
                                        feat["title"],
                                        height=0,
                                        style=feat_title_style,
                                    )
                                    ui.Label(  # type: ignore[attr-defined]
                                        feat["desc"],
                                        height=0,
                                        word_wrap=False,
                                        style={
                                            "color": 0x73FFFFFF,
                                            "font_size": S.FS_FEAT_DESC,
                                        },
                                    )
                                ui.Spacer(height=4)  # type: ignore[attr-defined]
                            ui.Spacer(width=12)  # type: ignore[attr-defined]

    # ── Caption bar ───────────────────────────────────────────────────────────

    def _build_caption(self, slide: dict) -> None:
        with ui.HStack(height=S.CAPTION_H, spacing=0):  # type: ignore[attr-defined]
            # Green left accent stripe
            ui.Rectangle(  # type: ignore[attr-defined]
                width=3,
                style={"background_color": S.CLR_GREEN, "border_radius": 0},
            )
            # Caption body
            with ui.ZStack(height=S.CAPTION_H):  # type: ignore[attr-defined]
                ui.Rectangle(style={  # type: ignore[attr-defined]
                    "background_color": S.CLR_CAPTION_AREA_BG,
                    "border_radius": 0,
                })
                with ui.HStack(height=S.CAPTION_H, spacing=0):  # type: ignore[attr-defined]
                    ui.Spacer(width=14)  # type: ignore[attr-defined]
                    icon_path = self._icon(slide.get("icon", ""))
                    _badge_h = S.CAPTION_ICON_W + 8  # 32px
                    _margin = (S.CAPTION_H - _badge_h) // 2  # (56-32)//2 = 12px
                    # Icon column: fixed-pixel spacers — reliable vertical centering regardless of parent
                    with ui.VStack(width=_badge_h, spacing=0):  # type: ignore[attr-defined]
                        ui.Spacer(height=_margin)  # type: ignore[attr-defined]
                        with ui.ZStack(width=_badge_h, height=_badge_h):  # type: ignore[attr-defined]
                            ui.Rectangle(style={  # type: ignore[attr-defined]
                                "background_color": 0xFF1E2A1E,
                                "border_radius": 6,
                            })
                            # Center 24px icon inside 32px badge with fixed-pixel spacers
                            _icon_margin = (_badge_h - S.CAPTION_ICON_W) // 2  # (32-24)//2 = 4px
                            with ui.VStack(spacing=0):  # type: ignore[attr-defined]
                                ui.Spacer(height=_icon_margin)  # type: ignore[attr-defined]
                                with ui.HStack(height=S.CAPTION_ICON_W, spacing=0):  # type: ignore[attr-defined]
                                    ui.Spacer(width=_icon_margin)  # type: ignore[attr-defined]
                                    if slide.get("icon") and os.path.isfile(icon_path):
                                        ui.Image(  # type: ignore[attr-defined]
                                            icon_path,
                                            width=S.CAPTION_ICON_W,
                                            height=S.CAPTION_ICON_W,
                                            fill_policy=ui.FillPolicy.PRESERVE_ASPECT_FIT,  # type: ignore[attr-defined]
                                            style={"color": 0xFFE8E8E8},
                                        )
                                    else:
                                        if slide.get("icon"):
                                            import carb  # type: ignore[import]
                                            carb.log_warn(f"[radeis.onboarding] caption icon not found: {icon_path}")
                                    ui.Spacer(width=_icon_margin)  # type: ignore[attr-defined]
                                ui.Spacer(height=_icon_margin)  # type: ignore[attr-defined]
                        ui.Spacer(height=_margin)  # type: ignore[attr-defined]
                    ui.Spacer(width=10)  # type: ignore[attr-defined]
                    # Text column: fixed-pixel spacers — reliable vertical centering regardless of parent
                    with ui.VStack(spacing=0):  # type: ignore[attr-defined]
                        ui.Spacer(height=_margin)  # type: ignore[attr-defined]
                        with ui.VStack(spacing=2):  # type: ignore[attr-defined]
                            ui.Label(  # type: ignore[attr-defined]
                                slide.get("caption", ""),
                                height=0,
                                word_wrap=True,
                                style={
                                    "color": S.CLR_TITLE,
                                    "font_size": S.FS_CAPTION,
                                },
                            )
                            ui.Label(  # type: ignore[attr-defined]
                                slide.get("subcaption", ""),
                                height=0,
                                word_wrap=True,
                                style={
                                    "color": S.CLR_CAPTION_SUB,
                                    "font_size": S.FS_SUB,
                                },
                            )
                        ui.Spacer(height=_margin)  # type: ignore[attr-defined]
                    ui.Spacer(width=14)  # type: ignore[attr-defined]

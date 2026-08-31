"""Contact Us popup window — shown when the user clicks a coming-soon feature."""
from __future__ import annotations

import asyncio
from typing import Optional

import omni.ui as ui
from omni.ui import color as cl


# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------
PANEL_BG   = cl("#15181b")
FIELD_BG   = cl("#0d0f11")
DIVIDER    = cl("#202326")
ACCENT     = cl("#ff2d3e")
ACCENT_OK  = cl("#1f9d6b")
T_STRONG   = cl("#f2f4f6")
T_ROW      = cl("#e6e9ec")
T_BODY     = cl("#b9c0c7")
T_MUTED    = cl("#a2aab1")
T_EYEBROW  = cl("#9aa1a8")
FIELD_TEXT = cl("#e2e6ea")
WHITE      = cl("#ffffff")

CONTACT_URL_DISPLAY = "vicone.com/contact-us"
CONTACT_URL_FULL    = "https://vicone.com/contact-us/"

CAPS = [
    ("Load your own robot",
     "Import your robot model and run it directly."),
    ("Load your own scene, factory or environment",
     "Drop in your real operating world to test in context."),
    ("Use your own AI model",
     "Run your perception stack against live attacks."),
    ("Adversarial Scenario MCP-Driven Generation",
     "Generate patches, target signs, and test images through an MCP server, "
     "enabling your tools and agents to automate AI robustness validation "
     "end to end."),
]

# Sub-label heights (px): font_size=14, ~6–7 px/char, ~461 px content width.
# Short rows: 1 line; MCP row: 3 lines.
_CAP_SUB_H = [18, 18, 18, 54]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _btn_style(bg):
    return {"background_color": bg, "color": WHITE, "border_radius": 6,
            "font_size": 15, ":hovered": {"background_color": bg}}


def _on_copy(btn_holder):
    try:
        import omni.kit.clipboard
        omni.kit.clipboard.copy(CONTACT_URL_FULL)
    except Exception:  # noqa: BLE001
        pass
    btn = btn_holder["btn"]
    if btn:
        btn.text = "Copied!"
        btn.style = _btn_style(ACCENT_OK)
    if btn_holder.get("task"):
        btn_holder["task"].cancel()
    btn_holder["task"] = asyncio.ensure_future(_reset(btn_holder))


async def _reset(btn_holder):
    try:
        await asyncio.sleep(1.8)
    except asyncio.CancelledError:
        return
    btn = btn_holder["btn"]
    if btn:
        btn.text = "Copy link"
        btn.style = _btn_style(ACCENT)


def _cap_row(title, sub, sub_h=18):
    # Explicit heights prevent greedy-stretch from swallowing cap rows.
    # row_h = title(22) + VStack spacing(4) + sub(sub_h)
    row_h = 26 + sub_h
    with ui.HStack(spacing=11, height=row_h):
        ui.Label(">", width=16, alignment=ui.Alignment.LEFT_TOP,
                 style={"color": ACCENT, "font_size": 15})
        with ui.VStack(spacing=4, height=row_h):
            ui.Label(title, word_wrap=True, height=22,
                     style={"color": T_ROW, "font_size": 16})
            ui.Label(sub, word_wrap=True, height=sub_h,
                     style={"color": T_MUTED, "font_size": 14})
    ui.Spacer(height=8)
    ui.Line(height=1, alignment=ui.Alignment.H_CENTER,
            style={"color": DIVIDER, "border_width": 1})
    ui.Spacer(height=8)


# ---------------------------------------------------------------------------
# Build function
# ---------------------------------------------------------------------------

def build_contact_ui():
    btn_holder = {"btn": None, "task": None}
    with ui.ZStack():
        ui.Rectangle(style={"background_color": PANEL_BG})
        # Outer VStack: only explicit-height Spacers for top/bottom margins.
        # Do NOT use style={"margin_height": N} here — Kit cascades it to every
        # child Label/Line, inflating each item by 2×N pixels.
        with ui.VStack(spacing=0):
            ui.Spacer(height=22)
            # HStack carries horizontal margins; inner VStack holds all content.
            with ui.HStack(spacing=0):
                ui.Spacer(width=26)
                with ui.VStack(spacing=0):
                    # eyebrow row
                    with ui.HStack(height=17, spacing=8):
                        with ui.VStack(width=7):
                            ui.Spacer()
                            ui.Circle(width=7, height=7, radius=3,
                                      alignment=ui.Alignment.CENTER,
                                      size_policy=ui.CircleSizePolicy.FIXED,
                                      style={"background_color": ACCENT})
                            ui.Spacer()
                        # Same eyebrow as the Get in Touch form
                        # (get_in_touch_win.py::EYEBROW). The two are sibling
                        # windows opened from the same panel and now sit in
                        # the same place, so a different wordmark on each read
                        # as two different products.
                        ui.Label("LABR7 - RADEIS",
                                 alignment=ui.Alignment.LEFT_CENTER,
                                 style={"color": T_EYEBROW, "font_size": 12})
                    ui.Spacer(height=12)
                    # headline: spec says 2 lines — height=64 (2 × ~32 px/line at size 24)
                    ui.Label("Bring your own robot, scene, and AI model.",
                             word_wrap=True, height=64,
                             style={"color": T_STRONG, "font_size": 24})
                    ui.Spacer(height=8)
                    # subtitle: ~2 lines at font_size=16
                    ui.Label("And it goes further - a fully automated adversarial-patch "
                             "generation pipeline stress-tests your AI model at scale.",
                             word_wrap=True, height=40,
                             style={"color": T_BODY, "font_size": 16})
                    ui.Spacer(height=16)
                    ui.Line(height=1, alignment=ui.Alignment.H_CENTER,
                            style={"color": DIVIDER, "border_width": 1})
                    ui.Spacer(height=6)
                    for (title, sub), sub_h in zip(CAPS, _CAP_SUB_H):
                        _cap_row(title, sub, sub_h)
                    ui.Spacer(height=12)
                    # CTA caption: ~2 lines at font_size=14
                    ui.Label("Reach the LabR7 team for advanced features, more patches "
                             "& early access - copy the link and open it in your browser:",
                             word_wrap=True, height=38,
                             style={"color": T_MUTED, "font_size": 14})
                    ui.Spacer(height=9)
                    with ui.HStack(height=40, spacing=8):
                        with ui.ZStack():
                            ui.Rectangle(style={"background_color": FIELD_BG,
                                                "border_color": cl("#2b2f33"),
                                                "border_width": 1, "border_radius": 6})
                            with ui.HStack(style={"margin_width": 12}):
                                ui.Label(CONTACT_URL_DISPLAY,
                                         alignment=ui.Alignment.LEFT_CENTER,
                                         style={"color": FIELD_TEXT, "font_size": 15})
                        btn_holder["btn"] = ui.Button("Copy link", width=110,
                                                      clicked_fn=lambda: _on_copy(btn_holder),
                                                      style=_btn_style(ACCENT))
                    # Stretchy spacer absorbs remaining window height — keeps content
                    # top-aligned and prevents greedy distribution to other widgets.
                    ui.Spacer()
                ui.Spacer(width=26)
            ui.Spacer(height=22)


# ---------------------------------------------------------------------------
# Singleton facade (public API)
# ---------------------------------------------------------------------------

_INSTANCE: Optional["ContactUsWin"] = None


def show_contact_us() -> None:
    """Open (or focus) the Contact Us popup window."""
    global _INSTANCE
    if _INSTANCE is None or _INSTANCE._window is None:
        _INSTANCE = ContactUsWin()
    try:
        _INSTANCE._window.visible = True
        _INSTANCE._window.focus()
    except Exception:  # noqa: BLE001
        _INSTANCE = ContactUsWin()
        _INSTANCE._window.visible = True


class ContactUsWin:
    """Floating Contact Us window shown for coming-soon features."""

    def __init__(self):
        self._window: Optional[ui.Window] = None
        self._build()

    def _build(self):
        self._window = ui.Window(
            "Contact Us",
            width=540, height=600,
            flags=ui.WINDOW_FLAGS_NO_SCROLLBAR,
        )
        self._window.frame.set_build_fn(build_contact_ui)
        self._window.visible = False

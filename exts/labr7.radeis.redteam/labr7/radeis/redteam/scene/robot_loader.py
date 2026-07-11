"""
Robot preset button builders.

Shared square-button widgets used by window.py to render robot preset
and custom-robot buttons.
"""

import os
import omni.ui as ui

from ..constants import CLR_BTN, CLR_BORDER, CLR_WHITE, CLR_RED

# Shared button dimensions — imported by window.py
ROBOT_BTN_SIZE = 120   # square side length (px)
_ROBOT_IMG_SIZE = 80  # icon height inside the square (≈2× the old 44 px)
_ROBOT_CUSTOM_W = 28  # plus-button width (tall rectangle, same height)


# ---------------------------------------------------------------------------
# Shared GUI helpers (used by window.py)
# ---------------------------------------------------------------------------

def build_robot_preset_btn(preset: dict, on_click, selected: bool = False):
    """Build a single 92×92 square robot preset button.

    Returns the background Rectangle so callers can update border style on selection.
    """
    with ui.ZStack(width=ROBOT_BTN_SIZE, height=ROBOT_BTN_SIZE, style={"margin": 1.5}):
        rect = ui.Rectangle(
            style={"background_color": CLR_BTN, "border_radius": 4,
                   "border_width": 2 if selected else 1,
                   "border_color": CLR_RED if selected else CLR_BORDER})
        rect.set_mouse_pressed_fn(
            lambda x, y, b, m, r=rect: on_click() if b == 0 and r.enabled else None)
        # Single VStack: icon top, flexible gap, label pinned to bottom
        with ui.VStack(spacing=0):
            ui.Spacer(height=8)
            if os.path.isfile(preset["icon"]):
                ui.Image(preset["icon"], height=_ROBOT_IMG_SIZE,
                         fill_policy=ui.FillPolicy.PRESERVE_ASPECT_FIT)
            else:
                ui.Spacer(height=_ROBOT_IMG_SIZE)
            # ui.Spacer()  # pushes label to bottom
            ui.Label(preset["label"], alignment=ui.Alignment.CENTER,
                     style={"color": CLR_WHITE, "font_size": 12})
            # ui.Spacer(height=0)
    return rect


def build_robot_custom_btn(on_click):
    """Build the '+' custom robot button (28×92 tall rectangle, same height as presets).

    Returns the outer ZStack so callers can disable it (e.g. while a wizard is open).
    """
    _zstack = ui.ZStack(width=_ROBOT_CUSTOM_W, height=ROBOT_BTN_SIZE, style={"margin": 1.5})
    with _zstack:
        rect = ui.Rectangle(
            style={"background_color": CLR_BTN, "border_radius": 4,
                   "border_width": 1, "border_color": CLR_BORDER})
        rect.set_mouse_pressed_fn(
            lambda x, y, b, m: on_click() if b == 0 else None)
        with ui.VStack():
            ui.Spacer(height=35)
            ui.Label("+", alignment=ui.Alignment.CENTER,
                     style={"color": 0xFFAAAAAA, "font_size": 20})
            ui.Spacer(height=35)
    return _zstack

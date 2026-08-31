"""Robustness Report window.

Pure presentation: this module does NOT parse the raw red-team result dict.
window.py is responsible for computing the pre-shaped ``summary`` dict (see
``ReportWindow.show`` docstring for the exact contract) and calling
``ReportWindow.show(summary)``. This keeps all business logic (flip
counting, robustness math, recommendation text) in one place and this
module strictly about layout.

ASCII-only: the Isaac Sim UI font has no check mark, gear, middot, em-dash,
or curly-chevron glyphs — every literal string here uses ASCII equivalents
("x", "!", "-", " | ") even where the spec doc's prose uses the Unicode
originals.
"""
from __future__ import annotations

from typing import Callable, Optional

import omni.ui as ui

from . import radeis_ui as R


# ═══════════════════════════════════════════════════════════════════════════
# Local layout constants (report-window-only; not shared with other windows)
# ═══════════════════════════════════════════════════════════════════════════

_WIN_W = 640
_WIN_H = 760

_TILE_H = 64
_ROW_H = 26
_BAR_W = 90
_BAR_H = 8

_GREEN = R.CLR_SPEC_ONLINE_GREEN
_AMBER = R.CLR_SPEC_HINT_AMBER
_RED = R.CLR_SPEC_ACCENT_RED
_MUTED = R.CLR_SPEC_MUTED


def _grade_for(attack_success: float):
    """Return (label, color) for the risk-grade pill from a 0..1 fraction."""
    pct = (attack_success or 0.0) * 100.0
    if pct >= 60:
        return "HIGH RISK", _RED
    if pct >= 30:
        return "MODERATE", _AMBER
    return "LOW RISK", _GREEN


def _robustness_color(robustness: float):
    if robustness >= 0.75:
        return _GREEN
    if robustness >= 0.50:
        return _AMBER
    return _RED


class ReportWindow:
    """Floating 'Robustness Report' window shown when a test run completes.

    Pure presentation layer — construct once, call ``show(summary)`` each
    time a run completes; the frame is cleared and rebuilt so repeated runs
    always reflect the latest summary.
    """

    def __init__(self, on_download: Optional[Callable[[dict], None]] = None,
                 on_export: Optional[Callable[[dict], None]] = None):
        self._on_download = on_download
        self._on_export = on_export
        self._window: Optional[ui.Window] = None
        self._frame: Optional[ui.Frame] = None
        self._summary: Optional[dict] = None

    # ------------------------------------------------------------ public

    def show(self, summary: dict) -> None:
        """(Re)build the report body from ``summary`` and reveal the window.

        summary contract (all pre-computed by window.py):
            run_id: str, robot: str, model: str, n_signs: int, n_attacks: int,
            attack_success: float(0..1), signs_vulnerable: int,
            avg_conf_drop: float|None, median_latency_ms: float|None,
            signs: [{'sign': str, 'group': str, 'attacks': int, 'flips': int,
                     'robustness': float(0..1)}, ...],
            worst_sign: str, recommendation: str, index_path: str
        """
        self._summary = summary
        if self._window is None:
            self._window = ui.Window(
                "Robustness Report",
                width=_WIN_W, height=_WIN_H,
                flags=ui.WINDOW_FLAGS_NO_SCROLLBAR,
            )
            self._window.frame.set_style(R.STYLE_WINDOW_FRAME)
            with self._window.frame:
                self._frame = ui.Frame()
        self._rebuild(summary)
        self._window.visible = True
        self._window.focus()

    def hide(self) -> None:
        if self._window:
            self._window.visible = False

    def destroy(self) -> None:
        if self._window:
            self._window.destroy()
            self._window = None
        self._frame = None

    # ----------------------------------------------------------- private

    def _rebuild(self, summary: dict) -> None:
        if self._frame is None:
            return
        self._frame.clear()
        with self._frame:
            with ui.ScrollingFrame(
                horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
            ):
                with ui.VStack(spacing=10, style={"margin": 14}):
                    self._build_title_block(summary)
                    self._build_grade_pill(summary)
                    self._build_metric_tiles(summary)
                    self._build_sign_table(summary)
                    self._build_recommendation(summary)
                    self._build_actions(summary)

    # ── 1. Title / meta ──────────────────────────────────────────────────

    def _build_title_block(self, summary: dict) -> None:
        run_id = summary.get("run_id", "-")
        robot = summary.get("robot", "-")
        model = summary.get("model", "-")
        n_signs = summary.get("n_signs", 0)
        n_attacks = summary.get("n_attacks", 0)

        with ui.VStack(spacing=4):
            ui.Label("Robustness Report", height=22,
                     style={"color": R.COLOR_TEXT_PRIMARY, "font_size": 17})
            ui.Label(f"localhost:8899/report/{run_id}", height=16,
                     style={"color": _MUTED, "font_size": R.FONT_DESCRIPTION})
            meta = (f"{run_id} . {robot} . {model} . "
                    f"{n_signs} signs . {n_attacks} attacks")
            ui.Label(meta, height=16,
                     style={"color": _MUTED, "font_size": R.FONT_DESCRIPTION})

    # ── 2. Risk-grade pill ───────────────────────────────────────────────

    def _build_grade_pill(self, summary: dict) -> None:
        label, color = _grade_for(summary.get("attack_success", 0.0))
        with ui.HStack(height=26):
            with ui.ZStack(width=0, height=24):
                ui.Rectangle(style={
                    "background_color": 0x22000000,
                    "border_radius": 11,
                    "border_width": 1,
                    "border_color": color,
                })
                ui.Label("  " + label + "  ",
                         style={"color": color, "font_size": R.FONT_STATUS_PILL},
                         alignment=ui.Alignment.CENTER)
            ui.Spacer()

    # ── 3. Metric tiles ──────────────────────────────────────────────────

    def _build_metric_tiles(self, summary: dict) -> None:
        attack_success = summary.get("attack_success", 0.0)
        signs_vulnerable = summary.get("signs_vulnerable", 0)
        n_signs = summary.get("n_signs", 0)
        avg_conf_drop = summary.get("avg_conf_drop")
        median_latency_ms = summary.get("median_latency_ms")

        conf_drop_text = (f"{avg_conf_drop * 100:.0f}%"
                           if avg_conf_drop is not None else "-")
        latency_text = (f"{median_latency_ms:.0f}ms"
                         if median_latency_ms is not None else "-")

        tiles = [
            ("ATTACK SUCCESS", f"{attack_success * 100:.0f}%"),
            ("SIGNS VULNERABLE", f"{signs_vulnerable}/{n_signs}"),
            ("AVG CONF DROP", conf_drop_text),
            ("MEDIAN LATENCY", latency_text),
        ]
        with ui.HStack(height=_TILE_H, spacing=8):
            for key, value in tiles:
                with ui.ZStack():
                    ui.Rectangle(style=R.STYLE_CARD)
                    with ui.VStack(style={"margin": 10}, spacing=4):
                        ui.Label(key, height=14,
                                 style={"color": _MUTED,
                                        "font_size": R.FONT_WIZARD_SMALL})
                        ui.Label(value, height=26,
                                 style={"color": R.COLOR_TEXT_PRIMARY,
                                        "font_size": R.FONT_CARD_TITLE})
                        ui.Spacer()

    # ── 4. Per-sign breakdown table ──────────────────────────────────────

    def _build_sign_table(self, summary: dict) -> None:
        signs = summary.get("signs") or []
        with ui.ZStack():
            ui.Rectangle(style=R.STYLE_CARD)
            with ui.VStack(style={"margin": 12}, spacing=6):
                ui.Label("PER-SIGN BREAKDOWN", height=14,
                          style={"color": _MUTED,
                                 "font_size": R.FONT_WIZARD_SMALL})
                # header row
                with ui.HStack(height=_ROW_H, spacing=6):
                    ui.Label("Sign", style={"color": _MUTED,
                                             "font_size": R.FONT_DESCRIPTION})
                    ui.Label("Group", width=90,
                             style={"color": _MUTED, "font_size": R.FONT_DESCRIPTION})
                    ui.Label("Attacks", width=60,
                             style={"color": _MUTED, "font_size": R.FONT_DESCRIPTION})
                    ui.Label("Flips", width=50,
                             style={"color": _MUTED, "font_size": R.FONT_DESCRIPTION})
                    ui.Label("Robustness", width=_BAR_W + 46,
                             style={"color": _MUTED, "font_size": R.FONT_DESCRIPTION})
                ui.Line(height=1, style={"color": R.COLOR_BORDER, "border_width": 1})
                if not signs:
                    ui.Label("No sign data for this run.", height=_ROW_H,
                              style={"color": _MUTED, "font_size": R.FONT_DESCRIPTION})
                for row in signs:
                    self._build_sign_row(row)

    def _build_sign_row(self, row: dict) -> None:
        sign = row.get("sign", "-")
        group = row.get("group", "-")
        attacks = row.get("attacks", 0)
        flips = row.get("flips", 0)
        robustness = row.get("robustness", 0.0)
        color = _robustness_color(robustness)
        frac = max(0.0, min(1.0, robustness))

        with ui.HStack(height=_ROW_H, spacing=6):
            ui.Label(sign, style={"color": R.COLOR_TEXT_SECONDARY,
                                   "font_size": R.FONT_DESCRIPTION})
            ui.Label(group, width=90,
                     style={"color": R.COLOR_TEXT_SECONDARY, "font_size": R.FONT_DESCRIPTION})
            ui.Label(str(attacks), width=60,
                     style={"color": R.COLOR_TEXT_SECONDARY, "font_size": R.FONT_DESCRIPTION})
            ui.Label(str(flips), width=50,
                     style={"color": R.COLOR_TEXT_SECONDARY, "font_size": R.FONT_DESCRIPTION})
            with ui.HStack(width=_BAR_W + 46, spacing=6):
                with ui.ZStack(width=_BAR_W, height=_BAR_H):
                    ui.Rectangle(style={"background_color": R.COLOR_BORDER,
                                         "border_radius": 3})
                    with ui.HStack():
                        ui.Rectangle(width=ui.Fraction(frac),
                                     style={"background_color": color,
                                            "border_radius": 3})
                        if frac < 1.0:
                            ui.Spacer(width=ui.Fraction(1.0 - frac))
                ui.Label(f"{robustness * 100:.0f}%", width=36,
                         style={"color": color, "font_size": R.FONT_DESCRIPTION})

    # ── 5. Recommendation ────────────────────────────────────────────────

    def _build_recommendation(self, summary: dict) -> None:
        attack_success = summary.get("attack_success", 0.0)
        color = _GREEN if attack_success < 0.30 else _RED
        recommendation = summary.get("recommendation", "")
        with ui.ZStack(height=60):
            ui.Rectangle(style=R.STYLE_CARD)
            with ui.HStack():
                ui.Rectangle(width=3, style={"background_color": color})
                with ui.VStack(style={"margin": 10}, spacing=2):
                    ui.Label("RECOMMENDATION", height=14,
                              style={"color": _MUTED, "font_size": R.FONT_WIZARD_SMALL})
                    ui.Label(recommendation, word_wrap=True,
                              style={"color": R.COLOR_TEXT_PRIMARY,
                                     "font_size": R.FONT_BODY})

    # ── 6. Actions ───────────────────────────────────────────────────────

    def _build_actions(self, summary: dict) -> None:
        with ui.HStack(height=R.HEIGHT_BTN_SECONDARY, spacing=8):
            ui.Spacer()
            R.secondary_button("Download PDF", self._handle_download,
                                width=140)
            R.secondary_button("Export JSON", self._handle_export,
                                width=140)

    def _handle_download(self) -> None:
        if self._on_download is not None and self._summary is not None:
            self._on_download(self._summary)

    def _handle_export(self) -> None:
        if self._on_export is not None and self._summary is not None:
            self._on_export(self._summary)

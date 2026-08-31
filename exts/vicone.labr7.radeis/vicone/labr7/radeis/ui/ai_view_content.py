"""Text content definitions for the AI Perception View panels.

Pure data module — no omni.ui imports. Each factory function returns a list
of Line objects; each Line carries a text string and an ABGR color integer.
Callers (ai_percept_win.py, window.py) pass these lists to the panel
rendering API.

Color values are ABGR integers that match the radeis_ui / constants palette.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .. import constants as C


MAX_PANEL_LINES = 10

# ── Color constants (ABGR, alpha=FF = fully opaque) ───────────────────────────
CLR_LABEL     = 0xFFFFFFFF   # white: field labels
CLR_NEUTRAL   = 0xFFFFFFFF   # white: normal text
CLR_MUTED     = 0xFFA8A8A8   # light gray: less important values
CLR_BASELINE  = 0xFF4ADE80   # green #80DE4A in ABGR: baseline action -- unified with
                             # constants.CLR_OK / radeis_ui.COLOR_STATUS_OK per issue #50
CLR_UNCHANGED = 0xFF4ADE80   # green #80DE4A in ABGR: UNCHANGED state (same unification)
CLR_CHANGED   = 0xFF5C5CFF   # red #FF5C5C in ABGR: CHANGED state
CLR_WARNING   = C.CLR_WARN   # amber #4DC4FF in ABGR: warning states -- issue #50's
                             # unification wrongly repointed this at error-red; restored to
                             # the shared amber (constants.CLR_WARN / radeis_ui.COLOR_STATUS_WARN)
                             # so "warning/in-progress" no longer reads as "error"
CLR_RUNNING   = CLR_WARNING  # amber (same as CLR_WARNING) for "running" status text


@dataclass
class Span:
    """One colored segment within a mixed-color line."""
    text: str
    color: int = CLR_NEUTRAL


@dataclass
class Line:
    """One line of text in an AI Perception panel.

    text      — the string shown on this line.
    color     — ABGR integer; default is CLR_NEUTRAL (white).
    spans     — optional list of Span objects for mixed-color rendering.
    font_size — optional override; None uses the panel default font size.
    """
    text: str
    color: int = CLR_NEUTRAL
    spans: Optional[List[Span]] = None
    font_size: Optional[int] = None

    @classmethod
    def multispan(cls, spans: List[Span]) -> "Line":
        joined = "".join(s.text for s in spans)
        return cls(text=joined, color=CLR_NEUTRAL, spans=list(spans))


# ── Left panel ────────────────────────────────────────────────────────────────

def left_panel_lines(
    sign_name: Optional[str],
    st_idx: Optional[int],
    n_stations: Optional[int],
    station_label: Optional[str],
    run_state: Optional[str],
    bl_action: Optional[str],
    run_idx: Optional[int] = None,
    n_runs: Optional[int] = None,
) -> List[Line]:
    """Produce rows for the left (context) panel.

    Order: header (Test Progress + run/station inline), Sign, [spacer], Status, Baseline.
    """
    rows = []

    # Row 0: "Test Progress" (muted) + " - Run: X of Y | Station: Z of W | Sign: ..." (white)
    has_run     = run_idx is not None and n_runs is not None
    has_station = st_idx is not None and n_stations is not None
    parts = []
    if has_run:
        parts.append(f"Run: {run_idx} of {n_runs}")
    if has_station:
        parts.append(f"Station: {st_idx + 1} of {n_stations}")
    parts.append(f"Sign: {sign_name if sign_name else 'Waiting'}")
    suffix = (" - " + "  |  ".join(parts)) if parts else ""
    rows.append(Line.multispan([
        Span("Test Progress", CLR_MUTED),
        Span(suffix, CLR_NEUTRAL),
    ]))

    # Row 1: Baseline action
    bl_clr = CLR_BASELINE if bl_action else CLR_MUTED
    _bl_line = Line.multispan([
        Span("Baseline behavior:  ", CLR_LABEL),
        Span(bl_action if bl_action else "Pending", bl_clr),
    ])
    _bl_line.font_size = 17
    rows.append(_bl_line)

    # Rows 2–5: spacers to push Status down
    for _ in range(4):
        rows.append(Line(" ", CLR_NEUTRAL))

    # Status — value text uses amber (CLR_RUNNING)
    if run_state:
        rows.append(Line.multispan([
            Span("Status:  ", CLR_LABEL),
            Span(run_state, CLR_RUNNING),
        ]))

    return rows


# ── Right panel ───────────────────────────────────────────────────────────────

def right_panel_lines(
    bl_action: Optional[str],
    action: Optional[str],
    confidence_text: Optional[str],
    infer_ms: Optional[float],
    *,
    is_baseline: bool = False,
    has_result: bool = True,
    is_running: bool = False,
    is_waiting: bool = False,
) -> List[Line]:
    """Produce exactly 3 rows for the right (result) panel.

    Row 1: Change status line.
    Row 2: Confidence.
    Row 3: Inference time.
    """
    # Row 1 — Behavior line
    if is_waiting:
        row1 = Line.multispan([
            Span("Behavior:  ", CLR_LABEL),
            Span("Waiting", CLR_MUTED),
        ])
        row1.font_size = 17
    elif is_running:
        row1 = Line.multispan([
            Span("Behavior:  ", CLR_LABEL),
            Span("Running", CLR_MUTED),
        ])
        row1.font_size = 17
    elif not has_result:
        row1 = Line.multispan([
            Span("Behavior:  ", CLR_LABEL),
            Span("NO RESULT", CLR_CHANGED),
        ])
        row1.font_size = 17
    elif is_baseline:
        row1 = Line.multispan([
            Span("Behavior:  ", CLR_LABEL),
            Span("BASELINE", CLR_UNCHANGED),
            Span("  [", CLR_NEUTRAL),
            Span(action if action else "?", CLR_BASELINE),
            Span("]", CLR_NEUTRAL),
        ])
        row1.font_size = 17
    elif action == bl_action:
        row1 = Line.multispan([
            Span("Behavior:  ", CLR_LABEL),
            Span("ROBUST", CLR_UNCHANGED),
            Span("  [", CLR_NEUTRAL),
            Span(action if action else "?", CLR_UNCHANGED),
            Span("  ->  ", CLR_NEUTRAL),
            Span(action if action else "?", CLR_UNCHANGED),
            Span("]", CLR_NEUTRAL),
        ])
        row1.font_size = 17
    else:
        row1 = Line.multispan([
            Span("Behavior:  ", CLR_LABEL),
            Span("VULNERABLE", CLR_CHANGED),
            Span("  [", CLR_NEUTRAL),
            Span(bl_action if bl_action else "?", CLR_BASELINE),
            Span("  ->  ", CLR_NEUTRAL),
            Span(action if action else "?", CLR_CHANGED),
            Span("]", CLR_NEUTRAL),
        ])
        row1.font_size = 17

    # Row 2 — Confidence
    conf_str = confidence_text if confidence_text else "unavailable"
    conf_clr = CLR_NEUTRAL if confidence_text else CLR_MUTED
    row2 = Line.multispan([
        Span("Confidence:  ", CLR_LABEL),
        Span(conf_str, conf_clr),
    ])

    # Row 3 — Inference time
    time_str = f"{infer_ms:.0f} ms" if infer_ms is not None else "unavailable"
    row3 = Line.multispan([
        Span("Inference time:  ", CLR_LABEL),
        Span(time_str, CLR_MUTED),
    ])

    header = Line.multispan([Span("Inference Summary - Does the behavior change?", CLR_MUTED)])
    spacers = [Line(" ", CLR_NEUTRAL)] * 3
    return [header, row1, *spacers, row2, row3]


# ── Helper factories ──────────────────────────────────────────────────────────

def status_idle() -> List[Line]:
    """Left panel initial state before any run starts."""
    return left_panel_lines(None, None, None, None, None, None)


def status_stopped() -> List[Line]:
    """Shown when the user presses Stop."""
    return [Line("Stopped by user", CLR_WARNING)]


def right_panel_idle() -> List[Line]:
    """Right panel initial state before any run starts."""
    return right_panel_lines(None, None, None, None, is_waiting=True)


def right_panel_running() -> List[Line]:
    """Right panel state while inference is in progress."""
    return right_panel_lines(None, None, None, None, is_running=True)


# ── reasoning_from_rec ────────────────────────────────────────────────────────

def reasoning_from_rec(
    rec: Optional[dict],
    station_idx: int,
    baseline_rec: Optional[dict] = None,
    display_sign_name: str = "",
    station_label: str = "",
) -> List[Line]:
    """Dispatch to right_panel_lines from a raw inference record.

    Args:
        rec:               The inference record dict from RedTeamSession.run_inference.
        station_idx:       0 = baseline; 1+ = attack station.
        baseline_rec:      Station-0 record for this sign (used for attack comparison).
        display_sign_name: Human-readable sign name (unused in right panel, kept for API compat).
        station_label:     Human-readable station label (unused in right panel, kept for API compat).
    """
    bl_action = (
        baseline_rec["action_token"]
        if baseline_rec
        and not baseline_rec.get("error")
        and baseline_rec.get("action_token") is not None
        else None
    )
    infer_ms = rec.get("infer_ms") if rec else None

    if rec is None or rec.get("error") or rec.get("action_token") is None:
        return right_panel_lines(bl_action, None, None, infer_ms, has_result=False)

    action = rec["action_token"]
    logit_margin = rec.get("logit_margin") or 0.0
    confidence_text = f"{int(logit_margin * 100)}%"

    return right_panel_lines(
        bl_action=bl_action,
        action=action,
        confidence_text=confidence_text,
        infer_ms=infer_ms,
        is_baseline=(station_idx == 0),
    )

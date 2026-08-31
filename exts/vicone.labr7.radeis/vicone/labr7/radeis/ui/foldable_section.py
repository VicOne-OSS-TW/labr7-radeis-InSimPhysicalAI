"""foldable_section.py — the ONE validated foldable-card mechanism for the Radeis panel.

This encapsulates, verbatim, the fold/unfold mechanism that section 1 of
window.py shipped with, CONFIRMED WORKING by a real mouse click in the live
Isaac Sim app. Several plausible-looking alternatives were tried live and
FAILED.

HARD CONSTRAINTS — validated live, do NOT "improve" on them:
  * The outer card ZStack gets an EXPLICIT pixel height at construction
    (header + body_height) and that number is mutated directly on toggle.
    omni.ui does NOT recompute this ZStack's box from a child's .visible
    flip or a child Frame rebuild after the first layout pass (the card
    background Rectangle sibling has no height of its own).
  * body_height is a HAND-COMPUTED constant: sum of the body's own explicit
    row heights plus (n_top_level_items - 1) * BODY_SPACING gaps. Never
    measured at runtime.
  * toggle() does ALL THREE of: flip arrow text, flip body .visible, set
    card ZStack .height. Each one alone was tried live and did NOT visually
    resize the card.
  * ASCII-only fold arrow: "v" expanded / ">" collapsed. The Isaac Sim UI
    font lacks Unicode triangle glyphs (silently renders "?").
  * NEVER ui.CollapsableFrame (separate documented silent-failure incident
    in this codebase). NEVER a nested ui.Frame + rebuild() for folding.
"""
from __future__ import annotations

import weakref
from typing import Callable, Optional

import omni.ui as ui

from . import radeis_ui as R

# Hover tint for the header strip — same literal section 1 shipped with
# (matches the wizard-card hover idiom). Fold-specific, so it lives here,
# not in radeis_ui.
_HEADER_HOVER_BG = 0xFF3A3A3A

# Spacing of the body VStack. Every _SN_BODY_HEIGHT constant in window.py is
# computed assuming exactly this value; change one only with the other.
BODY_SPACING = 2

# ~7.7px/char at font_size 12 (same ratio window.py's own _trunc() helper uses
# to keep omni.ui from letting a long Label grow its container) — status_label
# has a fixed R.WIDTH_SECTION_STATUS_TEXT box, so text longer than this must be
# truncated rather than left to overflow/expand the header. Kept in sync with
# R.WIDTH_SECTION_STATUS_TEXT (issue #32: 150px -> ~19 chars).
_STATUS_TEXT_MAX_CHARS = 19


def _truncate_status(text: str) -> str:
    """Middle-ellipsis truncation (keep head + tail) rather than trailing
    "..." — for status text like "Connected . gemma-4-e2b-it" the head alone
    ("Connected . g...") loses the one piece of information (the model name)
    the wider box exists to show; keeping both ends preserves a readable
    fragment of the model name. The full string is always available via the
    label's tooltip (see set_status())."""
    if len(text) <= _STATUS_TEXT_MAX_CHARS:
        return text
    # 3 chars for the "..." itself; split the remaining budget across head/tail.
    keep = _STATUS_TEXT_MAX_CHARS - 3
    head = (keep + 1) // 2
    tail = keep - head
    return text[:head] + "..." + (text[-tail:] if tail else "")


class FoldableSection:
    """One foldable card section: card ZStack > [bg Rectangle, VStack(header ZStack, body VStack)].

    Public attributes available after build():
      card_zstack      outer ui.ZStack — explicit height, mutated on toggle.
                       Re-enter it (``with sec.card_zstack:``) to append a
                       section-specific grayout overlay Rectangle as the
                       LAST child; that overlay is deliberately NOT part of
                       this class (it is run/build-state graying, unrelated
                       to folding).
      header_zstack    header strip (mouse handlers attached to it)
      header_bg_rect   header background Rectangle (hover restyling)
      title_label      the title ui.Label — window.py mutates
                       self._run_section_header_label.text at runtime, so
                       this must stay reachable
      fold_arrow_label ASCII "v"/">" indicator
      body_vstack      ui.VStack(spacing=BODY_SPACING); NO explicit height —
                       the fixed-size card_zstack is what controls the box
      extra_widget     whatever extra_header_fn returned (e.g. the Setup
                       Wizard button), or None
      collapsed        bool fold state (starts False — expanded)
    """

    def __init__(self, title: str, body_height: int):
        """title: passed to the Label VERBATIM — include the 4-space leading
        indent yourself (e.g. "    2 · Model Under Test"), exactly like the
        existing inline headers, so section 4's external
        ``.text = "    4. Run"`` mutation stays consistent.
        body_height: the hand-computed natural body content height constant.
        """
        self.title = title
        self.body_height = int(body_height)
        self.collapsed = False  # all sections start expanded
        self.card_zstack: Optional[ui.ZStack] = None
        self.header_zstack: Optional[ui.ZStack] = None
        self.header_bg_rect: Optional[ui.Rectangle] = None
        self.title_label: Optional[ui.Label] = None
        self.fold_arrow_label: Optional[ui.Label] = None
        self.body_vstack: Optional[ui.VStack] = None
        self.extra_widget = None
        self.status_label: Optional[ui.Label] = None
        self.status_dot: Optional[ui.Circle] = None

    # ------------------------------------------------------------ build
    def build(self,
              build_body_fn: Callable[[], None],
              extra_header_fn: Optional[Callable[[], object]] = None,
              with_status: bool = False) -> "FoldableSection":
        """Create the card in the CURRENT omni.ui container scope.

        build_body_fn:   called once inside the body VStack(spacing=2);
                         creates the body rows (existing body code moved
                         as-is). It runs as a bound method of the window, so
                         all self._xyz widget assignments keep working.
        extra_header_fn: optional; called inside the header HStack, right after
                         the title label and before the stretch Spacer
                         (section 2's Setup Wizard button) — sits next to the
                         title, not pushed to the far right. MUST return the
                         widget it created — used for the press hit-test so
                         clicking the button never also folds the section.
                         The caller stores its own reference
                         (self._wizard_btn = ...) before returning it.
        with_status:     optional; when True, inserts a status word Label
                         (self.status_label) into the header, after the
                         stretch Spacer and before the fold arrow — i.e.
                         pinned to the right edge of the header. Non-
                         interactive (no hit-test change needed). Mutate it
                         via set_status() after build(). (issue #19: the
                         completion dot that used to sit beside this label
                         was removed — the colored status text alone now
                         carries the state meaning. self.status_dot remains
                         a None-guarded attribute for compatibility.)
        """
        # Weakref, not self, in the widget lambdas: widget -> lambda -> self
        # -> widget is a cycle invisible to omni.ui's C++ side (same _w
        # pattern window.py already uses). The window holds the strong ref
        # to this instance (self._sN_fold), keeping the weakref alive.
        _ref = weakref.ref(self)
        self.card_zstack = ui.ZStack(
            height=R.HEIGHT_SECTION_HEADER + self.body_height)
        with self.card_zstack:
            # Card background — must stay a plain sibling inside this same
            # ZStack; it has no height of its own, the ZStack's explicit
            # height is what sizes it.
            ui.Rectangle(style=R.STYLE_CARD)
            with ui.VStack(spacing=0):
                # Foldable header (do not replace with ui.CollapsableFrame —
                # see module docstring)
                self.header_zstack = ui.ZStack(height=R.HEIGHT_SECTION_HEADER)
                with self.header_zstack:
                    self.header_bg_rect = ui.Rectangle(
                        style={"background_color": R.COLOR_SECTION_HEADER_BG})
                    with ui.HStack():
                        ui.Rectangle(width=R.WIDTH_ACCENT_BAR,
                                     style={"background_color": R.COLOR_ACCENT})
                        self.title_label = ui.Label(
                            self.title,
                            style={"color": R.COLOR_TEXT_PRIMARY,
                                   "font_size": R.FONT_SECTION_TITLE},
                            alignment=ui.Alignment.LEFT_CENTER)
                        if extra_header_fn is not None:
                            ui.Spacer(width=8)
                            self.extra_widget = extra_header_fn()
                        ui.Spacer()
                        # Right-hand cluster (status dot/text + fold arrow) is
                        # wrapped in ONE fixed-width HStack so it behaves as a
                        # single atomic, non-stretchable block. Without this,
                        # `ui.Spacer(width=N)` was measured live to act as a
                        # FLOOR, not a fixed size — it (and the bare stretch
                        # Spacer() above) both silently absorb slack whenever
                        # this row's total content is shorter than the
                        # available width, so the small width=3 gap between
                        # status and arrow ballooned by 50+px on sections with
                        # a short title, throwing the status box's position
                        # out of alignment between sections even though its
                        # own width was fixed. Locking this cluster's outer
                        # box to an explicit width stops the parent row from
                        # ever redistributing slack into it — only the single
                        # bare Spacer() above remains genuinely flexible.
                        _right_cluster_w = 24 + 6
                        if with_status:
                            _right_cluster_w += R.WIDTH_SECTION_STATUS_TEXT + 3
                        # style={"margin": 0} on this cluster HStack AND on every
                        # wrapper/leaf inside it: window.py's root content VStack
                        # applies R.STYLE_MAIN_OUTER_VSTACK = {"margin": 1}
                        # (radeis_ui.py) and that untyped "margin" key cascades
                        # down through every descendant container by default in
                        # this Kit build, silently inflating each nested wrapper
                        # Stack here (dot wrapper, gap Spacer, label wrapper) by
                        # ~1px per side. Re-declaring style={"margin": 0} at this
                        # cluster (nearest ancestor) stops the cascade from
                        # reaching everything below it, so computed_width matches
                        # _right_cluster_w exactly and the dot/label gap equals
                        # this section's declared Spacer width (2px) instead of
                        # being floored at ~4px.
                        with ui.HStack(width=_right_cluster_w, style={"margin": 0}):
                            if with_status:
                                # Status dot removed (issue #19): the colored
                                # status text already carries the state
                                # meaning, so no leading dot/gap is built here
                                # anymore. self.status_dot stays None; all its
                                # uses (set_status()) are None-guarded.
                                with ui.VStack(height=R.HEIGHT_SECTION_HEADER, spacing=0,
                                                style={"margin": 0}):
                                    ui.Spacer(height=(R.HEIGHT_SECTION_HEADER - 16) // 2)
                                    self.status_label = ui.Label(
                                        "", width=R.WIDTH_SECTION_STATUS_TEXT, height=16,
                                        style={"color": R.CLR_SPEC_ACCENT_RED,
                                               "font_size": R.FONT_DESCRIPTION,
                                               "margin": 0},
                                        alignment=ui.Alignment.RIGHT_CENTER)
                                    ui.Spacer(height=(R.HEIGHT_SECTION_HEADER - 16) // 2)
                                ui.Spacer(width=3, style={"margin": 0})
                            # ASCII-only fold indicator ("v" expanded /
                            # ">" collapsed) — see module docstring
                            self.fold_arrow_label = ui.Label(
                                ">" if self.collapsed else "v", width=24,
                                style={"color": R.COLOR_TEXT_PRIMARY,
                                       "font_size": R.FONT_SECTION_TITLE},
                                alignment=ui.Alignment.CENTER)
                            ui.Spacer(width=6)
                self.header_zstack.set_mouse_pressed_fn(
                    lambda x, y, b, m, _ref=_ref:
                        _ref() and _ref()._on_header_pressed(x, y, b))
                self.header_zstack.set_mouse_hovered_fn(
                    lambda h, _ref=_ref: _ref() and _ref()._set_header_hover(h))
                # Body — NO explicit height on this VStack; the fixed-size
                # card ZStack around it controls the box.
                self.body_vstack = ui.VStack(spacing=BODY_SPACING)
                with self.body_vstack:
                    build_body_fn()
        return self

    # ----------------------------------------------------------- toggle
    def _on_header_pressed(self, x: float, y: float, button: int):
        """Click on the header strip: fold/unfold (left button only)."""
        if button != 0:
            return
        # Defensive hit-test: if the press landed on the embedded extra
        # header widget (Setup Wizard button), its own clicked_fn owns that
        # click — folding on the same click would be wrong regardless of
        # whether omni.ui propagates the press to this ZStack. x/y and
        # screen_position_* are both screen-space. Guard never fires when
        # there is no extra widget, so sections 1/3/4/5 keep the exact
        # validated section-1 behavior.
        w = self.extra_widget
        if w is not None:
            try:
                if (w.screen_position_x <= x <= w.screen_position_x + w.computed_width
                        and w.screen_position_y <= y <= w.screen_position_y + w.computed_height):
                    return
            except Exception:  # noqa: BLE001 — never let the guard break folding
                pass
        self.toggle()

    def toggle(self):
        """ALL THREE mutations are required together — validated live in
        Isaac Sim; any subset updates its own state but does NOT visually
        resize the card (see module docstring)."""
        self.collapsed = not self.collapsed
        self.fold_arrow_label.text = ">" if self.collapsed else "v"
        self.body_vstack.visible = not self.collapsed
        # Explicit height, not auto-sizing: the card ZStack does not
        # recompute its box from a child's .visible flip.
        self.card_zstack.height = ui.Pixel(
            R.HEIGHT_SECTION_HEADER if self.collapsed
            else R.HEIGHT_SECTION_HEADER + self.body_height)

    def _set_header_hover(self, hovered: bool):
        """Subtle hover cue on the header strip (wizard-card idiom)."""
        self.header_bg_rect.style = {
            "background_color": _HEADER_HOVER_BG if hovered
            else R.COLOR_SECTION_HEADER_BG}

    # ------------------------------------------------------------ status
    def set_status(self, text: str, complete: bool):
        """Update the header status word built when with_status=True. GREEN
        (R.COLOR_STATUS_OK, #80DE4A — the unified connected/ok green, issue
        #50) when the section is ready/complete; otherwise R.CLR_SPEC_ACCENT_RED
        (#C23B2F — the unified pending/attention red, same as the next-action
        button pulse). Supersedes the earlier "always yellow when pending"
        override, per the issue #50 follow-up report. status_dot was removed
        under issue #19; the guard below is kept for safety."""
        if self.status_label is not None:
            self.status_label.text = _truncate_status(text)
            self.status_label.style = {
                "color": R.COLOR_STATUS_OK if complete else R.CLR_SPEC_ACCENT_RED,
                "font_size": R.FONT_DESCRIPTION}
            # Full untruncated text always available on hover — covers the
            # "still too long even at the wider box" case gracefully
            # (issue #32) without needing to grow the header further.
            self.status_label.tooltip = text
        if self.status_dot is not None:
            self.status_dot.visible = bool(complete)

    def set_collapsed(self, collapsed: bool):
        """Reach the target fold state by delegating to the already-
        validated toggle() (which performs all three required mutations)."""
        if bool(collapsed) == self.collapsed:
            return
        self.toggle()

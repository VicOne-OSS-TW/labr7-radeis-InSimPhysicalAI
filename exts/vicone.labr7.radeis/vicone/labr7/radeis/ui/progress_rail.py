"""progress_rail.py — the 5-step overview strip.

Five numbered circular nodes joined by 4 connector lines, with a caption
below naming the current step. Node/connector color state is driven purely
by update() — this module has no mouse handlers and no async, and never
draws a check-mark glyph (ASCII digits only, per the codebase's font
guardrail: the Kit UI font silently tofus check/gear/middot glyphs).

Layout (build()):
    HStack(height=~34)  node - connector - node - connector - ... - node
    Label(height=~16)   "Step N . <caption>"   (ASCII " . " separator, no middot)

Each node is a ZStack(26x26) stacking, bottom to top:
    1. outer focus-ring ui.Circle (radius 13) — transparent unless "current"
    2. inner solid ui.Circle (radius 13) — the colored disc
    3. centered ui.Label(str(i + 1)) — the digit, always visible

Completion is sequential: step i counts "done" only when it and every prior
step are done (see update()).
"""
from __future__ import annotations

import omni.ui as ui

from . import radeis_ui as R


class ProgressRail:
    """5-step sequential progress rail.

    Public attributes after build():
      _rings       list[ui.Circle]    outer focus-ring circle per node (len 5)
      _discs       list[ui.Circle]    inner solid disc per node (len 5)
      _nums        list[ui.Label]     centered digit label per node (len 5)
      _connectors  list[ui.Rectangle] connector line per gap (len 4) — index i
                                       is "the line leaving node i"
      _caption     ui.Label           "Step N . <name>" caption below the rail
    """

    STEP_NAMES = [
        "Choose scene & robot",
        "Connect the model",
        "Select signs to attack",
        "Running test",
        "Review results",
    ]
    # Index-aligned with STEP_NAMES — the spec's rail caption uses these same
    # phrases verbatim, so both names hold identical content.
    STEP_CAPTIONS = STEP_NAMES

    def __init__(self):
        self._rings = []
        self._discs = []
        self._nums = []
        self._connectors = []
        self._caption = None

    # ------------------------------------------------------------ build
    def build(self):
        """Create the rail in the CURRENT omni.ui container scope."""
        self._rings = []
        self._discs = []
        self._nums = []
        self._connectors = []

        with ui.VStack(spacing=0):
            with ui.HStack(height=R.HEIGHT_PROGRESS_RAIL_ROW):
                for i in range(5):
                    self._build_node(i)
                    if i < 4:
                        self._build_connector()
            self._caption = ui.Label(
                "", height=R.HEIGHT_PROGRESS_RAIL_CAPTION,
                style=R.STYLE_PROGRESS_RAIL_CAPTION)
        return self

    def _build_node(self, i: int):
        # Fixed-width column so the node stays centered while connector
        # columns around it stretch to fill the row.
        with ui.VStack(width=R.WIDTH_PROGRESS_RAIL_NODE):
            ui.Spacer()
            with ui.ZStack(width=R.WIDTH_PROGRESS_RAIL_NODE,
                            height=R.WIDTH_PROGRESS_RAIL_NODE):
                # 1. outer focus ring — transparent until update() marks
                #    this node "current".
                ring = ui.Circle(
                    width=R.WIDTH_PROGRESS_RAIL_NODE,
                    height=R.WIDTH_PROGRESS_RAIL_NODE,
                    radius=R.RADIUS_PROGRESS_RAIL_NODE,
                    alignment=ui.Alignment.CENTER,
                    size_policy=ui.CircleSizePolicy.FIXED,
                    style={
                        "background_color": 0x00000000,
                        "border_width": 0,
                        "border_color": 0x00000000,
                    })
                # 2. inner solid disc — recolored by update().
                disc = ui.Circle(
                    width=R.WIDTH_PROGRESS_RAIL_NODE,
                    height=R.WIDTH_PROGRESS_RAIL_NODE,
                    radius=R.RADIUS_PROGRESS_RAIL_NODE,
                    alignment=ui.Alignment.CENTER,
                    size_policy=ui.CircleSizePolicy.FIXED,
                    style={"background_color": R.CLR_SPEC_NODE_FUTURE})
                # 3. digit — ASCII only, never a check glyph.
                num = ui.Label(
                    str(i + 1),
                    alignment=ui.Alignment.CENTER,
                    style={"color": R.CLR_SPEC_MUTED2,
                           "font_size": R.FONT_DESCRIPTION})
            ui.Spacer()
        self._rings.append(ring)
        self._discs.append(disc)
        self._nums.append(num)

    def _build_connector(self):
        # Fixed width=80 to fill the gap between the fixed-width (26px) node
        # columns in the row HStack -- verified live (screen_position_x /
        # computed_width) to lay out correctly at the right x-position with
        # nonzero size, so a collapsing/zero-width column was ruled out as
        # the cause of the "invisible connector" bug.
        #
        # The actual cause: HEIGHT_PROGRESS_RAIL_CONNECTOR was 2 (logical
        # px). At that thickness the Rectangle reports correct nonzero
        # computed_width/computed_height and visible=True, yet paints zero
        # pixels on screen -- confirmed empirically via live screenshot +
        # per-pixel sampling (flat, unchanged background color across the
        # full gap, even after forcing a bright debug color). A 2px-tall
        # rect apparently rounds away to a sub-pixel/degenerate rasterized
        # height in this renderer. Bumping the token to 4 gives a
        # consistently visible line (verified: ~3 raster rows of the
        # connector color actually appear in the screenshot, vs 0 at
        # height=2). See HEIGHT_PROGRESS_RAIL_CONNECTOR in radeis_ui.py.
        with ui.VStack(width=80, height=R.HEIGHT_PROGRESS_RAIL_ROW):
            ui.Spacer()
            rect = ui.Rectangle(
                width=80,
                height=R.HEIGHT_PROGRESS_RAIL_CONNECTOR,
                style={"background_color": R.CLR_SPEC_NODE_FUTURE})
            ui.Spacer()
        self._connectors.append(rect)

    # ----------------------------------------------------------- update
    def update(self, scene: bool, model: bool, config: bool, run: bool, report: bool):
        """Recolor nodes/connectors/caption from the 5 step-completion flags.

        Sequential completion: step i counts done only when it AND every
        prior step are done. `current` is the first not-done step, or the
        last step if all 5 are done.
        """
        flags = [scene, model, config, run, report]
        done = [all(flags[:i + 1]) for i in range(5)]
        current = next((i for i in range(5) if not done[i]), 4)

        for i in range(5):
            if done[i]:
                disc_bg = R.CLR_SPEC_RAIL_ORANGE
                num_color = R.COLOR_TEXT_PRIMARY
                ring_style = {"border_width": 0, "border_color": 0x00000000}
            elif i == current:
                disc_bg = R.CLR_SPEC_ACCENT_RED
                num_color = R.COLOR_TEXT_PRIMARY
                ring_style = {"border_width": 2, "border_color": R.CLR_SPEC_ACCENT_RED}
            else:
                disc_bg = R.CLR_SPEC_NODE_FUTURE
                num_color = R.CLR_SPEC_MUTED2
                ring_style = {"border_width": 0, "border_color": 0x00000000}

            # Widgets may already be gone (window closed mid-update) — each
            # node's mutations are grouped so one gone widget doesn't stop
            # the rest of the rail from updating.
            try:
                self._discs[i].style = {"background_color": disc_bg}
                self._nums[i].style = {"color": num_color, "font_size": R.FONT_DESCRIPTION}
                self._rings[i].style = {
                    "background_color": 0x00000000,
                    "border_width": ring_style["border_width"],
                    "border_color": ring_style["border_color"],
                }
            except Exception:  # noqa: BLE001
                pass

        for i, conn in enumerate(self._connectors):
            color = R.CLR_SPEC_RAIL_ORANGE if done[i] else R.CLR_SPEC_NODE_FUTURE
            try:
                conn.style = {"background_color": color}
            except Exception:  # noqa: BLE001
                pass

        try:
            self._caption.text = f"Step {current + 1} . {self.STEP_CAPTIONS[current]}"
        except Exception:  # noqa: BLE001
            pass

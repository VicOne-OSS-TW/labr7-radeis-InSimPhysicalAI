"""Radeis-styled omni.ui helpers (VicOne dark theme + red/magenta accents).

Reuses the existing extension's ABGR palette (constants.CLR_*) and the
section-header-with-accent-bar idiom, so the new red-team panel matches the
original Radeis look. omni.ui is only importable inside Kit — this module is
imported solely by the extension window.

All style-related parameters are defined in this module as named constants,
organized into groups. Other modules should import values from here rather
than hardcoding magic numbers inline.
"""
from __future__ import annotations

import asyncio
import os as _os

import omni.kit.app
import omni.ui as ui

from .. import constants as C


# ═══════════════════════════════════════════════════════════════════════════════
# WINDOW DIMENSIONS
# ═══════════════════════════════════════════════════════════════════════════════

MAIN_WIN_W              = 550    # RadeisRedTeamWindow width
MAIN_WIN_H              = 892    # RadeisRedTeamWindow height
MAIN_WIN_X              = 840    # RadeisRedTeamWindow initial screen x position
MAIN_WIN_Y              = 15     # RadeisRedTeamWindow initial screen y position

WIZARD_WIN_W            = 620    # ModelWizard width
# Widened from 520 -- round-2/3 capture of full_png/01-choose-path.png showed
# the narrower window forcing Card B's third description line ("Run the
# provided setup script on the machine") to wrap to 2 lines (the reference
# renders it on one line), which then threw off the vertical alignment of
# the two path cards' status chips relative to each other. 620 is scaled from
# the live-measured content width (650px at the old 520 window token) up to
# the reference canvas's proportional width (771px): 520 * (771/650) ~= 620.
WIZARD_WIN_H            = 680    # ModelWizard height (all pages except Done - see below)
# The "Complete" (done) page's Configuration-row dividers + card-body
# insets + footer nav-band push that page's natural content height to
# ~814 logical px (measured live via frame.computed_height with the
# page's greedy trailing-Spacer temporarily starved by a too-small window,
# so it reports the true floor, not spacer-inflated slack) - taller than
# every other wizard page. Bumping the shared WIZARD_WIN_H would fix Done
# but leaves a large dead gap above the footer on lighter pages (e.g.
# choose_path), since their own trailing Spacer would just stretch further
# into the extra height. So instead ModelWizard._goto() resizes the window
# per-page: WIZARD_WIN_H_DONE only while on the Done page, WIZARD_WIN_H
# everywhere else.
#
# NOTE (issue #49): the ~814px floor above was stale -- it was measured
# before the Configuration card's row dividers were reverted from
# height=12 solid ui.Rectangle bars back to ui.Line(height=1) (issue #44)
# and before Card 1/Card 2 became auto-sized-to-content instead of fixed
# height=184/height=232 (issue #49's own structural fix). Re-measured live
# 2026-07-09 with the same starved-trailing-Spacer Method (ModelWizard
# navigated to the Done page in a running Isaac Sim instance, window
# temporarily shrunk to 100px so the greedy trailing Spacer is starved to
# ~0 and frame.computed_height reports the true content floor instead of
# spacer-inflated slack): the Done page's true content floor is ~621.5px,
# vs. ~606.6px for the landing page (whose WIZARD_WIN_H=680 above already
# encodes a ~73.4px window-chrome overhead with an ~0 trailing-Spacer gap
# at that size -- confirmed by re-measuring the landing page at window
# height=680 and getting the same ~606.6px). Applying that same
# floor+chrome formula to Done (621.5 + 73.4 ~= 695) and rounding up a few
# px for a small, deliberately-nonzero trailing gap (not a guess -- the
# issue explicitly asks for a small consistent margin, not for the gap to
# vanish to 0px, and undershooting clips the footer band, which is worse
# than a small gap) gives 700. Live-verified via screenshot at
# WIZARD_WIN_H_DONE=700: gap between the Test Inference card and the
# footer divider is small and consistent (in line with the other
# inter-card gaps), and the footer band + Back/Finish buttons render fully
# on-screen, not clipped.
WIZARD_WIN_H_DONE       = 700    # ModelWizard height while on the Done/Complete page only

# Path B's "Connect" page uninstall panel can reveal ~290px of extra content
# (2 code blocks + a button) that the fixed WIZARD_WIN_H window has no room
# for. Growing the WHOLE WINDOW to fit it (the same per-page-resize Method as
# WIZARD_WIN_H_DONE above) was tried and measured live to need ~980px -
# beyond what the Kit viewport can actually display on a standard-height
# monitor in this dev environment (a floating omni.ui window positioned near
# the top of Kit's own content area has only ~838 logical px of headroom
# before it renders past the bottom of the app's own viewport - confirmed via
# a live screenshot where the footer row was rendered past the physical
# screen edge, not just past the omni.ui window's own declared bounds).
# Fixed instead in sidecar_setup.py's _page_path_b_connect: the scrollable
# body (everything above the footer) is wrapped in its own bounded
# ui.ScrollingFrame sized to HEIGHT_WIZARD_PB_SCROLL_BODY, with the footer
# nav row as a sibling AFTER it (outside the scroll region) so the footer
# stays visible regardless of window height or how tall the uninstall panel
# gets - see HEIGHT_WIZARD_PB_SCROLL_BODY below.
HEIGHT_WIZARD_PB_SCROLL_BODY = 528  # Path B connect page: scrollable body height (footer sits outside)

SEE_REASON_WIN_W        = 860    # SeeReasonWindow width
SEE_REASON_WIN_H        = 560    # SeeReasonWindow height
SEE_REASON_WIN_X        = 560    # SeeReasonWindow initial screen x position
SEE_REASON_WIN_Y        = 30     # SeeReasonWindow initial screen y position


# ═══════════════════════════════════════════════════════════════════════════════
# COLOR PALETTE
# Semantic aliases over the raw CLR_* values in constants.py.
# Use these names inside this module; CLR_* names remain in constants.py for
# callers that import constants directly.
# ═══════════════════════════════════════════════════════════════════════════════

COLOR_WINDOW_BG         = C.CLR_BG           # outermost window / frame background
COLOR_CARD_BG           = C.CLR_CARD         # card rectangle fill
COLOR_SECTION_HEADER_BG = C.CLR_SECTION_BG   # section / card header strip fill
COLOR_PANEL_BG          = C.CLR_PANEL        # inset panel (slightly darker than card)

COLOR_ACCENT            = C.CLR_RED          # primary accent: left accent bar, selected border
COLOR_ACCENT_DARK       = C.CLR_RED_DARK     # primary button background (darker shade)
COLOR_ACCENT_MAGENTA    = C.CLR_MAGENTA      # VicOne secondary accent

COLOR_TEXT_PRIMARY      = C.CLR_WHITE        # headings, button labels, input values
COLOR_TEXT_SECONDARY    = C.CLR_GREY        # body labels, descriptions, captions
COLOR_TEXT_DIM          = C.CLR_GREY_DIM   # muted / disabled / hint text

COLOR_BUTTON_BG         = C.CLR_BTN         # secondary button and input field fill
COLOR_BORDER            = C.CLR_BORDER      # input borders, card outlines, secondary button border
# Local override (not C.CLR_CARD_SELECTED): full_png/01-choose-path.png's
# selected Local-path card reads as a subtle warm tint (~43,35,32 RGB), much
# less saturated than the shared C.CLR_CARD_SELECTED token (61,42,42) this
# used to alias. Grep-verified C.CLR_CARD_SELECTED has no other consumers in
# the codebase, but this file still gives the wizard landing-card fill its
# own dedicated value rather than editing the shared constants.py token, so
# nothing outside this one call site can be affected by a future retune.
COLOR_CARD_WIZARD_SELECTED_BG = 0xFF20232B  # ABGR — subtle warm tint (~43,35,32 RGB)
COLOR_CARD_SIGN_SELECTED_BG = C.CLR_CARD_SELECTED_STRONG  # ~30% accent tint — Test Signs grid selected row
COLOR_WIZARD_FOOTER_BG      = 0xFF151515    # ABGR — hairline darker than COLOR_WINDOW_BG, nav-footer band fill

COLOR_STATUS_OK         = C.CLR_OK          # green — healthy / ROBUST / pass
COLOR_STATUS_WARN       = C.CLR_WARN        # amber — warning / PARTIAL / unavailable
COLOR_STATUS_DANGER     = C.CLR_DANGER      # red   — error / VULNERABLE / offline

# 20%-alpha tints of the status colors, for filled badge-pill backgrounds
# (same RGB as COLOR_STATUS_OK / COLOR_STATUS_WARN, low alpha byte — ABGR format).
COLOR_STATUS_OK_TINT_BG   = 0x334ADE80      # green tint  — "Best for limited VRAM" badge fill
COLOR_STATUS_WARN_TINT_BG = 0x334DC4FF      # amber tint  — "Low VRAM · CPU mode" badge fill

# Wizard-only muted pill foreground/background pairs — softer than the shared
# COLOR_STATUS_OK/WARN/DANGER trio above (those stay bright; they're also used
# by the AI Perception View and must not change). Used only by the wizard's
# System Requirements Check status pills (design ref: soft tinted chip, not a
# saturated/neon fill).
COLOR_STATUS_OK_PILL_FG     = 0xFF9AC774    # muted green  #74C79A — pill text
COLOR_STATUS_OK_PILL_BG     = 0x248AB95C    # ~14%-alpha tint of the same green
COLOR_STATUS_WARN_PILL_FG   = 0xFF5AB2E1    # muted amber  #E1B25A — pill text
COLOR_STATUS_WARN_PILL_BG   = 0x293FA2D6    # ~16%-alpha tint of the same amber
COLOR_STATUS_DANGER_PILL_FG = 0xFF4E4ED8    # muted red    #D84E4E — pill text
COLOR_STATUS_DANGER_PILL_BG = 0x294E4ED8    # ~16%-alpha tint of the same red

COLOR_PROGRESS_FILL     = C.CLR_RED_DARK    # deep red progress bar fill (matches accent dark)
COLOR_IMAGE_PANEL_LABEL = 0xCCFFFFFF        # semi-transparent white for image-panel title labels
COLOR_GRAYOUT_OVERLAY   = 0x80000000        # wizard-open main-window grayout (black 50% opacity)
COLOR_DEBUG_CLICKABLE   = 0x4400AAFF        # debug: semi-transparent blue — marks clickable overlays
COLOR_DEBUG_EXPAND_AREA = 0x00000000        # debug: transparent blue  (ABGR) — header expand/collapse hit zone
COLOR_DEBUG_CB_AREA     = 0x00000000        # debug: transparent red   (ABGR) — header checkbox hit zone


# ═══════════════════════════════════════════════════════════════════════════════
# TYPOGRAPHY — font_size for every text role
# ═══════════════════════════════════════════════════════════════════════════════

FONT_SECTION_TITLE      = 17    # top-level section_header label
FONT_CARD_TITLE         = 17    # card_header label; also result summary text
FONT_BODY               = 13    # banner about-text, secondary button labels, body copy
FONT_LABEL              = 14    # field captions, combo row labels
FONT_DESCRIPTION        = 12    # helper text under fields, wizard hints, step labels
FONT_FIELD              = 12    # text inside combo / string / float fields; diagnostics

FONT_BTN_PRIMARY        = 14    # primary button label
FONT_BTN_SECONDARY      = 13    # secondary button label
FONT_STATUS_PILL        = 12    # status pill chip text
FONT_REASONING_TEXT     = 14    # AI Perception View streaming model-reasoning panel
FONT_WIZARD_STEP        = 13    # step-indicator labels and small-print wizard text
FONT_WIZARD_SMALL       = 10    # "Checked at:" / progress-bar percentage labels
FONT_IMAGE_PANEL_LABEL  = 22    # overlay label on live image panels (legible before first frame)


# ═══════════════════════════════════════════════════════════════════════════════
# SPACING & PADDING
# ═══════════════════════════════════════════════════════════════════════════════

MARGIN_OUTER                = 1   # outermost VStack style["margin"]
SPACING_OUTER               = 1   # outermost VStack spacing (gap between cards)
SPACING_CARD_INNER          = 2   # VStack spacing inside a standard card
SPACING_CARD_INNER_WIDE     = 4   # looser inner spacing used in wizard cards
SPACING_BETWEEN_CARDS       = 4   # Spacer height separating major card sections
PADDING_CARD_SIDE           = 10  # left/right HStack Spacer width inside cards

SPACING_INPUT_ROW           = 6   # HStack spacing within a caption + field row
MARGIN_BANNER               = 6   # banner HStack style["margin"]
SPACING_BANNER              = 10  # banner HStack spacing between logo and text

MARGIN_SEE_REASON           = 8   # SeeReasonWindow outer VStack style["margin"]
SPACING_SEE_REASON_SECTION  = 6   # Spacer between image row and reasoning panel
SPACING_IMAGE_PANELS        = 4   # HStack spacing between FPV and Inference panels
PADDING_IMG_LABEL_SIDE      = 5   # left Spacer for image-panel corner label
PADDING_REASONING_SIDE      = 8   # HStack Spacer inside reasoning text panel
PADDING_REASONING_TOP       = 8   # VStack top Spacer inside reasoning text panel

MARGIN_WIZARD_CARD_INNER    = 5   # style["margin"] on wizard path-card inner VStack
SPACING_WIZARD_CARD_INNER   = 3   # VStack spacing inside wizard path cards (Local/Remote)
MARGIN_DIAGNOSTICS          = 6   # diagnostics CollapsableFrame inner VStack margin
MARGIN_CODE_BLOCK           = 4   # code-block label style["margin"]


# ═══════════════════════════════════════════════════════════════════════════════
# ELEMENT HEIGHTS & WIDTHS
# ═══════════════════════════════════════════════════════════════════════════════

# ── Section / card header strips ──────────────────────────────────────────────
HEIGHT_SECTION_HEADER       = 32  # section_header() ZStack height
WIDTH_SECTION_STATUS_TEXT   = 150 # fixed box for FoldableSection's status word —
                                   # keeps header layout stable regardless of text
                                   # length (right-aligned against the fold arrow).
                                   # 150 fits "Connected . gemma-4-e2b-it"-length
                                   # labels without pushing the header over
                                   # MAIN_WIN_W (issue #32); anything still too
                                   # long falls back to middle-ellipsis text +
                                   # a full-text tooltip (foldable_section.py).
HEIGHT_CARD_HEADER          = 28  # card_header() default height
HEIGHT_CARD_HEADER_COMPACT  = 24  # nested card headers inside wizard path cards
WIDTH_ACCENT_BAR            = 3   # left accent bar width
WIDTH_ACCENT_BAR_WIZARD     = 4   # left accent bar width — wizard card headers

# ── Banner (top of main window) ───────────────────────────────────────────────
HEIGHT_BANNER               = 56  # banner ZStack height
SIZE_BANNER_LOGO            = 56  # square logo image width and height

# ── Primary buttons ────────────────────────────────────────────────────────────
HEIGHT_BTN_PRIMARY          = 36  # default primary_button() height
HEIGHT_BTN_PRIMARY_RUN      = 38  # RUN TEST / STOP action buttons
HEIGHT_BTN_PRIMARY_WIZARD   = 30  # wizard Next / Start Install / Load Model buttons

# ── Secondary buttons ─────────────────────────────────────────────────────────
HEIGHT_BTN_SECONDARY        = 32  # default secondary_button() height
HEIGHT_BTN_SECONDARY_COMPACT = 26 # Reset Test Cases / Open Report row buttons
HEIGHT_BTN_SECONDARY_INLINE = 22  # Setup Wizard / Refresh ↺ inside card headers
HEIGHT_BTN_SECONDARY_WIZARD = 28  # Clean Reinstall button

# ── Fixed-width buttons (only where explicit widths are set) ──────────────────
WIDTH_BTN_BUILD             = 120 # "Build" button in scene section
WIDTH_BTN_SETUP_WIZARD      = 112 # "Setup Wizard" inline header button
WIDTH_BTN_REFRESH           = 26  # single-glyph refresh button
WIDTH_BTN_RECONNECT         = 90
WIDTH_BTN_LOAD_MODEL        = 90
WIDTH_BTN_WIZARD_NEXT       = 130 # "Setup >" landing-page call-to-action

# ── Shared button decoration ──────────────────────────────────────────────────
RADIUS_BTN                  = 4   # border-radius applied to all buttons
WIDTH_BTN_BORDER            = 1   # border-width for secondary buttons

# ── Input rows (caption + field) ─────────────────────────────────────────────
HEIGHT_INPUT_ROW            = 26  # standard HStack height for a caption + field row
HEIGHT_INPUT_ROW_COMPACT    = 24  # tighter variant used in some sections
HEIGHT_INPUT_FIELD          = 24  # StringField / FloatField height
HEIGHT_INPUT_FIELD_COMPACT  = 22  # ComboBox inside the Model Under Test section
WIDTH_INPUT_CAPTION_DEFAULT = 110 # string_row() default caption label width
WIDTH_INPUT_CAPTION_URL     = 40  # "URL" / "Model" label width in main window

# ── Status pill ───────────────────────────────────────────────────────────────
RADIUS_STATUS_PILL          = 11  # high radius makes a capsule / pill shape
WIDTH_STATUS_PILL_BORDER    = 1

# ── Model status bar (section 2 bottom row) ───────────────────────────────────
HEIGHT_MODEL_STATUS_ROW     = 20  # HStack wrapper
HEIGHT_MODEL_STATUS_LABEL   = 16  # Label inside the status row

# ── Progress bars ─────────────────────────────────────────────────────────────
HEIGHT_PROGRESS_BAR         = 12  # ProgressBar widget height (main window)
HEIGHT_PROGRESS_BAR_ROW     = 16  # HStack wrapper around the progress bar
HEIGHT_PROGRESS_BAR_WIZARD  = 22  # ProgressBar height in wizard _make_progress_bar()

# ── Result / log output labels ────────────────────────────────────────────────
HEIGHT_RESULT_LABEL         = 22
HEIGHT_LOG_LABEL            = 72  # multi-line scrolling log output

# ── AI Perception View image panels ───────────────────────────────────────────
WIDTH_SEE_REASON_IMAGE      = 420 # FPV and Inference image panel width
HEIGHT_SEE_REASON_IMAGE     = 380 # image panel height
HEIGHT_SEE_REASON_REASONING = 90  # reasoning text ZStack height
HEIGHT_SEE_REASON_IMG_LABEL = 26  # label row height — must be ≥ font_size (22) + padding

# ── Wizard: step indicator ────────────────────────────────────────────────────
HEIGHT_WIZARD_STEP_INDICATOR    = 38  # top-of-wizard HStack height
SPACING_WIZARD_STEP_INDICATOR   = 2   # spacing between step columns
HEIGHT_WIZARD_STEP_BAR          = 4   # coloured progress bar under each step label
# (was 3 -- platform-gotchas/omni-ui-thin-rectangle-sub-pixel-height-invisible.md
# documents that a thin ui.Rectangle at height=3 rasterizes to only ~1 barely-
# visible row in this renderer despite reporting correct computed_height/visible;
# 4 is the doc's confirmed reliably-visible minimum. Round-2/3 capture showed
# this active-tab underline rendering ~1px thick vs the reference's 3px.)

# ── Wizard: path-selection cards (Local / Remote) ─────────────────────────────
HEIGHT_WIZARD_PATH_CARD         = 120 # clickable card HStack height
SPACING_WIZARD_PATH_CARDS       = 10  # HStack spacing between the two cards
HEIGHT_WIZARD_LANDING_HINT      = 16  # "Please select a path first" hint label
HEIGHT_WIZARD_LANDING_INTRO     = 48  # word-wrapped "Choose Local to run..." intro (up to 3 lines —
                                       # the sentence wraps to 3 lines at the wizard's default width,
                                       # a fixed 2-line box silently clipped the middle line)

# ── Wizard: bottom nav-footer band (choose_path "Continue" strip, ref
# full_png/01-choose-path.png) — a thin divider + a hairline-darker band
# pinned under a single trailing Spacer so it sits at the true bottom of the
# page instead of flowing with content (see choose_server.py::_page_landing).
HEIGHT_WIZARD_FOOTER_BAND       = 56  # bottom nav-footer band height

# ── Wizard: path-card radio indicator + status badge pill ────────────────────
WIDTH_WIZARD_RADIO_GLYPH        = 16  # leading radio-circle glyph column width
DIAMETER_WIZARD_RADIO           = 14  # drawn radio-circle diameter (fits inside WIDTH_WIZARD_RADIO_GLYPH)
DIAMETER_WIZARD_RADIO_DOT        = 7   # selected-state inner dot diameter (drawn inside the outer ring)
WIDTH_WIZARD_RADIO_BORDER        = 2   # ring thickness for the unselected radio circle
WIDTH_WIZARD_BADGE              = 150 # fixed-width status badge pill (e.g. "Best for limited VRAM")
HEIGHT_WIZARD_BADGE             = 22  # status badge pill height
RADIUS_WIZARD_BADGE             = 6   # status badge pill corner radius

# ── Wizard: resource / status labels ─────────────────────────────────────────
HEIGHT_WIZARD_RESOURCE_LABEL    = 16  # GPU / VRAM / DISK / RAM info rows
WIDTH_WIZARD_RESOURCE_COL       = 64  # "RESOURCE" column — short label only (GPU/VRAM/Disk/RAM),
                                       # detected value + requirement now live together in one
                                       # "DETECTED" column to its right (design ref grid: 88px/1fr/auto)
HEIGHT_WIZARD_CODE_BLOCK_SMALL      = 36  # single-command code-block label
HEIGHT_WIZARD_CODE_BLOCK_TWO_LINE   = 56  # two-line code-block (e.g. git clone + cd) — snug to 2 lines, not oversized
HEIGHT_WIZARD_CODE_BLOCK_LARGE      = 104 # multi-line setup-script code-block label

# ── Card decoration ────────────────────────────────────────────────────────────
RADIUS_CARD                 = 5   # border-radius for main-window cards
RADIUS_CARD_WIZARD          = 6   # slightly rounder radius used in wizard
WIDTH_CARD_BORDER_NORMAL    = 1   # unselected / default card border
WIDTH_CARD_BORDER_SELECTED  = 2   # highlighted / selected card border

# ── Banner & image panels ─────────────────────────────────────────────────────
RADIUS_BANNER               = 6   # banner ZStack Rectangle border-radius
RADIUS_IMAGE_PANEL          = 4   # AI Perception View image panel border-radius


# ═══════════════════════════════════════════════════════════════════════════════
# SHARED STYLE DICTS — pre-built dicts for repeated patterns
# ═══════════════════════════════════════════════════════════════════════════════

STYLE_WINDOW_FRAME = {"background_color": COLOR_WINDOW_BG}

# ── Wizard: bottom nav-footer band (see HEIGHT_WIZARD_FOOTER_BAND above) ──────
STYLE_WIZARD_FOOTER_BAND    = {"background_color": COLOR_WIZARD_FOOTER_BG}
STYLE_WIZARD_FOOTER_DIVIDER = {"background_color": COLOR_BORDER}

STYLE_CARD = {
    "background_color": COLOR_CARD_BG,
    "border_radius": RADIUS_CARD,
}

STYLE_CARD_WIZARD = {
    "background_color": COLOR_CARD_BG,
    "border_radius": RADIUS_CARD_WIZARD,
    "border_width": WIDTH_CARD_BORDER_NORMAL,
    "border_color": COLOR_BORDER,
}

STYLE_CARD_WIZARD_SELECTED = {
    "background_color": COLOR_CARD_WIZARD_SELECTED_BG,
    "border_radius": RADIUS_CARD_WIZARD,
    "border_width": WIDTH_CARD_BORDER_SELECTED,
    "border_color": COLOR_ACCENT,
}

STYLE_INPUT_FIELD = {
    "background_color": COLOR_BUTTON_BG,
    "border_width": WIDTH_BTN_BORDER,
    "border_color": COLOR_BORDER,
    "color": COLOR_TEXT_PRIMARY,
    "font_size": FONT_FIELD,
}

STYLE_INPUT_FIELD_WIZ = {
    "background_color": COLOR_BUTTON_BG,
    "border_width": WIDTH_BTN_BORDER,
    "border_color": COLOR_BORDER,
    "color": COLOR_TEXT_PRIMARY,
    "font_size": FONT_FIELD,
    ":focused": {"border_color": COLOR_ACCENT},
}

# Dim variant of STYLE_INPUT_FIELD, used to render placeholder/hint text
# (e.g. "hf_••••••••" in an empty HF Token field) in the same muted tone as
# other hint labels instead of full COLOR_TEXT_PRIMARY, matching
# reference-path_a_download_or_load.png.
STYLE_INPUT_FIELD_PLACEHOLDER = {**STYLE_INPUT_FIELD, "color": COLOR_TEXT_DIM}

STYLE_COMBO_URL = {
    "background_color": COLOR_BUTTON_BG,
    "border_width": WIDTH_BTN_BORDER,
    "border_color": COLOR_BORDER,
    "color": COLOR_TEXT_PRIMARY,
    "font_size": FONT_FIELD,
}

STYLE_COMBO_MODEL = {
    "background_color": COLOR_BUTTON_BG,
    "border_width": WIDTH_BTN_BORDER,
    "border_color": COLOR_BORDER,
    "color": COLOR_TEXT_PRIMARY,
    "font_size": FONT_FIELD,
}

STYLE_COMBO_STANDARD = STYLE_COMBO_MODEL

STYLE_PROGRESS_BAR = {"color": COLOR_PROGRESS_FILL}

# Tooltip style — set as the "Tooltip" key inside a widget's style dict.
# Controls the popup background, border, text colour, and font in one place
# so the same constant works for both Button (red/grey) and ZStack widgets.
STYLE_TOOLTIP = {
    "background_color": COLOR_BUTTON_BG,
    "border_radius": RADIUS_BTN,
    "border_width": WIDTH_BTN_BORDER,
    "border_color": COLOR_BORDER,
    "color": COLOR_TEXT_SECONDARY,
    "font_size": FONT_DESCRIPTION,
}

STYLE_BTN_RUNNING = {
    "background_color": COLOR_ACCENT_DARK,
    "border_radius": RADIUS_BTN,
    "border_width": WIDTH_BTN_BORDER,
    "border_color": COLOR_ACCENT,
    "color": COLOR_TEXT_PRIMARY,
    "font_size": FONT_BTN_SECONDARY,
}
STYLE_BTN_SECONDARY_DEFAULT = {
    "background_color": COLOR_BUTTON_BG,
    "border_radius": RADIUS_BTN,
    "border_width": WIDTH_BTN_BORDER,
    "border_color": COLOR_BORDER,
    "color": COLOR_TEXT_PRIMARY,
    "font_size": FONT_BTN_SECONDARY,
}
STYLE_BTN_INACTIVE = {
    "background_color": COLOR_PANEL_BG,
    "border_radius": RADIUS_BTN,
    "border_width": WIDTH_BTN_BORDER,
    "border_color": COLOR_BORDER,
    "color": COLOR_TEXT_DIM,
    "font_size": FONT_BTN_SECONDARY,
}

# Bundled monospace font for code blocks (Step 1/2 commands, uninstall
# scripts) — the Kit default font is proportional, so without an explicit
# "font" override every code block renders in a proportional face instead of
# monospace (full_png reference always shows fixed-width digits/punctuation).
# Bundled the same way as onboarding/style.py's FONT_BOLD (a ttf shipped next
# to the module, not a version-pinned extscache path).
FONT_MONO_WIZ: str = _os.path.join(_os.path.dirname(__file__), "wizard", "fonts", "DejaVuSansMono.ttf")

STYLE_CODE_BLOCK = {
    "color": COLOR_TEXT_SECONDARY,
    "font_size": FONT_DESCRIPTION,
    "font": FONT_MONO_WIZ,
    "background_color": COLOR_PANEL_BG,
    "border_width": WIDTH_BTN_BORDER,
    "border_color": COLOR_BORDER,
    "border_radius": RADIUS_BTN,
    "margin": MARGIN_CODE_BLOCK,
}

# Split variant for code-block content hosted on a bare ui.Label: unlike
# ui.StringField (used for STEP 1's clone command), a plain ui.Label does not
# reliably render background_color/border_* — same reason the codebase always
# pairs a background ui.Rectangle with label content elsewhere (see
# STYLE_WIZARD_LOG_PANEL/STYLE_WIZARD_LOG_LABEL, STYLE_WIZ_BANNER_OK/_DOT_OK
# below). Put STYLE_CODE_BLOCK_BG on a ui.Rectangle behind the Label, and
# STYLE_CODE_BLOCK_TEXT on the Label itself, inside a shared ui.ZStack.
STYLE_CODE_BLOCK_BG = {
    "background_color": COLOR_PANEL_BG,
    "border_width": WIDTH_BTN_BORDER,
    "border_color": COLOR_BORDER,
    "border_radius": RADIUS_BTN,
}
STYLE_CODE_BLOCK_TEXT = {
    "color": COLOR_TEXT_SECONDARY,
    "font_size": FONT_DESCRIPTION,
    "font": FONT_MONO_WIZ,
    "margin": MARGIN_CODE_BLOCK,
}

# ── Wizard typography (wizard-scoped type scale; do NOT reuse for main window) ──
# New wizard-only sizes where the required role conflicts with a shared
# FONT_* consumer. Roles already on-scale reuse existing constants:
#   body 13   -> FONT_BODY / FONT_WIZARD_STEP (unchanged)
#   caption 12-> FONT_DESCRIPTION (unchanged)
#   button    -> FONT_BTN_SECONDARY(13) / FONT_BTN_PRIMARY(14) (unchanged)
#   mono 12   -> FONT_DESCRIPTION via STYLE_WIZ_MONO / STYLE_CODE_BLOCK
FONT_WIZ_PAGE_TITLE  = 18    # wizard page title (FONT_SECTION_TITLE stays 17 for main window)
FONT_WIZ_CARD_TITLE  = 14    # wizard accent-bar card title (FONT_CARD_TITLE stays 17 for main window)
FONT_WIZ_FIELD_LABEL = 11    # wizard field caption (FONT_WIZARD_SMALL stays 10 for report_window.py)

STYLE_WIZ_PAGE_TITLE  = {"color": COLOR_TEXT_PRIMARY,   "font_size": FONT_WIZ_PAGE_TITLE}
STYLE_WIZ_CARD_TITLE  = {"color": COLOR_TEXT_PRIMARY,   "font_size": FONT_WIZ_CARD_TITLE}
STYLE_WIZ_FIELD_LABEL = {"color": COLOR_TEXT_DIM,       "font_size": FONT_WIZ_FIELD_LABEL}
STYLE_WIZ_MONO        = {"color": COLOR_TEXT_SECONDARY, "font_size": FONT_DESCRIPTION}  # single wizard mono size

# ── Wizard card title/description — issue #41 ──────────────────────────────
# The wizard's page-level card_header() title and its dim(=True) subtitle
# read washed-out next to the Contact Us card's equivalent text, even though
# both are dark-theme panels: card_header() hardcodes COLOR_TEXT_PRIMARY/
# FONT_CARD_TITLE (#e8e8e8 @ 17px) and R.label(dim=True, size=FONT_DESCRIPTION)
# uses COLOR_TEXT_DIM/FONT_DESCRIPTION (#666666 @ 12px — only ~40% brightness).
# Contact Us (contact_us_win.py T_ROW/T_MUTED) uses #e6e9ec @ 16px title and
# #a2aab1 @ 14px (~65% brightness) subtitle. COLOR_TEXT_PRIMARY/COLOR_TEXT_DIM/
# FONT_CARD_TITLE/FONT_DESCRIPTION are shared with the main window (Section
# 1-4 headers, the Contact Us card itself) and stay unchanged — these are
# new wizard-only tokens, applied only via card_header_wiz() and at wizard
# page-subtitle call sites (see sidecar_setup.py/choose_server.py).
COLOR_WIZARD_CARD_TITLE       = 0xFFECE9E6   # #e6e9ec, ABGR — Contact Us row title
COLOR_WIZARD_CARD_DESCRIPTION = 0xFFB1AAA2   # #a2aab1, ABGR — Contact Us row subtitle
FONT_WIZARD_CARD_TITLE        = 16   # wizard page/card title (FONT_CARD_TITLE stays 17 elsewhere)
FONT_WIZARD_CARD_DESCRIPTION  = 14   # wizard page/card subtitle (FONT_DESCRIPTION stays 12 elsewhere)

STYLE_WIZARD_CARD_DESCRIPTION = {"color": COLOR_WIZARD_CARD_DESCRIPTION,
                                  "font_size": FONT_WIZARD_CARD_DESCRIPTION}

# Pulse style pair (E17) — PulseController base/accent for wizard next-action
# buttons. BASE is byte-identical to the dict primary_button()/danger_button()
# build inline today (see refactor 1e); PULSE adds an accent fill + glow ring.
STYLE_WIZ_BTN_PRIMARY_BASE = {
    "background_color": COLOR_ACCENT_DARK,
    "border_radius": RADIUS_BTN,
    "color": COLOR_TEXT_PRIMARY,
    "font_size": FONT_BTN_PRIMARY,
    ":hovered": {"background_color": COLOR_ACCENT},
    ":disabled": {"background_color": COLOR_PANEL_BG, "color": COLOR_TEXT_DIM},
    "Tooltip": STYLE_TOOLTIP,
}
STYLE_WIZ_BTN_PRIMARY_PULSE = {
    **STYLE_WIZ_BTN_PRIMARY_BASE,
    "background_color": COLOR_ACCENT,
    "border_width": 1,
    "border_color": 0xFF8080FF,   # ABGR — light-red glow tint (rgb 255,128,128)
}

# Field variant of the same pulse pair (issue #47) — Path B's Sidecar URL
# field needs to be a valid next-action pulse target too (border-accent
# alternating), not just buttons. Unlike the button pair above this is
# border-only (no fill-swap): STYLE_INPUT_FIELD_WIZ already reserves
# COLOR_ACCENT for its own ":focused" border, so the pulse reuses that same
# accent color for consistency and just widens the border to make the
# alternation visible while unfocused.
STYLE_INPUT_FIELD_WIZ_PULSE = {
    **STYLE_INPUT_FIELD_WIZ,
    "border_color": COLOR_ACCENT,
    "border_width": 2,
}

# ── Wizard step indicator ──────────────────────────────────────────────────────
STYLE_WIZARD_STEP_LABEL_INACTIVE = {"color": COLOR_TEXT_DIM,       "font_size": FONT_WIZARD_STEP}
STYLE_WIZARD_STEP_LABEL_ACTIVE   = {"color": COLOR_TEXT_PRIMARY,   "font_size": FONT_WIZARD_STEP}
STYLE_WIZARD_STEP_LABEL_DONE     = {"color": COLOR_TEXT_SECONDARY, "font_size": FONT_WIZARD_STEP}
STYLE_WIZARD_STEP_BAR_INACTIVE   = {"background_color": 0x14FFFFFF}
STYLE_WIZARD_STEP_BAR_DONE       = {"background_color": COLOR_BORDER}
STYLE_WIZARD_STEP_BAR_CURRENT    = {"background_color": COLOR_ACCENT}

# ── Wizard: drawn radio-circle indicator (path cards) ─────────────────────────
# Both states draw the SAME outer ring (transparent fill + border); only the
# border color changes. full_png/01-choose-path.png shows the selected state
# as a ring + a separate smaller filled inner dot, not a single solid disc —
# the previous STYLE_WIZARD_RADIO_SELECTED (solid accent fill, border same
# color so the ring vanished into the fill) rendered as one ~16px flat disc
# with no visible ring. The inner dot itself is drawn separately by
# choose_server.py via STYLE_WIZARD_RADIO_DOT, toggled visible only when
# selected.
STYLE_WIZARD_RADIO_EMPTY    = {
    "background_color": 0x00000000,
    "border_width": WIDTH_WIZARD_RADIO_BORDER,
    "border_color": COLOR_BORDER,
}
STYLE_WIZARD_RADIO_SELECTED = {
    "background_color": 0x00000000,
    "border_width": WIDTH_WIZARD_RADIO_BORDER,
    "border_color": COLOR_ACCENT,
}
STYLE_WIZARD_RADIO_DOT = {"background_color": COLOR_ACCENT}

# ── Wizard inline text ─────────────────────────────────────────────────────────
STYLE_WIZARD_WARN_LABEL   = {"color": COLOR_STATUS_WARN,    "font_size": FONT_WIZARD_STEP}
STYLE_WIZARD_REQ_LABEL    = {"color": COLOR_TEXT_SECONDARY, "font_size": FONT_WIZARD_STEP}
STYLE_WIZARD_BODY_LABEL   = {"color": COLOR_TEXT_SECONDARY, "font_size": FONT_WIZARD_STEP}
STYLE_WIZARD_STATUS_TEXT  = {"color": COLOR_TEXT_SECONDARY, "font_size": FONT_FIELD}
STYLE_WIZARD_OK_TEXT      = {"color": COLOR_STATUS_OK,      "font_size": FONT_STATUS_PILL}
STYLE_WIZARD_ERROR_TEXT   = {"color": COLOR_STATUS_DANGER,  "font_size": FONT_STATUS_PILL}

# ── Wizard: outlined status badge chips (landing-page path cards) ────────────
# full_png/01-choose-path.png shows these as *outlined* chips: a near-
# background fill, a 1px colored border, and colored (not white) text — the
# exact same "border-only" Method status_pill()/_build_status_pill() already
# use correctly for the "OK"/"Tight" pills in the System Requirements Check
# table (sidecar_setup.py), confirmed live to match the mockup. The previous
# version filled with a bare ~20%-alpha COLOR_STATUS_*_TINT_BG rect and no
# border at all; round-2/3 capture showed it rendering as a near-opaque
# saturated fill (e.g. the Remote/"ok" chip came back ~(117,200,70), close to
# CLR_OK's raw un-blended RGB, not a subtle tint) with the border missing
# entirely. Reusing the already-correct COLOR_STATUS_*_PILL_BG/FG constants
# (defined above, shared read-only with sidecar_setup.py's resource pills —
# not mutated here) sidesteps whatever made the TINT_BG rect misbehave rather
# than trying to re-tune it.
STYLE_WIZARD_BADGE_OK     = {"background_color": COLOR_STATUS_OK_PILL_BG,
                              "border_radius": RADIUS_WIZARD_BADGE,
                              "border_width": WIDTH_STATUS_PILL_BORDER,
                              "border_color": COLOR_STATUS_OK}
STYLE_WIZARD_BADGE_WARN   = {"background_color": COLOR_STATUS_WARN_PILL_BG,
                              "border_radius": RADIUS_WIZARD_BADGE,
                              "border_width": WIDTH_STATUS_PILL_BORDER,
                              "border_color": COLOR_STATUS_WARN}
STYLE_WIZARD_BADGE_OK_TEXT   = {"color": COLOR_STATUS_OK_PILL_FG,   "font_size": FONT_WIZARD_STEP}
STYLE_WIZARD_BADGE_WARN_TEXT = {"color": COLOR_STATUS_WARN_PILL_FG, "font_size": FONT_WIZARD_STEP}
STYLE_WIZARD_CHECKED_AT   = {"color": COLOR_TEXT_SECONDARY, "font_size": FONT_WIZ_FIELD_LABEL}
STYLE_WIZARD_LOG_PANEL    = {"background_color": COLOR_PANEL_BG, "border_radius": 4,
                              "border_width": 1, "border_color": COLOR_BORDER}
STYLE_WIZARD_LOG_LABEL    = {"color": COLOR_TEXT_SECONDARY, "font_size": FONT_DESCRIPTION,
                              "margin": 6}

# ── Wizard: status banners (soft tinted fill + muted border + status dot) ──
COLOR_STATUS_OK_MUTED    = 0xFF8AB95C   # muted green (#5CB98A) — success, not neon lime
COLOR_WIZ_BANNER_OK_BG   = 0x1A8AB95C   # ~10% muted-green tint fill
COLOR_WIZ_BANNER_WARN_BG = 0x1A4DC4FF   # ~10% amber tint fill
COLOR_WIZ_BANNER_ERR_BG  = 0x1A4444EF   # ~10% danger tint fill
# Reference (reference-done.png) pixel-samples the OK banner's 1px outline
# at a flat (54,89,74) — a darker, more desaturated green than the dot/text
# fill (93,184,138, i.e. COLOR_STATUS_OK_MUTED). Reusing COLOR_STATUS_OK_MUTED
# for the outline (as before) reads brighter/more saturated than the
# reference's soft outline, so the border gets its own dedicated, wizard-only
# shade instead of overloading the shared constant (which stays untouched —
# it is also CLR_SPEC_ONLINE_GREEN, used by the AI Perception View).
COLOR_WIZ_BANNER_OK_BORDER = 0xFF4A5A36   # muted-dark green outline (#365A4A), wizard banner border only
STYLE_WIZ_BANNER_OK   = {"background_color": COLOR_WIZ_BANNER_OK_BG,   "border_radius": RADIUS_CARD_WIZARD,
                         "border_width": 1, "border_color": COLOR_WIZ_BANNER_OK_BORDER}
STYLE_WIZ_BANNER_WARN = {"background_color": COLOR_WIZ_BANNER_WARN_BG, "border_radius": RADIUS_CARD_WIZARD,
                         "border_width": 1, "border_color": COLOR_STATUS_WARN}
STYLE_WIZ_BANNER_ERR  = {"background_color": COLOR_WIZ_BANNER_ERR_BG,  "border_radius": RADIUS_CARD_WIZARD,
                         "border_width": 1, "border_color": COLOR_STATUS_DANGER}
STYLE_WIZ_BANNER_DOT_OK   = {"background_color": COLOR_STATUS_OK_MUTED, "border_radius": 4}
STYLE_WIZ_BANNER_DOT_WARN = {"background_color": COLOR_STATUS_WARN,     "border_radius": 4}
STYLE_WIZ_BANNER_DOT_ERR  = {"background_color": COLOR_STATUS_DANGER,   "border_radius": 4}
# "Server online and ready." success text on the done-page banner: reuse the
# same muted green as the banner's dot/border rather than the bright shared
# COLOR_STATUS_OK (that constant is also CLR_BASELINE in the AI Perception
# View and must stay untouched there) — keeps the whole online banner in one
# muted sage tone instead of a brighter accent reading as neon.
STYLE_WIZARD_OK_TEXT_MUTED = {"color": COLOR_STATUS_OK_MUTED, "font_size": FONT_STATUS_PILL}

# ── Outer layout containers ────────────────────────────────────────────────────
STYLE_MAIN_OUTER_VSTACK = {"margin": MARGIN_OUTER}
STYLE_SEE_REASON_OUTER_VSTACK = {"margin": MARGIN_SEE_REASON}

# ── Banner (main window top strip) ─────────────────────────────────────────────
STYLE_BANNER_RECT = {
    "background_color": COLOR_WINDOW_BG,
    "border_radius": RADIUS_BANNER,
}
STYLE_BANNER_HSTACK = {"margin": MARGIN_BANNER}
STYLE_BANNER_TEXT = {
    "color": COLOR_TEXT_SECONDARY,
    "font_size": FONT_BODY,
}

# ── Robot preset buttons (selected / unselected) ───────────────────────────────
STYLE_ROBOT_BTN_DEFAULT = {
    "background_color": COLOR_BUTTON_BG,
    "border_radius": RADIUS_BTN,
    "border_width": WIDTH_CARD_BORDER_NORMAL,
    "border_color": COLOR_BORDER,
}
STYLE_ROBOT_BTN_SELECTED = {
    "background_color": COLOR_BUTTON_BG,
    "border_radius": RADIUS_BTN,
    "border_width": WIDTH_CARD_BORDER_SELECTED,
    "border_color": COLOR_ACCENT,
}

# ── File picker hint label ("No file selected") ────────────────────────────────
STYLE_FILE_HINT_LABEL = {
    "color": COLOR_STATUS_WARN,
    "font_size": FONT_FIELD,
}

# ── Model status bar ────────────────────────────────────────────────────────────
STYLE_MODEL_STATUS_IDLE = {
    "color": COLOR_TEXT_DIM,
    "font_size": FONT_DESCRIPTION,
}
STYLE_MODEL_STATUS_OFFLINE = {
    "color": COLOR_STATUS_DANGER,
    "font_size": FONT_DESCRIPTION,
}
STYLE_MODEL_STATUS_LOADING = {
    "color": COLOR_STATUS_WARN,
    "font_size": FONT_DESCRIPTION,
}
STYLE_MODEL_STATUS_CONNECTED = {
    "color": COLOR_STATUS_OK,
    "font_size": FONT_DESCRIPTION,
}

# ── Run result label ────────────────────────────────────────────────────────────
STYLE_RESULT_LABEL_PENDING = {
    "color": COLOR_TEXT_SECONDARY,
    "font_size": 19,
}
STYLE_RESULT_LABEL_BY_STATUS = {
    "VULNERABLE": {"color": COLOR_STATUS_DANGER, "font_size": 19},
    "PARTIAL":    {"color": COLOR_STATUS_WARN,   "font_size": 19},
    "ROBUST":     {"color": COLOR_STATUS_OK,     "font_size": 19},
}

# ── Log output label ────────────────────────────────────────────────────────────
STYLE_LOG_LABEL = {
    "color": 0xFFFFFFFF,
    "font_size": FONT_DESCRIPTION,
}

STYLE_LOG_LABEL_OK = {
    "color": COLOR_STATUS_OK,
    "font_size": FONT_DESCRIPTION,
}

# ── AI Perception View image panels ────────────────────────────────────────────
STYLE_IMAGE_PANEL = {
    "background_color": COLOR_PANEL_BG,
    "border_radius": RADIUS_IMAGE_PANEL,
}
STYLE_IMAGE_PANEL_LABEL_FPV = {
    "color": COLOR_IMAGE_PANEL_LABEL,
    "font_size": FONT_IMAGE_PANEL_LABEL,
    "font_weight": "Bold",
}
STYLE_IMAGE_PANEL_LABEL_INFERENCE = {
    "color": COLOR_IMAGE_PANEL_LABEL,
    "font_size": FONT_IMAGE_PANEL_LABEL,
    "font_weight": "Bold",
}
STYLE_REASONING_PANEL = {
    "background_color": COLOR_PANEL_BG,
    "border_radius": RADIUS_IMAGE_PANEL,
    "border_width": WIDTH_CARD_BORDER_NORMAL,
    "border_color": COLOR_BORDER,
}
STYLE_REASONING_TEXT = {
    "color": COLOR_TEXT_SECONDARY,
    "font_size": FONT_REASONING_TEXT,
}
STYLE_STATUS_TEXT = {
    "color": COLOR_TEXT_SECONDARY,
    "font_size": FONT_REASONING_TEXT,
}
STYLE_PANEL_SUBHEADER = {
    "color": COLOR_TEXT_DIM,
    "font_size": 15,
}


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER WIDGETS
# ═══════════════════════════════════════════════════════════════════════════════

def section_header(text: str):
    with ui.ZStack(height=HEIGHT_SECTION_HEADER):
        ui.Rectangle(style={"background_color": COLOR_SECTION_HEADER_BG})
        ui.Rectangle(width=WIDTH_ACCENT_BAR, style={"background_color": COLOR_ACCENT})
        ui.Label(
            "    " + text,
            style={"color": COLOR_TEXT_PRIMARY, "font_size": FONT_SECTION_TITLE},
            alignment=ui.Alignment.LEFT_CENTER)


def card_header(text: str, height: int = HEIGHT_CARD_HEADER, bar_width: int = WIDTH_ACCENT_BAR, font_size: int = FONT_CARD_TITLE):
    """Section title for use inside a card."""
    with ui.ZStack(height=height):
        ui.Rectangle(style={"background_color": COLOR_SECTION_HEADER_BG})
        with ui.HStack():
            ui.Rectangle(width=bar_width, style={"background_color": COLOR_ACCENT})
            ui.Label(
                "  " + text,
                style={"color": COLOR_TEXT_PRIMARY, "font_size": font_size},
                alignment=ui.Alignment.LEFT_CENTER)


def card_header_wiz(text: str, height: int = HEIGHT_CARD_HEADER, bar_width: int = WIDTH_ACCENT_BAR,
                     font_size: int = FONT_WIZARD_CARD_TITLE, color: int = COLOR_WIZARD_CARD_TITLE):
    """Wizard-only card_header() variant (issue #41).

    Identical layout to card_header(), but defaults to the brighter/larger
    Contact-Us-matching title (#e6e9ec @ 16px) instead of card_header()'s
    shared COLOR_TEXT_PRIMARY/FONT_CARD_TITLE (#e8e8e8 @ 17px). card_header()
    itself is untouched — it's still used by the main window's Section 1-4
    headers and the Contact Us card.
    """
    with ui.ZStack(height=height):
        ui.Rectangle(style={"background_color": COLOR_SECTION_HEADER_BG})
        with ui.HStack():
            ui.Rectangle(width=bar_width, style={"background_color": COLOR_ACCENT})
            ui.Label(
                "  " + text,
                style={"color": color, "font_size": font_size},
                alignment=ui.Alignment.LEFT_CENTER)


def wizard_badge(text: str, ok: bool = True,
                  width: int = WIDTH_WIZARD_BADGE, height: int = HEIGHT_WIZARD_BADGE):
    """Outlined status badge chip (wizard landing-page path cards).

    ``ok=True`` renders the green "recommended" outline, ``ok=False`` the
    amber "warning" outline (near-background fill + colored 1px border +
    colored text, same Method as `status_pill()`). Sized to a fixed-size
    ZStack rather than to its content, since the two path cards need equal-
    width chips.
    """
    bg_style = STYLE_WIZARD_BADGE_OK if ok else STYLE_WIZARD_BADGE_WARN
    text_style = STYLE_WIZARD_BADGE_OK_TEXT if ok else STYLE_WIZARD_BADGE_WARN_TEXT
    with ui.ZStack(width=width, height=height):
        ui.Rectangle(style=bg_style)
        ui.Label(text, style=text_style, alignment=ui.Alignment.CENTER)


def apply_tooltip(widget, text: str, width: int = 240) -> None:
    """Apply a consistently styled, content-sized tooltip to any widget.

    Issue #45 (round 2). The tooltip popup's auto-fit sizing is poisoned by
    any UNSIZED HStack/VStack/Spacer sandwich wrapping a word_wrap Label —
    the popup then renders at a fixed ~320x110 regardless of text length,
    and adding explicit heights to that same sandwich (the first-round fix,
    the old apply_tooltip_wiz) does NOT cure it.

    Working structure (live-verified 2026-07-09, short + long strings, on a
    real STYLE_WIZ_BTN_PRIMARY_BASE button under a margin-cascading parent):
    a top-level ZStack with explicit width/height whose ONLY children are
    the chrome Rectangle and the Label — no intermediate stacks. Padding is
    done via the Label's margin_width/margin_height style, not Spacers.
    Two extra gotchas handled here:
      * the host context's cascaded "margin" style (e.g. the wizard footer
        HStack's ``style={"margin": 12}``) leaks INTO the popup content and
        insets the Rectangle, exposing the popup background (which is the
        host button's background_color — red for primary/danger buttons);
        every node therefore pins margin explicitly;
      * a host-style ``"Tooltip"`` sub-style dict does NOT restyle
        set_tooltip_fn popups at all, so the Rectangle must stay for chrome.

    Content size is estimated from text length: measured ~5 px/char and
    13.6 px line height at FONT_DESCRIPTION (12), so 6 px/char and 16 px
    lines are conservative (over-estimate → never clips). Short strings get
    a narrower box instead of always padding out to ``width``.
    """
    _PX_PER_CHAR = 6   # measured ~5 px/char at FONT_DESCRIPTION 12; 6 is safe
    _LINE_H = 16       # measured 13.6 px natural line height; 16 adds leading
    _PAD = 8
    _segs = text.split("\n")
    _label_w = min(width, max(max(len(s) for s in _segs) * _PX_PER_CHAR, 30))
    _cpl = max(1, _label_w // _PX_PER_CHAR)
    _lines = sum(max(1, -(-len(s) // _cpl)) for s in _segs)  # ceil, no import
    _label_h = _lines * _LINE_H

    def _build():
        with ui.ZStack(width=_label_w + 2 * _PAD, height=_label_h + 2 * _PAD,
                       style={"margin": 0}):
            ui.Rectangle(
                style={
                    "background_color": COLOR_BUTTON_BG,
                    "border_radius": 0,
                    "border_width": WIDTH_BTN_BORDER,
                    "border_color": COLOR_BORDER,
                    "margin": 0,
                },
            )
            ui.Label(text, word_wrap=True, alignment=ui.Alignment.LEFT_CENTER,
                     style={
                         "color": COLOR_TEXT_SECONDARY,
                         "font_size": FONT_DESCRIPTION,
                         "margin_width": _PAD,
                         "margin_height": _PAD,
                     })

    widget.set_tooltip_fn(_build)


def apply_tooltip_wiz(widget, text: str, width: int = 240) -> None:
    """Alias of apply_tooltip(), kept for the wizard call sites (issue #45).

    Historically a separate "content-sized" variant that kept the unsized-
    stack sandwich and only added explicit heights — which live measurement
    showed does nothing (popup still ~320x110 for any text). The structural
    fix now lives in apply_tooltip() and applies everywhere, so this is a
    pure alias retained for source compatibility with the wizard factories.
    """
    apply_tooltip(widget, text, width)


def primary_button(text, clicked_fn, height=HEIGHT_BTN_PRIMARY, tooltip="", width=0):
    kwargs = dict(
        height=height, clicked_fn=clicked_fn,
        style=STYLE_WIZ_BTN_PRIMARY_BASE)
    if width:
        kwargs["width"] = width
    btn = ui.Button(text, **kwargs)
    if tooltip:
        apply_tooltip_wiz(btn, tooltip)
    return btn


def danger_button(text, clicked_fn, height=HEIGHT_BTN_PRIMARY, tooltip="", width=0):
    kwargs = dict(
        height=height, clicked_fn=clicked_fn,
        style=STYLE_WIZ_BTN_PRIMARY_BASE)
    if width:
        kwargs["width"] = width
    btn = ui.Button(text, **kwargs)
    if tooltip:
        apply_tooltip_wiz(btn, tooltip)
    return btn


def secondary_button(text, clicked_fn, height=HEIGHT_BTN_SECONDARY, tooltip="", width=0, alignment=None, tooltip_width: int = 240):
    kwargs = dict(
        height=height, clicked_fn=clicked_fn,
        style={
            "background_color": COLOR_BUTTON_BG,
            "border_radius": RADIUS_BTN,
            "border_width": WIDTH_BTN_BORDER,
            "border_color": COLOR_BORDER,
            "color": COLOR_TEXT_PRIMARY,
            "font_size": FONT_BTN_SECONDARY,
            ":hovered": {"background_color": COLOR_BORDER},
            ":disabled": {"background_color": COLOR_PANEL_BG, "color": COLOR_TEXT_DIM, "border_color": COLOR_BORDER},
            "Tooltip": STYLE_TOOLTIP,
        })
    if width:
        kwargs["width"] = width
    if alignment is not None:
        kwargs["alignment"] = alignment
    btn = ui.Button(text, **kwargs)
    if tooltip:
        apply_tooltip(btn, tooltip, width=tooltip_width)
    return btn


def intro_button(text, clicked_fn, icon_path: str = "", tooltip: str = "", tooltip_width: int = 240,
                 center_vertically: bool = True, pill_width: int = 0):
    """Pill-style icon+text button — main-window banner intro-strip controls
    (issue #52). Distinct from secondary_button: fixed dedicated palette
    (STYLE_INTRO_BTN) and width=0
    so the pill hugs its content instead of using a hardcoded box size.

    Issue #52 regression note: omni.ui's native ``ui.Button(image_url=...)``
    slot hard-codes a VERTICAL image-above-label layout with no style/kwarg
    to make it horizontal, so the icon rendered stacked on top of the text.
    The pill is therefore composed manually with the same pattern as the
    wizard path cards (choose_server.py) / ``wizard_badge`` / ``status_pill``:
    a ``ui.ZStack`` holding a chrome ``ui.Rectangle`` plus an icon+label
    ``ui.HStack``, with click/hover wired via ``set_mouse_pressed_fn`` /
    ``set_mouse_hovered_fn`` on the ZStack. No ``ui.Button`` at all — live
    verification showed a chrome Button inside a ZStack keeps its thin
    natural height instead of filling the stack. The pill ZStack is
    sandwiched between two stretchy Spacers in a hugging VStack because its
    ``height=26`` is only a floor: placed bare in the tall banner HStack it
    stretched to the full banner height.
    STYLE_INTRO_BTN's ``margin_width`` (the old native button's 11px
    horizontal text inset) must NOT reach the chrome Rectangle — it would
    inset the pill inside its ZStack — so the inset is provided by explicit
    Spacers in the content row instead.
    """
    _bg_normal = {
        "background_color": CLR_INTRO_BTN_BG,
        "border_radius": RADIUS_INTRO_BTN,
        "border_width": 1,
        "border_color": CLR_INTRO_BTN_BORDER,
        "margin": 0,
    }
    _bg_hover = dict(_bg_normal, background_color=CLR_INTRO_BTN_BG_HOV)
    _txt_normal = {"color": CLR_INTRO_BTN_TXT, "font_size": FONT_INTRO_BTN, "margin": 0}
    _txt_hover = {"color": CLR_INTRO_BTN_TXT_HOV, "font_size": FONT_INTRO_BTN, "margin": 0}

    def _build_pill():
        pill = ui.ZStack(width=pill_width, height=HEIGHT_INTRO_BTN, style={"margin": 0})
        with pill:
            bg_rect = ui.Rectangle(style=_bg_normal)
            with ui.HStack(spacing=SPACING_INTRO_BTN_ICON, height=HEIGHT_INTRO_BTN,
                            style={"margin": 0}):
                ui.Spacer(width=PADDING_INTRO_BTN_SIDE)
                if icon_path:
                    # Vertical-center the fixed 12px glyph in the 26px pill
                    # with explicit computed Spacers (alignment= kwargs are
                    # unreliable).
                    with ui.VStack(width=WIDTH_INTRO_BTN_ICON, spacing=0,
                                    style={"margin": 0}):
                        ui.Spacer(height=(HEIGHT_INTRO_BTN - HEIGHT_INTRO_BTN_ICON) // 2)
                        ui.Image(icon_path,
                                 width=WIDTH_INTRO_BTN_ICON, height=HEIGHT_INTRO_BTN_ICON,
                                 fill_policy=ui.FillPolicy.PRESERVE_ASPECT_FIT,
                                 style={"margin": 0})
                        ui.Spacer(height=(HEIGHT_INTRO_BTN - HEIGHT_INTRO_BTN_ICON) // 2)
                lbl = ui.Label(text, width=0, alignment=ui.Alignment.LEFT_CENTER,
                               style=_txt_normal)
                ui.Spacer(width=PADDING_INTRO_BTN_SIDE)
        return pill, bg_rect, lbl

    # STYLE_BANNER_HSTACK's margin cascades to every descendant of the
    # banner, so the pill's own wrapper/ZStack/
    # HStack/icon VStack/Image all need an explicit margin:0 override or
    # they inherit the banner's inset and inflate/hide the icon.
    if center_vertically:
        with ui.VStack(width=0, spacing=0, style={"margin": 0}):
            ui.Spacer()  # stretchy pair vertically centers the fixed-height pill
            pill, bg_rect, lbl = _build_pill()
            ui.Spacer()
    else:
        pill, bg_rect, lbl = _build_pill()

    def _on_pressed(_x, _y, button, _mod):
        if button == 0 and clicked_fn is not None:
            clicked_fn()

    def _on_hovered(hovered):
        bg_rect.style = _bg_hover if hovered else _bg_normal
        lbl.style = _txt_hover if hovered else _txt_normal

    pill.set_mouse_pressed_fn(_on_pressed)
    pill.set_mouse_hovered_fn(_on_hovered)
    if tooltip:
        apply_tooltip(pill, tooltip, width=tooltip_width)
    return pill


def secondary_button_wiz(text, clicked_fn, height=HEIGHT_BTN_SECONDARY, tooltip="", width=0):
    """Outlined (transparent-fill) secondary button — wizard-only, matches mockup."""
    kwargs = dict(
        height=height, clicked_fn=clicked_fn,
        style={
            "background_color": 0x00000000,
            "border_radius": RADIUS_BTN,
            "border_width": WIDTH_BTN_BORDER,
            "border_color": COLOR_BORDER,
            "color": COLOR_TEXT_PRIMARY,
            "font_size": FONT_BTN_SECONDARY,
            ":hovered": {"background_color": COLOR_BUTTON_BG},
            ":disabled": {"background_color": 0x00000000, "color": COLOR_TEXT_DIM, "border_color": COLOR_BORDER},
            "Tooltip": STYLE_TOOLTIP,
        })
    if width:
        kwargs["width"] = width
    btn = ui.Button(text, **kwargs)
    if tooltip:
        apply_tooltip_wiz(btn, tooltip)
    return btn


def danger_button_wiz_outline(text, clicked_fn, height=HEIGHT_BTN_SECONDARY, tooltip="", width=0):
    """Outlined (transparent-fill) destructive button — red border/text, wizard-only.

    Distinct from secondary_button_wiz (neutral outline) and danger_button (solid
    red fill) — matches full_png/06-remote-uninstall.png's "Forget This Server".
    """
    kwargs = dict(
        height=height, clicked_fn=clicked_fn,
        style={
            "background_color": 0x00000000,
            "border_radius": RADIUS_BTN,
            "border_width": WIDTH_BTN_BORDER,
            "border_color": COLOR_ACCENT,
            "color": COLOR_ACCENT,
            "font_size": FONT_BTN_SECONDARY,
            ":hovered": {"background_color": COLOR_ACCENT_DARK, "color": COLOR_TEXT_PRIMARY},
            ":disabled": {"background_color": 0x00000000, "color": COLOR_TEXT_DIM, "border_color": COLOR_BORDER},
            "Tooltip": STYLE_TOOLTIP,
        })
    if width:
        kwargs["width"] = width
    btn = ui.Button(text, **kwargs)
    if tooltip:
        apply_tooltip_wiz(btn, tooltip)
    return btn


def label(text, dim=False, size=FONT_LABEL, height=0, word_wrap=False):
    kwargs = {"style": {"color": COLOR_TEXT_DIM if dim else COLOR_TEXT_SECONDARY, "font_size": size}}
    if height:
        kwargs["height"] = height
    if word_wrap:
        kwargs["word_wrap"] = True
    return ui.Label(text, **kwargs)


def string_row(caption: str, default: str = "", width_caption=WIDTH_INPUT_CAPTION_DEFAULT):
    """Caption + StringField; returns the model."""
    with ui.HStack(height=HEIGHT_INPUT_ROW, spacing=SPACING_INPUT_ROW):
        ui.Label(caption, width=width_caption,
                 style={"color": COLOR_TEXT_SECONDARY, "font_size": FONT_DESCRIPTION})
        f = ui.StringField(height=HEIGHT_INPUT_FIELD, style=STYLE_INPUT_FIELD)
        f.model.set_value(default)
    return f.model


def warning_window(
    title: str,
    message: str,
    items: list,
    footer: str,
    confirm_label: str,
    on_confirm,
    on_cancel=None,
    *,
    danger: bool = True,
    width: int = 380,
    height: int = 0,
    parent_win=None,
) -> "ui.Window":
    """Create and return a Radeis-styled confirmation dialog.

    The window auto-destroys when either button is pressed.  Caller must
    store the returned reference in an instance attribute to prevent GC.
    ``on_confirm`` / ``on_cancel`` are called *after* the window is destroyed.
    """
    _items = list(items)
    if height == 0:
        # Each item row may wrap once on long paths → allocate 32px per item.
        _content_h = 8   # top spacer
        if message:
            _content_h += 16 + 4
        if _items:
            _content_h += len(_items) * 32 + 4  # 32 per item allows one wrap
        if footer:
            _content_h += 16 + 4
        _content_h += 8 + 4   # gap spacer
        _content_h += 30 + 4  # buttons
        _content_h += 6       # bottom spacer
        height = 28 + _content_h  # no title bar overhead (NO_TITLE_BAR flag used)

    win = ui.Window(
        title,
        width=width, height=height,
        flags=(ui.WINDOW_FLAGS_NO_SCROLLBAR |
               ui.WINDOW_FLAGS_NO_RESIZE |
               ui.WINDOW_FLAGS_NO_COLLAPSE |
               ui.WINDOW_FLAGS_NO_TITLE_BAR),
    )
    win.frame.set_style(STYLE_WINDOW_FRAME)

    if parent_win is not None:
        try:
            win.position_x = parent_win.position_x + (parent_win.width - width) // 2
            win.position_y = parent_win.position_y + (parent_win.height - height) // 2
        except Exception:  # noqa: BLE001
            pass

    def _deferred_destroy_then(cb):
        # win.destroy() must not run synchronously from inside the button's
        # own click callback -- that callback is invoked mid-draw of this
        # same window's frame, and destroying it there tears down the
        # Container being drawn out from under the draw call, raising
        # "Container::destroy" (see issue #43). Defer to the next app-update
        # tick instead, mirroring choose_server.py's _async_landing_gpu_check
        # idiom. The documented "callback fires after destroy" contract is
        # preserved -- cb() still runs only once win is gone.
        async def _run():
            await omni.kit.app.get_app().next_update_async()
            try:
                win.destroy()
            except Exception:  # noqa: BLE001
                pass
            if cb:
                cb()
        asyncio.ensure_future(_run())

    def _do_cancel():
        _deferred_destroy_then(on_cancel)

    def _do_confirm():
        _deferred_destroy_then(on_confirm)

    with win.frame:
        with ui.VStack(spacing=0):
            card_header(title)
            with ui.ZStack():
                ui.Rectangle(style=STYLE_CARD)
                with ui.VStack(spacing=4, style={"margin_width": PADDING_CARD_SIDE}):
                    ui.Spacer(height=8)
                    if message:
                        ui.Label(message, height=16, style=STYLE_WIZARD_BODY_LABEL)
                    if _items:
                        for it in _items:
                            ui.Label(f"- {it}", height=0, word_wrap=True,
                                     style=STYLE_WIZARD_WARN_LABEL)
                    if footer:
                        ui.Label(footer, height=16, style=STYLE_WIZARD_ERROR_TEXT)
                    ui.Spacer(height=8)
                    with ui.HStack(height=30, spacing=8):
                        secondary_button("Cancel", _do_cancel, height=30,
                                         tooltip="Dismiss without changes")
                        if danger:
                            danger_button(confirm_label, _do_confirm, height=30)
                        else:
                            primary_button(confirm_label, _do_confirm, height=30)
                    ui.Spacer(height=6)
    return win


# ═══════════════════════════════════════════════════════════════════════════════
# PROGRESS RAIL — sequential 5-step overview strip
# New, additive-only block: consumed by ui/progress_rail.py (ProgressRail).
# ABGR literals converted from the spec's RGB hexes (0xAA_BB_GG_RR).
# ═══════════════════════════════════════════════════════════════════════════════

CLR_SPEC_RAIL_ORANGE   = 0xFF358AE0   # done node fill + connector — spec #E08A35
CLR_SPEC_ACCENT_RED    = 0xFF2F3BC2   # current node fill + focus ring — spec #C23B2F
CLR_SPEC_NODE_FUTURE   = 0xFF3A3733   # future node fill + connector — spec #33373A
CLR_SPEC_MUTED2        = 0xFF8A8A8A   # future-node digit label color (muted grey)

HEIGHT_PROGRESS_RAIL_ROW       = 34   # node/connector row HStack height
HEIGHT_PROGRESS_RAIL_CAPTION   = 16   # "Step N . <name>" caption label height
WIDTH_PROGRESS_RAIL_NODE       = 26   # per-node ZStack width/height (26x26)
RADIUS_PROGRESS_RAIL_NODE      = 13   # node/ring circle radius (fits the 26px box)
HEIGHT_PROGRESS_RAIL_CONNECTOR = 4    # connector line thickness

STYLE_PROGRESS_RAIL_CAPTION = {"color": COLOR_TEXT_DIM, "font_size": FONT_DESCRIPTION}


# ── FoldableSection header status slot (spec section 4: step status word +
# completion dot) — new names, additive only, do not repurpose the existing
# COLOR_STATUS_* trio used elsewhere. ──
CLR_SPEC_ONLINE_GREEN  = COLOR_STATUS_OK_MUTED  # filled dot shown only when a step completes
CLR_SPEC_STATUS_YELLOW = COLOR_STATUS_WARN      # status word — always this color, pending or done

# ── Robustness Report window (spec section 8) — additive only, new names.
# Converted from the spec doc's RGB hex to this file's ABGR int convention
# (0xAABBGGRR) rather than reusing COLOR_STATUS_* so the report's risk-grade
# palette matches the spec's literal swatches exactly. Reuses the
# CLR_SPEC_ACCENT_RED constant defined above (progress-rail block) — same
# spec swatch (#C23B2F), no need for a second HIGH RISK red. ──
CLR_SPEC_HINT_AMBER = 0xFF41A4D9  # spec "status yellow" #D9A441 — MODERATE grade, amber bar/number
CLR_SPEC_MUTED      = 0xFF938F8B  # spec "muted" #8B8F93 — fake-URL line, meta line, table headers

# ── Main-window next-action hint (issue #50) — dedicated, NOT the shared
# CLR_SPEC_HINT_AMBER above. CLR_SPEC_HINT_AMBER is also consumed by
# STYLE_SPEC_LOG_WARN (section-4 log lines), the AI Perception View's
# MODERATE-grade confidence bar (ai_percept_win.py), and report_window.py's
# amber table cells — retargeting its value would silently recolor all of
# those, which the issue never asked for. window.py's "Select at least one
# sign to attack." hint gets its own constant/style so only that label moves
# to orange/red, matching the reference accent-line swatch #D05050 — which
# is numerically identical to CLR_RED / COLOR_ACCENT already defined above,
# so this simply aliases that existing accent color under a hint-specific name.
CLR_SPEC_NEXT_ACTION_HINT = COLOR_ACCENT  # #D05050 — same value as CLR_RED


# ═══════════════════════════════════════════════════════════════════════════════
# PALETTE — global-ux-rules / progress-rail / step-frames-status /
# status-bar. Additive-only block, appended at end of file. Do not touch any
# line above this marker.
#
# omni.ui color format is ABGR = 0xAABBGGRR (alpha FF). Each token below is
# converted from the spec doc's #RRGGBB swatch by swapping the R and B bytes.
#
# NOTE (collision found at append time): CLR_SPEC_MUTED2, CLR_SPEC_ONLINE_GREEN,
# CLR_SPEC_STATUS_YELLOW and CLR_SPEC_HINT_AMBER were already defined earlier in
# this file (progress-rail / foldable-status / robustness-report blocks added
# concurrently by another in-flight task) with DIFFERENT values than this
# task's spec literals. Redefining those same names here would silently shadow
# the earlier ones for every consumer (Python keeps only the last binding),
# which risks breaking that other in-flight work. So those four names are
# intentionally NOT redefined below — see the flagged note in the task report.
# CLR_SPEC_ACCENT_RED, CLR_SPEC_RAIL_ORANGE, CLR_SPEC_NODE_FUTURE and
# CLR_SPEC_MUTED already exist above with values identical to this spec, so
# they are likewise not redefined here (no collision, just redundant).
# ═══════════════════════════════════════════════════════════════════════════════

CLR_SPEC_BRAND_GREEN   = 0xFF32C286   # #86C232 onboarding accents / CTA

# Style dicts for later rail/status/report code. Where the referenced
# CLR_SPEC_* token already exists above (ACCENT_RED, STATUS_YELLOW,
# ONLINE_GREEN, HINT_AMBER, MUTED), these dicts resolve to whatever value is
# currently bound to that name earlier in this module (see collision note).
STYLE_SPEC_STATUS_WORD = {"color": CLR_SPEC_STATUS_YELLOW, "font_size": FONT_DESCRIPTION}
STYLE_SPEC_HINT_AMBER  = {"color": CLR_SPEC_HINT_AMBER, "font_size": FONT_DESCRIPTION}
# Dedicated style for the main-window next-action hint label (issue #50) —
# see CLR_SPEC_NEXT_ACTION_HINT definition above for why this is its own
# constant rather than a reuse of STYLE_SPEC_HINT_AMBER.
STYLE_SPEC_NEXT_ACTION_HINT = {"color": CLR_SPEC_NEXT_ACTION_HINT, "font_size": FONT_DESCRIPTION}
STYLE_SPEC_LOG_INFO   = {"color": COLOR_TEXT_PRIMARY, "font_size": FONT_DESCRIPTION}   # plain primary-text info lines
STYLE_SPEC_LOG_FLIP   = {"color": CLR_SPEC_ACCENT_RED, "font_size": FONT_DESCRIPTION}
STYLE_SPEC_LOG_HELD   = {"color": CLR_SPEC_MUTED, "font_size": FONT_DESCRIPTION}
STYLE_SPEC_LOG_OK     = {"color": CLR_SPEC_ONLINE_GREEN, "font_size": FONT_DESCRIPTION}
STYLE_SPEC_LOG_WARN   = {"color": CLR_SPEC_HINT_AMBER, "font_size": FONT_DESCRIPTION}


# ═══════════════════════════════════════════════════════════════════════════════
# --- AI-perception behavior badge (baseline/inferred overlay) ---
# ═══════════════════════════════════════════════════════════════════════════════

CLR_BADGE_BORDER_GREEN = 0xFF6ABF3F         # badge pill border, unchanged/baseline state - spec css #3fbf6a
CLR_BADGE_BORDER_RED = 0xFF454BFF           # badge pill border, behavior-changed state - spec css #ff4b45
CLR_BADGE_KICKER_GREEN = 0xFF9BD77F         # badge kicker text (BASELINE / NO CHANGE) - spec css #7fd79b
CLR_BADGE_KICKER_RED = 0xFF959AFF           # badge kicker text (BEHAVIOR CHANGED) - spec css #ff9a95
CLR_BADGE_LABEL_GREEN = 0xFF83D64E          # badge big label text, green state - spec css #4ed683
CLR_BADGE_LABEL_RED = 0xFF555BFF            # badge big label text, red state - spec css #ff5b55
CLR_BADGE_BG_GREEN = 0xE01A211A             # translucent dark pill bg, slight green tint - css ~#1a211a at ~88% alpha
CLR_BADGE_BG_RED = 0xE0141420               # (retained, currently unused) original static red-tinted pill bg; the changed pill now seeds + holds CLR_BADGE_PULSE_DARK instead. css ~#201414 at ~88% alpha (ABGR; NOT 0xE0201414 which is a blue tint)
CLR_BADGE_RING_HOLE_GREEN = 0xFF1A211A      # (retained, unused) former dark hole-punch; the pass ring now punches to the green square color
CLR_BADGE_ICON_WHITE = 0xFFFFFFFF            # white glyph/ring inside the rounded square - css #ffffff (the '!' and the pass ring)

BADGE_ICON_BOX = 24                         # icon ZStack width/height (px) - both badge icons are 24px rounded squares
BADGE_HEIGHT = 46                           # pill overall height: 26px icon + 9px kicker/17px label two-line text block + padding
BADGE_MARGIN = 10                           # fixed top/left inset of the pill inside the image frame
RADIUS_BADGE_PILL = 10                      # pill border_radius
WIDTH_BADGE_BORDER = 2                      # pill border_width (~1.6px in spec, 2 is the safe int)
FONT_BADGE_KICKER = 9                       # small uppercase kicker line font size
FONT_BADGE_LABEL = 17                       # big behavior-label line font size (heavy weight via font_weight Bold)

CLR_BADGE_PULSE_DARK = 0xEB0C0C0C            # changed-badge pill bg pulse dark endpoint AND final hold state - css rgba(12,12,12,0.92) packed ABGR (alpha 0.92*255=234.6->235=0xEB)
CLR_BADGE_PULSE_LIGHT = 0xF2FFFFFF          # changed-badge pill bg pulse light endpoint - css rgba(255,255,255,0.95) packed ABGR (alpha 0.95*255=242.25->242=0xF2)
BADGE_PULSE_CYCLES = 8                      # exact number of dark->light->dark bg pulse cycles on a new CHANGED result, then hold on CLR_BADGE_PULSE_DARK
BADGE_PULSE_CYCLE_S = 0.6                   # seconds per pulse cycle, ease-in-out via 0.5-0.5*cos(2*pi*phase); total pulse ~4.8s, sampled from real elapsed time (frame-synced, not a timer tick)


# ═══════════════════════════════════════════════════════════════════════════════
# --- Banner "Intro" button pill style (issue #52) ---
# Main-window banner control only (NOT wizard-scoped). Dedicated palette, not
# a reuse of secondary_button's generic look, per the spec's exact swatches.
# ABGR literals converted from the spec's #RRGGBB via 0xFF | (B<<16)|(G<<8)|R.
# NOTE: the spec doc's own worked example got two of these wrong (BG_HOV and
# BORDER, off by a swapped/mistyped byte) -- values below are the corrected,
# independently-recomputed conversions:
#   BG      #2F3234 -> 0xFF34322F   (spec doc had this one right)
#   BG_HOV  #3A3E42 -> 0xFF423E3A   (spec doc wrote 0xFF3E3E3A -- wrong)
#   BORDER  #101214 -> 0xFF141210   (spec doc wrote 0xFF14120F -- wrong)
#   TXT     #9AA0A5 -> 0xFFA5A09A   (spec doc had this one right)
#   TXT_HOV #D6D7D8 -> 0xFFD8D7D6   (spec doc had this one right)
# Icon stroke (#86C232) is baked into intro_icon.svg itself and reuses the
# existing CLR_SPEC_BRAND_GREEN = 0xFF32C286 value defined earlier in this
# file (same spec swatch) -- no separate constant needed.
# ═══════════════════════════════════════════════════════════════════════════════

CLR_INTRO_BTN_BG      = 0xFF34322F   # #2F3234
CLR_INTRO_BTN_BG_HOV  = 0xFF423E3A   # #3A3E42
CLR_INTRO_BTN_BORDER  = 0xFF141210   # #101214
CLR_INTRO_BTN_TXT     = 0xFFA5A09A   # #9AA0A5
CLR_INTRO_BTN_TXT_HOV = 0xFFD8D7D6   # #D6D7D8

HEIGHT_INTRO_BTN        = 26   # pill height
RADIUS_INTRO_BTN        = 5    # pill corner radius
PADDING_INTRO_BTN_SIDE  = 11   # horizontal inset, both sides
WIDTH_INTRO_BTN_ICON    = 12   # info-glyph icon width/height
HEIGHT_INTRO_BTN_ICON   = 12
SPACING_INTRO_BTN_ICON  = 5    # gap between icon and "Intro" label
SPACING_INTRO_BTN_STACK = 2    # vertical gap between Intro and Contact pills
WIDTH_INTRO_BTN_STACK   = 82   # content-sized width for equal Intro/Contact strip pills
FONT_INTRO_BTN          = 11

HEIGHT_INTRO_BTN_STACK = HEIGHT_INTRO_BTN * 2 + SPACING_INTRO_BTN_STACK
PADDING_INTRO_BTN_STACK_TOP = max(0, (HEIGHT_BANNER - HEIGHT_INTRO_BTN_STACK) // 2)
PADDING_INTRO_BTN_STACK_BOTTOM = max(
    0, HEIGHT_BANNER - HEIGHT_INTRO_BTN_STACK - PADDING_INTRO_BTN_STACK_TOP)

STYLE_INTRO_BTN = {
    "background_color": CLR_INTRO_BTN_BG,
    "border_radius": RADIUS_INTRO_BTN,
    "border_width": 1,
    "border_color": CLR_INTRO_BTN_BORDER,
    "color": CLR_INTRO_BTN_TXT,
    "font_size": FONT_INTRO_BTN,
    "margin_width": PADDING_INTRO_BTN_SIDE,
    ":hovered": {"background_color": CLR_INTRO_BTN_BG_HOV, "color": CLR_INTRO_BTN_TXT_HOV},
    "Tooltip": STYLE_TOOLTIP,
}

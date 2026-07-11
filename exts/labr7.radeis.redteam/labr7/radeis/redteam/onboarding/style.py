"""Onboarding card — UI style constants.

All numeric and color values for the intro-card window live here.
Colors are in omni.ui ABGR format: 0xAABBGGRR.
"""
from __future__ import annotations

# ── Window geometry ─────────────────────────────────────────────────────────
WIN_W = 470          # onboarding window width  (px)
WIN_H = 640          # onboarding window height (px) — max across all slides
WIN_H_SLIDES = [595, 610, 510]  # per-slide heights: resized on navigate to avoid dead space
WIN_X = 10           # initial screen x — left side
WIN_Y = 30           # initial screen y — below Isaac Sim menu bar


# ── Colors — ABGR = 0xAABBGGRR ──────────────────────────────────────────────
CLR_GREEN           = 0xFF16CC84   # #84CC16  lime-600 (softer grass green)
CLR_WIN_BG          = 0xFF17110D   # #0d1117  deep dark window bg
CLR_CARD_BG         = 0xFF181212   # rgba(18,18,24)  card shell
CLR_TITLE           = 0xFFFFFFFF   # #ffffff  bright white
CLR_BODY            = 0x8CFFFFFF   # rgba(255,255,255,0.55)
CLR_COUNTER         = 0x47FFFFFF   # rgba(255,255,255,0.28)
CLR_CAPTION_SUB     = 0x73FFFFFF   # rgba(255,255,255,0.45)
CLR_DOT_INACTIVE    = 0x2EFFFFFF   # rgba(255,255,255,0.18)
CLR_TAG_BG          = 0x33003D1A   # dark green 0.20 alpha (cooler, less olive)
CLR_TAG_BORDER      = 0x5516CC84   # lime-600 border 0.33 alpha
CLR_CAPTION_AREA_BG = 0x1216CC84   # lime-600 tint 0.07 alpha
CLR_FEATURE_ROW_BG  = 0x33000000   # black 0.20 alpha
CLR_FEATURE_BORDER  = 0x0FFFFFFF   # white 0.06 alpha
CLR_FOOTER_BORDER   = 0x0DFFFFFF   # white 0.05 alpha
CLR_BTN_GHOST_FG    = 0x61FFFFFF   # rgba(255,255,255,0.38)
CLR_BTN_GHOST_BDR   = 0x1AFFFFFF   # rgba(255,255,255,0.10)
CLR_BTN_PRIMARY_FG  = 0xFF17110D   # dark text on green button
CLR_PLACEHOLDER_BG  = 0xFF0A0808   # image placeholder dark fill
CLR_PLACEHOLDER_BDR = 0x12FFFFFF   # image placeholder border

# ── Font sizes (px) ──────────────────────────────────────────────────────────
FS_TAG        = 10
FS_COUNTER    = 10
FS_TITLE      = 26
FS_BODY       = 14
FS_CAPTION    = 14
FS_SUB        = 14
FS_FEAT_TITLE = 13
FS_FEAT_DESC  = 12
FS_BTN        = 13

# ── Bold font path — bundled with the extension (SIL OFL 1.1) ─────────────────
import os as _os
FONT_BOLD: str = _os.path.join(_os.path.dirname(__file__), "fonts", "LiberationSans-Bold.ttf")

# ── Spacing / element sizes ──────────────────────────────────────────────────
ACCENT_BAR_H    = 3    # top gradient accent bar height
SIDE_PAD        = 28   # horizontal + vertical margin inside slide (HTML 28px)
GAP             = 14   # vertical gap between slide sections (HTML gap:14px)
DOT_W           = 6    # inactive progress-dot width
DOT_W_ACTIVE    = 18   # active  progress-dot width
DOT_H           = 6    # dot height
CAPTION_ICON_W  = 24   # caption icon size
CAPTION_H       = 56   # caption bar fixed height — ensures icon centers with text
FEAT_ICON_W     = 36   # feature-row icon size (bumped from 32 for reference proportions)
FOOTER_H        = 54   # footer strip height
TAG_H             = 20   # tag pill height
TAG_BORDER_RADIUS = 20   # fully-rounded pill (HTML border-radius: 20px)
BTN_BORDER_RADIUS = 8    # Next/primary button corner radius (moderate pill)
HEADER_PAD_TOP  = 24   # HTML .slide-header padding-top
HEADER_PAD_BTM  = 14   # HTML .slide-header padding-bottom
CONTENT_PAD_BTM = 10   # HTML .slide-content padding-bottom
VISUAL_H        = 200  # visual placeholder height (fallback only)
VISUAL_H_SLIDE  = [231, 260]  # per-slide visual heights: page1(1173×654→231px), page2(1251×787→260px)

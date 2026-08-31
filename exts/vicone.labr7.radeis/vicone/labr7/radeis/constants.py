"""
Shared constants for vicone.labr7.radeis.

Path-related constants (asset dirs, robot USD, bag path) are NOT defined here.
All path resolution happens at runtime in WarehouseWindow using ext_path.
Only stable prim paths, style values, and numeric tuning parameters live here.
"""

# =============================================================================
# Feature Flags
# =============================================================================
ONBOARDING_ENABLED = True   # set False to suppress the intro-card carousel on launch

# =============================================================================
# USD Prim Paths
# =============================================================================
FIX_POINT_PATH        = "/World/transporter/fix_point"
ROBOT_PRIM_PATH       = "/World/robot_visual"
TRANSPORTER_PRIM_PATH = "/World/transporter"


# =============================================================================
# Style Constants  (ABGR format for omni.ui)
# =============================================================================
CLR_BG         = 0xFF1A1A1A
CLR_CARD       = 0xFF242424
CLR_SECTION_BG = 0xFF2C2C2C
CLR_RED        = 0xFF5050D0
CLR_RED_DARK   = 0xFF30308B
CLR_WHITE      = 0xFFE8E8E8
CLR_GREY       = 0xFFAAAAAA
CLR_GREY_DIM   = 0xFF666666
CLR_BTN        = 0xFF333333
CLR_BORDER     = 0xFF404040
CLR_ACCENT     = CLR_RED
CLR_CARD_SELECTED = 0xFF2A2A3D  # 15% accent tint on CLR_CARD (ABGR: A=FF, B=2A, G=2A, R=3D)
CLR_CARD_SELECTED_STRONG = 0xFF313158  # ~30% accent tint on CLR_CARD (ABGR: A=FF, B=31, G=31, R=58) —
                                        # Test Signs grid selected row; bolder than the 15% wizard-card tint
                                        # so a checked row reads as a filled card, not a hairline outline.

# Extra Radeis-style colors for v0.2 (VicOne magenta + status)
CLR_MAGENTA    = 0xFF6D1CE8   # VicOne magenta accent (ABGR of rgb(232,28,109))
CLR_OK         = 0xFF4ADE80
CLR_WARN       = 0xFF4DC4FF
CLR_DANGER     = 0xFF4444EF
CLR_PANEL      = 0xFF202020

# =============================================================================
# v0.2 — Red-team tester (generic platform / stations / model-under-test)
# =============================================================================
# Generic prim-path conventions (replace warehouse-specific sign-board paths).
PLATFORM_PRIM_PATH   = "/World/platform"          # kinematic moving platform
ROBOT_ROOT_PATH      = "/World/robot"             # robot articulation root (sibling; pinned each step)
BODY_FIX_PATH        = "/World/platform/body_fix" # height-adaptive mount anchor
FPV_CAMERA_PATH      = "/World/platform/fpv_cam"   # forward-facing FPV camera
STATIONS_ROOT        = "/World/stations"
STATION_ROOT_FMT     = "/World/stations/station_{:02d}"
STATION_SIGN_FMT     = "/World/stations/station_{:02d}/sign"        # sign mesh
STATION_SIGN_MAT_FMT = "/World/Looks/StationSign_{:02d}"            # sign material

# The 9 standard action tokens the model-under-test can emit.
ACTION_TOKENS = ["Idle", "Forward", "Backward", "TurnLeft", "TurnRight",
                 "Stop", "EmergencyStop", "Run", "Jump"]

# Test-sample categories. Internal keys (used as dict keys / payload fields) — do not rename.
TEST_CATEGORIES = ["traffic", "iso_warning", "typography", "adv_patch"]

# Human-readable display labels for each internal category key (UI-facing only).
TEST_CATEGORY_LABELS = {
    "traffic": "Traffic",
    "iso_warning": "Warning Signs",
    "typography": "Typography",
    "adv_patch": "Adversarial Patches",
}

# =============================================================================
# Attack-Approach Taxonomy
# =============================================================================
# Canonical set of adversarial "attack approaches" a sign is tested against.
# Station count for a run (baseline + one station per approach) is driven by
# the LENGTH of this list -- NOT by how many attack PNGs a given sign happens
# to ship with on disk (data/test_samples/index.json "attacks" entries).
# Adding/removing an approach here is the ONLY thing that should change how
# many stations the patrol route has; signs with fewer PNGs than
# len(ATTACK_APPROACHES) simply leave the corresponding station(s) blank
# (see scene/stations.py assign_sign()) instead of shrinking the route.
#
# The shipped index.json has no explicit *named* attack-approach taxonomy --
# its "attacks" dict keys are per-sign ordinal strings ("1".."N") assigned at
# data-generation time, and the same numeric id does not denote the same
# underlying perturbation type across different signs (e.g. id "1" is a
# "translucent" overlay for turn_right but a "localized" patch for stop; see
# traffic/{stop,turn_right}/*_mod/<type>/ subfolders on disk). The four
# perturbation types that recur across signs there are localized,
# noise_poster, translucent, typography -- matching the maximum attack-id
# count shipped in the data (turn_right ships ids "1".."4"), so N=4 is the
# settled station count. This list is the single source of truth for it.
ATTACK_APPROACHES = ["1", "2", "3", "4"]

# Station sample roles. These strings are load-bearing across three modules --
# scene.stations assigns them, vlm.pipeline.compare_sign() scores ONLY
# ROLE_ATTACK, and report.report renders ROLE_FILLER as "NOT TESTED" -- so they
# live here rather than in any one of them. A board that merely displays a
# picture (no attack variant assigned) must never carry ROLE_ATTACK.
ROLE_BASELINE = "baseline"
ROLE_ATTACK = "attack"
ROLE_FILLER = "filler"

# Sidecar defaults (overridable via carb settings).
SIDECAR_URL_DEFAULT  = "http://127.0.0.1:8765"

# FPV capture resolution — 4:3. gemma's image-patch grid is aspect-auto-detected
# by the sidecar at runtime (not a fixed size); 4:3 factors cleanly (e.g. 19x14).
FPV_WIDTH            = 640
FPV_HEIGHT           = 480

# Run defaults
DWELL_SECONDS_DEFAULT = 3.0      # dwell at each station (UI-configurable)
TRAJ_BIAS_K_DEFAULT   = 0.5      # VLA trajectory-bias threshold (metres)
PLATFORM_SPEED_MPS    = 1.2      # cruise speed of the platform along the route

# Fix-point Z per robot so feet exactly touch the cart deck surface.
# Approximate values — re-measure from USD bbox after visual check.
ROBOT_FIX_HEIGHTS = {
    "Spot":    0.51,   # Boston Dynamics Spot standing height (body origin to foot)
    "Go2":     0.28,   # Unitree Go2 leg length in standing pose
    "Agility": 1.05,   # Digit v4 pelvis-to-foot distance
    "Fourier": 0.95,   # Fourier GR-1 pelvis-to-foot distance
}

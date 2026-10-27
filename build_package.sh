#!/usr/bin/env bash
# Build the installable Radeis Red-Team bundle.
#
# Produces two artifacts in dist/:
#   1. Registry ZIP  — Omniverse Community Registry format (exts/ at root)
#      Name: {github-namespace}-{github-repo}-linux-x86_64-v{VER}.zip
#      Structure required by NVIDIA's nightly discovery pipeline.
#
#   2. Sidecar ZIP   — standalone inference sidecar deliverable
#      Name: labr7-radeis-sidecar-v{VER}.zip
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
GH_NS="VicOne-OSS-TW"
GH_REPO="labr7-radeis-InSimPhysicalAI"
EXT="vicone.labr7.radeis"
EXT_ROOT="$ROOT/exts/$EXT"

# Version comes from the release tag (v1.2.3 -> 1.2.3) with the manifest as a
# fallback for local/dev builds not run from a tag. Either way it must match
# extension.toml's [package].version, or the ZIP filename would disagree with
# the manifest a user actually installs.
TOML_VER="$(sed -n 's/^version = "\(.*\)"/\1/p' "$EXT_ROOT/config/extension.toml" | head -1)"
VER="${GITHUB_REF_NAME:+${GITHUB_REF_NAME#v}}"
VER="${VER:-$TOML_VER}"

if [ "$VER" != "$TOML_VER" ]; then
  echo "ERROR: version mismatch — release tag resolves to v$VER but extension.toml has v$TOML_VER" >&2
  exit 1
fi

require_file() {
  local p="$1"
  [ -f "$p" ] || {
    echo "ERROR: required file missing: $p" >&2
    exit 1
  }
}

require_dir() {
  local p="$1"
  [ -d "$p" ] || {
    echo "ERROR: required directory missing: $p" >&2
    exit 1
  }
}

require_dir "$EXT_ROOT/config"
require_dir "$EXT_ROOT/vicone"
require_dir "$EXT_ROOT/docs"
require_dir "$EXT_ROOT/data/icon"
require_dir "$EXT_ROOT/data/test_samples"
require_dir "$EXT_ROOT/data/inference_sidecar"
require_dir "$EXT_ROOT/data/go2_policy"
require_file "$EXT_ROOT/data/inference_sidecar/server.py"
require_file "$EXT_ROOT/data/inference_sidecar/attention_core.py"
require_file "$EXT_ROOT/data/inference_sidecar/waypoint_head.py"
require_file "$EXT_ROOT/data/inference_sidecar/heads/traffic_sign_waypoint_head.pt"
require_file "$EXT_ROOT/data/inference_sidecar/requirements.txt"
require_file "$EXT_ROOT/data/go2_policy/policy.pt"
require_file "$EXT_ROOT/data/go2_policy/env.yaml"
require_file "$EXT_ROOT/data/scenes/aws_robomaker/NOTICE.md"
require_file "$EXT_ROOT/data/scenes/aws_robomaker/scenes/aws_bookstore_loop.usda"
require_file "$EXT_ROOT/data/scenes/aws_robomaker/scenes/aws_hospital_loop.usda"
require_file "$EXT_ROOT/data/scenes/aws_robomaker/scenes/aws_small_house_loop.usda"
require_file "$ROOT/inference_sidecar/launcher.py"
require_file "$ROOT/inference_sidecar/radeis-sidecar-setup.sh"
require_file "$ROOT/inference_sidecar/radeis-sidecar-uninstall.sh"
require_file "$ROOT/SIDECAR_SETUP.md"
require_file "$ROOT/CHANGES.md"
require_file "$EXT_ROOT/TELEMETRY.md"

# ── Extension registry ZIP ────────────────────────────────────────────────────
# NVIDIA pipeline requires: {namespace}-{repo}-linux-x86_64-{tag}.zip
# ZIP must contain exts/ at root (no extra wrapper directory).
EXT_STAGE="$ROOT/dist/ext-stage"
EXT_ZIP="$ROOT/dist/${GH_NS}-${GH_REPO}-linux-x86_64-v${VER}.zip"

rm -rf "$EXT_STAGE"
mkdir -p "$EXT_STAGE/exts/$EXT"

# extension code + config
cp -r "$EXT_ROOT/config" "$EXT_STAGE/exts/$EXT/"
cp -r "$EXT_ROOT/vicone"  "$EXT_STAGE/exts/$EXT/"

# docs (README, CHANGELOG, images)
cp -r "$EXT_ROOT/docs"   "$EXT_STAGE/exts/$EXT/"
# CHANGELOG: copy root CHANGES.md into the path extension.toml references
cp "$ROOT/CHANGES.md" "$EXT_STAGE/exts/$EXT/docs/CHANGELOG.md"
# TELEMETRY.md lives at the extension root (outside docs/), so the docs/
# copy above does not pick it up. It is the only place the full field
# schema, the feedback-tier disclosure, and the withdrawal/deletion
# channel are written - docs/README.md links to it as ./TELEMETRY.md.
cp "$EXT_ROOT/TELEMETRY.md" "$EXT_STAGE/exts/$EXT/docs/TELEMETRY.md"

# data required at runtime by the setup wizard and Go2 preset.
mkdir -p "$EXT_STAGE/exts/$EXT/data"
for d in icon test_samples inference_sidecar go2_policy scenes; do
  [ -d "$EXT_ROOT/data/$d" ] && cp -r "$EXT_ROOT/data/$d" "$EXT_STAGE/exts/$EXT/data/"
done

# Scenes live in Git LFS. A checkout without LFS content leaves ~130-byte pointer
# files that would ship as broken USD/PNG, so refuse to build in that case.
if grep -rlI --include='*.usd' --include='*.usda' --include='*.png' --include='*.jpg' \
     '^version https://git-lfs' "$EXT_STAGE/exts/$EXT/data/scenes" >/dev/null 2>&1; then
  echo "ERROR: data/scenes contains Git LFS pointer files - run 'git lfs pull' first" >&2
  exit 1
fi
# Kit may run as another user when the ZIP is installed into a shared location.
chmod -R a+rX "$EXT_STAGE/exts/$EXT/data/scenes" 2>/dev/null || true

# scrub caches
find "$EXT_STAGE" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
find "$EXT_STAGE" -type f \( -name "*.bak" -o -name ".DS_Store" -o -name "*.pyc" \) -delete 2>/dev/null || true

# zip with exts/ at root (cd into stage dir so no wrapper)
rm -f "$EXT_ZIP"
(cd "$EXT_STAGE" && zip -rq "$EXT_ZIP" exts/)
echo "BUILT (registry): $EXT_ZIP"

# ── Sidecar ZIP ───────────────────────────────────────────────────────────────
SIDE_STAGE="$ROOT/dist/sidecar-stage"
SIDE_ZIP="$ROOT/dist/labr7-radeis-sidecar-v${VER}.zip"

rm -rf "$SIDE_STAGE"
mkdir -p "$SIDE_STAGE/inference_sidecar"
# Use the extension-bundled sidecar server files as the release source so the
# setup wizard and standalone sidecar ZIP expose the same HTTP API.
cp "$EXT_ROOT/data/inference_sidecar/"{server.py,attention_core.py,waypoint_head.py,requirements.txt} \
   "$SIDE_STAGE/inference_sidecar/"
cp -r "$EXT_ROOT/data/inference_sidecar/heads" "$SIDE_STAGE/inference_sidecar/"
cp "$ROOT/inference_sidecar/"{launcher.py,radeis-sidecar-setup.sh,radeis-sidecar-uninstall.sh} \
   "$SIDE_STAGE/inference_sidecar/"
cp "$ROOT/SIDECAR_SETUP.md" "$SIDE_STAGE/"

find "$SIDE_STAGE" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true

rm -f "$SIDE_ZIP"
(cd "$SIDE_STAGE" && zip -rq "$SIDE_ZIP" .)
echo "BUILT (sidecar):  $SIDE_ZIP"

# ── Artifact validation ───────────────────────────────────────────────────────
for required in \
  "exts/$EXT/data/inference_sidecar/server.py" \
  "exts/$EXT/data/inference_sidecar/attention_core.py" \
  "exts/$EXT/data/inference_sidecar/waypoint_head.py" \
  "exts/$EXT/data/inference_sidecar/heads/traffic_sign_waypoint_head.pt" \
  "exts/$EXT/data/inference_sidecar/requirements.txt" \
  "exts/$EXT/data/go2_policy/policy.pt" \
  "exts/$EXT/data/go2_policy/env.yaml" \
  "exts/$EXT/data/scenes/aws_robomaker/NOTICE.md" \
  "exts/$EXT/data/scenes/aws_robomaker/scenes/aws_bookstore_loop.usda" \
  "exts/$EXT/data/scenes/aws_robomaker/scenes/aws_hospital_loop.usda" \
  "exts/$EXT/data/scenes/aws_robomaker/scenes/aws_small_house_loop.usda"
do
  unzip -l "$EXT_ZIP" "$required" >/dev/null || {
    echo "ERROR: registry ZIP missing $required" >&2
    exit 1
  }
done

for required in \
  "inference_sidecar/server.py" \
  "inference_sidecar/attention_core.py" \
  "inference_sidecar/waypoint_head.py" \
  "inference_sidecar/heads/traffic_sign_waypoint_head.pt" \
  "inference_sidecar/requirements.txt" \
  "inference_sidecar/launcher.py" \
  "inference_sidecar/radeis-sidecar-setup.sh" \
  "inference_sidecar/radeis-sidecar-uninstall.sh"
do
  unzip -l "$SIDE_ZIP" "$required" >/dev/null || {
    echo "ERROR: sidecar ZIP missing $required" >&2
    exit 1
  }
done

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "=== Registry ZIP structure (depth 3) ==="
(cd "$EXT_STAGE" && find exts -maxdepth 3 -not -path '*/data/test_samples/*' | sort)
echo ""
echo "=== Sizes ==="
du -sh "$EXT_ZIP" "$SIDE_ZIP"

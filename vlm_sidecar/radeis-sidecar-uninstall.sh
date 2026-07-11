#!/usr/bin/env bash
#
# radeis-sidecar-uninstall.sh — Remove the Radeis VLM sidecar installation.
#
# Stops the server process, disables the radeis-launcher systemd user service
# (or kills the nohup launcher if systemd was not used), removes the venv,
# clears state/lock files, and deletes downloaded HuggingFace models (by default).
#
# Usage:
#   bash radeis-sidecar-uninstall.sh [OPTIONS]
#
# Options:
#       --venv-dir DIR       Virtual-env location (default: ~/.labr7/venv)
#       --purge-model        Also delete the model weights downloaded by Radeis
#       --purge-logs         Also delete log files (~/.labr7/logs)
#   -y, --yes                Skip all confirmation prompts (non-interactive)
#   -h, --help               Show this help and exit
#
# Examples:
#   # Default cleanup (removes venv and state files only, keeps model weights):
#   bash radeis-sidecar-uninstall.sh
#
#   # Full cleanup including the downloaded model weights:
#   bash radeis-sidecar-uninstall.sh --purge-model
#
#   # Full cleanup including model weights and logs, no prompts:
#   bash radeis-sidecar-uninstall.sh --purge-model --purge-logs --yes
#
set -euo pipefail

# ---- colours ----------------------------------------------------------------
RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[0;33m'; BLU='\033[0;34m'; RST='\033[0m'
info()  { echo -e "${BLU}[radeis-uninstall]${RST} $*"; }
ok()    { echo -e "${GRN}[radeis-uninstall]${RST} $*"; }
warn()  { echo -e "${YLW}[radeis-uninstall]${RST} $*"; }
error() { echo -e "${RED}[radeis-uninstall]${RST} $*" >&2; exit 1; }

# ---- defaults ---------------------------------------------------------------
VENV_DIR="${HOME}/.labr7/venv"
LABR7_DIR="${HOME}/.labr7"
SYSTEMD_SVC_NAME="radeis-launcher"
SYSTEMD_SVC_FILE="${HOME}/.config/systemd/user/${SYSTEMD_SVC_NAME}.service"
PURGE_MODELS=false
PURGE_LOGS=false
YES=false

# Derive the specific model directory from sidecar_config.json (only Radeis-downloaded model)
_cfg_file="${HOME}/.labr7/sidecar_config.json"
_model_repo=$(python3 -c "
import json, pathlib, sys
cfg = pathlib.Path('${_cfg_file}')
d = json.loads(cfg.read_text()) if cfg.exists() else {}
print(d.get('model_repo', 'google/gemma-4-e2b-it'))
" 2>/dev/null || echo "google/gemma-4-e2b-it")
_model_dir_name="models--$(echo "${_model_repo}" | sed 's|/|--|g')"
HF_MODEL_CACHE="${HOME}/.cache/huggingface/hub/${_model_dir_name}"

# ---- arg parse --------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --venv-dir)      VENV_DIR="$2"; shift 2 ;;
        --purge-model)   PURGE_MODELS=true; shift ;;
        --purge-logs)    PURGE_LOGS=true; shift ;;
        -y|--yes)        YES=true; shift ;;
        -h|--help)
            sed -n '3,28p' "$0"
            exit 0 ;;
        *) error "Unknown option: $1  (use -h for help)" ;;
    esac
done

# ---- helper: ask for confirmation -------------------------------------------
confirm() {
    local prompt="$1"
    if $YES; then
        echo -e "${YLW}[radeis-uninstall]${RST} $prompt — auto-confirmed (--yes)"
        return 0
    fi
    read -r -p "$(echo -e "${YLW}[radeis-uninstall]${RST} $prompt [y/N] ")" answer
    [[ "${answer,,}" == "y" ]]
}

echo ""
info "Radeis VLM Sidecar Uninstaller"
info "Venv:  $VENV_DIR"
info "State: $LABR7_DIR"
echo ""

# ---- step 1: stop running processes -----------------------------------------
info "Stopping sidecar server and launcher processes..."

# 1a. Stop server (always launched with nohup, no systemd unit)
if pkill -f "vlm_sidecar/server.py" 2>/dev/null || pkill -f "radeis.*server.py" 2>/dev/null; then
    ok "server.py stopped"
else
    info "server.py was not running"
fi

# 1b. Stop launcher — try systemd user service first, then pkill fallback
if command -v systemctl &>/dev/null \
   && systemctl --user is-active --quiet "$SYSTEMD_SVC_NAME" 2>/dev/null; then
    systemctl --user stop "$SYSTEMD_SVC_NAME" 2>/dev/null && \
        ok "systemd service '${SYSTEMD_SVC_NAME}' stopped"
    systemctl --user disable "$SYSTEMD_SVC_NAME" 2>/dev/null && \
        ok "systemd service '${SYSTEMD_SVC_NAME}' disabled"
    systemctl --user daemon-reload 2>/dev/null || true
else
    # Covers nohup installs (--no-systemd) or machines without systemd
    if pkill -f "vlm_sidecar/launcher.py" 2>/dev/null || pkill -f "radeis.*launcher.py" 2>/dev/null; then
        ok "launcher.py stopped"
    else
        info "launcher.py was not running"
    fi
fi
sleep 1

# ---- step 2: remove virtual environment ------------------------------------
if [[ -d "$VENV_DIR" ]]; then
    if confirm "Remove virtual environment at $VENV_DIR?"; then
        rm -rf "$VENV_DIR"
        ok "Removed: $VENV_DIR"
    else
        warn "Skipped: $VENV_DIR"
    fi
else
    info "Venv not found at $VENV_DIR — skipping"
fi

# ---- step 3: remove systemd service file + state/lock files ----------------

# Remove service file left by setup.sh (even if already disabled above)
if [[ -f "$SYSTEMD_SVC_FILE" ]]; then
    rm -f "$SYSTEMD_SVC_FILE"
    ok "Removed service file: $SYSTEMD_SVC_FILE"
    systemctl --user daemon-reload 2>/dev/null || true
fi

STATE_FILES=(
    "$LABR7_DIR/sidecar.pid"
    "$LABR7_DIR/sidecar.lock"
    "$LABR7_DIR/sidecar_runtime.json"
    "$LABR7_DIR/tray.pid"
    "$LABR7_DIR/model_registry.json"
)
removed_any=false
for f in "${STATE_FILES[@]}"; do
    if [[ -f "$f" ]]; then
        rm -f "$f"
        ok "Removed: $f"
        removed_any=true
    fi
done
$removed_any || info "No state files found in $LABR7_DIR"

# ---- step 4: remove logs (opt-in) ------------------------------------------
LOG_DIR="$LABR7_DIR/logs"
if [[ -d "$LOG_DIR" ]]; then
    if $PURGE_LOGS; then
        rm -rf "$LOG_DIR"
        ok "Removed logs: $LOG_DIR"
    else
        warn "Log directory kept: $LOG_DIR  (pass --purge-logs to remove)"
    fi
fi

# ---- step 5: remove Radeis model weights (opt-in via --purge-model) ---------------
if $PURGE_MODELS; then
    if [[ -d "$HF_MODEL_CACHE" ]]; then
        cache_size=$(du -sh "$HF_MODEL_CACHE" 2>/dev/null | cut -f1 || echo "unknown size")
        if confirm "Remove model weights at $HF_MODEL_CACHE ($cache_size)?"; then
            rm -rf "$HF_MODEL_CACHE"
            ok "Removed model weights: $HF_MODEL_CACHE"
        else
            warn "Skipped: $HF_MODEL_CACHE"
        fi
    else
        info "Model weights not found at $HF_MODEL_CACHE — skipping"
    fi
else
    info "Model weights kept (pass --purge-model to remove): $_model_repo"
fi

echo ""
ok "Uninstall complete."
echo ""
info "To reinstall, run:  bash radeis-sidecar-setup.sh -m google/gemma-4-e2b-it --background"

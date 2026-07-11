#!/usr/bin/env bash
#
# radeis-sidecar-setup.sh — Install and start the Radeis VLM sidecar on a remote GPU machine.
#
# Usage:
#   bash radeis-sidecar-setup.sh [OPTIONS]
#
# Options:
#   -m, --model MODEL_REPO   HuggingFace repo to download & load at server start
#                            (default: google/gemma-4-e2b-it)
#   -p, --port PORT          Server port (default: 8765)
#   -H, --host HOST          Bind address (default: 0.0.0.0)
#   -d, --device DEVICE      cuda | cpu  (default: auto-detect)
#       --hf-token TOKEN     HuggingFace token for gated model downloads
#       --token BEARER       Bearer auth token for the API (default: none)
#       --venv-dir DIR       Virtual-env location (default: ~/.labr7/venv)
#       --with-launcher      Also start the launcher daemon (port+1) in background
#                            so the Isaac Sim extension can wake the sidecar remotely
#                            (DEFAULT: enabled — pass --no-launcher to disable)
#       --no-launcher        Disable the launcher daemon
#       --no-systemd         Skip systemd service install; use nohup only
#                            (DEFAULT: install systemd user service when available so
#                            the launcher survives reboot and auto-restarts on crash)
#   -h, --help               Show this help and exit
#
# Quick start (server + launcher + systemd, all defaults — loads
# google/gemma-4-e2b-it automatically):
#   bash radeis-sidecar-setup.sh
#
# Quick start (different model, gated — needs a token):
#   bash radeis-sidecar-setup.sh -m google/gemma-4-e2b-it --hf-token hf_xxx
#
set -euo pipefail

# ---- temp files -------------------------------------------------------------
_VENV_ERR=$(mktemp)
trap 'rm -f "$_VENV_ERR"' EXIT

# ---- defaults ---------------------------------------------------------------
MODEL_REPO="google/gemma-4-e2b-it"
PORT=8765
HOST="0.0.0.0"
DEVICE="auto"
HF_TOKEN=""
BEARER_TOKEN=""
VENV_DIR="${HOME}/.labr7/venv"
BACKGROUND=false
WITH_LAUNCHER=true
WITH_SYSTEMD=true

# ---- colours ----------------------------------------------------------------
RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[0;33m'; BLU='\033[0;34m'; RST='\033[0m'
info()  { echo -e "${BLU}[radeis]${RST} $*"; }
ok()    { echo -e "${GRN}[radeis]${RST} $*"; }
warn()  { echo -e "${YLW}[radeis]${RST} $*"; }
error() { echo -e "${RED}[radeis]${RST} $*" >&2; exit 1; }

# ---- arg parse --------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        -m|--model)      MODEL_REPO="$2";    shift 2 ;;
        -p|--port)       PORT="$2";           shift 2 ;;
        -H|--host)       HOST="$2";           shift 2 ;;
        -d|--device)     DEVICE="$2";         shift 2 ;;
        --hf-token)      HF_TOKEN="$2";       shift 2 ;;
        --token)         BEARER_TOKEN="$2";   shift 2 ;;
        --venv-dir)      VENV_DIR="$2";       shift 2 ;;
        --background)    BACKGROUND=true;      shift ;;
        --with-launcher) WITH_LAUNCHER=true;   shift ;;
        --no-launcher)   WITH_LAUNCHER=false;  shift ;;
        --no-systemd)    WITH_SYSTEMD=false;   shift ;;
        -h|--help)
            sed -n '3,34p' "$0"
            exit 0 ;;
        *) error "Unknown option: $1  (use -h for help)" ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---- root guard ---------------------------------------------------------------
if [[ $EUID -eq 0 ]]; then
    echo "ERROR: Do not run this script as root (sudo)."
    echo "       Running as root makes the HuggingFace model cache owned by root,"
    echo "       which blocks the sidecar (running as a normal user) from writing"
    echo "       lock files during model download (Permission denied on .locks/)."
    exit 1
fi

# ---- step 1: find Python 3.10–3.12 ------------------------------------------
info "Searching for Python 3.10 / 3.11 / 3.12 ..."
PYTHON=""
for ver in 3.12 3.11 3.10; do
    py="python${ver}"
    if command -v "$py" &>/dev/null && "$py" --version 2>&1 | grep -q "$ver"; then
        PYTHON=$(command -v "$py")
        break
    fi
done
if [[ -z "$PYTHON" ]]; then
    if command -v python3 &>/dev/null; then
        PY3VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "")
        if [[ "$PY3VER" == 3.10 || "$PY3VER" == 3.11 || "$PY3VER" == 3.12 ]]; then
            PYTHON=$(command -v python3)
        fi
    fi
fi
[[ -z "$PYTHON" ]] && error "Python 3.10–3.12 not found. Install with: sudo apt install python3.11 python3.11-venv"
ok "Using Python: $($PYTHON --version)"

# ---- step 2: detect CUDA driver / version -----------------------------------
CUDA_VER=""
DRIVER=""
if command -v nvidia-smi &>/dev/null; then
    DRIVER=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 || echo "")
    MAJOR=$(echo "$DRIVER" | cut -d. -f1)
    if   [[ "$MAJOR" -ge 570 ]]; then CUDA_VER="12.8"
    elif [[ "$MAJOR" -ge 550 ]]; then CUDA_VER="12.4"
    elif [[ "$MAJOR" -ge 525 ]]; then CUDA_VER="12.1"
    elif [[ "$MAJOR" -ge 450 ]]; then CUDA_VER="11.8"
    fi
fi
if [[ "$DEVICE" == "auto" ]]; then
    DEVICE="$([[ -n "$CUDA_VER" ]] && echo "cuda" || echo "cpu")"
fi
if [[ -n "$CUDA_VER" ]]; then
    ok "CUDA $CUDA_VER detected (driver $DRIVER) — device: $DEVICE"
else
    warn "CUDA not detected — using CPU (inference will be slower)"
    DEVICE="cpu"
fi

# ---- step 3: pick torch wheel index -----------------------------------------
TORCH_EXTRA_INDEX=""
if [[ -n "$CUDA_VER" ]]; then
    CU_MAJOR=$(echo "$CUDA_VER" | cut -d. -f1)
    CU_MINOR=$(echo "$CUDA_VER" | cut -d. -f2)
    if   [[ "$CU_MAJOR" -ge 12 && "$CU_MINOR" -ge 8 ]]; then CU_TAG="cu128"
    elif [[ "$CU_MAJOR" -ge 12 && "$CU_MINOR" -ge 4 ]]; then CU_TAG="cu124"
    elif [[ "$CU_MAJOR" -ge 12 ]];                           then CU_TAG="cu121"
    elif [[ "$CU_MAJOR" -ge 11 && "$CU_MINOR" -ge 8 ]]; then CU_TAG="cu118"
    else CU_TAG=""
    fi
    [[ -n "$CU_TAG" ]] && TORCH_EXTRA_INDEX="--extra-index-url https://download.pytorch.org/whl/$CU_TAG"
fi

# ---- step 4: create / reuse venv --------------------------------------------
info "Venv: $VENV_DIR"
_create_venv() {
    if ! $PYTHON -m venv "$VENV_DIR" >$_VENV_ERR 2>&1; then
        if grep -q "ensurepip" $_VENV_ERR; then
            PY_VER=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
            # Try pip-based virtualenv first (no sudo required)
            if pip3 install virtualenv --break-system-packages -q 2>/dev/null \
               || pip3 install virtualenv -q 2>/dev/null; then
                if $PYTHON -m virtualenv --version &>/dev/null; then
                    VENV_CMD="$PYTHON -m virtualenv"
                else
                    VENV_CMD="${HOME}/.local/bin/virtualenv"
                fi
                if $VENV_CMD "$VENV_DIR" >$_VENV_ERR 2>&1; then
                    ok "Venv created with virtualenv (pip fallback)"
                    return 0
                fi
            fi
            # Try passwordless sudo then interactive sudo
            warn "python${PY_VER}-venv is not installed — attempting auto-install..."
            if command -v apt-get &>/dev/null; then
                APT_CMD="apt-get install -y python${PY_VER}-venv"
                if sudo -n $APT_CMD 2>/dev/null || sudo $APT_CMD; then
                    ok "python${PY_VER}-venv installed"
                    rm -rf "$VENV_DIR"
                    if ! $PYTHON -m venv "$VENV_DIR" >$_VENV_ERR 2>&1; then
                        cat $_VENV_ERR >&2
                        error "Still failed to create venv after installing python${PY_VER}-venv."
                    fi
                else
                    error "Auto-install failed.\n  Fix manually:  sudo apt install python${PY_VER}-venv\n  Then re-run this script."
                fi
            else
                error "ensurepip missing and apt-get not found.\n  Fix manually:  sudo apt install python${PY_VER}-venv\n  Then re-run this script."
            fi
        else
            cat $_VENV_ERR >&2
            error "Failed to create virtual environment (see above)."
        fi
    fi
}
if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating virtual environment..."
    _create_venv
    ok "Venv created"
elif [[ ! -x "$VENV_DIR/bin/pip" || ! -x "$VENV_DIR/bin/python" ]]; then
    warn "Venv at $VENV_DIR is incomplete — recreating..."
    rm -rf "$VENV_DIR"
    _create_venv
    ok "Venv recreated"
else
    ok "Venv exists — reusing"
fi
PIP="$VENV_DIR/bin/pip"
PY="$VENV_DIR/bin/python"

# ---- step 5: install dependencies -------------------------------------------
REQ="$SCRIPT_DIR/requirements.txt"
[[ -f "$REQ" ]] || error "requirements.txt not found at $REQ"
info "Installing dependencies from $REQ (this may take several minutes)..."
# shellcheck disable=SC2086
if ! "$PIP" install -r "$REQ" $TORCH_EXTRA_INDEX; then
    warn "pip install failed — retrying with --no-cache-dir (clears corrupted cache)..."
    "$PIP" install --no-cache-dir -r "$REQ" $TORCH_EXTRA_INDEX
fi
ok "Dependencies installed"

# verify torch CUDA
TORCH_CUDA=$("$PY" -c "import torch; print(torch.cuda.is_available())" 2>/dev/null || echo "False")
if [[ "$DEVICE" == "cuda" && "$TORCH_CUDA" != "True" ]]; then
    warn "torch.cuda.is_available() = False — falling back to CPU"
    DEVICE="cpu"
elif [[ "$DEVICE" == "cuda" ]]; then
    ok "torch.cuda.is_available() = True"
fi

# ---- step 6: HuggingFace login (only needed for gated models) ---------------
if [[ -n "$MODEL_REPO" ]]; then
    if [[ -n "$HF_TOKEN" ]]; then
        info "Logging into HuggingFace with provided token..."
        # huggingface_hub ≥1.0 ships 'hf'; older versions ship 'huggingface-cli'
        HF_CLI=""
        [[ -x "$VENV_DIR/bin/hf" ]]               && HF_CLI="$VENV_DIR/bin/hf auth login"
        [[ -z "$HF_CLI" && -x "$VENV_DIR/bin/huggingface-cli" ]] && \
            HF_CLI="$VENV_DIR/bin/huggingface-cli login"
        if [[ -n "$HF_CLI" ]]; then
            $HF_CLI --token "$HF_TOKEN" && ok "HF login done"
        else
            warn "No HF CLI found — token will be passed directly to snapshot_download."
        fi
    else
        warn "No --hf-token provided."
        warn "If the model is gated, log in interactively: $VENV_DIR/bin/hf auth login"
        if [[ -t 0 ]]; then
            read -r -p "Press Enter to continue without login, or Ctrl+C to abort... "
        else
            warn "Non-interactive session — continuing without HF login."
        fi
    fi
fi

# ---- step 7: download model snapshot (optional) ----------------------------
MODEL_PATH=""
if [[ -n "$MODEL_REPO" ]]; then
    if [[ -d "$MODEL_REPO" ]]; then
        # Local directory path passed — skip HuggingFace download entirely
        MODEL_PATH="$MODEL_REPO"
        info "Using local model directory: $MODEL_PATH"
    else
        info "Downloading model: $MODEL_REPO ..."
        _TOKEN_ARG=""
        [[ -n "$HF_TOKEN" ]] && _TOKEN_ARG="token=\"$HF_TOKEN\","
        MODEL_PATH=$("$PY" - <<EOF
from huggingface_hub import snapshot_download
import sys, traceback
try:
    path = snapshot_download(repo_id="$MODEL_REPO", ${_TOKEN_ARG})
    print(path)
except Exception as e:
    traceback.print_exc(file=sys.stderr)
    print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1)
EOF
        )
        ok "Model downloaded to: $MODEL_PATH"
    fi
fi

# ---- step 8: stop a previous sidecar so re-running this script always -------
# ---- replaces it instead of failing to bind and leaving the old one up ------
PID_FILE="${HOME}/.labr7/sidecar.pid"
if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null || true)
    if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
        info "Stopping previous sidecar (PID $OLD_PID) so this run can bind port ${PORT}..."
        kill "$OLD_PID" 2>/dev/null || true
        for _ in $(seq 1 10); do
            kill -0 "$OLD_PID" 2>/dev/null || break
            sleep 0.5
        done
        kill -0 "$OLD_PID" 2>/dev/null && kill -9 "$OLD_PID" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
fi

# ---- step 9: build and launch server command --------------------------------
LOG_DIR="${HOME}/.labr7/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/sidecar_$(date +%Y%m%d_%H%M%S).log"

SERVER_CMD=(
    "$PY" "$SCRIPT_DIR/server.py"
    "--port"   "$PORT"
    "--host"   "$HOST"
    "--device" "$DEVICE"
)
[[ -n "$MODEL_PATH" ]]   && SERVER_CMD+=("--model" "$MODEL_PATH")
[[ -n "$BEARER_TOKEN" ]] && SERVER_CMD+=("--token" "$BEARER_TOKEN")

info "Starting sidecar server on ${HOST}:${PORT}  (device=${DEVICE})"
[[ -n "$MODEL_PATH" ]] && info "Pre-loading model: $MODEL_PATH"
info "Log: $LOG_FILE"
echo ""

if $BACKGROUND || $WITH_LAUNCHER; then
    # --with-launcher implies --background for the server
    nohup "${SERVER_CMD[@]}" > "$LOG_FILE" 2>&1 &
    SERVER_PID=$!
    # Write PID so the launcher's /status and /wake can track this process
    mkdir -p "${HOME}/.labr7"
    echo "$SERVER_PID" > "${HOME}/.labr7/sidecar.pid"
    ok "Server started in background (PID $SERVER_PID)"
    ok "Monitor:  tail -f $LOG_FILE"
    ok "Stop:     kill $SERVER_PID"
    # Health check: verify the server is actually accepting requests
    info "Waiting for server to become ready..."
    sleep 3
    _HEALTH_OK=false
    if kill -0 "$SERVER_PID" 2>/dev/null; then
        if curl -sf "http://127.0.0.1:${PORT}/healthz" -o /dev/null 2>/dev/null; then
            _HEALTH_OK=true
            ok "Server is healthy at http://127.0.0.1:${PORT}/healthz"
        else
            warn "Server process is running (PID $SERVER_PID) but /healthz did not respond."
            warn "The server may still be loading the model — check the log:"
            warn "  tail -f $LOG_FILE"
        fi
    else
        warn "Server process (PID $SERVER_PID) exited unexpectedly. Check the log for errors:"
        warn "  tail -20 $LOG_FILE"
        tail -20 "$LOG_FILE" >&2 || true
    fi
else
    exec "${SERVER_CMD[@]}" 2>&1 | tee "$LOG_FILE"
fi

# ---- step 10: start launcher daemon (--with-launcher) -----------------------
if $WITH_LAUNCHER; then
    LAUNCHER_PORT=$((PORT + 1))
    LAUNCHER_LOG="$LOG_DIR/launcher_$(date +%Y%m%d_%H%M%S).log"

    _SYSTEMD_OK=false
    if $WITH_SYSTEMD && command -v systemctl &>/dev/null; then
        _SVC_NAME="radeis-launcher"
        _SVC_DIR="${HOME}/.config/systemd/user"
        _SVC_FILE="${_SVC_DIR}/${_SVC_NAME}.service"
        mkdir -p "$_SVC_DIR"
        cat > "$_SVC_FILE" <<EOF
[Unit]
Description=Radeis VLM Launcher Daemon
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=${PY} ${SCRIPT_DIR}/launcher.py --host ${HOST} --port ${LAUNCHER_PORT}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
        if systemctl --user daemon-reload 2>/dev/null \
           && systemctl --user enable --now "$_SVC_NAME" 2>/dev/null; then
            # enable-linger so the service survives user logout / reboot
            loginctl enable-linger "$USER" 2>/dev/null || \
                warn "loginctl enable-linger failed — launcher may not survive logout (try: sudo loginctl enable-linger $USER)"
            _SYSTEMD_OK=true
            ok "Launcher installed as systemd user service: ${_SVC_NAME}"
            ok "Auto-restarts on crash, survives reboot"
            ok "Status:  systemctl --user status ${_SVC_NAME}"
            ok "Logs:    journalctl --user -u ${_SVC_NAME} -f"
            ok "Stop:    systemctl --user stop ${_SVC_NAME}"
            ok "Disable: systemctl --user disable --now ${_SVC_NAME}"
        else
            warn "systemd --user not available — falling back to nohup"
            rm -f "$_SVC_FILE"
        fi
    fi

    if ! $_SYSTEMD_OK; then
        info "Starting launcher daemon on ${HOST}:${LAUNCHER_PORT} (nohup) ..."
        nohup "$PY" "$SCRIPT_DIR/launcher.py" --host "$HOST" --port "$LAUNCHER_PORT" \
            > "$LAUNCHER_LOG" 2>&1 &
        LAUNCHER_PID=$!
        ok "Launcher started in background (PID $LAUNCHER_PID)"
        ok "Monitor:  tail -f $LAUNCHER_LOG"
        ok "Stop:     kill $LAUNCHER_PID"
        warn "Note: launcher will NOT survive reboot. Re-run this script after restart."
        warn "      Pass --no-systemd to silence this warning."
    fi

    echo ""
    ok "Isaac Sim URL field: http://<this-machine-ip>:${PORT}"
fi

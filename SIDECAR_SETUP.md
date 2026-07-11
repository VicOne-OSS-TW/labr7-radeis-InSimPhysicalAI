# Radeis — Inference Server Setup (Remote GPU Host)

The extension does **not** run the vision-language model inside Isaac Sim's
Python. The model (default **google/gemma-4-e2b-it**) runs as an out-of-process
**inference server** (the "VLM sidecar") so it can use `transformers` with
`attn_implementation="eager"` + `output_attentions=True` (needed for attention
heatmaps) without fighting Kit's pinned torch ABI, and so the model's VRAM
doesn't collide with the RTX renderer.

```
Isaac Sim (Kit)  ──HTTP /infer (FPV frame)──▶  Inference server (torch+transformers)
   extension     ◀─{action, heatmap, layer stack, logits}─   gemma-4-e2b-it
```

## When you need this document

For most setups you don't: the extension's built-in **Setup Wizard** handles
both the local case (installs and starts the server on the same machine) and
the remote case (walks you through the two commands below and registers the
URL). This document is for the **remote GPU host side** — the machine that has
no Isaac Sim UI — and for advanced/manual configuration.

## 1. What's in `vlm_sidecar/`

- `server.py` — FastAPI inference server
- `attention_core.py` — model load + attention extraction + action decode
- `launcher.py` — lightweight wake daemon (lets the extension start the server remotely, no SSH needed)
- `radeis-sidecar-setup.sh` — **one-command installer** (venv, deps, model download, server + launcher start)
- `radeis-sidecar-uninstall.sh` — clean removal (server, launcher service, venv, optionally model weights)
- `requirements.txt` — torch, transformers, accelerate, fastapi, uvicorn, huggingface_hub, …

## 2. Install & start — one command

Copy the `vlm_sidecar/` folder (or unzip the sidecar release ZIP) onto the GPU
host, then:

```bash
bash radeis-sidecar-setup.sh
```

With all defaults this installs a venv at `~/.labr7/venv`, auto-detects
CUDA and picks the matching torch wheel, downloads `google/gemma-4-e2b-it`,
starts the server on port **8765**, and starts the **launcher daemon** on port
**8766** as a systemd user service when available (survives reboot,
auto-restarts on crash; falls back to a plain background process otherwise).

Do **not** run it with `sudo` — the script refuses, because a root-owned
HuggingFace cache blocks later downloads by the normal user.

Common variants:

```bash
# gated model — pass a HuggingFace token
bash radeis-sidecar-setup.sh --hf-token hf_xxx

# use an already-downloaded local model directory (skips the download)
bash radeis-sidecar-setup.sh -m /path/to/model-snapshot

# no launcher daemon, no systemd — foreground server only
bash radeis-sidecar-setup.sh --no-launcher --no-systemd
```

Full option list: `bash radeis-sidecar-setup.sh -h`
(`-m/--model`, `-p/--port`, `-H/--host`, `-d/--device cuda|cpu`, `--hf-token`,
`--token` for bearer auth, `--venv-dir`, `--no-launcher`, `--no-systemd`).

Logs go to `~/.labr7/logs/`; the server PID is tracked in
`~/.labr7/sidecar.pid`. Re-running the script safely replaces a previous
server instead of failing to bind the port.

Health-check from anywhere:

```bash
curl http://<host>:8765/healthz
# → {"status":"ok","loaded":true,...}
```

## 3. Point the extension at it

In Isaac Sim: **Setup Wizard → Remote Install → Step 2**, enter
`http://<host>:8765` in the **Remote GPU Machine URL** field and click
**Test Connection**. The wizard registers the URL and verifies the model.

If the launcher daemon is running (default), the extension can also wake a
stopped server remotely — no SSH round-trip needed.

## 4. Manual run (no script)

Any Python 3.10–3.12 env with a working CUDA torch works:

```bash
<python> -m pip install -r vlm_sidecar/requirements.txt
<python> vlm_sidecar/server.py --port 8765 --host 0.0.0.0 \
    --model /path/to/model-snapshot        # omit to start bare and load later
```

Server flags: `--host` (default `0.0.0.0`), `--port` (default `8765`),
`--model` (local snapshot dir to preload), `--device` (default `cuda`),
`--token` (bearer token for request auth).

## 5. Uninstall

```bash
bash radeis-sidecar-uninstall.sh            # stops server+launcher, removes venv/state
bash radeis-sidecar-uninstall.sh --purge-model --purge-logs -y   # full wipe
```

## 6. API (for integrators)

Inference server (port 8765):

- `GET  /healthz` → status, model, loaded, layer count, action vocabulary
- `GET  /resources` → VRAM / device usage (drives the extension's VRAM monitor)
- `POST /load_model` `{source:"local"|"hub", path_or_repo, download}`
- `GET  /check_cache` → is a given repo already in the local HF cache
- `POST /download` `{repo}` → `{job_id}` · `GET /download/{job_id}` → `{state,pct}`
- `POST /infer` `{image_b64, system_prompt?, user_msg?, mode, want_attention,
  want_layer_stack, station_bbox?}` →
  `{action_token, logit_margin, heatmap{grid_w,grid_h,data}, peaks_2d,
    layer_stack, aram, tram, infer_ms}`
- `POST /shutdown` — stop the server process
- `GET /sleep` · `POST /sleep/arm` · `POST /sleep/cancel` — idle auto-sleep control

Launcher daemon (port 8766):

- `GET  /healthz` → `{"status":"ok","owner":"radeis-launcher"}`
- `GET  /status` → `{sidecar_running, pid}`
- `POST /wake` `{port?, model_path?, device?}` → starts `server.py`
- `GET  /log` → tail of the server log
- `POST /stop` → stops the running server process

Action vocabulary (9 tokens): `Idle / Forward / Backward / TurnLeft /
TurnRight / Stop / EmergencyStop / Run / Jump`, decoded from a single
`set_robot_action{action}` tool call.

## 7. Other models

The inference server ships with, and supports out of the box, exactly one
model: **google/gemma-4-e2b-it**. To run other vision-language models or VLA
policies against Radeis, [contact us](https://vicone.com/contact-us/).

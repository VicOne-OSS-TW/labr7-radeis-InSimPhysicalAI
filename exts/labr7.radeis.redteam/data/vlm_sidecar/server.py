"""Radeis red-team VLM sidecar — FastAPI service.

Runs in the sidecar venv on a GPU host. The Isaac Sim extension is a thin HTTP
client; this process owns torch + transformers + the (VRAM-heavy, eager-attention)
model.

Run:
    python server.py --port 8765 --host 127.0.0.1 --device cuda
or with preloaded model:
    python server.py --port 8765 --host 127.0.0.1 --device cuda \
        --model /path/to/gemma-4-e2b-it
"""
from __future__ import annotations

import argparse
import base64
import io
import os
import signal
import threading
import time
import traceback
import uuid
from typing import List, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel

import attention_core as ac

# guard against decompression-bomb images on the inference box
Image.MAX_IMAGE_PIXELS = 16_000_000  # ~16 MP cap

app = FastAPI(title="Radeis VLM Sidecar", version="0.2.0")

# --------------------------------------------------------------------------
# Global model state (single-model, serialized inference)
# --------------------------------------------------------------------------
_LOCK = threading.Lock()
_STATE = {"model": None, "processor": None, "model_id": None, "n_layers": None,
          "device": "cuda", "loading_since": None,
          "model_file_size": 0, "vram_before_load": 0, "preload_error": None}
_DOWNLOADS: dict = {}  # job_id -> {state, pct, msg}
_CANCELLED: set = set()  # job_ids that have been cancel-requested
_TOKEN: Optional[str] = None  # bearer token (None = auth disabled)
_rt_file = None  # set in __main__ before uvicorn.run(); used by /shutdown cleanup


class _DownloadCancelled(Exception):
    pass


_MAX_PNG_BYTES = 32 * 1024 * 1024  # 32 MB decoded-PNG cap

# --------------------------------------------------------------------------
# Auto-sleep state (sidecar manages its own inactivity shutdown)
# --------------------------------------------------------------------------
_SLEEP_STATE = {
    "active": False,
    "deadline": 0.0,   # time.monotonic() timestamp
    "timeout": 600,
}
_SLEEP_LOCK = threading.Lock()


def _sleep_watcher():
    while True:
        time.sleep(1)
        with _SLEEP_LOCK:
            if _SLEEP_STATE["active"] and time.monotonic() >= _SLEEP_STATE["deadline"]:
                print("[sidecar] auto-sleep timeout — shutting down", flush=True)
                os.kill(os.getpid(), signal.SIGTERM)
                break


# --------------------------------------------------------------------------
# Bearer token auth middleware
# --------------------------------------------------------------------------
@app.middleware("http")
async def _auth_middleware(request: Request, call_next):
    if _TOKEN is not None:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != _TOKEN:
            return JSONResponse(status_code=401, content={"error": "unauthorized"})
    return await call_next(request)


def _b64_to_pil(b64: str) -> Image.Image:
    raw = base64.b64decode(b64.split(",")[-1], validate=False)
    if len(raw) > _MAX_PNG_BYTES:
        raise ValueError(f"image too large ({len(raw)} bytes > {_MAX_PNG_BYTES})")
    return Image.open(io.BytesIO(raw)).convert("RGB")


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class LoadReq(BaseModel):
    source: str = "local"          # "local" | "hub"
    path_or_repo: str
    dtype: str = "bfloat16"
    download: bool = False         # for hub: download if missing
    hf_token: Optional[str] = None


class DownloadReq(BaseModel):
    repo: str
    revision: str = "main"
    target_dir: Optional[str] = None
    hf_token: Optional[str] = None


class InferReq(BaseModel):
    image_b64: str
    system_prompt: Optional[str] = None
    user_msg: Optional[str] = None
    prefix: str = ""
    mode: str = "vlm"              # "vlm" | "vla"
    tools: Optional[list] = None
    want_attention: bool = True
    want_layer_stack: bool = True
    station_bbox: Optional[List[int]] = None   # [x0,y0,x1,y1] attacker region
    max_new_tokens: int = 24


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
def _compute_model_size_bytes(model_path: str) -> int:
    """Sum safetensors/bin file sizes — proxy for GPU VRAM footprint during loading."""
    total = 0
    try:
        for root, _, files in os.walk(model_path):
            for f in files:
                if f.endswith(('.safetensors', '.bin', '.pt')):
                    total += os.path.getsize(os.path.join(root, f))
    except Exception:
        pass
    return total


def _compute_loading_pct() -> Optional[int]:
    """Estimate model loading progress (0-99) via torch CUDA memory delta.

    Normalises against model file size on disk (≈ VRAM footprint) rather than
    total GPU VRAM so progress reaches ~100% regardless of GPU size.
    """
    if _STATE["loading_since"] is None:
        return None
    model_size = _STATE["model_file_size"]
    if model_size <= 0:
        return None
    try:
        import torch
        if not torch.cuda.is_available():
            return None
        allocated_delta = torch.cuda.memory_allocated() - _STATE["vram_before_load"]
        if allocated_delta <= 0:
            return 1
        return min(99, int(allocated_delta / model_size * 100))
    except Exception:
        pass
    return None


@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "owner": "radeis-sidecar",
        "pid": os.getpid(),
        "model": _STATE["model_id"],
        "device": _STATE["device"],
        "loaded": _STATE["model"] is not None,
        "loading_pct": _compute_loading_pct(),
        "preload_error": _STATE["preload_error"],
        "attn_impl": "eager",
        "n_layers": _STATE["n_layers"],
        "actions": ac.ACTION_TOKENS,
    }


@app.get("/resources")
def resources():
    result = {
        "gpu_vram_used_gb": None,
        "gpu_vram_total_gb": None,
        "gpu_name": None,
        "cpu_ram_used_gb": None,
        "cpu_ram_total_gb": None,
    }
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        result["gpu_vram_used_gb"] = round(mem.used / 1024**3, 2)
        result["gpu_vram_total_gb"] = round(mem.total / 1024**3, 2)
        result["gpu_name"] = pynvml.nvmlDeviceGetName(handle)
    except Exception:  # noqa: BLE001
        pass
    try:
        import psutil
        vm = psutil.virtual_memory()
        result["cpu_ram_used_gb"] = round(vm.used / 1024**3, 2)
        result["cpu_ram_total_gb"] = round(vm.total / 1024**3, 2)
    except Exception:  # noqa: BLE001
        pass
    return result


@app.post("/load_model")
def load_model(req: LoadReq):
    import os
    path = req.path_or_repo
    if req.source == "local" and not os.path.isdir(path):
        return {"loaded": False, "error": f"local path not found: {path}"}
    if req.source == "hub" and not os.path.isdir(path):
        if not req.download:
            return {"loaded": False, "needs_download": True, "repo": path}
        try:
            from huggingface_hub import snapshot_download
            path = snapshot_download(repo_id=path,
                                     token=req.hf_token or None)
        except Exception as e:  # noqa: BLE001
            return {"loaded": False, "error": f"download failed: {e}"}
    try:
        with _LOCK:
            t0 = time.time()
            model, processor, n_layers = ac.load_gemma(
                path, device=_STATE["device"], dtype=req.dtype)
            _STATE.update(model=model, processor=processor, n_layers=n_layers,
                          model_id=os.path.basename(os.path.normpath(path)))
        _STATE["preload_error"] = None
        return {"loaded": True, "model_id": _STATE["model_id"], "n_layers": n_layers,
                "load_s": round(time.time() - t0, 1)}
    except Exception as e:  # noqa: BLE001
        _STATE["preload_error"] = str(e)
        return {"loaded": False, "error": str(e), "trace": traceback.format_exc()[-800:]}


def _cached_bytes_for_repo(repo_id: str) -> int:
    """Return bytes already on disk in the HF hub cache for *repo_id*.

    Scans blobs/ for completed files and the largest incomplete shard per
    blob hash, so _bytes_done can be pre-seeded and the progress bar starts
    at the correct resume offset instead of 0%.
    """
    import os
    from pathlib import Path

    cache_root = Path(
        os.environ.get("HF_HUB_CACHE") or
        os.environ.get("HUGGINGFACE_HUB_CACHE") or
        (Path.home() / ".cache" / "huggingface" / "hub")
    )
    blobs_dir = cache_root / f"models--{repo_id.replace('/', '--')}" / "blobs"
    if not blobs_dir.is_dir():
        return 0

    # Only count fully-completed blobs (no .incomplete suffix).
    # Incomplete files are NOT reliably resumed by HF Hub — it often starts a
    # fresh .incomplete file, so counting partials causes double-counting.
    try:
        return sum(
            f.stat().st_size
            for f in blobs_dir.iterdir()
            if f.is_file() and "." not in f.name
        )
    except OSError:
        return 0


def _get_complete_local_snapshot(repo_id: str):
    """Return a complete local snapshot directory for *repo_id*, or None.

    Checks refs/main first; if that snapshot has no .safetensors, falls back to
    any older snapshot directory that does.  Used to skip download and recover
    from a stale refs/main pointing at an empty/partial snapshot.
    """
    from pathlib import Path
    cache_root = Path(
        os.environ.get("HF_HUB_CACHE") or
        os.environ.get("HUGGINGFACE_HUB_CACHE") or
        (Path.home() / ".cache" / "huggingface" / "hub")
    )
    model_dir = cache_root / f"models--{repo_id.replace('/', '--')}"
    refs = model_dir / "refs" / "main"
    if refs.exists():
        commit = refs.read_text().strip()
        snap = model_dir / "snapshots" / commit
        if snap.is_dir() and any(snap.glob("*.safetensors")):
            return snap
    snaps_dir = model_dir / "snapshots"
    if snaps_dir.is_dir():
        for candidate in sorted(snaps_dir.iterdir(), reverse=True):
            if candidate.is_dir() and any(candidate.glob("*.safetensors")):
                return candidate
    return None


def _fix_hf_cache_ownership() -> None:
    """chown HuggingFace cache dirs back to the current user if they were created by root.

    When a previous install ran as root (e.g. sudo python), the .locks/ directory ends
    up owned by root:root.  The sidecar (running as a normal user) then gets EPERM when
    it tries to create lock files, causing every snapshot_download call to fail before
    downloading a single byte.
    """
    import pathlib
    import pwd
    import subprocess
    try:
        me = os.getuid()
        if me == 0:
            return  # already root — nothing to fix
        hf_hub = pathlib.Path.home() / ".cache" / "huggingface" / "hub"
        for d in [hf_hub, hf_hub / ".locks"]:
            if d.exists() and d.stat().st_uid == 0:
                username = pwd.getpwuid(me).pw_name
                result = subprocess.run(
                    ["sudo", "chown", "-R", f"{username}:{username}", str(d)],
                    capture_output=True, text=True)
                if result.returncode == 0:
                    print(f"[sidecar] Fixed root ownership on {d}", flush=True)
                else:
                    print(f"[sidecar] Could not fix root ownership on {d}: {result.stderr.strip()}", flush=True)
    except Exception:  # noqa: BLE001
        pass


def _do_download(job_id: str, repo: str, revision: str, target_dir, hf_token=None):
    # Disarm auto-sleep for the duration of the download so a long (1h+)
    # download is not interrupted by the inactivity watchdog.
    with _SLEEP_LOCK:
        _was_sleep_active = _SLEEP_STATE["active"]
        _SLEEP_STATE["active"] = False
    try:
        import threading as _th
        import pathlib as _pl
        from huggingface_hub import snapshot_download
        _fix_hf_cache_ownership()
        _DOWNLOADS[job_id] = {
            "state": "running", "pct": 0, "msg": "querying repo",
            "started_at": time.time(),
        }

        # Query repo manifest upfront to get accurate file count + total bytes.
        # Using list_repo_tree gives us LFS file sizes so _bytes_total is correct
        # from the start — without this, small metadata files set a misleading
        # total and pct jumps to 99 before the large shards even begin.
        n_total = 0
        known_total_bytes = 0
        try:
            from huggingface_hub import list_repo_tree
            entries = list(list_repo_tree(repo_id=repo, revision=revision,
                                          recursive=True, token=hf_token))
            n_total = sum(1 for e in entries if getattr(e, "size", None))
            known_total_bytes = sum(
                e.size for e in entries
                if getattr(e, "size", None)
            )
            _DOWNLOADS[job_id]["msg"] = f"0/{n_total} files"
        except Exception:  # noqa: BLE001
            try:
                from huggingface_hub import list_repo_files
                n_total = sum(1 for _ in list_repo_files(repo_id=repo, revision=revision,
                                                          token=hf_token))
                _DOWNLOADS[job_id]["msg"] = f"0/{n_total} files"
            except Exception:  # noqa: BLE001
                pass

        # Skip download entirely if a complete local snapshot already exists.
        snap = _get_complete_local_snapshot(repo)
        if snap is not None:
            _DOWNLOADS[job_id] = {"state": "done", "pct": 100, "path": str(snap)}
            return

        _counter = [0]
        _bytes_total = [known_total_bytes]  # pre-seeded from manifest
        # Pre-seed bytes_done from cache so the progress bar starts at the
        # resume offset instead of 0% on every restart.
        _already_bytes = _cached_bytes_for_repo(repo) if known_total_bytes > 0 else 0
        _bytes_done = [min(_already_bytes, known_total_bytes)]
        _lock_c = _th.Lock()

        try:
            from tqdm import tqdm as _base_tqdm

            class _FileTqdm(_base_tqdm):
                """Track byte-level progress so large files show progress immediately."""
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    # Only add to total if manifest query failed (known_total_bytes==0)
                    if known_total_bytes == 0 and self.total and self.total > 0:
                        with _lock_c:
                            _bytes_total[0] += self.total

                def update(self, n=1):
                    if job_id in _CANCELLED:
                        raise _DownloadCancelled()
                    super().update(n)
                    if isinstance(n, (int, float)) and n > 0:
                        with _lock_c:
                            _bytes_done[0] += n
                            bt = _bytes_total[0]
                            mb_done = int(_bytes_done[0] // 1_048_576)
                            mb_total = int(bt // 1_048_576)
                            # Use byte ratio when total reliably covers downloaded bytes.
                            if bt > 0 and bt >= _bytes_done[0]:
                                pct = min(99, int(_bytes_done[0] / bt * 100))
                            elif n_total > 0 and _counter[0] > 0:
                                pct = min(99, int(_counter[0] / n_total * 100))
                            else:
                                pct = _DOWNLOADS[job_id].get("pct", 0)
                            size_str = (f"{mb_done}/{mb_total} MB"
                                        if mb_total > 0 and mb_total >= mb_done
                                        else f"{mb_done} MB")
                            if n_total > 0:
                                msg = f"{_counter[0]}/{n_total} files, {size_str}"
                            else:
                                msg = size_str
                            _DOWNLOADS[job_id].update({"pct": pct, "msg": msg})

                def close(self):
                    super().close()
                    with _lock_c:
                        _counter[0] += 1
                        bt = _bytes_total[0]
                        mb_done = int(_bytes_done[0] // 1_048_576)
                        mb_total = int(bt // 1_048_576)
                        size_str = (f"{mb_done}/{mb_total} MB"
                                    if mb_total > 0 and mb_total >= mb_done
                                    else f"{mb_done} MB" if mb_done > 0 else "")
                        suffix = f", {size_str}" if size_str else ""
                        if n_total > 0:
                            pct = min(99, int(_counter[0] / n_total * 100))
                            _DOWNLOADS[job_id]["msg"] = f"{_counter[0]}/{n_total} files{suffix}"
                            _DOWNLOADS[job_id]["pct"] = pct
                        elif size_str:
                            _DOWNLOADS[job_id]["msg"] = size_str

            path = snapshot_download(repo_id=repo, revision=revision,
                                     local_dir=target_dir, tqdm_class=_FileTqdm,
                                     token=hf_token)
        except _DownloadCancelled:
            raise  # let outer handler set state="cancelled"
        except Exception:  # noqa: BLE001
            path = snapshot_download(repo_id=repo, revision=revision,
                                     local_dir=target_dir, token=hf_token)

        # Validate snapshot has actual model weight files; an empty dir means a
        # previous failed download updated refs/main to a hollow snapshot hash.
        snap_files = list(_pl.Path(path).glob("*.safetensors")) + list(_pl.Path(path).glob("*.bin"))
        if not snap_files:
            raise RuntimeError(
                f"Snapshot directory is empty (no .safetensors/.bin files): {path}\n"
                "This usually means refs/main points to a failed partial download. "
                "Delete the empty snapshot dir and reset refs/main to a complete hash, "
                "or clear ~/.cache/huggingface/hub/<model>/ entirely and re-download.")
        _DOWNLOADS[job_id] = {"state": "done", "pct": 100, "path": path}
    except _DownloadCancelled:
        _DOWNLOADS[job_id] = {"state": "cancelled", "pct": 0, "msg": "Cancelled by user"}
    except Exception as e:  # noqa: BLE001
        fallback = _get_complete_local_snapshot(repo)
        if fallback:
            _DOWNLOADS[job_id] = {"state": "done", "pct": 100, "path": str(fallback)}
        else:
            _DOWNLOADS[job_id] = {"state": "error", "pct": 0, "msg": str(e),
                                   "trace": traceback.format_exc()[-1200:]}
    finally:
        _CANCELLED.discard(job_id)
        # Re-arm sleep watchdog after download completes/fails/cancels.
        with _SLEEP_LOCK:
            if _was_sleep_active:
                _SLEEP_STATE.update(active=True,
                                    deadline=time.monotonic() + _SLEEP_STATE["timeout"])


@app.get("/check_cache")
def check_cache(repo: str):
    """Return whether a complete local HF snapshot exists for *repo*."""
    snap = _get_complete_local_snapshot(repo)
    if snap is not None:
        return {"exists": True, "path": str(snap)}
    return {"exists": False, "path": None}


@app.post("/download")
def download(req: DownloadReq):
    job_id = "dl_" + uuid.uuid4().hex[:12]
    th = threading.Thread(target=_do_download,
                          args=(job_id, req.repo, req.revision, req.target_dir,
                                req.hf_token),
                          daemon=True)
    th.start()
    return {"job_id": job_id}


@app.get("/download/{job_id}")
def download_status(job_id: str):
    return _DOWNLOADS.get(job_id, {"state": "unknown", "pct": 0})


@app.delete("/download/{job_id}")
def download_cancel(job_id: str):
    if job_id not in _DOWNLOADS:
        return {"ok": False, "msg": "job not found"}
    _CANCELLED.add(job_id)
    return {"ok": True}


@app.post("/infer")
def infer(req: InferReq):
    if _STATE["model"] is None:
        return {"error": "no model loaded — call /load_model first"}
    try:
        bbox = req.station_bbox
        if bbox is not None and len(bbox) != 4:
            return {"error": f"station_bbox must be [x0,y0,x1,y1], got len={len(bbox)}"}
        img = _b64_to_pil(req.image_b64)
        with _LOCK:
            res = ac.infer(
                _STATE["model"], _STATE["processor"], img,
                system_prompt=req.system_prompt or ac.DEFAULT_SYSTEM_PROMPT,
                user_msg=req.user_msg or ac.DEFAULT_USER_MSG,
                prefix=req.prefix,
                tools=req.tools,
                want_attention=req.want_attention,
                want_layer_stack=req.want_layer_stack,
                station_bbox=req.station_bbox,
                device=_STATE["device"],
                max_new_tokens=req.max_new_tokens,
            )
        with _SLEEP_LOCK:
            if _SLEEP_STATE["active"]:
                _SLEEP_STATE["deadline"] = time.monotonic() + _SLEEP_STATE["timeout"]
        return res
    except Exception as e:  # noqa: BLE001
        return {"error": str(e), "trace": traceback.format_exc()[-1200:]}


@app.post("/shutdown")
def shutdown():
    """Forcefully terminate this server process, killing any in-progress model load.

    Uses os._exit(0) directly rather than SIGTERM so that uvicorn's graceful-shutdown
    path (which waits for the in-flight /load_model thread to finish) is bypassed.
    SIGTERM → uvicorn graceful shutdown → waits for _LOCK held by _preload → full load
    completes before process exits.  os._exit kills all threads immediately.
    """
    def _exit():
        time.sleep(0.1)
        if _rt_file is not None:
            _cleanup_runtime(_rt_file)
        os._exit(0)

    threading.Thread(target=_exit, daemon=True).start()
    return {"ok": True}


@app.get("/sleep")
def sleep_status():
    with _SLEEP_LOCK:
        active = _SLEEP_STATE["active"]
        remaining = max(0, int(_SLEEP_STATE["deadline"] - time.monotonic())) if active else None
    return {"active": active, "remaining": remaining}


@app.post("/sleep/arm")
def sleep_arm(timeout: int = 600):
    with _SLEEP_LOCK:
        _SLEEP_STATE.update(active=True,
                            deadline=time.monotonic() + timeout,
                            timeout=timeout)
    return {"ok": True, "timeout": timeout}


@app.post("/sleep/cancel")
def sleep_cancel():
    with _SLEEP_LOCK:
        _SLEEP_STATE["active"] = False
    return {"ok": True}


def _write_runtime(port: int, model_path: str | None):
    """Write ~/.labr7/sidecar_runtime.json so tray/extension can find our PID."""
    import json as _json
    from pathlib import Path
    labr7_dir = Path.home() / ".labr7"
    labr7_dir.mkdir(parents=True, exist_ok=True)
    runtime = {
        "pid": os.getpid(),
        "port": port,
        "command": __import__("sys").argv,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model_path": model_path,
        "owner": "radeis-sidecar",
    }
    runtime_file = labr7_dir / "sidecar_runtime.json"
    with open(runtime_file, "w") as f:
        _json.dump(runtime, f, indent=2)
    return runtime_file


def _cleanup_runtime(runtime_file):
    try:
        runtime_file.unlink(missing_ok=True)
        lock = runtime_file.parent / "sidecar.lock"
        lock.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--model", default=None, help="local model snapshot dir to preload")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--token", default=None, help="bearer token for request auth")
    args = ap.parse_args()
    _STATE["device"] = args.device
    if args.token:
        _TOKEN = args.token
        print(f"[sidecar] bearer auth enabled", flush=True)
    if args.model:
        # Load model in a background thread so uvicorn starts immediately and
        # /healthz responds with loaded=false while loading is in progress.
        # The reconnect flow can then show a live progress display instead of
        # timing out waiting for the port to open.
        _model_arg = args.model
        _device_arg = args.device
        def _preload():
            print(f"[sidecar] preloading {_model_arg} ...", flush=True)
            _STATE["loading_since"] = time.time()
            _STATE["preload_error"] = None
            _STATE["model_file_size"] = _compute_model_size_bytes(_model_arg)
            try:
                import torch as _torch
                _STATE["vram_before_load"] = (
                    _torch.cuda.memory_allocated() if _torch.cuda.is_available() else 0)
            except Exception:
                _STATE["vram_before_load"] = 0
            try:
                with _LOCK:
                    m, p, n = ac.load_gemma(_model_arg, device=_device_arg)
                    _STATE.update(model=m, processor=p, n_layers=n,
                                  model_id=os.path.basename(
                                      os.path.normpath(_model_arg)))
                print(f"[sidecar] loaded ({n} layers)", flush=True)
            except Exception as _e:
                _STATE["preload_error"] = str(_e)
                print(f"[sidecar] preload FAILED: {_e}", flush=True)
                import traceback as _tb
                _tb.print_exc()
            finally:
                _STATE["loading_since"] = None
                _STATE["model_file_size"] = 0
                _STATE["vram_before_load"] = 0
        threading.Thread(target=_preload, daemon=True, name="preload").start()
    # Write runtime file so tray agent and extension can always find our PID,
    # regardless of how this server was started (debugger, shell script, extension).
    _rt_file = _write_runtime(args.port, args.model)
    import atexit
    atexit.register(_cleanup_runtime, _rt_file)
    _orig_sigterm = signal.getsignal(signal.SIGTERM)
    def _handle_sigterm(signum, frame):
        _cleanup_runtime(_rt_file)
        # os._exit bypasses Python cleanup and kills all threads immediately,
        # including any daemon preload thread stuck in a CUDA memory transfer.
        # raise SystemExit(0) would wait for uvicorn non-daemon threads to
        # finish first, allowing model loading to complete before dying.
        os._exit(0)
    signal.signal(signal.SIGTERM, _handle_sigterm)
    print("[sidecar] auto-sleep idle — arm via POST /sleep/arm (server runs until stopped)", flush=True)
    threading.Thread(target=_sleep_watcher, daemon=True).start()
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")

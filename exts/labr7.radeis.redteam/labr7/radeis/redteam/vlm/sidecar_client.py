"""Thin HTTP client for the Radeis VLM sidecar.

Runs INSIDE Isaac Sim's Kit Python, so it uses *stdlib only* (urllib, json,
zlib, struct, base64) — no requests, no PIL, no numpy-image deps beyond the
numpy array the caller hands us. A minimal pure-python PNG encoder turns the
captured RGB frame into a base64 PNG for the wire.

The sidecar itself (torch + transformers + gemma, eager attention) lives in a
separate process / GPU host; see ``<repo>/vlm_sidecar/``.
"""
from __future__ import annotations

import base64
import http.client
import json
import re
import socket
import struct
import threading
import urllib.error
import urllib.request
import zlib
from collections import deque
from typing import List, Optional
from urllib.parse import urlparse


def _fmt_net_err(e: Exception) -> str:
    """Strip Python's angle-bracket urllib repr from network errors.

    urllib wraps socket errors as ``<urlopen error [Errno N] message>``; that
    raw repr looks like broken HTML in a UI label.  Extract the human-readable
    part only.
    """
    raw = str(e)
    m = re.search(r"<urlopen error (.+?)>", raw)
    if m:
        return m.group(1)
    return raw


# ---------------------------------------------------------------------------
# Minimal RGB-ndarray → PNG bytes (no PIL dependency)
# ---------------------------------------------------------------------------
def _rgb_to_png_bytes(arr) -> bytes:
    """Encode an (H, W, 3) uint8 numpy array as PNG bytes using stdlib zlib."""
    import numpy as np

    a = np.asarray(arr)
    if a.ndim == 2:
        a = np.stack([a, a, a], axis=-1)
    if a.shape[2] == 4:
        a = a[:, :, :3]
    if a.dtype != np.uint8:
        a = np.clip(a, 0, 255).astype(np.uint8)
    h, w, _ = a.shape

    # raw scanlines, each prefixed with filter byte 0
    raw = bytearray()
    rowbytes = w * 3
    flat = a.reshape(h, rowbytes)
    for y in range(h):
        raw.append(0)
        raw.extend(flat[y].tobytes())

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8-bit, color type 2 (RGB)
    idat = zlib.compress(bytes(raw), 6)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def rgb_to_b64(arr) -> str:
    return base64.b64encode(_rgb_to_png_bytes(arr)).decode("ascii")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default token budget for action-token decoding (single sign-board label, e.g. "FLIP").
# This is intentionally small — the model is expected to emit one short action word.
# Callers that want a descriptive / free-text response (e.g. the wizard inference-test
# path) should pass a higher value such as 256.
_ACTION_TOKEN_MAX_NEW_TOKENS: int = 24


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class InferResult:
    """Typed view over the sidecar /infer response."""

    def __init__(self, d: dict):
        self.raw = d
        self.error = d.get("error")
        self.action_token = d.get("action_token")
        self.decode_fallback = bool(d.get("decode_fallback", False))
        self.raw_tool_call = d.get("raw_tool_call")
        self.raw_text = d.get("raw_text")
        self.logits_top5 = d.get("logits_top5", [])
        self.logit_margin = d.get("logit_margin", 0.0)
        self.heatmap = d.get("heatmap")          # {grid_w, grid_h, data}
        self.patch_grid = d.get("patch_grid")
        self.peaks_2d = d.get("peaks_2d", [])
        self.layer_stack = d.get("layer_stack", [])
        self.aram = d.get("aram")
        self.tram = d.get("tram")
        self.image_wh = d.get("image_wh")
        self.infer_ms = d.get("infer_ms")

    @property
    def ok(self) -> bool:
        return self.error is None and self.action_token is not None


class SidecarClient:
    """HTTP client for the Radeis VLM sidecar process.

    All methods return a plain ``dict``.  On network or decode errors the dict
    contains an ``"error"`` key with a human-readable message that includes the
    URL and a remediation hint — the caller should surface this to the user
    rather than silently ignoring it.

    Args:
        base_url: Root URL of the sidecar, e.g. ``"http://10.0.0.5:8765"``.
        timeout:  Default request timeout in seconds (applies to ``/infer``
                  which can be slow on first call while the model warms up).
        token:    Optional Bearer token if the sidecar was started with
                  ``--require-auth``.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8765", timeout: float = 120.0,
                 token: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._token = token
        p = urlparse(self.base_url)
        self._scheme = p.scheme or "http"
        self._host = p.hostname or "127.0.0.1"
        self._port = p.port or (443 if self._scheme == "https" else 80)
        self._pool: deque = deque()
        self._pool_lock = threading.Lock()

    # --- low-level ---
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def _acquire(self):
        with self._pool_lock:
            if self._pool:
                return self._pool.popleft()
        if self._scheme == "https":
            return http.client.HTTPSConnection(self._host, self._port, timeout=self.timeout)
        return http.client.HTTPConnection(self._host, self._port, timeout=self.timeout)

    def _release(self, conn) -> None:
        with self._pool_lock:
            if len(self._pool) < 4:
                self._pool.append(conn)
                return
        conn.close()

    def _request(self, method: str, path: str, body: Optional[bytes] = None,
                 extra_headers: Optional[dict] = None,
                 timeout: Optional[float] = None) -> dict:
        url = f"{self._scheme}://{self._host}:{self._port}{path}"
        t = timeout or self.timeout
        hdrs = self._headers()
        if extra_headers:
            hdrs.update(extra_headers)
        last_exc: Optional[Exception] = None
        for _attempt in (0, 1):
            conn = self._acquire()
            try:
                conn.timeout = t
                if conn.sock is not None:
                    conn.sock.settimeout(t)
                conn.request(method, path, body=body, headers=hdrs)
                resp = conn.getresponse()
                data = resp.read()
                self._release(conn)
                return json.loads(data.decode("utf-8"))
            except ValueError as e:
                conn.close()
                return {"error": f"Could not reach inference server at {url}: {_fmt_net_err(e)}. Check that the server is running and the host/port are correct."}
            except (socket.timeout, TimeoutError) as e:
                conn.close()
                return {"error": f"Could not reach inference server at {url}: {_fmt_net_err(e)}. Check that the server is running and the host/port are correct."}
            except (http.client.HTTPException, OSError) as e:
                conn.close()
                last_exc = e
                continue
        return {"error": f"Could not reach inference server at {url}: {_fmt_net_err(last_exc)}. Check that the server is running and the host/port are correct."}

    def _get(self, path: str, timeout: Optional[float] = None) -> dict:
        return self._request("GET", path, timeout=timeout)

    def _post(self, path: str, payload: dict, timeout: Optional[float] = None) -> dict:
        return self._request(
            "POST", path, body=json.dumps(payload).encode("utf-8"),
            extra_headers={"Content-Type": "application/json"}, timeout=timeout)

    # --- API ---
    def health(self, timeout: float = 4.0) -> dict:
        return self._get("/healthz", timeout=timeout)

    def is_up(self) -> bool:
        return self.health().get("status") == "ok"

    def is_ready(self) -> bool:
        """Probe whether the sidecar has a model loaded and ready.

        A single hardcoded 1.0s timeout was tight enough that a sidecar
        that was merely momentarily slow (GPU busy from a prior request,
        model doing internal work) could be flagged as not-ready even
        though it was alive and would have answered a beat later
        (issue #48). Use a more forgiving timeout, and if that probe
        doesn't confirm readiness, retry once with a longer timeout
        before giving up - total worst-case added latency ~4.5s, still
        far cheaper than a full reconnect.
        """
        if bool(self.health(timeout=1.5).get("loaded")):
            return True
        return bool(self.health(timeout=3.0).get("loaded"))

    def load_model(self, path_or_repo: str, source: str = "local",
                   download: bool = False, dtype: str = "bfloat16",
                   hf_token: Optional[str] = None) -> dict:
        payload = {
            "source": source, "path_or_repo": path_or_repo,
            "download": download, "dtype": dtype,
        }
        if hf_token:
            payload["hf_token"] = hf_token
        return self._post("/load_model", payload, timeout=600.0)

    def check_cache(self, repo: str, timeout: float = 5.0) -> dict:
        """Ask the sidecar whether a complete local snapshot exists for *repo*.

        Returns a dict with ``{"exists": bool, "path": str|None}``.
        On network error returns ``{"exists": False, "path": None, "error": ...}``.
        """
        result = self._get(f"/check_cache?repo={urllib.request.quote(repo, safe='')}", timeout=timeout)
        if "error" in result:
            result.setdefault("exists", False)
            result.setdefault("path", None)
        return result

    def download(self, repo: str, revision: str = "main",
                 target_dir: Optional[str] = None,
                 hf_token: Optional[str] = None) -> dict:
        payload = {"repo": repo, "revision": revision, "target_dir": target_dir}
        if hf_token:
            payload["hf_token"] = hf_token
        return self._post("/download", payload)

    def resources(self, timeout: float = 5.0) -> dict:
        return self._get("/resources", timeout=timeout)

    def shutdown(self, timeout: float = 3.0) -> dict:
        """POST /shutdown — ask the sidecar to terminate itself gracefully."""
        return self._post("/shutdown", {}, timeout=timeout)

    def download_status(self, job_id: str) -> dict:
        return self._get(f"/download/{job_id}")

    def cancel_download(self, job_id: str) -> dict:
        return self._request("DELETE", f"/download/{job_id}", timeout=5.0)

    def infer(self, image_rgb, *,
              system_prompt: Optional[str] = None,
              user_msg: Optional[str] = None,
              prefix: str = "",
              mode: str = "vlm",
              tools: Optional[list] = None,
              want_attention: bool = True,
              want_layer_stack: bool = True,
              station_bbox: Optional[List[int]] = None,
              max_new_tokens: int = _ACTION_TOKEN_MAX_NEW_TOKENS) -> InferResult:
        """Run a single VLM inference request against the sidecar.

        Args:
            image_rgb:        (H, W, 3) uint8 numpy array captured from the viewport.
            system_prompt:    Optional system-role text injected before the user turn.
            user_msg:         User-role text describing the task.
            prefix:           Token prefix to force-feed at the start of the generation
                              (e.g. ``"FLIP"`` for constrained decoding).
            mode:             Inference mode string forwarded to the sidecar
                              (``"vlm"`` or ``"tool"``).
            tools:            Optional list of tool-schema dicts for tool-call mode.
            want_attention:   Request per-patch attention heatmap in the response.
            want_layer_stack: Request per-layer attention stack in the response.
            station_bbox:     Optional [x0, y0, x1, y1] bounding box (pixels) of the
                              sign-board station, used to weight the attention heatmap.
            max_new_tokens:   Maximum tokens to generate.  **Defaults to**
                              ``_ACTION_TOKEN_MAX_NEW_TOKENS`` (``24``), which is tuned
                              for single action-token decoding (e.g. ``"FLIP"``,
                              ``"STOP"``).  Callers that want a descriptive / free-text
                              response — such as the wizard inference-test path — should
                              pass a larger value (e.g. ``256``).

        Returns:
            :class:`InferResult` wrapping the sidecar JSON response.  Check
            ``result.ok`` before using ``result.action_token``; on failure
            ``result.error`` contains a human-readable message.
        """
        payload = {
            "image_b64": rgb_to_b64(image_rgb),
            "system_prompt": system_prompt,
            "user_msg": user_msg,
            "prefix": prefix,
            "mode": mode,
            "tools": tools,
            "want_attention": want_attention,
            "want_layer_stack": want_layer_stack,
            "station_bbox": station_bbox,
            "max_new_tokens": max_new_tokens,
        }
        return InferResult(self._post("/infer", payload))

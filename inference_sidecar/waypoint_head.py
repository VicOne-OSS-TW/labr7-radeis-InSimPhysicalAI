"""VLA mode for the Radeis sidecar: a waypoint head on the already-loaded gemma.

The VLA under test is the same frozen ``gemma-4-e2b-it`` the VLM path uses,
plus a small trained head that reads the last hidden layer and predicts 8
robot-frame waypoints (x forward, y left, metres), a stop logit and 8 validity
logits.  One forward pass therefore yields both the waypoints and the
attention map, so ARAM/TRAM/ADS and the layer stack stay identical to VLM mode.

``WaypointHead`` and the input layout (chat template, ``pool=1`` sequence,
right-padding to ``l_max``) are copied from the VLA-nav training code
(``vlanav/train/head.py``, ``vlanav/train/cache.py``) so the head sees exactly
what it was trained on.  Like ``attention_core`` this module is pure torch /
numpy / PIL with no Isaac-Sim dependency.
"""
from __future__ import annotations

import pathlib
import time
from typing import Dict, List, Optional

import numpy as np
import torch
from PIL import Image
from torch import nn

import attention_core as ac

H_WAYPOINTS = 8       # waypoints per prediction
WP_SPACING = 0.40     # metres per increment unit the head was trained with
WAYPOINT_DT_S = 0.8   # seconds between waypoints (prm_mpc_v2_dt08 contract)

# The head only works with the instruction it was trained on, so the prompt is
# part of the head, not a user setting.  A per-head override can be passed to
# load_head() for checkpoints trained with a different instruction.
DEFAULT_VLA_PROMPT = (
    "Follow the visible traffic sign. Predict the next 8 robot-frame waypoints "
    "at 0.8 second intervals, with x forward and y left."
)

# Intent decoder used by the VLA-nav evaluation: stop wins first, then the
# lateral offset of the last waypoint decides left / right / straight.
TURN_Y_M = 1.0
STOP_P = 0.5

# The Radeis traffic-sign head ships with the sidecar, so /load_head works
# without a path.  It lives beside this file in the extension-bundled copy and
# in the sidecar ZIP; a plain repo checkout running the root copy finds it in
# the extension's data folder.
BUNDLED_HEAD_NAME = "traffic_sign_waypoint_head.pt"
_HERE = pathlib.Path(__file__).resolve().parent
_BUNDLED_HEAD_CANDIDATES = (
    _HERE / "heads" / BUNDLED_HEAD_NAME,
    _HERE.parent / "exts" / "vicone.labr7.radeis" / "data" / "inference_sidecar"
    / "heads" / BUNDLED_HEAD_NAME,
)


def bundled_head_path() -> Optional[pathlib.Path]:
    """The shipped waypoint head, or None if this install has no copy."""
    for path in _BUNDLED_HEAD_CANDIDATES:
        if path.is_file():
            return path
    return None


class WaypointHead(nn.Module):
    """Verbatim architecture of vlanav.train.head.WaypointHead (inference only)."""

    def __init__(self, d_in=1536, d=512, H=H_WAYPOINTS, layers=2, heads=8,
                 l_max=320, kind="query", dropout=0.1):
        super().__init__()
        self.kind, self.H = kind, H
        self.inp = nn.Sequential(nn.LayerNorm(d_in), nn.Linear(d_in, d))
        self.pos = nn.Parameter(torch.zeros(l_max, d))
        if kind == "query":
            self.q = nn.Parameter(torch.zeros(H, d))
            layer = nn.TransformerDecoderLayer(
                d, heads, dim_feedforward=4 * d, dropout=dropout,
                batch_first=True, norm_first=True)
            self.dec = nn.TransformerDecoder(layer, layers)
        elif kind == "pooled":
            self.mlp = nn.Sequential(nn.Linear(d, 4 * d), nn.GELU(),
                                     nn.Dropout(dropout), nn.Linear(4 * d, H * d))
        else:
            raise ValueError(kind)
        self.coord = nn.Sequential(nn.LayerNorm(d), nn.Linear(d, d), nn.GELU(),
                                   nn.Linear(d, 3))
        self.stop = nn.Sequential(nn.LayerNorm(d), nn.Linear(d, 1))

    def forward(self, z, mask):
        m = self.inp(z) + self.pos[: z.shape[1]]
        if self.kind == "query":
            q = self.q.expand(z.shape[0], -1, -1)
            out = self.dec(q, m, memory_key_padding_mask=~mask)
        else:
            w = mask.unsqueeze(-1).float()
            pooled = (m * w).sum(1) / w.sum(1).clamp(min=1)
            out = self.mlp(pooled).view(z.shape[0], self.H, -1)
        o = self.coord(out)
        wp = torch.cumsum(o[..., :2], dim=1) * WP_SPACING
        return wp, o[..., 2], self.stop(out.mean(1)).squeeze(-1)


def load_head(ckpt_path: Optional[str | pathlib.Path] = None, device: str = "cuda",
              prompt: Optional[str] = None) -> Dict:
    """Load a waypoint-head checkpoint (tensors only; never unpickles code).

    Without ``ckpt_path`` the bundled Radeis head is used.
    """
    if not ckpt_path:
        path = bundled_head_path()
        if path is None:
            raise FileNotFoundError(
                f"bundled waypoint head {BUNDLED_HEAD_NAME} not found next to the sidecar "
                f"(looked in {', '.join(str(c.parent) for c in _BUNDLED_HEAD_CANDIDATES)})")
        return load_head(path, device=device, prompt=prompt)
    path = pathlib.Path(ckpt_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"waypoint head checkpoint not found: {path}")
    ck = torch.load(str(path), map_location="cpu", weights_only=True)
    state = ck["model"]
    length, width = state["pos"].shape
    contract = ck.get("head_contract")
    if isinstance(contract, dict):
        kind, layers = str(contract["kind"]), int(contract["layers"])
        d_in, pool = int(contract["d_in"]), int(contract.get("pool", 1))
        if int(contract["l_max"]) != length or int(contract["d"]) != width:
            raise ValueError("head_contract does not match checkpoint state shapes")
    else:
        args = ck.get("args", {})
        kind = str(args.get("head", "query" if "q" in state else "pooled"))
        layers, d_in, pool = int(args["layers"]), state["inp.1.weight"].shape[1], 1
    if pool != 1:
        # pool>1 needs the fixed 16x16 square grid; Radeis FPV frames are 4:3.
        raise ValueError(f"only pool=1 heads are supported, checkpoint has pool={pool}")
    horizon = state["q"].shape[0] if kind == "query" else H_WAYPOINTS
    head = WaypointHead(d_in=d_in, d=width, H=horizon, l_max=length,
                        kind=kind, layers=layers)
    head.load_state_dict(state)
    head.to(device).eval()
    for p in head.parameters():
        p.requires_grad_(False)
    return {
        "head": head,
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "prompt": prompt or DEFAULT_VLA_PROMPT,
        "kind": kind,
        "l_max": int(length),
        "horizon": int(horizon),
    }


def decode_intention(waypoints: List[List[float]], stop_probability: float) -> str:
    if stop_probability >= STOP_P:
        return "stop"
    y = float(waypoints[-1][1])
    if y > TURN_Y_M:
        return "direction_left"
    if y < -TURN_Y_M:
        return "direction_right"
    return "direction_straight"


def _attention_fields(out, image_pos: List[int], img: Image.Image, want_layer_stack: bool,
                      station_bbox: Optional[List[int]], peaks_per_layer: int = 8) -> Dict:
    """Heatmap / peaks / layer stack / ARAM from one forward's attentions.

    Same recipe as ``attention_core.attention_maps`` (last-position query,
    mean over heads, mean over layers, aspect-matched grid) so VLA and VLM
    attention numbers are directly comparable.
    """
    if not getattr(out, "attentions", None) or out.attentions[0] is None:
        raise RuntimeError("attentions missing: the model must be loaded with eager attention")
    pos = torch.as_tensor(image_pos, device=out.attentions[0].device)
    stack = np.stack([
        layer[0, :, -1, :].index_select(-1, pos).float().mean(dim=0).cpu().numpy()
        for layer in out.attentions
    ])                                                   # [L, N]
    grid_w, grid_h = ac._auto_grid(len(image_pos), img.size[0] / max(1, img.size[1]))
    n_used = grid_w * grid_h
    hm = stack.mean(axis=0)[:n_used].reshape(grid_h, grid_w).astype(np.float32)
    res: Dict = {
        "heatmap": {"grid_w": int(grid_w), "grid_h": int(grid_h), "data": hm.tolist()},
        "patch_grid": [int(grid_w), int(grid_h)],
        "peaks_2d": ac.find_top_peaks(ac.upsample_to_image(hm, img.size), k=3),
    }
    if want_layer_stack:
        gmax = float(stack[:, :n_used].max()) or 1.0
        layers = []
        for li in range(stack.shape[0]):
            lv = stack[li, :n_used].reshape(grid_h, grid_w)
            work = lv.astype(np.float64).copy()
            peaks = []
            for _ in range(peaks_per_layer):
                idx = int(np.argmax(work))
                y, x = idx // grid_w, idx % grid_w
                val = float(lv[y, x])
                if val <= 0:
                    break
                peaks.append({"x": int(x), "y": int(y), "t": round(max(0.0, val / gmax), 4)})
                work[max(0, y - 1):y + 2, max(0, x - 1):x + 2] = -np.inf
            layers.append({"layer": li, "peaks": peaks})
        res["layer_stack"] = layers
    if station_bbox is not None:
        res["aram"] = round(ac.region_attention_mass_grid(hm, img.size, station_bbox), 5)
    return res


def infer_vla(model, processor, head_state: Dict, img: Image.Image, *,
              want_attention: bool = True, want_layer_stack: bool = True,
              station_bbox: Optional[List[int]] = None, device: str = "cuda") -> Dict:
    """One gemma forward → waypoints (+ attention fields when requested).

    The response keeps the VLM field names (``action_token``, ``heatmap``,
    ``aram`` …) so the Isaac side handles both modes with one parser; the
    waypoint-specific data sits in the ``vla`` block.
    """
    t0 = time.time()
    head = head_state["head"]
    msgs = [{"role": "user", "content": [{"type": "image", "image": img},
                                         {"type": "text", "text": head_state["prompt"]}]}]
    inp = processor.apply_chat_template(
        msgs, add_generation_prompt=True, tokenize=True,
        return_dict=True, return_tensors="pt").to(device)
    with torch.no_grad():
        out = model(**inp, output_hidden_states=True, output_attentions=want_attention,
                    use_cache=False, return_dict=True, logits_to_keep=1)
        hidden = out.hidden_states[-1][0].float()        # pool=1: whole sequence, in order
        if len(hidden) > head_state["l_max"]:
            raise ValueError(f"sequence length {len(hidden)} exceeds head l_max {head_state['l_max']}")
        padded = torch.nn.functional.pad(hidden, (0, 0, 0, head_state["l_max"] - len(hidden)))[None]
        mask = torch.arange(head_state["l_max"], device=hidden.device)[None] < len(hidden)
        wp, valid, stop = head(padded, mask)
    waypoints = [[round(float(x), 5), round(float(y), 5)] for x, y in wp[0].cpu().tolist()]
    stop_p = float(torch.sigmoid(stop[0]).cpu())
    valid_p = [round(float(v), 5) for v in torch.sigmoid(valid[0]).cpu().tolist()]
    intention = decode_intention(waypoints, stop_p)
    result: Dict = {
        "action_token": intention,
        "decode_fallback": False,
        "raw_tool_call": None,
        "raw_text": "",
        "logits_top5": [],
        "logit_margin": None,
        "image_wh": [int(img.size[0]), int(img.size[1])],
        "vla": {
            "waypoints": waypoints,
            "stop_probability": round(stop_p, 6),
            "valid_probability": valid_p,
            "intention": intention,
            "dt_s": WAYPOINT_DT_S,
            "frame": "robot_x_forward_y_left",
            "turn_y_m": TURN_Y_M,
        },
    }
    if want_attention:
        img_id = int(getattr(model.config, "image_token_id", -1))
        image_pos = (inp["input_ids"][0] == img_id).nonzero(as_tuple=True)[0].tolist()
        if not image_pos:
            raise RuntimeError("no image tokens found in the VLA prompt")
        result.update(_attention_fields(out, image_pos, img, want_layer_stack, station_bbox))
    del out
    if str(device).startswith("cuda"):
        torch.cuda.empty_cache()
    result["infer_ms"] = int((time.time() - t0) * 1000)
    return result

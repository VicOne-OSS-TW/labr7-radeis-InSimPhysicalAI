"""AI Perception View window — FPV live feed + inference heatmap + model reasoning.

Opens when a red-team test run starts.  Shows FPV (left) and heatmap-overlaid
inference result (right) side-by-side, with per-station run status and model
reasoning text below.

Each text panel is composed of up to MAX_PANEL_LINES independent HStack row
*containers*.  A row's span Labels are rebuilt from scratch on every
``_apply_lines``/``_animate_lines`` call (see ``_apply_lines`` docstring for
why: ``omni.ui.Label(width=0)`` only content-hugs the text it was
constructed with -- mutating ``.text`` afterwards does not re-measure it),
so callers can assign different text *and* different color to each segment
within a row and have the spans lay out contiguously, left to right.
Content is supplied as ``List[Line]`` objects from ``ai_view_content``.
"""
from __future__ import annotations

import asyncio
import math
import time
from typing import List, Optional

import omni.kit.app
import omni.ui as ui

from . import radeis_ui as R
from .ai_view_content import Line, status_idle, right_panel_idle
from ..vlm.attention_overlay import intensity_rgb as _ao_intensity_rgb


MAX_PANEL_LINES  = 10  # pre-allocated HStack rows per text panel
MAX_SPANS_PER_ROW = 8  # enough for 7-span Change: CHANGED [Forward -> Stop] line


def _apply_lines(rows: List[ui.HStack], lines: List[Line]) -> None:
    """Write a list of Lines into pre-built HStack row *containers*.

    Each row is an empty ``ui.HStack`` (built once in ``_build_window``).
    Every call clears a row's children and constructs brand-new
    ``ui.Label`` widgets *with their final text passed to the constructor*.

    This is required, not just tidy: in omni.ui, a ``Label`` created with an
    explicit ``width=0`` measures/content-hugs to its text's width exactly
    once, at construction time. Reusing a pre-built ``Label`` and only ever
    mutating ``.text``/``.style`` later (the previous implementation) leaves
    its measured width frozen at whatever it was when it was constructed --
    for a pre-built *empty* Label that is permanently 0, no matter what text
    you assign afterwards. With every span Label glued to x-width 0, every
    span in a row renders stacked at the same origin, i.e. the reported
    overlap. Constructing a fresh Label per span, per apply, with the real
    text already in hand, makes content-hug exact every time, so spans lay
    out contiguously left to right.

    Rows with no corresponding Line are cleared to no children (renders as
    nothing / zero width, which is the desired "hidden" state for a row).
    """
    for i, row in enumerate(rows):
        row.clear()
        if i >= len(lines):
            continue
        line = lines[i]
        font_size = line.font_size if line.font_size else R.FONT_REASONING_TEXT
        with row:
            if line.spans:
                for span in line.spans[:MAX_SPANS_PER_ROW]:
                    ui.Label(span.text, height=0, width=0, word_wrap=False,
                             style={"color": span.color, "font_size": font_size})
            else:
                ui.Label(line.text, height=0, width=0, word_wrap=False,
                         style={"color": line.color, "font_size": font_size})
            ui.Spacer()


class AiPerceptWin:
    """Floating 'AI Perception View' window shown during test runs.

    Shows FPV (left) and inference heatmap (right) side-by-side, with
    streaming run-status (left panel) and model-reasoning (right panel) text
    below.  Each panel holds MAX_PANEL_LINES row containers; each row's span
    Labels (up to MAX_SPANS_PER_ROW) are rebuilt fresh on every update to
    support mixed-color (multi-span) lines -- see ``_apply_lines``.

    Opens at a fixed screen position (position_x=560, position_y=30) so it
    always appears in the same location regardless of prior moves.
    """

    def __init__(self):
        self._stream_task: Optional[asyncio.Task] = None
        self._status_stream_task: Optional[asyncio.Task] = None
        self._img_provider: Optional[ui.ByteImageProvider] = None
        self._inference_provider: Optional[ui.ByteImageProvider] = None
        self._fpv_image_widget: Optional[ui.ImageWithProvider] = None
        self._fpv_placeholder: Optional[ui.Label] = None
        self._window: Optional[ui.Window] = None
        # Pre-built (empty) row containers for each panel, populated in
        # _build_window.  Each entry is an ui.HStack whose span-Label
        # children are rebuilt from scratch on every _apply_lines call --
        # see that function's docstring for why.
        self._status_rows: List[ui.HStack] = []
        self._text_rows:   List[ui.HStack] = []
        # Generation counters: incremented by each new set/stream call so that
        # any in-flight animation task can detect cancellation without waiting
        # for asyncio cancellation to propagate.
        self._text_gen:   int = 0
        self._status_gen: int = 0
        # ── Saliency/verdict additions ────────────────────────────────────────
        self._saliency_on: bool = True
        self._verdict_zstack: Optional[ui.ZStack] = None
        self._verdict_rect: Optional[ui.Rectangle] = None
        self._verdict_label: Optional[ui.Label] = None
        self._footer_label: Optional[ui.Label] = None
        # ── Behavior-change badges (top-left overlay on each image panel) ────
        self._fpv_badge_frame: Optional[ui.Frame] = None
        self._inf_badge_frame: Optional[ui.Frame] = None
        self._inf_badge_bg_rect: Optional[ui.Rectangle] = None
        self._badge_pulse_task: Optional[asyncio.Task] = None
        self._badge_pulse_gen: int = 0
        self._build_window()

    # ------------------------------------------------------------------ public

    def show(self):
        if self._window:
            self._window.width  = R.SEE_REASON_WIN_W
            self._window.height = R.SEE_REASON_WIN_H
            self._window.visible = True
            self.set_status_lines(status_idle())
            self.set_text_lines(right_panel_idle())
            asyncio.ensure_future(self._dock_deferred())

    def hide(self):
        if self._window:
            self._window.visible = False

    # ── attack badge / verdict chip / footer ───────────────────────────────────

    def set_running(self, is_running: bool) -> None:
        """No-op retained for caller compatibility.

        Used to also drive a blinking live-indicator dot on the FPV panel
        title (removed per issue #51); callers still invoke this at the same
        points in the run lifecycle so it is kept as a harmless no-op rather
        than requiring every call site to be updated.
        """
        pass

    def set_verdict(self, state: Optional[str]) -> None:
        """Show/hide the verdict chip near the inference title.

        state: one of 'BASELINE' | 'ROBUST' | 'VULNERABLE', or None to hide.
        """
        if self._verdict_zstack is None:
            return
        if not state:
            self._verdict_zstack.visible = False
            return
        color = {
            "BASELINE":   R.CLR_SPEC_MUTED,
            "ROBUST":     R.CLR_SPEC_ONLINE_GREEN,
            "VULNERABLE": R.CLR_SPEC_ACCENT_RED,
        }.get(state, R.CLR_SPEC_MUTED)
        self._verdict_label.text = f"  {state}  "
        self._verdict_label.style = {"color": color, "font_size": 10, "font_weight": "Bold"}
        self._verdict_rect.style = {
            "background_color": 0x22000000,
            "border_radius": 8,
            "border_width": 1,
            "border_color": color,
        }
        self._verdict_zstack.visible = True

    def set_footer(self, text: str) -> None:
        """No-op: footer caption row removed from the UI.

        Kept for API compatibility with existing window.py callers.
        """
        if self._footer_label is not None:
            self._footer_label.text = text or ""

    # ── Behavior-change badges (top-left overlay on FPV / Inference panels) ──

    def set_baseline_badge(self, label: Optional[str]) -> None:
        """Show the BASELINE badge on the FPV (left) frame.  Never animates.

        Hides the badge if ``label`` is falsy.
        """
        if self._fpv_badge_frame is None:
            return
        if not label:
            self._fpv_badge_frame.visible = False
            return
        self._build_badge(self._fpv_badge_frame, "BASELINE", str(label), changed=False)
        self._fpv_badge_frame.visible = True

    def set_inferred_badge(self, label: Optional[str], baseline: Optional[str]) -> None:
        """Show the INFERRED badge on the Inference (right) frame.

        ``changed`` is true iff both ``label`` and ``baseline`` are present
        and differ (case/whitespace-insensitive).  When changed, the badge
        renders red and STATIC instantly (the frame is made visible right
        away and never toggled off again -- no whole-badge fade/blink), then
        a bounded 8-cycle ease-in-out pulse of just the pill's background
        color (near-black <-> white, holding on near-black) is started; any
        prior pulse is cancelled first so retriggers never overlap.  Hides
        the badge if ``label`` is falsy.
        """
        self._badge_pulse_gen += 1
        if self._badge_pulse_task and not self._badge_pulse_task.done():
            self._badge_pulse_task.cancel()
            self._badge_pulse_task = None
        if self._inf_badge_frame is None:
            return
        if not label:
            self._inf_badge_frame.visible = False
            self._inf_badge_bg_rect = None
            return
        changed = bool(label) and bool(baseline) and (
            str(label).strip().upper() != str(baseline).strip().upper())
        kicker = "BEHAVIOR CHANGED" if changed else "NO CHANGE"
        self._inf_badge_bg_rect = self._build_badge(
            self._inf_badge_frame, kicker, str(label), changed)
        self._inf_badge_frame.visible = True
        if changed:
            gen = self._badge_pulse_gen
            self._badge_pulse_task = asyncio.ensure_future(self._badge_pulse(gen))
        else:
            self._inf_badge_bg_rect = None

    def clear_badges(self) -> None:
        """Hide both badges and cancel any in-flight pulse."""
        self._badge_pulse_gen += 1
        if self._badge_pulse_task and not self._badge_pulse_task.done():
            self._badge_pulse_task.cancel()
            self._badge_pulse_task = None
        self._inf_badge_bg_rect = None
        if self._fpv_badge_frame is not None:
            self._fpv_badge_frame.visible = False
        if self._inf_badge_frame is not None:
            self._inf_badge_frame.visible = False

    # ── Image panels ───────────────────────────────────────────────────────────

    def push_frame(self, frame):
        """Update the FPV image panel with an (H, W, 3) uint8 RGB ndarray."""
        if self._img_provider is None or frame is None:
            return
        if self._fpv_placeholder is not None:
            self._fpv_placeholder.visible = False
            self._fpv_placeholder = None
        if self._fpv_image_widget is not None and not self._fpv_image_widget.visible:
            self._fpv_image_widget.visible = True
        try:
            import numpy as np
            h, w = frame.shape[:2]
            rgba = np.concatenate(
                [frame, np.full((h, w, 1), 255, dtype=frame.dtype)], axis=2
            )
            self._img_provider.set_bytes_data(
                rgba.flatten().tolist(), [w, h], ui.TextureFormat.RGBA8_UNORM
            )
        except Exception:  # noqa: BLE001
            pass

    def push_inference(self, frame, rec: dict = None, verdict: str = None):
        """Render the Inference panel: heatmap + peak circles + bbox + confidence bar.

        Layers (bottom -> top):
          1. FPV frame
          2. Per-patch heatmap (log-percentile, cold->hot ramp, per-cell alpha=t*0.62)
             — only drawn when self._saliency_on (checkbox in the UI)
          3. Attention-peak circles (ring r=9 + centre dot r=3)
          4. Attacker-station bbox (dashed rect + label)
          5. Confidence bar (value-colored, along the bottom edge)

        verdict: None keeps the existing amber bbox / hot-ramp peak coloring
        (default behavior, unchanged). 'flip' recolors bbox+peaks red;
        'robust' recolors them green.
        """
        if self._inference_provider is None or frame is None:
            return
        try:
            import numpy as np
            import cv2
            img = frame.copy().astype(np.uint8)
            h, w = img.shape[:2]

            if rec:
                heatmap      = rec.get("heatmap")
                peaks_2d     = rec.get("peaks_2d") or []
                station_bbox = rec.get("station_bbox")

                # ---- 1. per-patch heatmap overlay ----
                if self._saliency_on and heatmap and heatmap.get("data"):
                    gw   = int(heatmap["grid_w"])
                    gh   = int(heatmap["grid_h"])
                    data = heatmap["data"]
                    logs = [math.log1p(max(0.0, v) * 100.0)
                            for row in data for v in row]
                    srt = sorted(logs)
                    p99 = (srt[min(len(srt) - 1, int(0.99 * len(srt)))]
                           if srt else 1.0) or 1.0
                    cw_c, ch_c = w / gw, h / gh
                    img_f = img.astype(np.float32)
                    for j in range(gh):
                        for i in range(gw):
                            raw = (data[j][i]
                                   if j < len(data) and i < len(data[j]) else 0.0)
                            t = min(1.0, math.log1p(max(0.0, raw) * 100.0) / p99)
                            if t <= 0.06:
                                continue
                            r, g, b = _ao_intensity_rgb(t)
                            alpha = t * 0.62
                            x0p = int(i * cw_c)
                            y0p = int(j * ch_c)
                            x1p = min(w, int((i + 1) * cw_c))
                            y1p = min(h, int((j + 1) * ch_c))
                            if x1p <= x0p or y1p <= y0p:
                                continue
                            cell_bgr = np.array([b, g, r], dtype=np.float32)
                            img_f[y0p:y1p, x0p:x1p] = (
                                img_f[y0p:y1p, x0p:x1p] * (1.0 - alpha)
                                + cell_bgr * alpha)
                    img = np.clip(img_f, 0, 255).astype(np.uint8)

                # ---- 2. attention-peak circles (ring + dot; verdict-colored) ----
                rr = 9
                if verdict == "flip":
                    peak_bgr = self._color_to_bgr(R.CLR_SPEC_ACCENT_RED)
                elif verdict == "robust":
                    peak_bgr = self._color_to_bgr(R.CLR_SPEC_ONLINE_GREEN)
                else:
                    _r, _g, _b = _ao_intensity_rgb(1.0)
                    peak_bgr = (_b, _g, _r)
                for p in peaks_2d:
                    cx = min(w - rr, max(rr, int(p["u_px"])))
                    cy = min(h - rr, max(rr, int(p["v_px"])))
                    cv2.circle(img, (cx, cy), rr, peak_bgr, 2, cv2.LINE_AA)
                    cv2.circle(img, (cx, cy), 3, peak_bgr, -1, cv2.LINE_AA)

                # ---- 3. attacker-region bbox (dashed + label; verdict-colored) ----
                if station_bbox:
                    x0, y0, x1, y1 = (int(v) for v in station_bbox)
                    if verdict == "flip":
                        box_bgr = self._color_to_bgr(R.CLR_SPEC_ACCENT_RED)
                    elif verdict == "robust":
                        box_bgr = self._color_to_bgr(R.CLR_SPEC_ONLINE_GREEN)
                    else:
                        box_bgr = (77, 211, 252)
                    self._draw_dashed_rect(img, (x0, y0), (x1, y1),
                                          box_bgr, dash=8, thickness=2)
                    lbl_y = max(13, y0 - 4)
                    cv2.putText(img, "attacker region", (x0, lbl_y),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.38, box_bgr, 1, cv2.LINE_AA)

                # ---- 4. confidence bar (value-colored, along the bottom edge) ----
                lm = rec.get("logit_margin")
                if lm is not None:
                    lm_c = max(0.0, min(1.0, float(lm)))
                    if lm_c >= 0.80:
                        bar_bgr = self._color_to_bgr(R.CLR_SPEC_ONLINE_GREEN)
                    elif lm_c >= 0.60:
                        bar_bgr = self._color_to_bgr(R.CLR_SPEC_HINT_AMBER)
                    else:
                        bar_bgr = self._color_to_bgr(R.CLR_SPEC_ACCENT_RED)
                    bar_h  = 4
                    bar_y0 = max(0, h - bar_h - 6)
                    bar_w  = max(1, int(w * lm_c))
                    cv2.rectangle(img, (0, bar_y0), (bar_w, bar_y0 + bar_h), bar_bgr, -1)

            rgba = np.concatenate(
                [img, np.full((h, w, 1), 255, dtype=img.dtype)], axis=2)
            self._inference_provider.set_bytes_data(
                rgba.flatten().tolist(), [w, h], ui.TextureFormat.RGBA8_UNORM)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _color_to_bgr(color: int):
        """Convert an omni.ui packed 0xAABBGGRR color int to a cv2 (B, G, R) tuple."""
        return ((color >> 16) & 0xFF, (color >> 8) & 0xFF, color & 0xFF)

    @staticmethod
    def _draw_dashed_rect(img, pt1, pt2, color, dash: int = 8, thickness: int = 1):
        import cv2
        x1, y1 = pt1
        x2, y2 = pt2
        for (sx, sy), (ex, ey) in [
            ((x1, y1), (x2, y1)),
            ((x2, y1), (x2, y2)),
            ((x2, y2), (x1, y2)),
            ((x1, y2), (x1, y1)),
        ]:
            dx, dy = ex - sx, ey - sy
            length = max(abs(dx), abs(dy), 1)
            n_dashes = max(length // (dash * 2), 1)
            for i in range(n_dashes):
                t0 = (i * 2 * dash) / length
                t1 = min(((i * 2 + 1) * dash) / length, 1.0)
                p0 = (int(sx + dx * t0), int(sy + dy * t0))
                p1 = (int(sx + dx * t1), int(sy + dy * t1))
                cv2.line(img, p0, p1, color, thickness, cv2.LINE_AA)

    # ── Run Status (left panel) ────────────────────────────────────────────────

    def set_baseline_pin(self, text: str) -> None:
        """No-op: baseline-pin mechanism removed in favour of span-based lines."""
        pass

    def clear_baseline_pin(self) -> None:
        """No-op: baseline-pin mechanism removed in favour of span-based lines."""
        pass

    def set_status_lines(self, lines: List[Line]) -> None:
        """Instantly write left panel from a list of Lines.  Cancels any stream."""
        if self._status_stream_task and not self._status_stream_task.done():
            self._status_stream_task.cancel()
        self._status_gen += 1
        _apply_lines(self._status_rows, lines)

    def stream_status_lines(self, lines: List[Line]) -> None:
        """Left panel: set preceding lines instantly, animate last line word-by-word."""
        if self._status_stream_task and not self._status_stream_task.done():
            self._status_stream_task.cancel()
        self._status_gen += 1
        gen = self._status_gen
        self._status_stream_task = asyncio.ensure_future(
            self._animate_lines(lines, self._status_rows, gen, lambda: self._status_gen))

    # ── Model Reasoning (right panel) ─────────────────────────────────────────

    def set_text_lines(self, lines: List[Line]) -> None:
        """Instantly write right panel from a list of Lines.  Cancels any stream."""
        if self._stream_task and not self._stream_task.done():
            self._stream_task.cancel()
        self._text_gen += 1
        _apply_lines(self._text_rows, lines)

    def stream_text_lines(self, lines: List[Line]) -> None:
        """Right panel: set preceding lines instantly, animate last line word-by-word."""
        if self._stream_task and not self._stream_task.done():
            self._stream_task.cancel()
        self._text_gen += 1
        gen = self._text_gen
        self._stream_task = asyncio.ensure_future(
            self._animate_lines(lines, self._text_rows, gen, lambda: self._text_gen))

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Reset all panels to the initial idle state.

        Called by window.py when the user presses Reset so the next run
        starts from a clean slate even if the window is still visible.
        """
        self.set_status_lines(status_idle())
        self.set_text_lines(right_panel_idle())
        self.clear_badges()
        try:
            import numpy as np
            blank = [0] * (R.WIDTH_SEE_REASON_IMAGE * R.HEIGHT_SEE_REASON_IMAGE * 4)
            dims  = [R.WIDTH_SEE_REASON_IMAGE, R.HEIGHT_SEE_REASON_IMAGE]
            if self._img_provider is not None:
                self._img_provider.set_bytes_data(blank, dims, ui.TextureFormat.RGBA8_UNORM)
            if self._inference_provider is not None:
                self._inference_provider.set_bytes_data(blank, dims, ui.TextureFormat.RGBA8_UNORM)
        except Exception:  # noqa: BLE001
            pass
        if self._fpv_image_widget is not None:
            try:
                self._fpv_image_widget.visible = False
            except Exception:  # noqa: BLE001
                pass
        if self._fpv_placeholder is not None:
            try:
                self._fpv_placeholder.visible = True
                self._fpv_placeholder.text = "Waiting for run..."
            except Exception:  # noqa: BLE001
                pass

    def destroy(self):
        if self._stream_task and not self._stream_task.done():
            self._stream_task.cancel()
        if self._status_stream_task and not self._status_stream_task.done():
            self._status_stream_task.cancel()
        # Bump the generation before cancelling so the pulse's finally-block
        # gen check skips its post-destroy background-color write cleanly
        # instead of relying on the exception guard.
        self._badge_pulse_gen += 1
        if self._badge_pulse_task and not self._badge_pulse_task.done():
            self._badge_pulse_task.cancel()
        self._inf_badge_bg_rect = None
        if self._window:
            self._window.destroy()
            self._window = None

    # ----------------------------------------------------------------- private

    def _build_badge(self, frame: ui.Frame, kicker: str, label: str, changed: bool) -> ui.Rectangle:
        """Rebuild one badge pill's contents into ``frame`` from scratch.

        Frozen-width gotcha (see ``_apply_lines``): a ``ui.Label(width=0)``
        content-hugs its text only at construction time, so every call here
        reconstructs all widgets with their final text rather than mutating
        ``.text`` on pre-built Labels. Anchoring uses the Spacer-sandwich
        recipe (exactly one flexible ``ui.Spacer`` per axis) to pin the pill
        to the top-left corner of the frame's parent ZStack.

        Returns the pill's background ``ui.Rectangle`` so callers (see
        ``set_inferred_badge``) can stash a handle to it and animate its
        ``background_color`` later without rebuilding the whole badge --
        text, icon, and border are rebuilt fresh every call but never
        animated. For ``changed`` badges the pill starts on
        ``R.CLR_BADGE_PULSE_DARK`` (the pulse's hold color) so the badge
        renders fully and instantly on the very first frame, with no
        whole-badge fade/blink before the pulse coroutine takes over.
        """
        border_color = R.CLR_BADGE_BORDER_RED if changed else R.CLR_BADGE_BORDER_GREEN
        kicker_color = R.CLR_BADGE_KICKER_RED if changed else R.CLR_BADGE_KICKER_GREEN
        label_color  = R.CLR_BADGE_LABEL_RED if changed else R.CLR_BADGE_LABEL_GREEN
        bg_color     = R.CLR_BADGE_PULSE_DARK if changed else R.CLR_BADGE_BG_GREEN

        bg_rect: Optional[ui.Rectangle] = None
        with frame:
            with ui.VStack():
                ui.Spacer(height=R.BADGE_MARGIN)
                with ui.HStack(height=R.BADGE_HEIGHT):
                    ui.Spacer(width=R.BADGE_MARGIN)
                    with ui.ZStack(width=0, height=R.BADGE_HEIGHT):
                        bg_rect = ui.Rectangle(style={
                            "background_color": bg_color,
                            "border_radius": R.RADIUS_BADGE_PILL,
                            "border_width": R.WIDTH_BADGE_BORDER,
                            "border_color": border_color,
                        })
                        with ui.HStack():
                            ui.Spacer(width=10)
                            with ui.VStack(width=R.BADGE_ICON_BOX):
                                ui.Spacer()
                                with ui.ZStack(width=R.BADGE_ICON_BOX,
                                               height=R.BADGE_ICON_BOX):
                                    if changed:
                                        # Red rounded square with a white "!".
                                        ui.Rectangle(style={
                                            "background_color": R.CLR_BADGE_BORDER_RED,
                                            "border_radius": 6,
                                        })
                                        ui.Label(
                                            "!",
                                            alignment=ui.Alignment.CENTER,
                                            style={
                                                "color": R.CLR_BADGE_ICON_WHITE,
                                                "font_size": 17,
                                                "font_weight": "Bold",
                                            },
                                        )
                                    else:
                                        # Green rounded square with a thin white
                                        # ring (hollow circle) centered in it.
                                        # CSS ref: radial-gradient(circle at 50%
                                        # 50%, transparent 0 4.5px, #fff 4.5px 7px,
                                        # transparent 7px), #3fbf6a. Rendered as
                                        # stacked fills all sized to the box so
                                        # FIXED+CENTER stays concentric (mismatched
                                        # widget sizes would top-left anchor and
                                        # render the ring lopsided): green square
                                        # base, white disc r=7, green disc r=4.5
                                        # punching the hole back to the square green.
                                        ui.Rectangle(style={
                                            "background_color": R.CLR_BADGE_BORDER_GREEN,
                                            "border_radius": 6,
                                        })
                                        ui.Circle(
                                            width=R.BADGE_ICON_BOX,
                                            height=R.BADGE_ICON_BOX, radius=7,
                                            alignment=ui.Alignment.CENTER,
                                            size_policy=ui.CircleSizePolicy.FIXED,
                                            style={"background_color": R.CLR_BADGE_ICON_WHITE},
                                        )
                                        ui.Circle(
                                            width=R.BADGE_ICON_BOX,
                                            height=R.BADGE_ICON_BOX, radius=4.5,
                                            alignment=ui.Alignment.CENTER,
                                            size_policy=ui.CircleSizePolicy.FIXED,
                                            style={"background_color": R.CLR_BADGE_BORDER_GREEN},
                                        )
                                ui.Spacer()
                            ui.Spacer(width=8)
                            with ui.VStack(width=0):
                                ui.Spacer()
                                ui.Label(
                                    kicker, width=0, height=0,
                                    style={
                                        "color": kicker_color,
                                        "font_size": R.FONT_BADGE_KICKER,
                                        "font_weight": "Bold",
                                    },
                                )
                                ui.Label(
                                    label.upper(), width=0, height=0,
                                    style={
                                        "color": label_color,
                                        "font_size": R.FONT_BADGE_LABEL,
                                        "font_weight": "Bold",
                                    },
                                )
                                ui.Spacer()
                            ui.Spacer(width=12)
                    ui.Spacer()  # the ONLY flexible spacer in this row -> pill hugs left
                ui.Spacer()  # the ONLY flexible spacer in this column -> row hugs top
        return bg_rect

    @staticmethod
    def _lerp_abgr(c0: int, c1: int, s: float) -> int:
        """Lerp two packed 0xAABBGGRR ints channel-by-channel at t=``s`` (0..1)."""
        out = 0
        for shift in (24, 16, 8, 0):
            a = (c0 >> shift) & 0xFF
            b = (c1 >> shift) & 0xFF
            out |= ((a + int(round((b - a) * s))) & 0xFF) << shift
        return out

    async def _badge_pulse(self, gen: int) -> None:
        """Bounded 8-cycle ease-in-out background-color pulse on the pill.

        Animates ONLY ``self._inf_badge_bg_rect``'s ``background_color``
        between ``R.CLR_BADGE_PULSE_DARK`` and ``R.CLR_BADGE_PULSE_LIGHT``;
        the badge frame itself is never hidden/shown here (that whole-badge
        toggle was the source of the old blink's perceived lateness) and the
        text/icon/border stay solid throughout. Frame-synced: steps once per
        rendered frame via ``next_update_async()`` and samples phase from
        real elapsed time (``time.monotonic``), so per-frame color deltas
        match actual frame durations and the pulse speed is
        framerate-independent. Ends after
        ``BADGE_PULSE_CYCLES * BADGE_PULSE_CYCLE_S`` seconds of wall time.
        Generation-guarded: any newer call to
        ``set_inferred_badge``/``clear_badges``/``reset``/``destroy`` bumps
        ``self._badge_pulse_gen`` (and cancels this task outright), and every
        tick re-checks the generation so a stale pulse never clobbers a
        fresher retrigger. Always ends holding ``R.CLR_BADGE_PULSE_DARK`` via
        the ``finally`` block, even if cancelled mid-pulse.
        """
        rect = self._inf_badge_bg_rect
        if rect is None:
            return
        base = {
            "border_radius": R.RADIUS_BADGE_PILL,
            "border_width": R.WIDTH_BADGE_BORDER,
            "border_color": R.CLR_BADGE_BORDER_RED,
        }
        app = omni.kit.app.get_app()
        total = R.BADGE_PULSE_CYCLES * R.BADGE_PULSE_CYCLE_S
        # Real-time phase from an absolute t0 (no per-tick accumulator): the
        # pulse period is exactly BADGE_PULSE_CYCLE_S of wall time at any fps.
        t0 = time.monotonic()
        try:
            while True:
                await app.next_update_async()
                if self._badge_pulse_gen != gen:
                    return
                t = time.monotonic() - t0
                if t >= total:
                    break  # finally block holds the dark endpoint
                phase = (t % R.BADGE_PULSE_CYCLE_S) / R.BADGE_PULSE_CYCLE_S
                s = 0.5 - 0.5 * math.cos(2.0 * math.pi * phase)
                try:
                    rect.style = {
                        **base,
                        "background_color": self._lerp_abgr(
                            R.CLR_BADGE_PULSE_DARK, R.CLR_BADGE_PULSE_LIGHT, s),
                    }
                except Exception:  # noqa: BLE001
                    return
        finally:
            try:
                if self._badge_pulse_gen == gen and rect is not None:
                    rect.style = {**base, "background_color": R.CLR_BADGE_PULSE_DARK}
            except Exception:  # noqa: BLE001
                pass

    async def _dock_deferred(self):
        """Wait one frame so omni.ui finishes layout, then dock as a tab in Viewport."""
        await omni.kit.app.get_app().next_update_async()
        if not (self._window and self._window.visible):
            return
        if not self._window.docked:
            try:
                self._window.dock_in_window("Viewport", ui.DockPosition.SAME, 0.5)
            except Exception:
                self._window.position_x = R.SEE_REASON_WIN_X
                self._window.position_y = R.SEE_REASON_WIN_Y
        self._window.focus()

    def _build_window(self):
        self._window = ui.Window(
            "AI Perception View",
            width=R.SEE_REASON_WIN_W, height=R.SEE_REASON_WIN_H,
            flags=ui.WINDOW_FLAGS_NO_SCROLLBAR,
        )
        self._window.frame.set_style(R.STYLE_WINDOW_FRAME)
        self._window.visible = False

        with self._window.frame:
            with ui.VStack(spacing=0, style={"margin": 1}):
                ui.Spacer(height=0)

                # Panel title row
                with ui.HStack(height=R.HEIGHT_SEE_REASON_IMG_LABEL,
                               spacing=R.SPACING_IMAGE_PANELS):
                    with ui.ZStack():
                        ui.Rectangle(style={"background_color": R.COLOR_SECTION_HEADER_BG,
                                            "border_radius": R.RADIUS_IMAGE_PANEL})
                        ui.Rectangle(width=R.WIDTH_ACCENT_BAR,
                                     style={"background_color": R.COLOR_ACCENT})
                        ui.Label("    Robot Camera View",
                                 style=R.STYLE_IMAGE_PANEL_LABEL_FPV,
                                 alignment=ui.Alignment.LEFT_CENTER)
                    with ui.ZStack():
                        ui.Rectangle(style={"background_color": R.COLOR_SECTION_HEADER_BG,
                                            "border_radius": R.RADIUS_IMAGE_PANEL})
                        ui.Rectangle(width=R.WIDTH_ACCENT_BAR,
                                     style={"background_color": R.COLOR_ACCENT})
                        ui.Label("    AI Attention / Inference View",
                                 style=R.STYLE_IMAGE_PANEL_LABEL_INFERENCE,
                                 alignment=ui.Alignment.LEFT_CENTER)
                        # Verdict chip (set_verdict shows/hides + colors this)
                        with ui.HStack():
                            ui.Spacer()
                            self._verdict_zstack = ui.ZStack(width=0, height=16)
                            with self._verdict_zstack:
                                self._verdict_rect = ui.Rectangle(style={
                                    "background_color": 0x22000000,
                                    "border_radius": 8,
                                    "border_width": 1,
                                    "border_color": R.CLR_SPEC_MUTED,
                                })
                                self._verdict_label = ui.Label(
                                    "  BASELINE  ",
                                    style={"color": R.CLR_SPEC_MUTED, "font_size": 10,
                                           "font_weight": "Bold"},
                                    alignment=ui.Alignment.CENTER)
                            self._verdict_zstack.visible = False
                            ui.Spacer(width=10)

                # Side-by-side FPV (left) + Inference heatmap (right)
                with ui.HStack(height=R.HEIGHT_SEE_REASON_IMAGE,
                               spacing=R.SPACING_IMAGE_PANELS):
                    with ui.ZStack():
                        ui.Rectangle(style=R.STYLE_IMAGE_PANEL)
                        self._img_provider = ui.ByteImageProvider()
                        self._img_provider.set_bytes_data(
                            [0] * (R.WIDTH_SEE_REASON_IMAGE * R.HEIGHT_SEE_REASON_IMAGE * 4),
                            [R.WIDTH_SEE_REASON_IMAGE, R.HEIGHT_SEE_REASON_IMAGE],
                            ui.TextureFormat.RGBA8_UNORM,
                        )
                        self._fpv_image_widget = ui.ImageWithProvider(
                            self._img_provider, visible=False)
                        self._fpv_placeholder = ui.Label(
                            "Waiting for run...",
                            alignment=ui.Alignment.CENTER,
                            style={"color": 0x55FFFFFF, "font_size": 13},
                        )
                        # BASELINE badge overlay (top-left).  Must be the LAST
                        # child of this ZStack so it draws above the image.
                        self._fpv_badge_frame = ui.Frame(visible=False)

                    with ui.ZStack():
                        ui.Rectangle(style=R.STYLE_IMAGE_PANEL)
                        self._inference_provider = ui.ByteImageProvider()
                        self._inference_provider.set_bytes_data(
                            [0] * (R.WIDTH_SEE_REASON_IMAGE * R.HEIGHT_SEE_REASON_IMAGE * 4),
                            [R.WIDTH_SEE_REASON_IMAGE, R.HEIGHT_SEE_REASON_IMAGE],
                            ui.TextureFormat.RGBA8_UNORM,
                        )
                        ui.ImageWithProvider(self._inference_provider)
                        # INFERRED badge overlay (top-left).  Must be the LAST
                        # child of this ZStack so it draws above the image.
                        self._inf_badge_frame = ui.Frame(visible=False)

                ui.Spacer(height=R.SPACING_SEE_REASON_SECTION)

                # Bottom: two framed text panels below the image row
                with ui.HStack(height=R.HEIGHT_SEE_REASON_REASONING,
                               spacing=R.SPACING_IMAGE_PANELS):
                    # Left - Run Status
                    with ui.ZStack():
                        ui.Rectangle(style=R.STYLE_REASONING_PANEL)
                        with ui.VStack():
                            ui.Spacer(height=R.PADDING_REASONING_TOP)
                            with ui.HStack():
                                ui.Spacer(width=R.PADDING_REASONING_SIDE)
                                with ui.VStack(spacing=2):
                                    with ui.VStack(spacing=3):
                                        for _ in range(MAX_PANEL_LINES):
                                            # Empty row container: span Labels are
                                            # constructed fresh on every _apply_lines
                                            # call (see that function's docstring).
                                            self._status_rows.append(ui.HStack(height=0))
                                    ui.Spacer()
                                ui.Spacer(width=R.PADDING_REASONING_SIDE)

                    # Right - Model Reasoning
                    with ui.ZStack():
                        ui.Rectangle(style=R.STYLE_REASONING_PANEL)
                        with ui.VStack():
                            ui.Spacer(height=R.PADDING_REASONING_TOP)
                            with ui.HStack():
                                ui.Spacer(width=R.PADDING_REASONING_SIDE)
                                with ui.VStack(spacing=2):
                                    with ui.VStack(spacing=3):
                                        for _ in range(MAX_PANEL_LINES):
                                            # Empty row container: span Labels are
                                            # constructed fresh on every _apply_lines
                                            # call (see that function's docstring).
                                            self._text_rows.append(ui.HStack(height=0))
                                    ui.Spacer()
                                ui.Spacer(width=R.PADDING_REASONING_SIDE)

    async def _animate_lines(
        self,
        lines: List[Line],
        rows: List[ui.HStack],
        gen: int,
        gen_ref,
    ):
        """Set preceding lines instantly; animate last line word-by-word.

        ``gen`` / ``gen_ref`` are the generation-counter guard: callers
        capture the current counter before scheduling this coroutine and pass
        a callable that returns the live value.  After each ``await`` the
        coroutine checks whether the counter has advanced; if so it stops
        immediately so a half-finished animation never races with a newer one.

        If the last line has .spans it is applied instantly (mixed-color rows
        are not animated word-by-word).  If the last line has no .spans the
        text is streamed word-by-word: each tick clears the row and
        constructs a fresh single Label holding the accumulated text so far
        (same width=0-content-hug-at-construction reasoning as
        ``_apply_lines`` -- a growing string needs a fresh Label every tick,
        not a mutated one, to stay correctly sized).
        """
        app = omni.kit.app.get_app()
        if not lines:
            _apply_lines(rows, [])
            return

        # Set all lines except the last one instantly
        _apply_lines(rows[:len(lines) - 1], lines[:-1])

        # Clear unused rows beyond len(lines)-1
        for i in range(len(lines), len(rows)):
            rows[i].clear()

        # Handle the last line
        last     = lines[-1]
        last_idx = len(lines) - 1

        if last_idx >= len(rows):
            return

        if gen_ref() != gen:
            return

        last_row = rows[last_idx]

        if last.spans:
            # Multi-span last line: apply instantly, no word-by-word animation
            _apply_lines([last_row], [last])
        else:
            # Single-color last line: animate word-by-word, rebuilding the
            # row's Label each tick with the accumulated text so far.
            font_size = last.font_size if last.font_size else R.FONT_REASONING_TEXT

            def _set_row_text(text: str) -> None:
                last_row.clear()
                with last_row:
                    ui.Label(text, height=0, width=0, word_wrap=False,
                             style={"color": last.color, "font_size": font_size})
                    ui.Spacer()

            _set_row_text("")
            words = last.text.split()
            accum = ""
            for word in words:
                if gen_ref() != gen:
                    return
                sep    = "" if not accum else " "
                accum += sep + word
                _set_row_text(accum)
                for _ in range(5):
                    await app.next_update_async()
                    if gen_ref() != gen:
                        return

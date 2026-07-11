"""Single-target 'next-action pulse' controller.

Exactly one control pulses at a time: whichever widget is currently the
recommended next action. PulseController owns the asyncio task that
alternates a widget's style between its normal (base) style and an
accent-bordered style, and guarantees the widget is restored to its base
style whenever the pulse stops or targets a new widget.
"""
from __future__ import annotations

import asyncio

import omni.ui as ui  # noqa: F401  (kept for parity with other ui/ modules; not directly used)


class PulseController:
    """Drives a slow on/off style pulse on a single omni.ui widget at a time."""

    def __init__(self):
        self._task = None
        self._widget = None
        self._base_style = None

    def pulse(self, widget, base_style: dict, accent_style: dict):
        """Start pulsing `widget` between `base_style` and `accent_style`.

        Stops any previous pulse first, so only one widget ever pulses.
        Passing widget=None just stops the current pulse.
        """
        self.stop()
        if widget is None:
            return
        self._widget = widget
        self._base_style = base_style
        self._task = asyncio.ensure_future(self._loop(accent_style))

    async def _loop(self, accent_style):
        while True:
            try:
                if self._widget is None:
                    break
                self._widget.style = accent_style
                await asyncio.sleep(0.55)
                if self._widget is None:
                    break
                self._widget.style = self._base_style
                await asyncio.sleep(0.55)
            except asyncio.CancelledError:
                break
            except Exception:
                break

    def stop(self):
        """Cancel any running pulse task and restore the widget's base style."""
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

        if self._widget is not None and self._base_style is not None:
            try:
                self._widget.style = self._base_style
            except Exception:
                pass

        self._widget = None
        self._base_style = None

    def is_pulsing_widget(self, widget) -> bool:
        """True if `widget` is the currently-active pulse target."""
        return self._widget is widget and self._task is not None and not self._task.done()

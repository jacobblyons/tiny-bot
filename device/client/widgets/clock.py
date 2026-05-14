"""Uptime widget — shows seconds since boot.

We don't have an RTC by default on the T-Deck, so wall-clock time would
either need NTP or user setup. Uptime is honest and useful for debugging.
"""
import time

from engine.display.ui.elements import Label
from engine.display.ui.models import Align, Dimensions, Position, Style

from client.views.theme import TEXT_PRIMARY, TEXT_DIM


class Widget:
    TITLE = "uptime"

    def __init__(self, app):
        self._app = app
        self._t0 = time.monotonic()
        self._label = None
        self._sub = None
        self._tick = 0.0

    def build(self, group, x, y, w, h):
        # Two stacked centered labels. The clock value occupies the
        # top half, the "since boot" caption the bottom half. Both
        # vertically-center their text inside their slot so the
        # widget keeps looking right at any cell height.
        half = max(12, h // 2)
        self._label = Label(
            "00:00",
            root_group=group,
            dimensions=Dimensions(w, half),
            position=Position(x, y),
            default_style=Style(
                font_size=12,
                font_color=TEXT_PRIMARY,
                horizontal_align=Align.Center,
                vertical_align=Align.Center,
            ),
        )
        self._sub = Label(
            "since boot",
            root_group=group,
            dimensions=Dimensions(w, h - half),
            position=Position(x, y + half),
            default_style=Style(
                font_size=12,
                font_color=TEXT_DIM,
                horizontal_align=Align.Center,
                vertical_align=Align.Center,
            ),
        )

    def update(self, delta_time):
        # Throttle to once per second; redrawing terminalio labels is
        # cheap but unnecessary at the per-frame rate.
        self._tick += delta_time
        if self._tick < 1.0:
            return
        self._tick = 0.0
        secs = int(time.monotonic() - self._t0)
        h = secs // 3600
        m = (secs // 60) % 60
        s = secs % 60
        if h:
            text = "{:d}:{:02d}:{:02d}".format(h, m, s)
        else:
            text = "{:02d}:{:02d}".format(m, s)
        self._label.text = text
        self._label._dirty = True
        self._label.draw()

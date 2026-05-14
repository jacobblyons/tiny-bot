"""Free-memory widget."""
import gc

from engine.display.ui.elements import Label
from engine.display.ui.models import Align, Dimensions, Position, Style

from client.views.theme import TEXT_PRIMARY, TEXT_DIM


class Widget:
    TITLE = "mem"

    def __init__(self, app):
        self._free = None
        self._unit = None
        self._tick = 0.0

    def build(self, group, x, y, w, h):
        half = max(12, h // 2)
        self._free = Label(
            "...",
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
        self._unit = Label(
            "KB free",
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
        self._refresh()

    def update(self, delta_time):
        self._tick += delta_time
        if self._tick < 1.0:
            return
        self._tick = 0.0
        self._refresh()

    def _refresh(self):
        gc.collect()
        kb = gc.mem_free() // 1024
        self._free.text = str(kb)
        self._free._dirty = True
        self._free.draw()

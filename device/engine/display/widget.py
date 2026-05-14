"""Widget abstraction for the home screen.

A widget is a small stateful object that renders into a rectangular slot.
The home scene gives it a fixed (x, y, w, h) box and the widget draws
itself into the supplied displayio.Group. The WidgetCard wraps each
widget with a border and title and isolates errors so a single bad
widget can't take down the home screen.

Authoring a widget:
    class Widget:
        TITLE = "clock"
        def __init__(self, app): ...
        def build(self, group, x, y, w, h): ...   # one-shot setup
        def update(self, delta_time): ...          # optional per-frame
"""
import displayio
from adafruit_display_shapes.rect import Rect

from engine.display.ui.elements import Label
from engine.display.ui.models import Align, Dimensions, Position, Style


class WidgetCard:
    """Renders a single widget inside a bordered card.

    Failures during build/update are caught and the card switches to an
    error state so the rest of the home screen keeps working. This is
    the central reason widgets exist as a layer at all — we want the
    agent to install experimental code without bricking the launcher.
    """

    TITLE_BAR_H = 12

    def __init__(self, root_group, x, y, w, h, widget,
                 bg_color, border_color, title_color, error_color):
        """Color arguments are Color objects (not raw ints). The card
        uses .value when handing them to shape primitives and passes the
        Color objects through to Label, which expects them as well."""
        self._root = root_group
        self._x, self._y, self._w, self._h = x, y, w, h
        self._widget = widget
        self._bg_color = bg_color
        self._border_color = border_color
        self._title_color = title_color
        self._error_color = error_color
        self._inner_group = displayio.Group()
        self._error_label = None
        self._title_label = None
        self._broken = False

    def build(self):
        # Card chrome — background, border, title bar.
        self._root.append(Rect(self._x, self._y, self._w, self._h,
                               fill=self._bg_color.value,
                               outline=self._border_color.value, stroke=1))
        title = getattr(self._widget, "TITLE", None) \
                or self._widget.__class__.__name__
        self._title_label = Label(
            "[ " + title + " ]",
            root_group=self._root,
            dimensions=Dimensions(self._w - 6, self.TITLE_BAR_H),
            position=Position(self._x + 4, self._y + 2),
            default_style=Style(
                font_size=12,
                font_color=self._title_color,
                horizontal_align=Align.Start,
                vertical_align=Align.Start,
            ),
        )
        # Inner group for widget content. Anything the widget draws
        # goes through this group so we can hot-swap to an error view
        # without disturbing the card chrome.
        self._root.append(self._inner_group)

        inner_y = self._y + self.TITLE_BAR_H + 4
        inner_h = self._h - self.TITLE_BAR_H - 6
        try:
            self._widget.build(self._inner_group,
                               self._x + 4, inner_y,
                               self._w - 8, inner_h)
        except Exception as e:
            self._fail("build: " + str(e)[:40])

    def update(self, delta_time):
        if self._broken:
            return
        try:
            fn = getattr(self._widget, "update", None)
            if fn is not None:
                fn(delta_time)
        except Exception as e:
            self._fail("update: " + str(e)[:40])

    def _fail(self, msg):
        """Replace whatever the widget tried to draw with a single error
        label. We don't re-raise — the goal is for the rest of the home
        screen to keep functioning."""
        self._broken = True
        # Clear any partial widget content.
        while len(self._inner_group) > 0:
            try:
                self._inner_group.pop()
            except Exception:
                break
        inner_y = self._y + self.TITLE_BAR_H + 4
        self._error_label = Label(
            "x " + msg,
            root_group=self._inner_group,
            dimensions=Dimensions(self._w - 8, 12),
            position=Position(self._x + 4, inner_y + 2),
            default_style=Style(
                font_size=12,
                font_color=self._error_color,
                horizontal_align=Align.Start,
                vertical_align=Align.Start,
            ),
        )

    @property
    def rect(self):
        return (self._x, self._y, self._w, self._h)

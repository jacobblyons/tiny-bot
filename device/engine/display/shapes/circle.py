from displayio import Group
from adafruit_display_shapes.circle import Circle as DispCircle

from engine.display.ui.elements import UIElement
from engine.display.ui.models import Dimensions, Position, Style


class Circle(UIElement):
    def __init__(
        self,
        root_group: Group,
        radius: int,
        position: Position = Position(),
        style: Style = Style(),
    ):
        UIElement.__init__(self, root_group, Dimensions(radius, radius), position, False, style, None, None)
        self._circle = DispCircle(
            position.x, position.y, radius,
            fill=style.bg_color.value if style.bg_color is not None else None,
            outline=style.border_color.value,
            stroke=style.border_width,
        )
        self._root_group.append(self._circle)

    def draw(self):
        if not self._dirty:
            return
        self._circle.x0 = self._position.x
        self._circle.y0 = self._position.y
        self._dirty = False

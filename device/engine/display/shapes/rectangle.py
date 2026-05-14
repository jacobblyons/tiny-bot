from displayio import Group
from adafruit_display_shapes.rect import Rect

from engine.display.ui.elements import UIElement
from engine.display.ui.models import Dimensions, Position, Style


class Rectangle(UIElement):
    def __init__(
        self,
        root_group: Group,
        dimensions: Dimensions,
        position: Position = Position(),
        style: Style = Style(),
    ):
        UIElement.__init__(self, root_group, dimensions, position, False, style, None, None)
        self.rect = Rect(
            position.x, position.y,
            height=dimensions.height, width=dimensions.width,
            fill=style.bg_color.value if style.bg_color is not None else None,
            outline=style.border_color.value,
            stroke=style.border_width,
        )
        self._root_group.append(self.rect)

    def draw(self):
        if not self._dirty:
            return
        self.rect.x = self._position.x
        self.rect.y = self._position.y
        self._dirty = False

    def center(self):
        return Position(
            x=self._position.x + self._dimensions.width / 2,
            y=self._position.y + self._dimensions.height / 2,
        )

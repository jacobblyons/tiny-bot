from displayio import Group
from adafruit_display_text import label
import terminalio

from engine.display.ui.elements.ui_element import UIElement
from engine.display.ui.models import Dimensions, Position, Style, Align

DEFAULT_FONT_SIZE = 12
ALIGN_TO_ANCHOR = {
    Align.Start: 0,
    Align.Center: 0.5,
    Align.End: 1,
}


class Label(UIElement):
    def __init__(
        self,
        text,
        root_group: Group,
        dimensions: Dimensions = Dimensions(),
        position: Position = Position(),
        selectable: bool = False,
        default_style: Style = Style(),
        highlighted_style: Style = None,
        selected_style: Style = None,
    ):
        UIElement.__init__(
            self, root_group, dimensions, position, selectable,
            default_style, highlighted_style, selected_style,
        )
        self._text = text
        self._text_area = label.Label(terminalio.FONT, text=self._text)
        self._apply_to_text_area()
        self._root_group.append(self._text_area)
        self._dirty = False

    def _apply_to_text_area(self):
        self._text_area.text = self._text
        self._text_area.color = self.style.font_color.value
        self._text_area.scale = max(1, int(self._style.font_size / DEFAULT_FONT_SIZE))
        self._text_area.anchor_point = (
            ALIGN_TO_ANCHOR[self._style.horizontal_align],
            ALIGN_TO_ANCHOR[self._style.vertical_align],
        )
        self._text_area.anchored_position = self._anchored_position()

    def draw(self):
        if not self._dirty:
            return
        self._apply_to_text_area()
        self._dirty = False

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value: str):
        if self._text != value:
            self._dirty = True
        self._text = value

    def _anchored_position(self):
        p, d, s = self._position, self._dimensions, self._style
        x, y = p.x, p.y
        if s.horizontal_align == Align.Center:
            x = p.x + d.width / 2
        elif s.horizontal_align == Align.End:
            x = p.x + d.width
        if s.vertical_align == Align.Center:
            y = p.y + d.height / 2
        elif s.vertical_align == Align.End:
            y = p.y + d.height
        return (int(x), int(y))

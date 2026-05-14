from adafruit_display_shapes.rect import Rect

from engine.display.ui.elements import UIElement
from engine.display.ui.models import Position


class ManualLayout(UIElement):
    """Container that does not auto-position its children; each child draws at its own coords."""

    def __init__(self, root_group, dimensions, position: Position = Position(),
                 default_style=None, highlighted_style=None, selected_style=None):
        UIElement.__init__(
            self, root_group, dimensions, position, False,
            default_style, highlighted_style, selected_style,
        )
        self._highlighted_index = 0
        self._elements = []
        self._selectable_elements = []
        self._dirty = True

        if self.style.bg_color is not None:
            self._rect = Rect(
                int(self._position.x), int(self._position.y),
                int(dimensions.width), int(dimensions.height),
                outline=self._style.border_color.value,
                stroke=self.style.border_width,
                fill=self.style.bg_color.value,
            )
            self._root_group.append(self._rect)

    def add_element(self, element: UIElement):
        self._elements.append(element)
        if element.is_selectable():
            self._selectable_elements.append(element)

    def draw(self):
        for el in self._elements:
            el.draw()
        if not self._dirty:
            return
        if self.style.bg_color is not None:
            self._rect.x = int(self._position.x)
            self._rect.y = int(self._position.y)
            if int(self._dimensions.width) != int(self._rect.width) or int(self._dimensions.height) != int(self._rect.height):
                self._root_group.remove(self._rect)
                self._rect = Rect(
                    int(self._position.x), int(self._position.y),
                    int(self._dimensions.width), int(self._dimensions.height),
                    outline=self._style.border_color.value,
                    stroke=self.style.border_width,
                    fill=self.style.bg_color.value,
                )
                self._root_group.insert(0, self._rect)
        self._dirty = False

    def highlight_next(self):
        if not self._selectable_elements:
            return
        self._selectable_elements[self._highlighted_index].unhighlight()
        self._highlighted_index = (self._highlighted_index + 1) % len(self._selectable_elements)
        self._selectable_elements[self._highlighted_index].highlight()

    def highlight_previous(self):
        if not self._selectable_elements:
            return
        self._selectable_elements[self._highlighted_index].unhighlight()
        self._highlighted_index = (self._highlighted_index - 1) % len(self._selectable_elements)
        self._selectable_elements[self._highlighted_index].highlight()

    def select(self):
        if self._selectable_elements:
            self._selectable_elements[self._highlighted_index].select()

    def is_selectable(self):
        return False

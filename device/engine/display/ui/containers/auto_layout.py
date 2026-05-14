from adafruit_display_shapes.rect import Rect

from engine.display.ui.elements import UIElement
from engine.display.ui.models import Dimensions, Flex, Position, Direction


class AutoLayout(UIElement):
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
        offset = Position(
            x=self._position.x + self.style.margin,
            y=self._position.y + self.style.margin,
        )
        for el in self._elements:
            if self._dirty:
                el.dimensions.width = self._width_per_element() if el.dimensions.flex_x == Flex.Freely else el.dimensions.width
                el.dimensions.height = self._height_per_element() if el.dimensions.flex_y == Flex.Freely else el.dimensions.height
                el.position = Position(
                    x=el.initial_position.x + offset.x,
                    y=el.initial_position.y + offset.y,
                )
                if self.style.direction == Direction.Horizontal:
                    offset = Position(x=offset.x + el.dimensions.width + self.style.margin, y=offset.y)
                else:
                    offset = Position(x=offset.x, y=offset.y + el.dimensions.height + self.style.margin)
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

    def _height_per_element(self):
        total = len(self._elements)
        n_flex = 0
        h_fixed = 0
        for el in self._elements:
            if el.dimensions.flex_y == Flex.Freely:
                n_flex += 1
            else:
                h_fixed += el.dimensions.height
        margins = total + 1 if self.style.direction == Direction.Vertical else 2
        total_h = self._dimensions.height - margins * self.style.margin
        if self.style.direction == Direction.Vertical:
            return (total_h - h_fixed) / max(1, n_flex)
        return total_h

    def _width_per_element(self):
        total = len(self._elements)
        n_flex = 0
        w_fixed = 0
        for el in self._elements:
            if el.dimensions.flex_x == Flex.Freely:
                n_flex += 1
            else:
                w_fixed += el.dimensions.width
        margins = total + 1 if self.style.direction == Direction.Horizontal else 2
        total_w = self._dimensions.width - margins * self.style.margin
        if self.style.direction == Direction.Horizontal:
            return (total_w - w_fixed) / max(1, n_flex)
        return total_w

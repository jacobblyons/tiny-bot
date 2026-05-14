from engine.display.ui.models.dimensions import Dimensions
from engine.display.ui.models.position import Position
from engine.display.ui.models.style import HighlightedState, Style


class UIElement:
    def __init__(
        self,
        root_group,
        dimensions: Dimensions = Dimensions(),
        position: Position = Position(),
        selectable: bool = False,
        default_style=None,
        highlighted_style=None,
        selected_style=None,
    ):
        self._dimensions = dimensions
        self._root_group = root_group
        self._position = position
        self.initial_position = position
        self._dirty = True
        self._selectable = selectable
        self._style = default_style
        if highlighted_style is not None:
            highlighted_style.highlighted_state = HighlightedState.Highlighted
        if selected_style is not None:
            selected_style.highlighted_state = HighlightedState.Selected
        self._style_collection = {
            "default": default_style,
            "highlighted": highlighted_style,
            "selected": selected_style,
        }

    @property
    def position(self):
        return self._position

    @position.setter
    def position(self, value: Position):
        if self._position.x != value.x or self._position.y != value.y:
            self._dirty = True
        self._position = value

    @property
    def dimensions(self):
        return self._dimensions

    @dimensions.setter
    def dimensions(self, value: Dimensions):
        if self._dimensions.width != value.width or self._dimensions.height != value.height:
            self._dirty = True
        self._dimensions = value

    @property
    def style(self):
        return self._style

    @style.setter
    def style(self, value: Style):
        if self._style != value:
            self._dirty = True
        self._style = value

    def is_selectable(self):
        return self._selectable

    def highlight(self):
        if not self._selectable:
            return
        self._style = self._style_collection["highlighted"]
        self._dirty = True

    def unhighlight(self):
        if not self._selectable:
            return
        self._style = self._style_collection["default"]
        self._dirty = True

    def select(self):
        if not self._selectable:
            return
        self._style = self._style_collection["selected"]
        self._dirty = True

    def draw(self):
        raise NotImplementedError

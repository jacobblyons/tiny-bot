from .color import Color, MonoColor


class Align:
    Start = 1
    Center = 2
    End = 3


class HighlightedState:
    Not = 1
    Highlighted = 2
    Selected = 3


class Direction:
    Vertical = 1
    Horizontal = 2


class Style:
    def __init__(
        self,
        margin=5,
        padding=5,
        font="fonts-dejavu",
        font_size=12,
        font_color=MonoColor(0),
        bg_color=None,
        direction=Direction.Vertical,
        horizontal_align=Align.Center,
        vertical_align=Align.Center,
        border_color=MonoColor(0),
        border_width: int = 0,
        border_radius: int = 0,
    ):
        self.margin = margin
        self.padding = padding
        self.font = font
        self.font_size = font_size
        self.font_color = font_color
        self.bg_color = bg_color
        self.direction = direction
        self.horizontal_align = horizontal_align
        self.vertical_align = vertical_align
        self.border_color = border_color
        self.border_width = border_width
        self.border_radius = border_radius
        self.highlighted_state = HighlightedState.Not

from displayio import Group

from engine.application import IView
from engine.display.ui.elements import Label, UIElement
from engine.display.ui.models import Align, Dimensions, MonoColor, Position, Style


class StatusView(IView):
    def __init__(self, root_group: Group, text="", y=100):
        self._label = Label(
            text,
            root_group=root_group,
            dimensions=Dimensions(320, 20),
            position=Position(0, y),
            default_style=Style(
                font_size=12,
                font_color=MonoColor(1),
                horizontal_align=Align.Center,
                vertical_align=Align.Center,
            ),
        )

    def set_text(self, text):
        self._label.text = text

    def draw(self):
        self._label.draw()

    def getElement(self) -> UIElement:
        return self._label

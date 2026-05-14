"""Bottom-status footer styled to match ChromeView.

Mirrors the header band — fixed height, surface background, accent pip,
configurable text. Used by the home scene; reusable from other scenes
that want a consistent agent-terminal look.
"""
from displayio import Group
from adafruit_display_shapes.rect import Rect
from adafruit_display_shapes.line import Line

from engine.application import IView
from engine.display.ui.elements import Label, UIElement
from engine.display.ui.models import Align, Dimensions, Position, Style

from client.views.theme import (
    SCREEN_W, SCREEN_H, FOOTER_H, BODY_LEFT,
    BG_SURFACE, BORDER, TEXT_DIM, ACCENT,
)


class FooterView(IView):
    """Slim bottom hint bar — spans the body width only (sidebar's
    [bot] button already occupies the bottom-left corner)."""

    def __init__(self, root_group: Group, hint="[tap] launch  [TB] scroll"):
        self._root_group = root_group
        y = SCREEN_H - FOOTER_H
        body_w = SCREEN_W - BODY_LEFT

        self._sep = Line(BODY_LEFT, y, SCREEN_W, y, color=BORDER.value)
        root_group.append(self._sep)
        self._bg = Rect(BODY_LEFT, y + 1, body_w, FOOTER_H - 1,
                        fill=BG_SURFACE.value, outline=None)
        root_group.append(self._bg)

        self._hint = Label(
            hint,
            root_group=root_group,
            dimensions=Dimensions(body_w - 16, FOOTER_H),
            position=Position(BODY_LEFT + 4, y),
            default_style=Style(
                font_size=12,
                font_color=TEXT_DIM,
                horizontal_align=Align.Start,
                vertical_align=Align.Center,
                padding=4,
            ),
        )

        # Accent pip mirroring the header.
        self._pip = Rect(SCREEN_W - 9, y + 7, 4, 4,
                         fill=ACCENT.value, outline=None)
        root_group.append(self._pip)

    def set_hint(self, text):
        self._hint.text = text
        self._hint._dirty = True
        self._hint.draw()

    def getElement(self) -> UIElement:
        return self._hint

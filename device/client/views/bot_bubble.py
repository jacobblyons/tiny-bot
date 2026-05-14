"""Always-on-top bot launcher button.

A small bordered rect in the bottom-right that the App composites
on top of any non-home scene. Tapping it tells the App to switch
to the bot scene, which preserves the launching scene's reference
in `app.bot_return_target` so the bot's [<] button comes back here.

The bubble lives in its own displayio.Group so the App can toggle
its visibility independently of the active scene's group.
"""
import displayio
from adafruit_display_shapes.rect import Rect

from engine.display.ui.elements import Label
from engine.display.ui.models import Align, Dimensions, Position, Style


SCREEN_W = 320
SCREEN_H = 240

BUBBLE_W = 56
BUBBLE_H = 28
BUBBLE_MARGIN = 4
# Bottom-right anchor. Apps are warned in the system prompt not to
# put critical UI in this rectangle; if they do, the bubble sits
# on top and they get partial occlusion.
BUBBLE_X = SCREEN_W - BUBBLE_W - BUBBLE_MARGIN
BUBBLE_Y = SCREEN_H - BUBBLE_H - BUBBLE_MARGIN


class BotBubble:
    def __init__(self, theme):
        self.group = displayio.Group()
        # Two stacked rects so the bubble has a subtle "raised" feel
        # against busy app backgrounds — outer fill + inner outline.
        self._shadow = Rect(
            BUBBLE_X + 1, BUBBLE_Y + 1, BUBBLE_W, BUBBLE_H,
            fill=theme["bg_main"].value, outline=None,
        )
        self.group.append(self._shadow)
        self._bg = Rect(
            BUBBLE_X, BUBBLE_Y, BUBBLE_W, BUBBLE_H,
            fill=theme["bg_surface"].value,
            outline=theme["accent"].value, stroke=1,
        )
        self.group.append(self._bg)
        self._label = Label(
            "[bot]",
            root_group=self.group,
            dimensions=Dimensions(BUBBLE_W, BUBBLE_H),
            position=Position(BUBBLE_X, BUBBLE_Y),
            default_style=Style(
                font_size=12, font_color=theme["accent"],
                horizontal_align=Align.Center,
                vertical_align=Align.Center,
            ),
        )
        self._rect = (BUBBLE_X, BUBBLE_Y, BUBBLE_W, BUBBLE_H)
        self.group.hidden = True

    @property
    def visible(self):
        return not self.group.hidden

    def show(self):
        self.group.hidden = False

    def hide(self):
        self.group.hidden = True

    def hit(self, px, py):
        if px is None or py is None:
            return False
        x, y, w, h = self._rect
        return x <= px < x + w and y <= py < y + h

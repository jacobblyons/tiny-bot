"""Boot splash: TINY-BOT logo + 'press space to continue'.

The splash blocks on input rather than auto-advancing so the user can
actually read it. Any key, trackball click, or screen tap continues.

The logo art and two-tone coloring come from `theme.LOGO_LINES` so
this matches what the home screen shows in idle mode pixel-for-pixel.
"""
import time
import displayio
from adafruit_display_shapes.rect import Rect

from engine.application import IScene
from engine.display.ui.elements import Label
from engine.display.ui.models import Align, Dimensions, Position, Style

from client.views.theme import (
    SCREEN_W, SCREEN_H,
    BG_MAIN, BG_SURFACE, BORDER, TEXT_PRIMARY, TEXT_DIM, ACCENT, SUCCESS,
    build_logo, logo_total_w, logo_total_h,
)


PROMPT = "press space to continue"
SUBHEAD = "an agent in your pocket"


class SplashScene(IScene):
    def __init__(self, app):
        self.app = app
        self.kbd = app.GetKeyboard()
        self.rootGroup = displayio.Group()
        self._started = False
        self._blink_t = 0.0
        self._blink_on = True
        self._prompt = None

    def OnStartup(self):
        # Full-screen background. Drawn first so logo + prompt sit on top.
        self.rootGroup.append(Rect(0, 0, SCREEN_W, SCREEN_H,
                                   fill=BG_MAIN.value, outline=None))

        # Logo block — centered horizontally. Width comes from the
        # shared logo helper so the frame around it tracks the
        # underlying art size.
        logo_w = logo_total_w()
        logo_x = (SCREEN_W - logo_w) // 2
        logo_h = logo_total_h()

        # Window-chrome frame with terminalish padding around the
        # logo + subhead. The frame's geometry tracks the logo size
        # so changes to LOGO_LINES don't desync the visuals.
        frame_pad_x = 10
        frame_pad_y = 12
        subhead_gap = 8
        subhead_h = 12
        frame_w = logo_w + frame_pad_x * 2
        frame_h = logo_h + subhead_gap + subhead_h + frame_pad_y * 2
        frame_x = (SCREEN_W - frame_w) // 2
        frame_y = (SCREEN_H - frame_h) // 2 - 12  # nudge up so prompt has room
        if frame_y < 8:
            frame_y = 8

        self.rootGroup.append(Rect(frame_x, frame_y, frame_w, frame_h,
                                   fill=BG_SURFACE.value,
                                   outline=BORDER.value, stroke=1))

        logo_y = frame_y + frame_pad_y
        build_logo(self.rootGroup, logo_x, logo_y)

        # Subhead under the logo block.
        Label(
            SUBHEAD,
            root_group=self.rootGroup,
            dimensions=Dimensions(SCREEN_W, subhead_h),
            position=Position(0, logo_y + logo_h + subhead_gap),
            default_style=Style(
                font_size=12,
                font_color=TEXT_DIM,
                horizontal_align=Align.Center,
                vertical_align=Align.Start,
            ),
        )

        # Blinking prompt near the bottom — classic "boot ready" cue.
        self._prompt = Label(
            "> " + PROMPT + " _",
            root_group=self.rootGroup,
            dimensions=Dimensions(SCREEN_W, 14),
            position=Position(0, SCREEN_H - 28),
            default_style=Style(
                font_size=12,
                font_color=SUCCESS,
                horizontal_align=Align.Center,
                vertical_align=Align.Start,
            ),
        )

        # Pointer is constructed here so the cursor sprite lives above
        # the splash background. We don't actually consume cursor motion
        # on the splash — any tap counts as "continue".
        self.pointer = self.app.GetPointer(self.rootGroup)

    def OnUpdate(self, delta_time):
        if not self._started:
            self._started = True
            self._wait_for_continue()

    def _wait_for_continue(self):
        """Block until the user signals 'continue'. We poll the keyboard,
        trackball click, and touch press in a tight loop so any of them
        advances the boot."""
        while True:
            # Blink the prompt cursor for liveness.
            self._blink_t += 0.02
            if self._blink_t >= 0.5:
                self._blink_t = 0.0
                self._blink_on = not self._blink_on
                self._prompt.text = ("> " + PROMPT + (" _" if self._blink_on else "  "))
                self._prompt._dirty = True
                self._prompt.draw()

            k = self.kbd.poll()
            if k:
                # Space is the documented "continue" key but anything
                # printable works — we don't want to confuse the user
                # who reflexively hits ENTER instead.
                self.app.SwitchScene("home")
                return

            ev = self.pointer.poll()
            if ev["click"]:
                self.app.SwitchScene("home")
                return

            time.sleep(0.02)

    def OnDraw(self):
        pass

    def OnShutdown(self):
        pass

    def GetRootGroup(self):
        return self.rootGroup

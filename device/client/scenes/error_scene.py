"""Recovery scene shown when a scene's lifecycle raises.

The error scene is the universal "soft landing" for crashes — instead of
the device returning to the REPL (effectively bricked from a touch-only
user's perspective), App.Run captures the exception, stashes details on
`app.pending_error`, and force-switches here.

UI:
  - sad ASCII face at the top
  - one-line summary ("snake :: OnUpdate")
  - the error type + message, wrapped
  - first lines of the traceback
  - two large touch buttons:
      [ back to home ]  [ ask bot to fix ]

The "ask bot to fix" button stuffs a fix-request prompt into
`app.pending_bot_prompt` and switches to the bot scene. The bot scene's
auto-send picks that up and dispatches it without waiting for the user
to type anything, so the agent can immediately start diagnosing.
"""
import displayio
from adafruit_display_shapes.rect import Rect

from engine.application import IScene
from engine.display.ui.elements import Label
from engine.display.ui.models import Align, Dimensions, Position, Style

from client.views import ChromeView
from client.views.theme import (
    SCREEN_W, SCREEN_H, CHROME_H, FOOTER_H, BODY_LEFT, BODY_W,
    BG_MAIN, BG_SURFACE, BORDER, TEXT_PRIMARY, TEXT_DIM, ACCENT, WARN, SUCCESS,
)


SAD_FACE = [
    "  _________",
    " /         \\",
    "|  X     X  |",
    "|     _     |",
    "|    /-\\    |",
    " \\_________/",
]

ERR_WRAP_WIDTH = max(20, (BODY_W - 12) // 6)
ERR_BODY_LINES = 5


def _wrap(text, width=ERR_WRAP_WIDTH):
    out = []
    for para in text.split("\n"):
        if not para:
            out.append("")
            continue
        while len(para) > width:
            out.append(para[:width])
            para = para[width:]
        if para:
            out.append(para)
    return out


class ErrorScene(IScene):
    def __init__(self, app):
        self.app = app
        self.kbd = app.GetKeyboard()
        self.touch = app.GetTouch()
        self.trackball = app.GetTrackball()
        self.rootGroup = displayio.Group()

        # Take a snapshot of the error and clear the slot so a *fresh*
        # crash overwrites cleanly later.
        self.error = getattr(app, "pending_error", None) or {
            "where": "unknown",
            "type": "Exception",
            "message": "(no error details)",
            "traceback": "",
        }
        self.app.pending_error = None

        self._chrome = None
        # Button touch zones — (x, y, w, h) tuples; populated in OnStartup
        # so the geometry lives next to the labels we draw.
        self._home_rect = None
        self._fix_rect = None
        # Trackball-selection model: 0 = home, 1 = fix
        self._sel = 0
        self._home_bg = None
        self._home_lbl = None
        self._fix_bg = None
        self._fix_lbl = None
        self._handled = False

    # ---- layout -------------------------------------------------------------

    def OnStartup(self):
        title = "oops :: " + str(self.error.get("where", "?"))[:24]
        # No chrome back/bot buttons — the body provides its own
        # explicit [home] and [ask bot to fix] buttons. Skipping the
        # chrome buttons also dodges the back-target auto-redirect:
        # error recovery should always offer a clean path home rather
        # than potentially bouncing back to whatever scene crashed.
        self._chrome = ChromeView(self.rootGroup,
                                  title=title,
                                  back_target=None,
                                  bot_target=None)

        body_top = CHROME_H + 6

        # Sad face — centered horizontally inside the body area.
        face_x = BODY_LEFT + (BODY_W - len(SAD_FACE[0]) * 6) // 2
        for i, row in enumerate(SAD_FACE):
            Label(
                row,
                root_group=self.rootGroup,
                dimensions=Dimensions(BODY_W, 12),
                position=Position(face_x, body_top + i * 11),
                default_style=Style(
                    font_size=12, font_color=WARN,
                    horizontal_align=Align.Start,
                    vertical_align=Align.Start,
                ),
            )

        # Error type + message (single line, truncated if wide).
        err_msg = "{}: {}".format(self.error.get("type", "?"),
                                  self.error.get("message", "?"))
        err_msg_lines = _wrap(err_msg)[:2]
        msg_y = body_top + len(SAD_FACE) * 11 + 6
        for i, line in enumerate(err_msg_lines):
            Label(
                line,
                root_group=self.rootGroup,
                dimensions=Dimensions(BODY_W - 12, 12),
                position=Position(BODY_LEFT + 6, msg_y + i * 12),
                default_style=Style(
                    font_size=12, font_color=TEXT_PRIMARY,
                    horizontal_align=Align.Start,
                    vertical_align=Align.Start,
                ),
            )

        # First few lines of the traceback for triage at a glance.
        tb_y = msg_y + len(err_msg_lines) * 12 + 4
        tb_lines = _wrap(self.error.get("traceback", ""))[:ERR_BODY_LINES]
        for i, line in enumerate(tb_lines):
            Label(
                line,
                root_group=self.rootGroup,
                dimensions=Dimensions(BODY_W - 12, 12),
                position=Position(BODY_LEFT + 6, tb_y + i * 11),
                default_style=Style(
                    font_size=12, font_color=TEXT_DIM,
                    horizontal_align=Align.Start,
                    vertical_align=Align.Start,
                ),
            )

        # Two action buttons. Wide touch targets, drawn just above the
        # screen edge so they're hard to miss with a thumb.
        btn_h = 24
        btn_y = SCREEN_H - FOOTER_H - btn_h - 4
        gap = 8
        home_w = min(120, (BODY_W - gap * 3) // 2)
        fix_w = BODY_W - home_w - gap * 3
        home_x = BODY_LEFT + gap
        fix_x = home_x + home_w + gap

        self._home_rect = (home_x, btn_y, home_w, btn_h)
        self._fix_rect = (fix_x, btn_y, fix_w, btn_h)

        self._home_bg, self._home_lbl = self._draw_button(
            self._home_rect, "[ home ]", SUCCESS)
        self._fix_bg, self._fix_lbl = self._draw_button(
            self._fix_rect, "[ ask bot to fix ]", ACCENT)

        # No FooterView here — buttons already occupy the bottom band.
        self._highlight_selected()

    def _draw_button(self, rect, text, color):
        x, y, w, h = rect
        bg = Rect(x, y, w, h, fill=BG_SURFACE.value,
                  outline=color.value, stroke=1)
        self.rootGroup.append(bg)
        lbl = Label(
            text,
            root_group=self.rootGroup,
            dimensions=Dimensions(w, h),
            position=Position(x, y),
            default_style=Style(
                font_size=12, font_color=color,
                horizontal_align=Align.Center,
                vertical_align=Align.Center,
            ),
        )
        return bg, lbl

    def _highlight_selected(self):
        """Visual hint for the trackball-driven selection. Stroke color
        moves between the two buttons."""
        sel_color = ACCENT.value
        dim_color = BORDER.value
        self._home_bg.outline = sel_color if self._sel == 0 else dim_color
        self._fix_bg.outline = sel_color if self._sel == 1 else dim_color

    # ---- input --------------------------------------------------------------

    def OnUpdate(self, delta_time):
        if self._handled:
            return

        # Touch first — biggest input affordance on this scene.
        if self.touch.available:
            ev = self.touch.read()
            if ev["click"] and ev["x"] is not None:
                px, py = ev["x"], ev["y"]
                # Chrome [<] back also goes home.
                target = self._chrome.button_hit(px, py)
                if target is not None:
                    self._go_home()
                    return
                if self._hit(self._home_rect, px, py):
                    self._go_home()
                    return
                if self._hit(self._fix_rect, px, py):
                    self._ask_bot_to_fix()
                    return

        # Trackball: roll to switch button, click to activate.
        tb = self.trackball.read()
        if tb["left"] or tb["right"] or tb["up"] or tb["down"]:
            delta = ((tb["right"] - tb["left"])
                     + (tb["down"] - tb["up"]))
            if delta != 0:
                self._sel = (self._sel + (1 if delta > 0 else -1)) % 2
                self._highlight_selected()
        if tb["click"]:
            if self._sel == 0:
                self._go_home()
            else:
                self._ask_bot_to_fix()
            return

        # Keyboard fallback.
        k = self.kbd.poll()
        if k == 0x08 or k == 0x1B:  # BSP / ESC
            self._go_home()
        elif k == 0x0D:             # ENTER
            if self._sel == 0:
                self._go_home()
            else:
                self._ask_bot_to_fix()

    def _hit(self, rect, px, py):
        if rect is None:
            return False
        x, y, w, h = rect
        return x <= px < x + w and y <= py < y + h

    def _go_home(self):
        self._handled = True
        self.app.SwitchScene("home")

    def _ask_bot_to_fix(self):
        self._handled = True
        err = self.error
        prompt = (
            "An app on the device just crashed and the user wants you to "
            "diagnose and fix it. Don't ask for confirmation — read the "
            "relevant file, find the bug, write a corrected version, "
            "then call restart_runtime so the user can re-launch.\n\n"
            "Crash details:\n"
            "  where: " + str(err.get("where", "?")) + "\n"
            "  type: " + str(err.get("type", "?")) + "\n"
            "  message: " + str(err.get("message", "?")) + "\n\n"
            "Traceback:\n" + str(err.get("traceback", "(none)"))
        )
        # Stage the prompt and hand off to the bot scene. The bot
        # scene's OnStartup drains pending_bot_prompt and sends the
        # turn automatically, so the agent starts diagnosing without
        # the user typing. Bot's [<] back-target is set so closing
        # the bot returns the user to home (not back here — the error
        # state is already captured in the conversation).
        self.app.pending_bot_prompt = prompt
        self.app.bot_return_target = "home"
        self.app.SwitchScene("bot")

    def OnDraw(self):
        pass

    def OnShutdown(self):
        pass

    def GetRootGroup(self):
        return self.rootGroup

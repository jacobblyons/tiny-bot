"""Built-in 'system' scene: live device telemetry.

Ported from the original /sd/apps/sysinfo.py — now firmware-protected
so it's always available and can't be overwritten by the agent. Uses
the touchable chrome back button instead of ESC.
"""
import gc
import time
import displayio

from engine.application import IScene
from engine.display.ui.elements import Label
from engine.display.ui.models import (
    Align, Dimensions, Position, Style,
)

from engine import wifi_helper
from client.views import ChromeView
from client.views.theme import (
    SCREEN_W, SCREEN_H, CHROME_H, BODY_LEFT, BODY_W,
    TEXT_PRIMARY, TEXT_DIM, ACCENT, SUCCESS,
)


class SystemScene(IScene):
    REFRESH_INTERVAL_S = 1.0

    def __init__(self, app):
        self.app = app
        self.kbd = app.GetKeyboard()
        self.touch = app.GetTouch()
        self.rootGroup = displayio.Group()
        self._lines = []
        self._last_refresh = 0.0
        self._started = False
        self._chrome = None

    def OnStartup(self):
        self._chrome = ChromeView(self.rootGroup,
                                  title="system",
                                  back_target="home",
                                  bot_target="bot")

        rows = [
            ("uptime",   "..."),
            ("free mem", "..."),
            ("wifi",     "..."),
            ("ip",       "..."),
            ("rssi",     "..."),
        ]
        value_x = BODY_LEFT + 96
        for i, (key, val) in enumerate(rows):
            row_y = CHROME_H + 12 + i * 18
            Label(
                key, root_group=self.rootGroup,
                dimensions=Dimensions(80, 14),
                position=Position(BODY_LEFT + 12, row_y),
                default_style=Style(
                    font_size=12, font_color=TEXT_DIM,
                    horizontal_align=Align.Start,
                    vertical_align=Align.Start,
                ),
            )
            v = Label(
                val, root_group=self.rootGroup,
                dimensions=Dimensions(SCREEN_W - value_x - 4, 14),
                position=Position(value_x, row_y),
                default_style=Style(
                    font_size=12, font_color=TEXT_PRIMARY,
                    horizontal_align=Align.Start,
                    vertical_align=Align.Start,
                ),
            )
            self._lines.append((key, v))

        # Hint along the bottom — the [<] chrome button is the
        # canonical way out, but BSP still works for keyboard users.
        Label(
            "tap [<] or press BSP to exit",
            root_group=self.rootGroup,
            dimensions=Dimensions(BODY_W - 12, 14),
            position=Position(BODY_LEFT + 6, SCREEN_H - 16),
            default_style=Style(
                font_size=12, font_color=ACCENT,
                horizontal_align=Align.Start,
                vertical_align=Align.Start,
            ),
        )

    def _refresh(self):
        gc.collect()
        info = wifi_helper.info() if wifi_helper.is_connected() else None
        values = {
            "uptime":   "{:.0f}s".format(time.monotonic()),
            "free mem": "{} bytes".format(gc.mem_free()),
            "wifi":     info["ssid"] if info else "(disconnected)",
            "ip":       info["ip"] if info else "-",
            "rssi":     "{} dBm".format(info["rssi"]) if info else "-",
        }
        for key, lbl in self._lines:
            text = values.get(key, "")
            if lbl.text != text:
                lbl.text = text
                lbl._dirty = True
                lbl.draw()

    def OnUpdate(self, delta_time):
        if not self._started:
            self._started = True
            self._refresh()
        now = time.monotonic()
        if now - self._last_refresh >= self.REFRESH_INTERVAL_S:
            self._last_refresh = now
            self._refresh()
        # Chrome buttons (back/bot) are the primary navigation.
        if self.touch.available:
            ev = self.touch.read()
            if ev["click"] and ev["x"] is not None:
                target = self._chrome.button_hit(ev["x"], ev["y"])
                if target is not None:
                    self.app.SwitchScene(target)
                    return
        # Back via the keyboard (BSP).
        k = self.kbd.poll()
        if k == 0x08 or k == 0x1B:
            self.app.SwitchScene("home")

    def OnDraw(self):
        pass

    def OnShutdown(self):
        pass

    def GetRootGroup(self):
        return self.rootGroup

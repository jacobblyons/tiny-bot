"""WiFi status widget."""
from engine.display.ui.elements import Label
from engine.display.ui.models import Align, Dimensions, Position, Style

from engine import wifi_helper
from client.views.theme import TEXT_PRIMARY, TEXT_DIM, SUCCESS, WARN


class Widget:
    TITLE = "wifi"

    def __init__(self, app):
        self._status = None
        self._ssid = None
        self._ip = None
        self._tick = 0.0

    def build(self, group, x, y, w, h):
        # Three stacked lines; the bottom two hide themselves if the
        # cell is too short to fit them. Status line always renders.
        line_h = 12
        self._has_ssid_row = h >= line_h * 2
        self._has_ip_row = h >= line_h * 3
        self._status = Label(
            "...",
            root_group=group,
            dimensions=Dimensions(w, line_h),
            position=Position(x, y),
            default_style=Style(
                font_size=12,
                font_color=TEXT_PRIMARY,
                horizontal_align=Align.Start,
                vertical_align=Align.Start,
            ),
        )
        if self._has_ssid_row:
            self._ssid = Label(
                "",
                root_group=group,
                dimensions=Dimensions(w, line_h),
                position=Position(x, y + line_h),
                default_style=Style(
                    font_size=12,
                    font_color=TEXT_DIM,
                    horizontal_align=Align.Start,
                    vertical_align=Align.Start,
                ),
            )
        if self._has_ip_row:
            self._ip = Label(
                "",
                root_group=group,
                dimensions=Dimensions(w, line_h),
                position=Position(x, y + line_h * 2),
                default_style=Style(
                    font_size=12,
                    font_color=TEXT_DIM,
                    horizontal_align=Align.Start,
                    vertical_align=Align.Start,
                ),
            )
        self._refresh()

    def update(self, delta_time):
        self._tick += delta_time
        if self._tick < 2.0:
            return
        self._tick = 0.0
        self._refresh()

    def _refresh(self):
        if wifi_helper.is_connected():
            info = wifi_helper.info()
            self._status.text = "[ online ]"
            self._status.style.font_color = SUCCESS
            ssid_text = "ssid: " + info.get("ssid", "?")
            ip_text = "ip:   " + info.get("ip", "?")
        else:
            self._status.text = "[ offline ]"
            self._status.style.font_color = WARN
            ssid_text = ""
            ip_text = ""
        labels = [self._status]
        if self._has_ssid_row:
            self._ssid.text = ssid_text
            labels.append(self._ssid)
        if self._has_ip_row:
            self._ip.text = ip_text
            labels.append(self._ip)
        for lbl in labels:
            lbl._dirty = True
            lbl.draw()

"""Battery widget — shows charge % and a horizontal fill bar.

Reads board.BAT_ADC each refresh (15s cadence). The bar fill grows
left-to-right as charge increases; the bar's color steps through
SUCCESS / ACCENT / WARN as the battery drains so the user can spot
"plug me in" at a glance without reading the number.
"""
import board
import analogio
from adafruit_display_shapes.rect import Rect

from engine.display.ui.elements import Label
from engine.display.ui.models import Align, Dimensions, Position, Style

from client.views.theme import ACCENT, SUCCESS, WARN, BORDER, BG_SURFACE


# T-Deck Li-ion cell range. _V_MIN is "we're about to brown out",
# _V_MAX is "fully charged"; everything in between maps linearly to
# the percentage. Not super accurate (cells aren't linear) but
# accurate enough for an at-a-glance widget.
_V_MIN = 3.0
_V_MAX = 4.2


class Widget:
    TITLE = "battery"

    def __init__(self, app):
        self._app = app
        self._group = None
        self._fill = None
        self._track_x = 0
        self._track_y = 0
        self._track_h = 0
        self._fill_max_w = 0
        self._label = None
        self._label_x = 0
        self._label_y = 0
        self._label_w = 0
        self._label_h = 0
        # Start past the refresh interval so the first frame triggers
        # an immediate _refresh — otherwise the bar stays at the
        # placeholder width for 15 seconds after boot.
        self._elapsed = 15.0

    def build(self, group, x, y, w, h):
        self._group = group
        self._label_x = x
        self._label_y = y
        self._label_w = w
        self._label_h = h

        # Bar lives in the bottom quarter of the cell; label fills the
        # remainder above. Both scale with `h` so the widget reads OK
        # whether it lands in a tall 2x2 cell or a short 3x2 one.
        bar_h = max(6, h // 4)
        bar_y = y + h - bar_h - 2
        self._track_x = x + 2
        self._track_y = bar_y
        self._track_h = bar_h
        self._fill_max_w = w - 6

        group.append(Rect(x + 2, bar_y, w - 4, bar_h,
                          fill=BG_SURFACE.value, outline=BORDER.value))
        # Placeholder fill — 2 px wide so something is on screen even
        # before the first ADC read completes. Rect width is immutable
        # in CircuitPython so refresh swaps the whole Rect.
        self._fill = Rect(x + 3, bar_y + 1, 2, bar_h - 2,
                          fill=SUCCESS.value, outline=None)
        group.append(self._fill)

    def update(self, delta_time):
        self._elapsed += delta_time
        if self._elapsed < 15.0:
            return
        self._elapsed = 0.0
        self._refresh()

    def _refresh(self):
        v = self._read_voltage()
        if v is None:
            pct = None
            txt = "bat: N/A"
        else:
            pct = int(max(0, min(100,
                                 (v - _V_MIN) / (_V_MAX - _V_MIN) * 100.0)))
            txt = "{}%  {:.2f}V".format(pct, v)

        if self._fill is not None and self._group is not None and pct is not None:
            # Swap the fill Rect since width is read-only after construction.
            try:
                self._group.remove(self._fill)
            except Exception:
                pass
            fw = max(2, int(self._fill_max_w * pct / 100))
            color = self._pct_color(pct)
            self._fill = Rect(self._track_x + 1,
                              self._track_y + 1,
                              fw,
                              self._track_h - 2,
                              fill=color.value, outline=None)
            self._group.append(self._fill)

        # Lazy-construct the label so we don't allocate it until we
        # have something useful to display.
        if self._label is None and self._group is not None:
            bar_h = max(6, self._label_h // 4)
            lbl_h = self._label_h - bar_h - 4
            self._label = Label(
                txt,
                root_group=self._group,
                dimensions=Dimensions(self._label_w, max(lbl_h, 12)),
                position=Position(self._label_x, self._label_y + 2),
                default_style=Style(
                    font_size=12,
                    font_color=ACCENT,
                    horizontal_align=Align.Center,
                    vertical_align=Align.Center,
                ),
            )
        elif self._label is not None:
            self._label.text = txt
            self._label.draw()

    def _read_voltage(self):
        try:
            adc = analogio.AnalogIn(board.BAT_ADC)
            raw = adc.value
            ref = adc.reference_voltage
            adc.deinit()
            # ESP32-S3 batt sense pin uses a 2:1 divider on the T-Deck.
            return (raw / 65535) * ref * 2.0
        except Exception:
            return None

    def _pct_color(self, pct):
        if pct > 50:
            return SUCCESS
        if pct > 20:
            return ACCENT
        return WARN

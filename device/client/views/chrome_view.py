"""Top header primitive: back-button (left) | title (center) | status (right).

The chrome bar runs across the top of every non-splash scene. Its
height comes from theme.CHROME_H (user-tunable in the config scene)
so users with bigger thumbs can ask for a taller header.

  - `[<]` upper-left   -> back_target (typically "home"); hidden on home
  - centered title     -> short page name
  - right-side status  -> battery % + uptime, auto-refreshing

The old `[bot]` shortcut button is gone — the chat is now reachable
either via the bottom-right floating bubble (on non-home scenes) or
via home's inline input bar (on home). Removing it freed the right
side of the header for live status info.

Status refresh: chrome ticks itself on every App.Run frame via the
module-level `tick_active()` helper. Internally it throttles to
STATUS_REFRESH_MS so we don't redraw the label every tick.
"""
import time

from displayio import Group
from adafruit_display_shapes.rect import Rect
from adafruit_display_shapes.line import Line

from engine.application import IView
from engine.display.ui.elements import Label, UIElement
from engine.display.ui.models import Align, Dimensions, Position, Style

from client.views.theme import (
    SCREEN_W, SCREEN_H, CHROME_H,
    BG_MAIN, BG_SURFACE, BORDER, TEXT_DIM, TEXT_PRIMARY, ACCENT,
)


def _back_btn_w():
    return max(36, CHROME_H + 12)


def _status_w():
    # The right-side status zone needs to fit roughly "100% 12h34" =
    # 10 chars. At 6 px/char that's 60 px; budget a bit extra so
    # longer labels (e.g. "v=3.85V" debug strings) don't clip.
    return max(70, CHROME_H + 38)


BACK_GLYPH = "[<]"


_GLOBAL_APP = None
_ACTIVE_CHROME = None


def set_app(app):
    """Called by App.__init__ so chrome can resolve the
    app_return_target override and read live battery state."""
    global _GLOBAL_APP
    _GLOBAL_APP = app


def _set_active(chrome):
    global _ACTIVE_CHROME
    _ACTIVE_CHROME = chrome


def tick_active():
    """App.Run calls this every frame; chrome internally throttles
    so the right-side status label only repaints when its value
    actually changes."""
    if _ACTIVE_CHROME is not None:
        try:
            _ACTIVE_CHROME.tick()
        except Exception:
            # A chrome tick failure shouldn't poison the App.Run loop.
            pass


class ChromeView(IView):
    """Top header bar — see module docstring."""

    # How often to recompute battery + uptime (ms). Battery doesn't
    # move fast; uptime ticks every second so we re-render at 1 Hz.
    STATUS_REFRESH_MS = 1000

    def __init__(self, root_group: Group, title="",
                 back_target="home", bot_target=None):
        """
        Args:
            root_group:  the scene's displayio.Group; chrome owns the
                         backdrop and bar fill, drawn first.
            title:       short page name shown centered.
            back_target: scene name the [<] button switches to. Pass
                         None on home/wizard/splash to hide the button.
            bot_target:  IGNORED in the new chrome layout — kept for
                         backward compat with scenes that still pass
                         bot_target="bot". The chat now opens via the
                         floating bubble or home's input bar.
        """
        self._root_group = root_group
        if back_target == "home" and _GLOBAL_APP is not None:
            override = getattr(_GLOBAL_APP, "app_return_target", None)
            if override:
                back_target = override
        self._back_target = back_target
        # bot_target intentionally not stored — feature gone.

        self._back_w = _back_btn_w()
        self._status_w = _status_w()

        # Full-screen slate background.
        self._screen_bg = Rect(0, 0, SCREEN_W, SCREEN_H,
                               fill=BG_MAIN.value, outline=None)
        root_group.append(self._screen_bg)

        # Chrome strip + 1px separator.
        self._chrome_bg = Rect(0, 0, SCREEN_W, CHROME_H,
                               fill=BG_SURFACE.value, outline=None)
        root_group.append(self._chrome_bg)
        self._sep = Line(0, CHROME_H, SCREEN_W, CHROME_H, color=BORDER.value)
        root_group.append(self._sep)

        # Back button (only when back_target is set).
        if back_target:
            self._back_btn_bg = Rect(2, 2, self._back_w - 4, CHROME_H - 4,
                                     fill=BG_MAIN.value,
                                     outline=ACCENT.value, stroke=1)
            root_group.append(self._back_btn_bg)
            self._back_label = Label(
                BACK_GLYPH,
                root_group=root_group,
                dimensions=Dimensions(self._back_w, CHROME_H),
                position=Position(0, 0),
                default_style=Style(
                    font_size=12,
                    font_color=ACCENT,
                    horizontal_align=Align.Center,
                    vertical_align=Align.Center,
                    padding=2,
                ),
            )
        else:
            self._back_btn_bg = None
            self._back_label = None

        # Right-side status zone. No outline, no button look — this
        # is informational, not tappable.
        self._status_label = Label(
            "",
            root_group=root_group,
            dimensions=Dimensions(self._status_w, CHROME_H),
            position=Position(SCREEN_W - self._status_w, 0),
            default_style=Style(
                font_size=12,
                font_color=TEXT_DIM,
                horizontal_align=Align.End,
                vertical_align=Align.Center,
                padding=2,
            ),
        )

        # Title in the middle band.
        left_inset = self._back_w if back_target else 0
        right_inset = self._status_w
        title_x = left_inset
        title_w = SCREEN_W - left_inset - right_inset
        self._title = Label(
            title,
            root_group=root_group,
            dimensions=Dimensions(title_w, CHROME_H),
            position=Position(title_x, 0),
            default_style=Style(
                font_size=12,
                font_color=TEXT_PRIMARY,
                horizontal_align=Align.Center,
                vertical_align=Align.Center,
                padding=2,
            ),
        )

        self._last_status_ms = 0
        self._last_status_text = ""
        # Register so App.Run can tick us each frame.
        _set_active(self)
        # Initial paint so the status zone isn't blank.
        self.tick(force=True)

    # ---- status refresh ----------------------------------------------------

    def tick(self, force=False):
        now = int(time.monotonic() * 1000)
        if not force and now - self._last_status_ms < self.STATUS_REFRESH_MS:
            return
        self._last_status_ms = now
        text = self._compute_status_text()
        if text != self._last_status_text:
            self._status_label.text = text
            self._status_label._dirty = True
            self._status_label.draw()
            self._last_status_text = text

    def _compute_status_text(self):
        bat = self._battery_percent()
        clk = self._uptime_str()
        if bat is None:
            return clk
        return "{}% {}".format(bat, clk)

    @staticmethod
    def _battery_percent():
        """Quick Li-ion cell read via board.BAT_ADC. None if the
        ADC isn't accessible (host build / wired-up wrong / etc.)."""
        try:
            import board
            import analogio
            adc = analogio.AnalogIn(board.BAT_ADC)
            raw = adc.value
            ref = adc.reference_voltage
            adc.deinit()
            # 2:1 divider on the T-Deck batt sense pin.
            v = (raw / 65535) * ref * 2.0
            pct = int(max(0, min(100, (v - 3.0) / 1.2 * 100.0)))
            return pct
        except Exception:
            return None

    @staticmethod
    def _uptime_str():
        """Uptime as 'M:SS' under an hour, 'Hh MM' over. No wall-
        clock since the T-Deck has no RTC and we don't currently
        sync via NTP."""
        sec = int(time.monotonic())
        if sec >= 3600:
            h = sec // 3600
            m = (sec // 60) % 60
            return "{}h{:02d}".format(h, m)
        m = sec // 60
        s = sec % 60
        return "{:d}:{:02d}".format(m, s)

    # ---- touch hit-testing -------------------------------------------------

    def button_hit(self, px, py):
        """Return the scene name to navigate to if (px, py) hits the
        back button, else None. The status zone is informational only
        and never returns a hit."""
        if py is None or px is None:
            return None
        if py >= CHROME_H:
            return None
        if self._back_target and px < self._back_w:
            return self._back_target
        return None

    def back_hit(self, px, py):
        target = self.button_hit(px, py)
        if target == self._back_target:
            return target
        return None

    # ---- mutation ----------------------------------------------------------

    def set_title(self, text):
        self._title.text = text
        self._title._dirty = True
        self._title.draw()

    def getElement(self) -> UIElement:
        return self._title

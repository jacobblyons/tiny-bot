"""Modal single-select picker.

Renders a centered card overlaying the current scene that shows a title
and a vertical list of options. Returns the user's choice via a blocking
`show()` call so callers can simply write:

    picked = Select.show(scene_group, "model",
                         options=["claude-opus-4-7", "claude-sonnet-4-6"],
                         current=cfg["agent"]["model"],
                         kbd=kbd, trackball=tb, touch=touch)
    if picked is not None:
        cfg["agent"]["model"] = picked

Input handling supports all three pointing devices:

  - touch: tap a row to pick it immediately (single tap)
  - trackball: roll up/down to highlight, click to commit
  - keyboard: ENTER picks the highlighted row, BSP/ESC cancels

A solid backdrop covers the underlying scene while the modal is up so
the user isn't visually confused by content showing through. The
modal's own sprites are cleaned up automatically on close.
"""
import time
import displayio
from adafruit_display_shapes.rect import Rect

from engine.display.ui.elements.label import Label
from engine.display.ui.models import Align, Color, Dimensions, Position, Style


# Theme defaults — match the rest of the UI but live here so this
# component remains usable from any scene without importing client/.
# All defaults are Color objects: Rect needs the .value int, but Label
# wants the wrapping Color, so we keep both ergonomic by passing Color
# through and unwrapping at the Rect calls below.
DEFAULT_BG          = Color(hex=0x152130)
DEFAULT_BACKDROP    = Color(hex=0x0A1626)
DEFAULT_BORDER      = Color(hex=0x3D5878)
DEFAULT_TITLE       = Color(hex=0xFFB454)
DEFAULT_TEXT        = Color(hex=0xE0E8F0)
DEFAULT_TEXT_DIM    = Color(hex=0x7A8FA8)
DEFAULT_ACCENT      = Color(hex=0xFFB454)

SCREEN_W = 320
SCREEN_H = 240

KEY_BACKSPACE = 0x08
KEY_ENTER = 0x0D
KEY_ESC = 0x1B


class Select:
    """Modal single-pick component. Use the `show` classmethod."""

    MODAL_W = 240
    ROW_H = 20
    TITLE_H = 16
    PAD = 8

    @classmethod
    def show(cls, parent_group, title, options, current=None,
             kbd=None, trackball=None, touch=None,
             bg=DEFAULT_BG, backdrop=DEFAULT_BACKDROP, border=DEFAULT_BORDER,
             title_color=DEFAULT_TITLE, text_color=DEFAULT_TEXT,
             text_dim=DEFAULT_TEXT_DIM, accent=DEFAULT_ACCENT):
        """Show modal and block until user picks an option or cancels.

        Returns the chosen value (an element of `options`) or None if
        the user cancelled (tap outside / BSP / ESC).
        """
        instance = cls(parent_group, title, options, current,
                       kbd, trackball, touch,
                       bg, backdrop, border,
                       title_color, text_color, text_dim, accent)
        try:
            return instance._run()
        finally:
            instance._cleanup()

    def __init__(self, parent_group, title, options, current,
                 kbd, trackball, touch,
                 bg, backdrop, border,
                 title_color, text_color, text_dim, accent):
        self._parent = parent_group
        self._options = list(options) if options else []
        self._kbd = kbd
        self._trackball = trackball
        self._touch = touch
        self._text_color = text_color
        self._accent = accent

        # Locate the current value so the highlight starts on it. If the
        # caller passes a value not in the list (e.g. an old model name),
        # we fall back to index 0 — better than failing the modal.
        self._sel = 0
        if current is not None:
            for i, opt in enumerate(self._options):
                if opt == current:
                    self._sel = i
                    break

        # Compute modal geometry. Height grows with option count up to a
        # cap so very long lists don't push past the screen — we accept
        # truncation rather than implementing scrolling here.
        n = max(1, len(self._options))
        max_rows = (SCREEN_H - 60) // self.ROW_H
        visible_n = min(n, max_rows)
        modal_h = self.TITLE_H + self.PAD * 3 + visible_n * self.ROW_H
        mx = (SCREEN_W - self.MODAL_W) // 2
        my = (SCREEN_H - modal_h) // 2
        self._modal_rect = (mx, my, self.MODAL_W, modal_h)
        self._visible_n = visible_n
        # Scroll offset (first visible option index). Stays at 0 if all
        # options fit; otherwise tracks the selection so the highlight
        # is always on screen.
        self._scroll = 0
        self._update_scroll()

        # Build the modal in its own group so we can drop it cleanly.
        self._group = displayio.Group()
        # Backdrop covers the whole screen so the underlying scene
        # doesn't visually fight with the modal.
        self._group.append(Rect(0, 0, SCREEN_W, SCREEN_H,
                                fill=backdrop.value, outline=None))
        # Card.
        self._group.append(Rect(mx, my, self.MODAL_W, modal_h,
                                fill=bg.value, outline=border.value, stroke=1))
        # Title.
        Label(
            title,
            root_group=self._group,
            dimensions=Dimensions(self.MODAL_W - self.PAD * 2, self.TITLE_H),
            position=Position(mx + self.PAD, my + self.PAD),
            default_style=Style(
                font_size=12, font_color=title_color,
                horizontal_align=Align.Start,
                vertical_align=Align.Center,
            ),
        )
        # Divider under title.
        self._group.append(Rect(
            mx + self.PAD, my + self.PAD + self.TITLE_H,
            self.MODAL_W - self.PAD * 2, 1,
            fill=border.value, outline=None,
        ))

        # One label per visible row — we recycle them on scroll.
        self._list_top = my + self.PAD * 2 + self.TITLE_H
        self._option_labels = []
        for i in range(visible_n):
            lbl = Label(
                "",
                root_group=self._group,
                dimensions=Dimensions(self.MODAL_W - self.PAD * 2, self.ROW_H),
                position=Position(mx + self.PAD,
                                  self._list_top + i * self.ROW_H),
                default_style=Style(
                    font_size=12, font_color=text_color,
                    horizontal_align=Align.Start,
                    vertical_align=Align.Center,
                ),
            )
            self._option_labels.append(lbl)

        parent_group.append(self._group)
        self._render()

    # ---- rendering ----------------------------------------------------------

    def _update_scroll(self):
        """Keep self._sel inside the visible window."""
        if self._sel < self._scroll:
            self._scroll = self._sel
        elif self._sel >= self._scroll + self._visible_n:
            self._scroll = self._sel - self._visible_n + 1

    def _render(self):
        self._update_scroll()
        for slot, lbl in enumerate(self._option_labels):
            idx = self._scroll + slot
            if idx >= len(self._options):
                lbl.text = ""
                lbl._dirty = True
                lbl.draw()
                continue
            prefix = "> " if idx == self._sel else "  "
            new = prefix + str(self._options[idx])
            if lbl.text != new:
                lbl.text = new
                lbl._dirty = True
            lbl.style.font_color = (
                self._accent if idx == self._sel else self._text_color)
            lbl.draw()

    # ---- hit-testing --------------------------------------------------------

    def _hit_row(self, px, py):
        mx, my, mw, mh = self._modal_rect
        # Inside modal but below the title?
        if not (mx <= px < mx + mw and self._list_top <= py < my + mh - self.PAD):
            return None
        slot = (py - self._list_top) // self.ROW_H
        idx = self._scroll + slot
        if 0 <= idx < len(self._options):
            return idx
        return None

    def _is_outside_modal(self, px, py):
        mx, my, mw, mh = self._modal_rect
        return not (mx <= px < mx + mw and my <= py < my + mh)

    # ---- input loop ---------------------------------------------------------

    def _run(self):
        if not self._options:
            return None
        while True:
            if self._touch is not None and getattr(self._touch, "available", False):
                ev = self._touch.read()
                if ev["click"] and ev["x"] is not None:
                    px, py = ev["x"], ev["y"]
                    row = self._hit_row(px, py)
                    if row is not None:
                        # Single tap commits — feels right on a touch UI.
                        return self._options[row]
                    if self._is_outside_modal(px, py):
                        return None
            if self._trackball is not None:
                tb = self._trackball.read()
                if tb["up"] or tb["down"]:
                    delta = tb["down"] - tb["up"]
                    self._sel = (self._sel + delta) % len(self._options)
                    self._render()
                if tb["click"]:
                    return self._options[self._sel]
            if self._kbd is not None:
                k = self._kbd.poll()
                if k:
                    if k == KEY_ENTER:
                        return self._options[self._sel]
                    if k in (KEY_ESC, KEY_BACKSPACE):
                        return None
            time.sleep(0.01)

    def _cleanup(self):
        try:
            self._parent.remove(self._group)
        except ValueError:
            pass

"""Always-visible bot input row for the home scene.

A multi-line input strip pinned to the bottom of home. Typing into
it tracks a local buffer; pressing ENTER on a non-empty buffer
switches to the bot scene with the typed text staged as a pending
prompt. Pressing ENTER on an empty buffer just switches to the bot
scene so the user can compose there with the full overlay UI.

The strip exposes simple per-frame `feed_*` methods rather than
running its own input loop, so the host scene's OnUpdate dispatches
input the same way as for any other view.
"""
from adafruit_display_shapes.rect import Rect

from engine.display.ui.elements import Label
from engine.display.ui.models import Align, Dimensions, Position, Style

from client.services.bot import _wrap


INPUT_LINES = 2
INPUT_LINE_H = 14
INPUT_AREA_H = INPUT_LINES * INPUT_LINE_H


class BotInputBar:
    KEY_BACKSPACE = 0x08
    KEY_ENTER = 0x0D
    KEY_ESC = 0x1B

    def __init__(self, root_group, theme, x, y, w, h=None,
                 placeholder="ask the bot..."):
        """
        Args:
            root_group:   the scene's root displayio.Group; the bar
                          appends itself directly.
            theme:        dict of Color objects.
            x, y, w:      top-left + width of the bar.
            h:            optional height override (defaults to
                          INPUT_LINES * INPUT_LINE_H + 4).
            placeholder:  greyed text shown while the buffer is empty.
        """
        self._theme = theme
        self._x = x
        self._y = y
        self._w = w
        self._h = h or (INPUT_AREA_H + 4)
        self._placeholder = placeholder
        self._buffer = []
        # Wrap width in chars — leave a 6-px margin each side and
        # subtract for the leading "> " / "  " prefix.
        self._wrap_width = max(20, (w - 16) // 6) - 2
        # Background + border so the strip reads as an interactive
        # field rather than blending into the scene.
        self._bg = Rect(
            x, y, w, self._h,
            fill=theme["bg_surface"].value,
            outline=theme["border"].value, stroke=1,
        )
        root_group.append(self._bg)
        # Pre-allocate one label per line.
        self._labels = []
        for i in range(INPUT_LINES):
            lbl = Label(
                "",
                root_group=root_group,
                dimensions=Dimensions(w - 10, INPUT_LINE_H),
                position=Position(x + 6, y + 2 + i * INPUT_LINE_H),
                default_style=Style(
                    font_size=12, font_color=theme["accent"],
                    horizontal_align=Align.Start,
                    vertical_align=Align.Start,
                ),
            )
            self._labels.append(lbl)
        self._render()
        self._rect = (x, y, w, self._h)

    @property
    def rect(self):
        return self._rect

    def hit(self, px, py):
        if px is None or py is None:
            return False
        x, y, w, h = self._rect
        return x <= px < x + w and y <= py < y + h

    def has_text(self):
        return bool(self._buffer)

    def consume_text(self):
        """Return the current buffer and clear it. Used by the host
        scene when ENTER fires to forward the text to the bot."""
        text = "".join(self._buffer).strip()
        self._buffer = []
        self._render()
        return text

    def feed_key(self, k):
        """Handle one key event. Returns one of:
          - "send"  : caller should consume_text() and forward to bot
          - "open"  : ENTER on empty buffer; caller should switch to
                      the bot scene without a pending prompt
          - "cancel": ESC pressed — caller may want to clear focus
          - None    : key consumed normally
        """
        if k == self.KEY_ENTER:
            if self._buffer:
                return "send"
            return "open"
        if k == self.KEY_ESC:
            if self._buffer:
                self._buffer = []
                self._render()
                return None
            return "cancel"
        if k == self.KEY_BACKSPACE:
            if self._buffer:
                self._buffer.pop()
                self._render()
            return None
        if 0x20 <= k <= 0x7E and len(self._buffer) < 512:
            self._buffer.append(chr(k))
            self._render()
        return None

    def _render(self):
        raw = "".join(self._buffer)
        if not raw:
            # Placeholder occupies row 0 with the dim color.
            self._labels[0].style.font_color = self._theme["text_dim"]
            self._labels[0].text = "> " + self._placeholder + "_"
            self._labels[0]._dirty = True
            self._labels[0].draw()
            if len(self._labels) > 1:
                self._labels[1].style.font_color = self._theme["text_dim"]
                self._labels[1].text = ""
                self._labels[1]._dirty = True
                self._labels[1].draw()
            return
        wrapped = _wrap(raw, self._wrap_width)
        if not wrapped:
            wrapped = [""]
        wrapped = wrapped[-INPUT_LINES:]
        while len(wrapped) < INPUT_LINES:
            wrapped.append("")
        last_with_content = 0
        for i in range(INPUT_LINES - 1, -1, -1):
            if wrapped[i]:
                last_with_content = i
                break
        for i, lbl in enumerate(self._labels):
            prefix = "> " if i == 0 else "  "
            text = prefix + wrapped[i]
            if i == last_with_content:
                text += "_"
            lbl.style.font_color = self._theme["accent"]
            if lbl.text != text:
                lbl.text = text
                lbl._dirty = True
                lbl.draw()

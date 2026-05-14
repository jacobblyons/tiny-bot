"""Shared terminal-agent theme constants.

`CHROME_H` is read from /config.json at import time so the user can
tune the top header height (and thus the touch-target size of the
chrome buttons) without touching firmware. Bad values fall back to
defaults — we never want a busted config to make the chrome
unrenderable.
"""
import json

from engine.display.ui.models import Color

# Geometry
SCREEN_W = 320
SCREEN_H = 240
FOOTER_H = 18
BODY_INSET = 6         # frame inset from screen edges

# Top header height. Configurable in config_scene (`header h`) so the
# user can match their thumb size. theme clamps to a sane range.
_DEFAULT_CHROME_H = 32
_CHROME_MIN = 16
_CHROME_MAX = 64


def _load_chrome_h():
    try:
        with open("/config.json", "r") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return _DEFAULT_CHROME_H
    try:
        h = int(cfg.get("ui", {}).get("header_height", _DEFAULT_CHROME_H))
    except (TypeError, ValueError):
        return _DEFAULT_CHROME_H
    if h < _CHROME_MIN:
        return _CHROME_MIN
    if h > _CHROME_MAX:
        return _CHROME_MAX
    return h


CHROME_H = _load_chrome_h()
# Kept as legacy aliases so the rest of the scene code (which was
# briefly written for the sidebar layout) keeps working with the
# top-bar chrome — body is now the full screen width.
BODY_LEFT = 0
BODY_W = SCREEN_W

# Palette (warm "campfire terminal")
# Dark backgrounds carry a warm reddish-brown undertone instead of
# slate blue. Primary accent is a vivid orange; warnings are a
# saturated red. Success drops to a warm gold so it reads as a
# different beat from the orange accent without flipping back to
# blue/green.
#
# Wire-order note: this T-Deck's ST7789 panel is wired BGR — the
# board firmware's MADCTL has the BGR bit set, so any RGB888 we hand
# displayio gets its R and B channels swapped on the way to the
# pixels. We compensate by pre-swapping R and B in our hex constants
# via `_bgr_swap()` below. Changing the panel's MADCTL would also
# rotate the screen since rotation bits share the same register, so
# fixing it in software here is cleaner.


def _bgr_swap(rrggbb):
    """Swap R and B in a 24-bit color so it renders correctly on the
    BGR-ordered panel. Use this for every theme constant you want the
    user to see in true color."""
    r = (rrggbb >> 16) & 0xFF
    g = (rrggbb >> 8) & 0xFF
    b = rrggbb & 0xFF
    return (b << 16) | (g << 8) | r


BG_MAIN = Color(hex=_bgr_swap(0x0F0808))
BG_SURFACE = Color(hex=_bgr_swap(0x1F1313))
TILE_FILL = Color(hex=_bgr_swap(0x2D1B1B))   # carousel card fill
BORDER = Color(hex=_bgr_swap(0x8B3A1A))      # burnt-orange divider
TEXT_PRIMARY = Color(hex=_bgr_swap(0xF0E5D5))  # warm cream
TEXT_DIM = Color(hex=_bgr_swap(0x99776A))    # muted clay
ACCENT = Color(hex=_bgr_swap(0xFF7A2E))      # vivid orange
ACCENT_DIM = Color(hex=_bgr_swap(0xB85020))
SUCCESS = Color(hex=_bgr_swap(0xCCAA33))     # warm gold
WARN = Color(hex=_bgr_swap(0xE53030))        # saturated red


# Shared TINY-BOT logo. Splash and home both render this. Five rows
# of figlet-standard block letters at 6 px/char wide; the dash field
# in row 3 is exactly 5 chars so the 'B', 'O', 'T' columns line up
# vertically with rows 2, 4, 5.
LOGO_LINES = (
    " _____  ___  _   _ __   __      ____    ___   _____ ",
    "|_   _||_ _|| \\ | |\\ \\ / /     | __ )  / _ \\ |_   _|",
    "  | |   | | |  \\| | \\ V /  --- |  _ \\ | | | |  | |  ",
    "  | |   | | | |\\  |  | |       | |_) || |_| |  | |  ",
    "  |_|  |___||_| \\_|  |_|       |____/  \\___/   |_|  ",
)
LOGO_LINE_H = 11
LOGO_CHAR_W = 6

# Left-to-right warm gradient applied across the full logo: every
# row uses the same horizontal sweep so the columns line up. Eight
# stops yield smooth-enough banding without exploding the label
# count (5 rows × 8 segments = 40 labels). Colors are wrapped in
# _bgr_swap so they render correctly on the BGR-ordered panel.
LOGO_GRADIENT = (
    Color(hex=_bgr_swap(0xFFD060)),  # warm amber
    Color(hex=_bgr_swap(0xFFB040)),
    Color(hex=_bgr_swap(0xFF9030)),
    Color(hex=_bgr_swap(0xFF7028)),  # vivid orange (around ACCENT)
    Color(hex=_bgr_swap(0xFF5020)),
    Color(hex=_bgr_swap(0xEE3818)),
    Color(hex=_bgr_swap(0xCC2820)),
    Color(hex=_bgr_swap(0xAA2020)),  # deep red
)
LOGO_SEGMENTS = len(LOGO_GRADIENT)


def _segment_slices(text, n):
    """Split `text` into `n` contiguous slices of as-even length as
    possible. Leftover characters are distributed to the leading
    slices so the sweep stays anchored at the left edge."""
    L = len(text)
    base = L // n
    extra = L % n
    out = []
    pos = 0
    for i in range(n):
        size = base + (1 if i < extra else 0)
        out.append(text[pos:pos + size])
        pos += size
    return out


def build_logo(root_group, x, y):
    """Render the TINY-BOT block logo into `root_group` starting at
    (x, y). Each row is sliced into LOGO_SEGMENTS chunks and each
    chunk takes the corresponding LOGO_GRADIENT color, giving a
    left-to-right warm-amber → deep-red sweep. Splash and home both
    call this so the brand looks identical across scenes."""
    # Late import keeps the theme module free of UI dependencies for
    # tests that just want palette constants.
    from engine.display.ui.elements import Label
    from engine.display.ui.models import Align, Dimensions, Position, Style

    for row_idx, line in enumerate(LOGO_LINES):
        slices = _segment_slices(line, LOGO_SEGMENTS)
        offset_chars = 0
        for seg_idx, seg in enumerate(slices):
            seg_w = len(seg) * LOGO_CHAR_W
            if seg_w == 0:
                continue
            Label(
                seg,
                root_group=root_group,
                dimensions=Dimensions(seg_w, LOGO_LINE_H),
                position=Position(x + offset_chars * LOGO_CHAR_W,
                                  y + row_idx * LOGO_LINE_H),
                default_style=Style(
                    font_size=12,
                    font_color=LOGO_GRADIENT[seg_idx],
                    horizontal_align=Align.Start,
                    vertical_align=Align.Start,
                ),
            )
            offset_chars += len(seg)


def logo_total_w():
    return len(LOGO_LINES[0]) * LOGO_CHAR_W


def logo_total_h():
    return len(LOGO_LINES) * LOGO_LINE_H

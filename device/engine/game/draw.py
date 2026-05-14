"""Quick draw helpers — text + shapes with sane defaults.

These wrap the underlying adafruit_display_text + adafruit_display_shapes
primitives so games can draw without remembering anchor_point math
or the dimensions/style boilerplate the UI element system requires.

Each function returns the underlying displayio object so the caller
can mutate it later — typically `.text = ...` for text labels or
swap-the-Rect for shapes (Rect dimensions are immutable in
CircuitPython).
"""
import terminalio
from adafruit_display_text import label as _adafruit_label
from adafruit_display_shapes.rect import Rect


# anchor_point values for each named anchor. (0,0) = top-left of
# text bounding box maps to (x, y); (1,1) = bottom-right; (.5, .5)
# = center.
_ANCHORS = {
    "topleft":     (0.0, 0.0),
    "top":         (0.5, 0.0),
    "topright":    (1.0, 0.0),
    "left":        (0.0, 0.5),
    "center":      (0.5, 0.5),
    "right":       (1.0, 0.5),
    "bottomleft":  (0.0, 1.0),
    "bottom":      (0.5, 1.0),
    "bottomright": (1.0, 1.0),
}


def _color_value(color):
    """Accept either a raw int or a theme Color object (.value)."""
    if hasattr(color, "value"):
        return color.value
    return int(color)


def text(group, message, x, y, color=0xFFFFFF, anchor="topleft", scale=1):
    """Place text on `group` at (x, y).

    `anchor` controls what (x, y) means — see _ANCHORS keys.
    Defaults to "topleft" which matches "draw text starting here".
    Use "center" + (160, 120) for screen-centered text without
    measuring the string yourself.

    Mutate via `.text = "new"` and (if you also rebuild) `.color`.
    Position is fixed on creation; for moving text use a fresh
    anchored_position assignment via the returned label.
    """
    lbl = _adafruit_label.Label(
        terminalio.FONT,
        text=message,
        color=_color_value(color),
        scale=scale,
    )
    lbl.anchor_point = _ANCHORS.get(anchor, _ANCHORS["topleft"])
    lbl.anchored_position = (int(x), int(y))
    group.append(lbl)
    return lbl


def fill_rect(group, x, y, w, h, color):
    """Solid-color rectangle. Returns the Rect; remove via
    `group.remove(rect)` to erase, since Rect dimensions are
    immutable after construction."""
    r = Rect(int(x), int(y), int(w), int(h),
             fill=_color_value(color), outline=None)
    group.append(r)
    return r


def outline_rect(group, x, y, w, h, color, stroke=1):
    """Hollow rectangle — outline only, no fill."""
    r = Rect(int(x), int(y), int(w), int(h),
             fill=None, outline=_color_value(color), stroke=stroke)
    group.append(r)
    return r

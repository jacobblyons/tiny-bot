"""On-screen pointer sprite + unified touch/trackball input.

The pointer position is driven by whichever input changed most recently:
- A touch press snaps the cursor to that pixel.
- Trackball motion nudges it relatively.

Scenes consume input by calling `poll()`, which returns a dict describing
this frame's pointer state plus discrete events (click, release).
"""
from adafruit_display_shapes.rect import Rect


CURSOR_SIZE = 9
CURSOR_THICKNESS = 1


class Cursor:
    """Crosshair-style cursor rendered as four short rects.

    We use rects (not a bitmap) so the cursor inherits the same
    "terminal art" feel as the rest of the UI — no anti-aliasing, hard
    pixel edges.
    """

    def __init__(self, root_group, color, x=160, y=120):
        self._root = root_group
        self._x = x
        self._y = y
        self._color = color
        self._visible = True
        half = CURSOR_SIZE // 2
        # Horizontal arms (left + right of center) and vertical arms
        # (above + below). Leaving the center pixel unfilled keeps a peek
        # at what's underneath so it doesn't fully obscure small targets.
        self._left = Rect(0, 0, half - 1, CURSOR_THICKNESS, fill=color)
        self._right = Rect(0, 0, half - 1, CURSOR_THICKNESS, fill=color)
        self._top = Rect(0, 0, CURSOR_THICKNESS, half - 1, fill=color)
        self._bottom = Rect(0, 0, CURSOR_THICKNESS, half - 1, fill=color)
        for r in (self._left, self._right, self._top, self._bottom):
            root_group.append(r)
        self._reposition()

    def _reposition(self):
        half = CURSOR_SIZE // 2
        self._left.x = self._x - half
        self._left.y = self._y
        self._right.x = self._x + 2
        self._right.y = self._y
        self._top.x = self._x
        self._top.y = self._y - half
        self._bottom.x = self._x
        self._bottom.y = self._y + 2

    def move_to(self, x, y):
        if x < 0: x = 0
        elif x > 319: x = 319
        if y < 0: y = 0
        elif y > 239: y = 239
        self._x = x
        self._y = y
        self._reposition()

    def nudge(self, dx, dy):
        self.move_to(self._x + dx, self._y + dy)

    @property
    def position(self):
        return (self._x, self._y)

    def set_visible(self, visible):
        if visible == self._visible:
            return
        self._visible = visible
        if visible:
            for r in (self._left, self._right, self._top, self._bottom):
                self._root.append(r)
        else:
            for r in (self._left, self._right, self._top, self._bottom):
                try:
                    self._root.remove(r)
                except ValueError:
                    pass

    def reattach(self, root_group):
        """Move the cursor sprite into a new scene's root group.

        Each scene owns its own displayio Group. When the active scene
        changes, the cursor sprites have to migrate too or they'll vanish
        with the old group.
        """
        for r in (self._left, self._right, self._top, self._bottom):
            try:
                self._root.remove(r)
            except ValueError:
                pass
        self._root = root_group
        if self._visible:
            for r in (self._left, self._right, self._top, self._bottom):
                root_group.append(r)


class Pointer:
    """Combines touch + trackball into a single pointer-event stream.

    Touch is treated as an absolute device: a press sets the cursor's
    position directly. Trackball motion is relative — it nudges from the
    last known position. Whichever device interacts most recently "wins"
    for the click event in that frame, so the user can mix-and-match
    inputs without modal switching.
    """

    # Pixels per trackball tick. Bumped up from 6 — at the lower step the
    # cursor took a full second to cross the screen during a slow roll
    # and the device felt sluggish. 14 keeps fine targeting workable while
    # making long sweeps feel responsive.
    TRACKBALL_STEP = 14

    def __init__(self, cursor, touch=None, trackball=None):
        self._cursor = cursor
        self._touch = touch
        self._trackball = trackball

    def poll(self):
        out = {
            "x": None, "y": None,
            "click": False, "release": False,
            "moved": False,
        }
        if self._touch is not None and self._touch.available:
            t = self._touch.read()
            if t["pressed"] and t["x"] is not None:
                self._cursor.move_to(t["x"], t["y"])
                out["moved"] = True
            if t["click"]:
                out["click"] = True
            if t["release"]:
                out["release"] = True
        if self._trackball is not None:
            tb = self._trackball.read()
            dx = (tb["right"] - tb["left"]) * self.TRACKBALL_STEP
            dy = (tb["down"] - tb["up"]) * self.TRACKBALL_STEP
            if dx or dy:
                self._cursor.nudge(dx, dy)
                out["moved"] = True
            if tb["click"]:
                # The trackball click is a single-edge event with no
                # corresponding "release" later — but consumers tap-launch
                # off the release edge, so emit both here so the click
                # behaves like an instant down-up.
                out["click"] = True
                out["release"] = True
        out["x"], out["y"] = self._cursor.position
        return out

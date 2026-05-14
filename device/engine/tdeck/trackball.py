import board
import digitalio
import countio


class TDeckTrackball:
    """Trackball with 4 directional pins (pulse-on-roll) + 1 click pin."""

    def __init__(self):
        self._up = countio.Counter(board.TRACKBALL_UP, edge=countio.Edge.FALL)
        self._down = countio.Counter(board.TRACKBALL_DOWN, edge=countio.Edge.FALL)
        self._left = countio.Counter(board.TRACKBALL_LEFT, edge=countio.Edge.FALL)
        self._right = countio.Counter(board.TRACKBALL_RIGHT, edge=countio.Edge.FALL)
        self._click = digitalio.DigitalInOut(board.TRACKBALL_CLICK)
        self._click.direction = digitalio.Direction.INPUT
        self._click.pull = digitalio.Pull.UP
        self._click_was_pressed = False

    def read(self):
        u, d, l, r = self._up.count, self._down.count, self._left.count, self._right.count
        self._up.reset()
        self._down.reset()
        self._left.reset()
        self._right.reset()
        click_now = not self._click.value
        click_edge = click_now and not self._click_was_pressed
        self._click_was_pressed = click_now
        return {"up": u, "down": d, "left": l, "right": r, "click": click_edge}

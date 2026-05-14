"""Game-input wrappers: keyboard-as-buttons + trackball-as-stick.

Both wrap the bare TDeck drivers and present per-frame state that's
easier to reason about in a game loop.

Why Buttons exists: the T-Deck keyboard sends a key code each time
a key event fires. There's no separate "release" event, so naive
games can't tell when a key is let go. Buttons fixes that by
treating "no event for HOLD_TIMEOUT ms" as a release, and exposes
pressed / down / released states keyed by logical action names.

Why Stick exists: the trackball is four edge-pulse counters (one per
direction) plus a click pin. A pure-diagonal roll fires pulses on
both axes simultaneously, and games that only check one axis at a
time will see diagonals as "snapping" to whichever axis they polled
first. Stick reads all four counters in one go and presents a
single dx/dy vector, plus an 8-way grid-direction helper for
turn-based games.
"""
import time


class Buttons:
    """Keyboard-as-game-controller.

    Map key codes to logical action names once, then query state
    per-frame with `pressed(name)` / `down(name)` / `released(name)`.

    The T-Deck keyboard doesn't report key releases, so we infer
    them from key-repeat timing: if no event for an action arrives
    within `hold_timeout_ms`, the action is considered released.
    On the stock CardKB firmware, key-repeat fires roughly every
    50-80 ms after an initial ~400 ms delay — so a hold_timeout of
    150 ms catches sustained holds without false-releasing on a
    single slow repeat tick.

    Caveat: the first repeat is delayed. A `down('up')` query for
    the FIRST 300-400 ms of a hold may flicker between true and
    false. For movement, use `pressed('up')` to handle the first
    press immediately, then `down('up')` for continued motion.
    """

    DEFAULT_HOLD_TIMEOUT_MS = 150

    def __init__(self, kbd, bindings=None, hold_timeout_ms=None):
        """
        Args:
            kbd:               TDeckKeyboard instance (app.GetKeyboard()).
            bindings:          dict mapping key code (int, e.g. ord('w'))
                               to action name (str). Multiple codes can
                               map to the same action.
            hold_timeout_ms:   how long after the last event before we
                               call an action released. Defaults to
                               150 ms which works with stock CardKB
                               key repeat.
        """
        self._kbd = kbd
        self._bindings = dict(bindings) if bindings else {}
        self._hold_timeout = (hold_timeout_ms
                              if hold_timeout_ms is not None
                              else self.DEFAULT_HOLD_TIMEOUT_MS)
        # action -> ms timestamp of last seen event
        self._last_seen = {}
        # actions currently held (per the timeout heuristic)
        self._held = set()
        # edge-trigger sets, refreshed each update()
        self._just_pressed = set()
        self._just_released = set()
        # Raw codes that didn't match any binding — surfaced via
        # `unmapped()` so games can still grab ENTER/ESC/etc.
        self._unmapped = []

    @staticmethod
    def _now_ms():
        return int(time.monotonic() * 1000)

    def update(self):
        """Refresh state. Call once per frame, before any queries.

        Drains all pending key events from the keyboard since the
        last call, marks new presses and timed-out releases, and
        clears edge state from the previous frame.
        """
        now = self._now_ms()
        self._just_pressed = set()
        self._just_released = set()
        self._unmapped = []

        # Drain the keyboard FIFO so a held key with rapid repeats
        # doesn't pile up codes across frames.
        while True:
            k = self._kbd.poll()
            if not k:
                break
            action = self._bindings.get(k)
            if action is None:
                self._unmapped.append(k)
                continue
            if action not in self._held:
                self._just_pressed.add(action)
                self._held.add(action)
            self._last_seen[action] = now

        # Timeout-based release detection. A held key whose last
        # event is older than hold_timeout_ms is considered released.
        for action in list(self._held):
            last = self._last_seen.get(action, 0)
            if now - last > self._hold_timeout:
                self._held.discard(action)
                self._just_released.add(action)

    def pressed(self, action):
        """True ONLY on the frame this action was first pressed.

        Use for one-shot events: fire a bullet, jump, open a menu.
        """
        return action in self._just_pressed

    def down(self, action):
        """True every frame this action is currently held.

        Use for continuous actions: walk, hold-to-charge.
        """
        return action in self._held

    def released(self, action):
        """True ONLY on the frame this action was just released."""
        return action in self._just_released

    def any_pressed(self):
        """Set of all actions that were just pressed this frame."""
        return set(self._just_pressed)

    def unmapped(self):
        """List of key codes from this frame that had no binding.

        Useful for capturing ENTER/ESC/BACKSPACE without registering
        them as game actions.
        """
        return list(self._unmapped)


class Stick:
    """Trackball as an analog stick.

    Reads all four direction counters + click each frame and packs
    them into one dict so a single read() handles diagonals cleanly:

        m = stick.read()
        player.x += m['dx']
        player.y += m['dy']
        if m['click']: shoot()

    `read()` returns scaled-pixel motion. `grid_step()` returns the
    same input quantized to {-1, 0, +1} per axis once enough pulses
    have accumulated — handy for turn-based / tile-based games where
    you want one-cell-per-roll, not pixel motion.
    """

    DEFAULT_SENSITIVITY = 4
    DEFAULT_GRID_THRESHOLD = 2

    def __init__(self, trackball,
                 sensitivity=None, grid_threshold=None):
        """
        Args:
            trackball:       TDeckTrackball instance (app.GetTrackball()).
            sensitivity:     pixels per pulse for read(). Defaults to 4
                             — small enough that single-pulse jitter
                             doesn't fling the player across the screen,
                             big enough that a hard roll covers ground.
            grid_threshold:  pulses-per-step for grid_step(). Defaults
                             to 2 so light bumps don't fire moves but
                             a clear roll does.
        """
        self._tb = trackball
        self._sens = (sensitivity
                      if sensitivity is not None
                      else self.DEFAULT_SENSITIVITY)
        self._grid_threshold = (grid_threshold
                                if grid_threshold is not None
                                else self.DEFAULT_GRID_THRESHOLD)
        # Sub-step accumulators for grid_step so partial rolls don't
        # vanish — pulses below the threshold sit here until enough
        # accumulate to cross.
        self._gx_accum = 0
        self._gy_accum = 0

    def read(self):
        """Return {"dx", "dy", "click"} for this frame.

        dx/dy are pixels (positive = right/down). Both axes are
        sampled in a single trackball.read() so diagonal rolls always
        produce non-zero motion on BOTH axes when pulses fire on
        both — no axis ever "wins" or hides the other.
        """
        tb = self._tb.read()
        dx = (tb["right"] - tb["left"]) * self._sens
        dy = (tb["down"] - tb["up"]) * self._sens
        return {"dx": dx, "dy": dy, "click": tb["click"]}

    def grid_step(self):
        """Return ({-1,0,1}, {-1,0,1}) for 8-way tile movement.

        Accumulates raw pulses internally; once either axis crosses
        `grid_threshold` it emits a step and decrements the
        accumulator. Both axes can step in the same call (a clean
        diagonal roll produces (1, -1) etc.). Tiny stray pulses
        below the threshold are absorbed rather than producing
        stuttery moves.
        """
        tb = self._tb.read()
        self._gx_accum += tb["right"] - tb["left"]
        self._gy_accum += tb["down"] - tb["up"]
        dx = 0
        dy = 0
        if self._gx_accum >= self._grid_threshold:
            dx = 1
            self._gx_accum -= self._grid_threshold
        elif self._gx_accum <= -self._grid_threshold:
            dx = -1
            self._gx_accum += self._grid_threshold
        if self._gy_accum >= self._grid_threshold:
            dy = 1
            self._gy_accum -= self._grid_threshold
        elif self._gy_accum <= -self._grid_threshold:
            dy = -1
            self._gy_accum += self._grid_threshold
        return (dx, dy, tb["click"])

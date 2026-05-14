"""Frame-pacing helper for games.

Two common needs:
  - delta_time: seconds since last frame, for velocity-based motion
  - fixed-step: run game logic at a constant rate regardless of
                rendering frame rate (collision, physics, AI)

`Clock.tick()` gives delta_time. `Clock.fixed_step()` integrates a
classic accumulator that calls your update function N times per
frame, where N depends on how long the frame took. The accumulator
clamps after a few steps to prevent the spiral-of-death where a
slow frame triggers more steps which take longer which trigger more
steps.
"""
import time


class Clock:
    """Per-frame timing tracker. Construct once in OnStartup, then
    call tick() at the top of every OnUpdate.

    Note: IScene.OnUpdate already receives a delta_time. Clock is
    handy when you want fixed-step logic, a frame counter, or want
    to time-gate effects without managing your own timestamps.
    """

    # Cap on fixed_step iterations per call. If a single frame takes
    # so long that we'd run more than this many steps, we drop the
    # backlog rather than spiral.
    MAX_FIXED_STEPS_PER_FRAME = 5

    def __init__(self):
        self._last = time.monotonic()
        self._fixed_accum = 0.0
        self._frame = 0
        self._elapsed = 0.0

    def tick(self):
        """Return seconds since last tick. Also advances the frame
        counter and total elapsed time."""
        now = time.monotonic()
        dt = now - self._last
        self._last = now
        self._frame += 1
        self._elapsed += dt
        return dt

    def fixed_step(self, dt, rate_hz, fn):
        """Call `fn(step_dt)` once per fixed timestep that fits in `dt`.

        Args:
            dt:       seconds since the last frame (usually from tick()
                      or the scene's delta_time argument)
            rate_hz:  target update rate (e.g. 30 for 30 Hz physics)
            fn:       callable taking a single float `step_dt` argument

        Example:
            def update_physics(step_dt):
                self.player.y += self.player.vy * step_dt

            self.clock.fixed_step(dt, rate_hz=30, fn=update_physics)
        """
        period = 1.0 / rate_hz
        self._fixed_accum += dt
        steps = 0
        while self._fixed_accum >= period:
            fn(period)
            self._fixed_accum -= period
            steps += 1
            if steps >= self.MAX_FIXED_STEPS_PER_FRAME:
                # Drop the backlog. A slow frame shouldn't cascade
                # into a multi-second physics catch-up.
                self._fixed_accum = 0.0
                break

    @property
    def frame(self):
        """Total frames since construction."""
        return self._frame

    @property
    def elapsed(self):
        """Total seconds since construction."""
        return self._elapsed

    def every(self, interval_s):
        """True if at least `interval_s` has passed since this clock
        last returned True for the same interval.

        Quick way to schedule periodic effects without state:

            if self.clock.every(0.5):
                self.flash_cursor()

        Note: shares state per-interval is keyed by the float value,
        so use the same literal across frames.
        """
        # Lazy-init the per-interval ledger.
        ledger = getattr(self, "_every_ledger", None)
        if ledger is None:
            ledger = {}
            self._every_ledger = ledger
        last = ledger.get(interval_s, -1.0)
        if self._elapsed - last >= interval_s:
            ledger[interval_s] = self._elapsed
            return True
        return False

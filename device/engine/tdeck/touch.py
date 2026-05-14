"""GT911 capacitive touch driver.

The T-Deck's GT911 lives on the same I2C bus as the keyboard, so we share
board.I2C() and use try_lock/unlock to avoid contention. We poll the
status register on demand instead of wiring the INT pin — keeps the driver
self-contained and avoids fighting other code over GPIO16.
"""
import time
import board

# GT911 I2C addresses (some boards strap to 0x5D instead).
GT911_PRIMARY = 0x14
GT911_SECONDARY = 0x5D

# Register addresses (16-bit, big-endian on the wire).
REG_STATUS = 0x814E
REG_POINT_1 = 0x8150
REG_CONFIG_VERSION = 0x8047

# Display geometry. The GT911 reports raw coordinates and we map them
# into screen space — the T-Deck panel is mounted landscape so we swap
# axes and flip Y to match the displayio coordinate system.
SCREEN_W = 320
SCREEN_H = 240


class TDeckTouch:
    """Polls the GT911 and returns the first active touch point.

    Coexists with TDeckKeyboard on the shared I2C bus. All bus access
    is wrapped in try_lock/unlock so a half-completed read by another
    consumer can't corrupt our transfer.
    """

    # If we don't see a fresh "pressed" sample for this long, synthesize a
    # release. The GT911's "lift-off" event isn't reliable on all firmware
    # revs — without this timeout, a quick tap registers as press but
    # never as release, so anything gated on release (like our tap-to-
    # launch in the carousel) silently fails.
    STALE_PRESS_MS = 120

    def __init__(self, i2c=None, poll_interval_ms=20, rotation=270):
        self._i2c = i2c or board.I2C()
        self._poll_interval_ms = poll_interval_ms
        self._last_poll_ms = 0
        self._addr = None
        self._rotation = rotation
        self._was_pressed = False
        self._down_pos = None
        self._last_pressed_ms = 0
        self._scratch = bytearray(8)
        self._reg_buf = bytearray(2)
        self._probe()

    def _now_ms(self):
        return int(time.monotonic() * 1000)

    def _probe(self):
        """Find which GT911 strap the panel is using. If neither responds
        we just disable touch — better than crashing the whole UI."""
        for candidate in (GT911_PRIMARY, GT911_SECONDARY):
            try:
                while not self._i2c.try_lock():
                    pass
                try:
                    # Reading the version register is a cheap "are you there?".
                    self._i2c.writeto(candidate, bytes([REG_CONFIG_VERSION >> 8,
                                                         REG_CONFIG_VERSION & 0xFF]))
                    probe_buf = bytearray(1)
                    self._i2c.readfrom_into(candidate, probe_buf)
                    self._addr = candidate
                    return
                finally:
                    self._i2c.unlock()
            except OSError:
                try:
                    self._i2c.unlock()
                except Exception:
                    pass
                continue
        self._addr = None  # touch disabled

    def _read_reg(self, reg, length):
        if self._addr is None:
            return None
        self._reg_buf[0] = (reg >> 8) & 0xFF
        self._reg_buf[1] = reg & 0xFF
        buf = self._scratch if length <= 8 else bytearray(length)
        try:
            while not self._i2c.try_lock():
                pass
            try:
                self._i2c.writeto(self._addr, self._reg_buf)
                view = memoryview(buf)[:length]
                self._i2c.readfrom_into(self._addr, view)
            finally:
                self._i2c.unlock()
        except OSError:
            return None
        return memoryview(buf)[:length]

    def _write_reg(self, reg, value):
        if self._addr is None:
            return
        try:
            while not self._i2c.try_lock():
                pass
            try:
                self._i2c.writeto(self._addr,
                                  bytes([(reg >> 8) & 0xFF, reg & 0xFF, value]))
            finally:
                self._i2c.unlock()
        except OSError:
            pass

    def _map_coords(self, raw_x, raw_y):
        """Map raw GT911 coords into screen space.

        The T-Deck panel is mounted landscape (320 x 240) but the GT911
        is configured for portrait native (240 x 320) — verified by
        reading regs 0x8048..0x804B. For rotation=270 the long axis
        of the panel (raw_y, 0..320) becomes screen X and the short
        axis (raw_x, 0..240) becomes screen Y with a flip. The flip
        must use the panel's X output max (240), not SCREEN_W (320),
        or a chunk of one screen edge becomes unreachable.

        We clamp to screen bounds because the GT911's calibrated range
        can over-shoot by a pixel or two at the edges, and a corrupt
        I2C read could in theory return values way outside expected
        range — clamping is a cheap safeguard against that mapping to
        a "phantom" tap on the chrome back button.
        """
        if self._rotation == 270:
            x = raw_y
            y = SCREEN_H - 1 - raw_x
        elif self._rotation == 90:
            x = SCREEN_W - 1 - raw_y
            y = raw_x
        elif self._rotation == 180:
            x = SCREEN_W - 1 - raw_x
            y = SCREEN_H - 1 - raw_y
        else:  # 0
            x, y = raw_x, raw_y
        # Sanity-reject obviously bad reads (stale buffer / I/O glitch).
        # Without this, a 0xFFFF returned for raw_x would after the flip
        # become a huge negative -> clamped to 0, i.e. land squarely on
        # the back-button row at top-of-screen even though the user
        # didn't touch there.
        if x < 0 or x > SCREEN_W * 2 or y < 0 or y > SCREEN_H * 2:
            return None, None
        if x < 0: x = 0
        elif x >= SCREEN_W: x = SCREEN_W - 1
        if y < 0: y = 0
        elif y >= SCREEN_H: y = SCREEN_H - 1
        return x, y

    def read(self):
        """Return current touch state.

        {
          "pressed": bool,     # finger is currently down
          "click":   bool,     # rising-edge press detected this poll
          "release": bool,     # falling-edge detected this poll
          "x":       int|None, # screen x while pressed
          "y":       int|None, # screen y while pressed
        }
        """
        out = {"pressed": False, "click": False, "release": False,
               "x": None, "y": None}
        if self._addr is None:
            return out
        now = self._now_ms()
        if now - self._last_poll_ms < self._poll_interval_ms:
            # Surface remembered position so callers can keep drawing a cursor.
            if self._was_pressed and self._down_pos is not None:
                out["pressed"] = True
                out["x"], out["y"] = self._down_pos
            return out
        self._last_poll_ms = now

        status = self._read_reg(REG_STATUS, 1)
        if status is None:
            return out
        status_byte = status[0]
        # Bit 7 = "buffer ready / new event". When clear we don't have
        # fresh sample data. If we've been "pressed" too long without
        # any fresh data, the finger has lifted and the controller just
        # didn't post an explicit release — synthesize one. Without this
        # the carousel tap-to-launch hangs waiting for an event that
        # never comes.
        if not (status_byte & 0x80):
            if self._was_pressed:
                if now - self._last_pressed_ms > self.STALE_PRESS_MS:
                    out["release"] = True
                    self._was_pressed = False
                    self._down_pos = None
                else:
                    if self._down_pos is not None:
                        out["pressed"] = True
                        out["x"], out["y"] = self._down_pos
            return out

        n_touches = status_byte & 0x0F
        pressed_now = n_touches > 0
        if pressed_now:
            point = self._read_reg(REG_POINT_1, 8)
            if point is not None:
                # Empirical byte layout on this T-Deck's GT911 firmware,
                # determined by tap-and-dump diagnostics (scripts/touch_diag2.py):
                #   [X_lo, X_hi, Y_lo, Y_hi, size_lo, size_hi, 0, 0]
                # The official GT911 datasheet puts a track-ID byte at
                # offset 0; this build doesn't. Reading at the spec-
                # documented offsets (1..4) returned interleaved
                # X_hi|Y_lo, producing values in the 3000-17000 range
                # instead of 0..240/0..320 — and the resulting clamp
                # landed every tap on the chrome [home] button. Trust
                # the wire, not the datasheet.
                raw_x = point[0] | (point[1] << 8)
                raw_y = point[2] | (point[3] << 8)
                x, y = self._map_coords(raw_x, raw_y)
                if x is not None:
                    out["pressed"] = True
                    out["x"], out["y"] = x, y
                    if not self._was_pressed:
                        out["click"] = True
                    self._was_pressed = True
                    self._down_pos = (x, y)
                    self._last_pressed_ms = now
        else:
            if self._was_pressed:
                out["release"] = True
            self._was_pressed = False
            self._down_pos = None

        # Always clear the ready flag — otherwise the controller stops
        # producing new samples.
        self._write_reg(REG_STATUS, 0x00)
        return out

    @property
    def available(self):
        return self._addr is not None

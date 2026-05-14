import time
import board
import busio

KEYBOARD_ADDR = 0x55

KEY_BACKSPACE = 0x08
KEY_ENTER = 0x0D
KEY_ESC = 0x1B
KEY_TAB = 0x09


class TDeckKeyboard:
    def __init__(self, i2c=None, poll_interval_ms=20):
        self._i2c = i2c or board.I2C()
        self._buf = bytearray(1)
        self._poll_interval_ms = poll_interval_ms
        self._last_poll_ms = 0

    def _now_ms(self):
        return int(time.monotonic() * 1000)

    def poll(self):
        now = self._now_ms()
        if now - self._last_poll_ms < self._poll_interval_ms:
            return 0
        self._last_poll_ms = now
        try:
            while not self._i2c.try_lock():
                pass
            try:
                self._i2c.readfrom_into(KEYBOARD_ADDR, self._buf)
            finally:
                self._i2c.unlock()
        except OSError:
            return 0
        return self._buf[0]

    def wait_key(self, timeout_ms=None):
        start = self._now_ms()
        while True:
            k = self.poll()
            if k:
                return k
            if timeout_ms is not None and self._now_ms() - start >= timeout_ms:
                return 0
            time.sleep(0.005)

    def read_line(self, on_change, mask=False, max_len=128):
        buf = []
        while True:
            k = self.wait_key()
            if k == KEY_ENTER:
                return "".join(buf)
            if k == KEY_ESC:
                return None
            if k == KEY_BACKSPACE:
                if buf:
                    buf.pop()
                    on_change("*" * len(buf) if mask else "".join(buf))
                continue
            if 0x20 <= k <= 0x7E and len(buf) < max_len:
                buf.append(chr(k))
                on_change("*" * len(buf) if mask else "".join(buf))

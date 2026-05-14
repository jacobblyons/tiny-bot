# Dump ALL 8 bytes of the GT911 touch point register so we can decode
# the actual byte layout this firmware variant uses.
import time
import board

GT_ADDR = 0x5D
i2c = board.I2C()
LOG_PATH = "/touch_log.txt"
log_f = open(LOG_PATH, "w")


def log(msg):
    print(msg)
    log_f.write(msg + "\n")
    log_f.flush()


def rr(reg, n):
    while not i2c.try_lock():
        pass
    try:
        i2c.writeto(GT_ADDR, bytes([(reg >> 8) & 0xFF, reg & 0xFF]))
        b = bytearray(n)
        i2c.readfrom_into(GT_ADDR, b)
        return b
    finally:
        i2c.unlock()


def clear_status():
    while not i2c.try_lock():
        pass
    try:
        i2c.writeto(GT_ADDR, bytes([0x81, 0x4E, 0x00]))
    finally:
        i2c.unlock()


log("---- byte-dump diag — tap top-left, top-right, bottom-left, bottom-right ----")
log("(you have 30 seconds)")
was_pressed = False
start = time.monotonic()
while time.monotonic() - start < 30:
    s = rr(0x814E, 1)
    if s[0] & 0x80:
        n = s[0] & 0x0F
        if n > 0:
            p = rr(0x8150, 8)
            if not was_pressed:
                bytes_str = " ".join("0x{:02X}".format(b) for b in p)
                log("PRESS bytes=[" + bytes_str + "]")
            was_pressed = True
        else:
            if was_pressed:
                log("release")
            was_pressed = False
        clear_status()
    time.sleep(0.02)
log("---- done ----")
log_f.close()

# Run with: mpremote connect COM9 run scripts/touch_diag.py
# Tap each corner + the center; output is also written to /touch_log.txt
# so you don't have to copy/paste from the terminal.
import time
import board

GT_ADDR = 0x5D
SCREEN_W = 320
SCREEN_H = 240

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


def map_rot270_buggy(rx, ry):
    # Current production formula (the one we suspect is wrong).
    x = ry
    y = SCREEN_W - 1 - rx
    if x < 0: x = 0
    elif x >= SCREEN_W: x = SCREEN_W - 1
    if y < 0: y = 0
    elif y >= SCREEN_H: y = SCREEN_H - 1
    return x, y


def map_rot270_fixed(rx, ry):
    # Use panel's actual X max (240) for the flip instead of SCREEN_W.
    x = ry
    y = SCREEN_H - 1 - rx
    if x < 0: x = 0
    elif x >= SCREEN_W: x = SCREEN_W - 1
    if y < 0: y = 0
    elif y >= SCREEN_H: y = SCREEN_H - 1
    return x, y


log("---- touch diag: tap 5 spots (center, then each corner) ----")
log("each press logs raw + two candidate mappings.")
log("(running 30s — finish your taps before then)")

was_pressed = False
start = time.monotonic()
while time.monotonic() - start < 30:
    s = rr(0x814E, 1)
    if s[0] & 0x80:
        n = s[0] & 0x0F
        if n > 0:
            p = rr(0x8150, 8)
            rx = p[1] | (p[2] << 8)
            ry = p[3] | (p[4] << 8)
            if not was_pressed:
                bx, by = map_rot270_buggy(rx, ry)
                fx, fy = map_rot270_fixed(rx, ry)
                log("PRESS raw=({},{})  buggy=({},{})  fixed=({},{})"
                      .format(rx, ry, bx, by, fx, fy))
            was_pressed = True
        else:
            if was_pressed:
                log("release")
            was_pressed = False
        clear_status()
    time.sleep(0.02)
log("---- done ----")
log_f.close()

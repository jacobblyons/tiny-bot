import time, gc
from harness.ui.drivers import display
gc.collect()
d = display.get()

d.clear(display.BLACK)
d.fill_rect(0, 0, 320, 24, display.DARK_GRAY)
d.text("cc-esp32-harness", 6, 8, display.WHITE)
d.fill_rect(0, 224, 320, 16, display.DARK_GRAY)
d.show()

STATUS_Y = 100
STATUS_H = 14

def status(msg):
    d.fill_rect(0, STATUS_Y, 320, STATUS_H, display.BLACK)
    d.text(msg, 6, STATUS_Y + 3, display.WHITE)
    d.show_strip(STATUS_Y, STATUS_H)

print("--- production-context status updates ---")
messages = [
    "Booting...",
    "Mounting SD...",
    "Loading config...",
    "Connecting to MyVeryLongNetworkName...",
    "Got IP 192.168.1.123",
    "Ready.",
]
n = 6
for it in range(3):
    t0 = time.ticks_us()
    for m in messages:
        ts = time.ticks_us()
        status(m)
        print("  status (%s) = %.2f ms" % (m[:18], time.ticks_diff(time.ticks_us(), ts) / 1000))
    elapsed = time.ticks_diff(time.ticks_us(), t0) / 1000
    print("iter", it, "total:", elapsed, "ms (", elapsed / n, "ms/update)")

print("--- now alternative: copy slice instead of memoryview ---")
def status_copy(msg):
    d.fill_rect(0, STATUS_Y, 320, STATUS_H, display.BLACK)
    d.text(msg, 6, STATUS_Y + 3, display.WHITE)
    d._set_window(0, STATUS_Y, 319, STATUS_Y + STATUS_H - 1)
    d._dc(1)
    d._cs(0)
    start = STATUS_Y * 320 * 2
    end = (STATUS_Y + STATUS_H) * 320 * 2
    d._spi.write(d._buf[start:end])
    d._cs(1)

t0 = time.ticks_us()
for _ in range(3):
    for m in messages:
        status_copy(m)
elapsed = time.ticks_diff(time.ticks_us(), t0) / 1000
print("copy-slice 3x6:", elapsed, "ms (", elapsed / (3*n), "ms/update)")

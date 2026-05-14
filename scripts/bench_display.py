import time, gc
from harness.ui.drivers import display
gc.collect()
d = display.get()
d.clear(display.WHITE)
print("--- benchmark ---")
n = 20
t0 = time.ticks_ms()
for _ in range(n):
    d.show()
elapsed = time.ticks_diff(time.ticks_ms(), t0)
print("show() x", n, "->", elapsed, "ms total,", elapsed / n, "ms avg")
t0 = time.ticks_ms()
for _ in range(n):
    d.show_strip(60, 14)
elapsed = time.ticks_diff(time.ticks_ms(), t0)
print("show_strip(60,14) x", n, "->", elapsed, "ms total,", elapsed / n, "ms avg")
print("free:", gc.mem_free(), "alloc:", gc.mem_alloc())

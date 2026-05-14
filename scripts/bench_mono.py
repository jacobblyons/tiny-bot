import time, gc
from harness.ui.drivers import display
gc.collect()
d = display.get()

# Mixed content so framebuf ops aren't trivial
def fill_test_screen():
    d.fb.fill(0)
    for y in range(0, 240, 14):
        d.fb.text("Hello world line at y=%d" % y, 6, y, 1)

print("--- 1-bit framebuf benchmark ---")
fill_test_screen()
n = 20
t0 = time.ticks_ms()
for _ in range(n):
    d.show()
elapsed = time.ticks_diff(time.ticks_ms(), t0)
print("show() x%d -> %dms total, %.2fms avg" % (n, elapsed, elapsed/n))

t0 = time.ticks_ms()
for _ in range(n):
    d.show_strip(60, 14)
elapsed = time.ticks_diff(time.ticks_ms(), t0)
print("show_strip(60,14) x%d -> %dms total, %.2fms avg" % (n, elapsed, elapsed/n))

# typical UI update: clear strip + draw text + push strip
t0 = time.ticks_ms()
for i in range(n):
    d.fill_rect(0, 100, 320, 14, 0)
    d.text("Counter: %d" % i, 6, 103, 1)
    d.show_strip(100, 14)
elapsed = time.ticks_diff(time.ticks_ms(), t0)
print("typical strip update x%d -> %dms total, %.2fms avg" % (n, elapsed, elapsed/n))

# framebuf clear cost on its own
t0 = time.ticks_ms()
for _ in range(100):
    d.fb.fill(0)
elapsed = time.ticks_diff(time.ticks_ms(), t0)
print("fb.fill(0) x100 -> %dms total, %.3fms avg" % (elapsed, elapsed/100))

# fill_rect strip cost on its own
t0 = time.ticks_ms()
for _ in range(100):
    d.fill_rect(0, 100, 320, 14, 0)
elapsed = time.ticks_diff(time.ticks_ms(), t0)
print("fill_rect 320x14 x100 -> %dms total, %.3fms avg" % (elapsed, elapsed/100))

print("free:", gc.mem_free(), "alloc:", gc.mem_alloc())

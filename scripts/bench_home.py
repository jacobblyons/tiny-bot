import time, gc
gc.collect()

t = time.ticks_ms

start_total = t()

t0 = t()
from harness.ui.drivers import display
print("import display:", time.ticks_diff(t(), t0), "ms")

t0 = t()
from harness.ui.page import Page
print("import page:", time.ticks_diff(t(), t0), "ms")

t0 = t()
from harness.ui.framework import Label, AutoLayout, Position, Dimensions, Style, Direction, Align, Flex
print("import framework:", time.ticks_diff(t(), t0), "ms")

t0 = t()
d = display.get()
print("display.get():", time.ticks_diff(t(), t0), "ms")

t0 = t()
page = Page(d)
print("Page(d):", time.ticks_diff(t(), t0), "ms")

# Build layout
t0 = t()
body = AutoLayout(
    dimensions=Dimensions(320, 200),
    position=Position(0, 24),
    style=Style(direction=Direction.Vertical, margin=4, bg_color=None),
)
title_lbl = Label(
    "Booting",
    dimensions=Dimensions(width=320, height=40, flex=Flex.Locked),
    style=Style(font_size=32, font_color="green", bg_color="bg", align=Align.Center),
)
body.add_element(title_lbl)

status_lbl = Label(
    "Mounting SD...",
    dimensions=Dimensions(width=320, height=14, flex=Flex.Locked),
    style=Style(font_size=8, font_color="fg", bg_color="bg", align=Align.Start, padding=6),
)
body.add_element(status_lbl)

info_rows = []
for i in range(4):
    lbl = Label(
        "Info line %d" % i,
        dimensions=Dimensions(width=320, height=14, flex=Flex.Locked),
        style=Style(font_size=8, font_color="gray", bg_color="bg", align=Align.Start, padding=6),
    )
    body.add_element(lbl)
    info_rows.append(lbl)
print("build layout:", time.ticks_diff(t(), t0), "ms")

# Chrome
t0 = t()
d.clear(display.BLACK)
d.text("cc-esp32-harness", 6, 8, display.WHITE)
d.hline(0, 22, 320, display.WHITE)
d.hline(0, 224, 320, display.WHITE)
print("draw chrome (framebuf):", time.ticks_diff(t(), t0), "ms")

# Body draw — the framework path
t0 = t()
body.draw(page._draw)
print("body.draw() (framework, framebuf only):", time.ticks_diff(t(), t0), "ms")

# Full show
t0 = t()
d.show()
print("d.show():", time.ticks_diff(t(), t0), "ms")

print("--- total time:", time.ticks_diff(t(), start_total), "ms ---")

# Now stress test repeat
import gc
gc.collect()
print("\n--- repeat 5x to amortize JIT/cache effects ---")
for trial in range(5):
    t0 = t()
    d.clear(display.BLACK)
    d.text("cc-esp32-harness", 6, 8, display.WHITE)
    d.hline(0, 22, 320, display.WHITE)
    d.hline(0, 224, 320, display.WHITE)
    body.draw(page._draw)
    d.show()
    print("trial %d full render:" % trial, time.ticks_diff(t(), t0), "ms")

"""Game-friendly primitives layered over the bare engine.

Apps under /sd/apps/ frequently need three things the bare scene
contract doesn't make easy:

  - Frame-coherent input (held vs just-pressed, debounced)
  - 8-way trackball motion that handles diagonals cleanly
  - Quick text + shape draws without the verbose UI element imports

This package wraps those into thin classes / functions. Nothing
here is required — direct keyboard/trackball/displayio access still
works — but apps that opt in get sane defaults and avoid common
foot-guns.

Typical usage inside an app's Scene.OnUpdate:

    from engine.game import Buttons, Stick, Clock, text

    # in __init__ / OnStartup:
    self.btns = Buttons(self.kbd, bindings={
        ord('w'): 'up', ord('s'): 'down',
        ord('a'): 'left', ord('d'): 'right',
        ord(' '): 'fire',
    })
    self.stick = Stick(self.trackball)
    self.clock = Clock()

    # in OnUpdate(self, delta_time):
    dt = self.clock.tick()
    self.btns.update()
    if self.btns.pressed('fire'):
        self.shoot()
    if self.btns.down('up'):
        self.move(0, -1)
    motion = self.stick.read()
    self.cursor_x += motion['dx']
"""
from .input import Buttons, Stick
from .clock import Clock
from .draw import text, fill_rect, outline_rect

__all__ = ("Buttons", "Stick", "Clock", "text", "fill_rect", "outline_rect")

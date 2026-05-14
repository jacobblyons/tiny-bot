"""Built-in widgets that ship with the firmware.

User/agent-installed widgets live under /sd/widgets/ and are discovered
at home-scene startup. The names here are guaranteed to load even with
no SD card present.
"""
from .clock import Widget as ClockWidget
from .wifi import Widget as WifiWidget
from .mem import Widget as MemWidget
from .battery import Widget as BatteryWidget

BUILTIN_WIDGETS = (ClockWidget, WifiWidget, MemWidget, BatteryWidget)

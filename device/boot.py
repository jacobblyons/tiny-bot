import gc
import os
import storage

# Filesystem ownership toggle.
# - Default (no /.dev file): prod mode. Python owns the filesystem so the
#   wizard can save /config.json. The host sees CIRCUITPY as read-only.
# - With /.dev present: dev mode. Skip remount so the host can drag-drop
#   files onto CIRCUITPY for development.
#
# Toggle from the serial REPL while in prod mode:
#   open('/.dev', 'w').close()        # enable dev mode (need reset)
#   import os; os.remove('/.dev')     # back to prod (need reset)

DEV_FLAG = "/.dev"


def _has_flag():
    try:
        os.stat(DEV_FLAG)
        return True
    except OSError:
        return False


if not _has_flag():
    try:
        storage.remount("/", readonly=False)
    except RuntimeError:
        pass

gc.collect()

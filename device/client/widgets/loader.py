"""Discover and import widgets from /sd/widgets/.

Each user widget is a single .py file under WIDGETS_DIR exposing a class
named `Widget` with the same shape as a built-in. Bad imports are
swallowed and logged — one broken file shouldn't hide the rest.
"""
import os
import sys

from client.widgets import BUILTIN_WIDGETS

WIDGETS_DIR = "/sd/widgets"


def _add_to_path():
    if WIDGETS_DIR not in sys.path:
        sys.path.insert(0, WIDGETS_DIR)


def _discover_user():
    names = []
    try:
        for entry in os.listdir(WIDGETS_DIR):
            if entry.endswith(".py") and not entry.startswith("_"):
                names.append(entry[:-3])
    except OSError:
        # No widgets directory yet — fine, we'll just use builtins.
        return []
    return sorted(names)


def load_all(app):
    """Return a list of instantiated widgets: builtins first, then user.

    Failures are logged and skipped so a typo'd widget file can't keep
    home from rendering.
    """
    _add_to_path()
    widgets = []
    for cls in BUILTIN_WIDGETS:
        try:
            widgets.append(cls(app))
        except Exception as e:
            print("builtin widget failed:", cls.__name__, e)

    for name in _discover_user():
        # Drop any cached version so edits re-import. The agent rewrites
        # widget files in place, so we never want the stale module.
        if name in sys.modules:
            del sys.modules[name]
        try:
            mod = __import__(name)
            cls = getattr(mod, "Widget", None)
            if cls is None:
                print("widget", name, "has no Widget class")
                continue
            widgets.append(cls(app))
        except Exception as e:
            print("widget", name, "failed:", e)
    return widgets

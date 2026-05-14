"""AppState — simple per-app key/value store with two scopes.

`session` scope holds RAM-only state that survives navigation
between scenes within a single boot. Use it for "where was I?"
data like a half-finished snake game or the cursor position in a
text viewer. State here vanishes on power-cycle, restart_runtime,
or hard_reset.

`persistent` scope writes to a JSON file under /sd/state/<name>.json.
Use it for data the user expects to keep across reboots: todo
lists, high scores, completed achievements, user-tuned settings
the agent persisted on the user's behalf.

Apps usually want both: session for in-flight game state, persistent
for the score table. Each AppState instance is scoped to one name
(typically the app filename) and one scope.

Contract:
  - `get(key, default)` and `set(key, value)` mirror dict semantics
  - session-scope sets are RAM-write-through (no save needed)
  - persistent-scope sets stay in RAM until `save()` is called
    (writes to flash are slow; the app decides when to flush)
  - `save()` is atomic for persistent (tmp file + rename) so a
    crash mid-write can't corrupt the existing JSON

Example:

    from engine.persistence import AppState

    class Scene:
        def __init__(self, app):
            self.app = app
            # Mid-game state — survives chat/menu detours
            self.session = AppState(app, "snake", AppState.SESSION)
            # Long-term — survives reboots
            self.persistent = AppState(app, "snake", AppState.PERSISTENT)

        def OnStartup(self):
            self.x = self.session.get("x", 160)
            self.y = self.session.get("y", 120)
            self.high_score = self.persistent.get("high_score", 0)

        def OnShutdown(self):
            self.session.set("x", self.x)
            self.session.set("y", self.y)
            # session writes are immediate — no save() needed

        def game_over(self, score):
            if score > self.high_score:
                self.persistent.set("high_score", score)
                self.persistent.save()  # flush to /sd/state/snake.json
"""
import json
import os


PERSISTENT_DIR = "/sd/state"


class AppState:
    SESSION = "session"
    PERSISTENT = "persistent"

    def __init__(self, app, name, scope=SESSION):
        if not isinstance(name, str) or not name:
            raise ValueError("AppState name must be a non-empty string")
        if "/" in name or name.startswith("."):
            raise ValueError("AppState name can't contain '/' or start with '.'")
        if scope not in (self.SESSION, self.PERSISTENT):
            raise ValueError("scope must be 'session' or 'persistent'")
        self._app = app
        self._name = name
        self._scope = scope
        self._data = self._load()

    # ---- internal ---------------------------------------------------------

    def _persistent_path(self):
        return "{}/{}.json".format(PERSISTENT_DIR, self._name)

    def _ensure_dir(self):
        try:
            os.stat(PERSISTENT_DIR)
        except OSError:
            try:
                os.mkdir(PERSISTENT_DIR)
            except OSError:
                # Either parent doesn't exist (no SD card) or the
                # dir already does. Both are fine for our purposes —
                # the open() below will surface a real problem.
                pass

    def _load(self):
        if self._scope == self.SESSION:
            store = getattr(self._app, "_session_state", None)
            if store is None:
                store = {}
                self._app._session_state = store
            if self._name not in store:
                store[self._name] = {}
            # Return the in-store dict by reference so mutations
            # propagate without us having to copy on every set().
            return store[self._name]
        # persistent
        try:
            with open(self._persistent_path(), "r") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                return loaded
            return {}
        except (OSError, ValueError):
            return {}

    # ---- public api -------------------------------------------------------

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        """Stash value under key. Session writes are visible
        immediately (the store dict is shared by reference);
        persistent writes stay in RAM until save() is called."""
        self._data[key] = value

    def delete(self, key):
        """Remove a key. Returns True if it existed, False if not."""
        if key in self._data:
            del self._data[key]
            return True
        return False

    def clear(self):
        """Wipe all keys for this AppState instance. For persistent
        scope this also deletes the on-disk file."""
        self._data.clear()
        if self._scope == self.PERSISTENT:
            try:
                os.remove(self._persistent_path())
            except OSError:
                pass

    def save(self):
        """Flush state to its backing store.

        Session is already write-through, so this is a no-op there
        (returns True for API symmetry).

        Persistent writes through a tmp file + rename so a crash
        mid-write can't half-clobber the existing JSON. Returns
        False on failure with an error printed to REPL.
        """
        if self._scope == self.SESSION:
            return True
        self._ensure_dir()
        path = self._persistent_path()
        tmp = path + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(self._data, f)
            os.rename(tmp, path)
            return True
        except (OSError, ValueError) as e:
            print("AppState save failed for", self._name, ":", e)
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False

    def keys(self):
        return list(self._data.keys())

    def as_dict(self):
        """Snapshot of current state. Returned dict is a copy —
        mutating it does NOT mutate the AppState."""
        return dict(self._data)

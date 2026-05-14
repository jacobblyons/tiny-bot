import gc
import os
import sys
import time
import board
import displayio

from engine.application import IApp

from client import config
from client.services.bot import BotService, init_colors as bot_init_colors
from engine.tdeck import TDeckKeyboard
from client.scenes.boot_wizard_scene import BootWizardScene
from client.scenes.bot_scene import BotScene
from client.scenes.config_scene import ConfigScene
from client.scenes.error_scene import ErrorScene
from client.scenes.home_scene import HomeScene
from client.scenes.splash_scene import SplashScene
from client.scenes.system_scene import SystemScene
from client.views import chrome_view
from client.views import BotBubble
from client.views.theme import (
    BG_MAIN, BG_SURFACE, BORDER,
    TEXT_PRIMARY, TEXT_DIM, ACCENT, SUCCESS, WARN,
)

APPS_DIR = "/sd/apps"

NANOSECONDS_PER_SECOND = 1_000_000_000

# Paths the App owns at boot. The bot session is preserved across an
# agent-triggered restart_runtime / hard_reset via a marker file —
# without that marker we treat the on-disk session as stale and wipe
# it, so a cold boot or power-cycle starts with a fresh chat instead
# of resurrecting whatever conversation happened to be on disk last.
SESSION_PATH = "/session.jsonl"
SESSION_RESUME_MARKER = "/session.marker"

# Scenes where the always-on-top [bot] bubble shouldn't appear:
#   - bot itself (would be tapping the bubble to open the bot)
#   - home (has its own inline input bar; bubble would be redundant)
#   - wizard/splash (pre-login flows where the agent isn't usable)
#   - error (its own modal-like recovery flow with explicit buttons)
_NO_BUBBLE_SCENES = ("bot", "home", "wizard", "splash", "error")


# ---- input filter -----------------------------------------------------------

_EMPTY_TOUCH = {"pressed": False, "click": False, "release": False,
                "x": None, "y": None}


class _FilteredTouch:
    """One-event-per-frame caching wrapper around the GT911 driver.

    Why: the App.Run loop needs to peek at touch events BEFORE the
    scene's OnUpdate runs, so it can intercept taps on the always-on-
    top [bot] bubble. The raw driver consumes edge state on each
    read(), so a naive "App reads then scene reads" pattern would
    have the scene miss the click edge.

    Lifecycle: App.Run calls begin_frame() at the top of each tick,
    which reads the raw driver once and caches the result. The App
    then peeks / consumes as needed; whatever's left in the cache
    is what the scene's `read()` returns. After the frame, the
    cache is cleared by the next begin_frame().
    """

    def __init__(self, raw):
        self._raw = raw
        self._cached = None
        self._used = False

    @property
    def available(self):
        return self._cached is not None and not self._used

    def begin_frame(self):
        if hasattr(self._raw, "available") and not self._raw.available:
            self._cached = None
        else:
            try:
                self._cached = self._raw.read()
            except Exception:
                self._cached = None
        self._used = False

    def peek(self):
        return None if self._used else self._cached

    def consume(self):
        self._used = True

    def read(self):
        if self._used or self._cached is None:
            return _EMPTY_TOUCH
        self._used = True
        return self._cached


class _NullTouch:
    """Stand-in when the GT911 isn't reachable so scenes don't have
    to branch on touch availability."""
    available = False

    def read(self):
        return dict(_EMPTY_TOUCH)


class BatchDisplayUpdate:
    def __init__(self, the_display):
        self.the_display = the_display
        self.auto_refresh = the_display.auto_refresh

    def __enter__(self):
        self.the_display.auto_refresh = False

    def __exit__(self, *unused):
        self.the_display.refresh()
        self.the_display.auto_refresh = self.auto_refresh


class App(IApp):
    def __init__(self):
        # CircuitPython auto-reload restarts code.py whenever the
        # filesystem changes. The agent uses restart_runtime for
        # explicit reloads instead so it can coordinate scene state.
        import supervisor
        supervisor.runtime.autoreload = False

        # Session preserve / wipe based on marker (set by BotService
        # before agent-triggered restart). Without the marker, an
        # old conversation would resurrect on every cold boot.
        keep_session = False
        try:
            os.stat(SESSION_RESUME_MARKER)
            keep_session = True
            os.remove(SESSION_RESUME_MARKER)
        except OSError:
            pass
        if not keep_session:
            try:
                os.remove(SESSION_PATH)
            except OSError:
                pass

        self._scene_change_pending = False
        self._pending_scene_name = None

        self.display = board.DISPLAY
        self.keyboard = TDeckKeyboard()
        self.trackball = None
        self._raw_touch = None
        self.touch = None
        self.cursor = None
        self.pointer = None

        self.cfg = config.load() if config.exists() else None

        if self.cfg and self.cfg["wifi"]["ssid"]:
            try:
                from engine import wifi_helper
                wifi_helper.connect(
                    self.cfg["wifi"]["ssid"],
                    self.cfg["wifi"]["password"],
                    timeout_s=15,
                )
            except Exception as e:
                print("wifi auto-connect failed:", e)

        # Make /sd/apps importable so dynamically-loaded apps can
        # `import` their own helpers and the engine modules.
        if APPS_DIR not in sys.path:
            sys.path.insert(0, APPS_DIR)

        # Firmware scenes. "bot" is a real scene again — back to the
        # pre-overlay isolation model so an app crash can't take the
        # chat down with it.
        self._scenes = {
            "wizard": BootWizardScene,
            "splash": SplashScene,
            "home": HomeScene,
            "bot": BotScene,
            "config": ConfigScene,
            "system": SystemScene,
            "error": ErrorScene,
        }
        # Cross-scene communication slots.
        self.pending_error = None
        self.pending_bot_prompt = None
        # When the user taps [<] in the bot scene, where to go back to.
        # Set by SwitchScene("bot") before constructing the bot scene.
        self.bot_return_target = None
        # Reference to the displayio group of the scene that launched
        # the bot, used by snapshot_scene so the agent can dump what
        # was on screen when the user opened it. Stashed alongside
        # bot_return_target.
        self.bot_previous_group = None
        # ChromeView's "home" back redirects here when set (e.g.
        # apps launched from the bot get back-buttoned to the bot).
        self.app_return_target = None
        # Persistent bot session cache (RAM).
        self.bot_session = None
        # Session state for AppState(SESSION) — apps stash mid-run
        # state here, keyed by app name. Persists across scene
        # navigation, lost on power cycle.
        self._session_state = {}

        chrome_view.set_app(self)
        self._scene_history = []

        # Bootstrap input drivers before constructing the scene so
        # the scene's __init__ can ask for them.
        self.GetTouch()
        self.GetTrackball()

        # Bot service. The bot scene reads turns from here; the
        # service outlives any individual bot scene instance so
        # conversation state survives [<] back -> reopen.
        bot_init_colors(
            primary=TEXT_PRIMARY, dim=TEXT_DIM,
            accent=ACCENT, warn=WARN, success=SUCCESS,
        )
        self.bot = BotService(self, wrap_width=50)
        self._theme = {
            "bg_main": BG_MAIN, "bg_surface": BG_SURFACE,
            "border": BORDER,
            "text_primary": TEXT_PRIMARY, "text_dim": TEXT_DIM,
            "accent": ACCENT, "warn": WARN, "success": SUCCESS,
        }
        self._bot_bubble = BotBubble(self._theme)

        # Composite group: [scene, bubble] — last child draws on top.
        # The bot bubble is always-on-top; scene swap is a single
        # .pop / .insert at index 0 of the composite.
        self._composite = displayio.Group()
        # Bootstrap scene.
        initial = "splash" if config.is_configured(self.cfg) else "wizard"
        self.scene = self._scenes[initial](self)
        self._current_scene_name = initial
        self._composite.append(self.scene.GetRootGroup())
        self._composite.append(self._bot_bubble.group)
        self.display.root_group = self._composite

    # ---- driver getters ---------------------------------------------------

    def GetKeyboard(self):
        return self.keyboard

    def GetTrackball(self):
        if self.trackball is None:
            from engine.tdeck import TDeckTrackball
            self.trackball = TDeckTrackball()
        return self.trackball

    def GetTouch(self):
        if self.touch is None:
            from engine.tdeck import TDeckTouch
            try:
                self._raw_touch = TDeckTouch()
            except Exception as e:
                print("touch init failed:", e)
                self._raw_touch = _NullTouch()
            self.touch = _FilteredTouch(self._raw_touch)
        return self.touch

    def GetRawTouch(self):
        """Return the unfiltered GT911 driver. Used by code paths
        that run outside the App.Run frame loop (e.g. the bot's
        rate-limit countdown) where the filter's begin_frame() isn't
        being driven."""
        self.GetTouch()  # ensure init
        return self._raw_touch

    def GetCursor(self, root_group=None, color=None):
        from engine.display.cursor import Cursor
        if color is None:
            color = ACCENT.value
        if self.cursor is None:
            self.cursor = Cursor(root_group or self.scene.GetRootGroup(),
                                 color=color)
        elif root_group is not None:
            self.cursor.reattach(root_group)
        return self.cursor

    def GetPointer(self, root_group=None):
        from engine.display.cursor import Pointer
        cursor = self.GetCursor(root_group)
        if self.pointer is None:
            self.pointer = Pointer(cursor,
                                   touch=self.GetTouch(),
                                   trackball=self.GetTrackball())
        return self.pointer

    # ---- scene management ------------------------------------------------

    def SwitchScene(self, scene_name):
        """Switch to a named scene. When the target is "bot", we stash
        the current scene name as the bot's return target AND grab a
        reference to the current scene's group for snapshot_scene
        (since the scene is torn down on transition)."""
        if scene_name == "chat":
            # Legacy alias.
            scene_name = "bot"
        if scene_name not in self._scenes:
            raise ValueError("unknown scene: " + scene_name)
        if scene_name == "bot" and self._current_scene_name != "bot":
            self.bot_return_target = self._current_scene_name
            try:
                self.bot_previous_group = self.scene.GetRootGroup()
            except Exception:
                self.bot_previous_group = None
        self._pending_scene_name = scene_name
        self._scene_change_pending = True

    RESERVED_SCENES = ("config", "system",
                       "home", "splash", "wizard", "error", "bot")

    def RegisterScene(self, scene_name, scene_class):
        if scene_name in self.RESERVED_SCENES:
            raise ValueError(
                "scene '" + scene_name + "' is firmware-reserved")
        self._scenes[scene_name] = scene_class

    def GoBack(self):
        if self._scene_history:
            self.SwitchScene(self._scene_history.pop())

    def _mount_scene(self):
        """Swap composite's bottom layer to the active scene's group.
        Idempotent — safe to call when the scene hasn't changed."""
        scene_group = self.scene.GetRootGroup()
        if len(self._composite) > 0 and self._composite[0] is scene_group:
            return
        try:
            self._composite.pop(0)
        except (IndexError, Exception):
            pass
        self._composite.insert(0, scene_group)

    def _update_bubble_visibility(self):
        """Bubble shows everywhere except the no-bubble scenes."""
        if self._current_scene_name in _NO_BUBBLE_SCENES:
            self._bot_bubble.hide()
        else:
            self._bot_bubble.show()

    # ---- error capture ---------------------------------------------------

    def _capture_error(self, e, where):
        import io
        import traceback
        print("scene error in", where, ":", e)
        buf = io.StringIO()
        try:
            traceback.print_exception(type(e), e,
                                      getattr(e, "__traceback__", None),
                                      file=buf)
        except Exception:
            buf.write(repr(e))
        tb_str = buf.getvalue()
        if len(tb_str) > 2048:
            tb_str = "...\n" + tb_str[-2000:]
        self.pending_error = {
            "where": (self._current_scene_name or "?") + ":" + where,
            "type": type(e).__name__,
            "message": str(e)[:200],
            "traceback": tb_str,
        }

    # ---- main loop --------------------------------------------------------

    def Run(self):
        error_loop_count = 0
        while True:
            try:
                self._mount_scene()
                self._update_bubble_visibility()
                with BatchDisplayUpdate(self.display):
                    self.scene.OnStartup()

                last_ns = time.monotonic_ns()
                while not self._scene_change_pending:
                    now_ns = time.monotonic_ns()
                    delta = (now_ns - last_ns) / NANOSECONDS_PER_SECOND
                    last_ns = now_ns

                    # Read inputs for the frame.
                    self.touch.begin_frame()
                    touch_ev = self.touch.peek()

                    # Refresh the active chrome's status zone every
                    # frame; chrome internally throttles repaint.
                    chrome_view.tick_active()

                    # Bubble preempts taps in its hit zone on scenes
                    # where it's visible.
                    if (touch_ev and touch_ev["click"]
                            and self._bot_bubble.visible
                            and self._bot_bubble.hit(
                                touch_ev["x"], touch_ev["y"])):
                        self.touch.consume()
                        self.SwitchScene("bot")
                    else:
                        self.scene.OnUpdate(delta)
                        self.scene.OnDraw()

                # Normal transition.
                try:
                    self.scene.OnShutdown()
                except Exception as e:
                    print("OnShutdown error:", e)

                self._scene_history.append(self._current_scene_name)
                if len(self._scene_history) > 16:
                    self._scene_history = self._scene_history[-16:]
                target = self._pending_scene_name
                self._pending_scene_name = None
                self._scene_change_pending = False
                self._current_scene_name = target
                self.scene = self._scenes[target](self)
                error_loop_count = 0
                gc.collect()

            except Exception as e:
                error_loop_count += 1
                if error_loop_count > 3:
                    print("FATAL: error recovery itself crashed; halting")
                    print("mem:", gc.mem_free())
                    return
                self._capture_error(e, "scene")
                try:
                    self.scene.OnShutdown()
                except Exception:
                    pass
                try:
                    self.scene = ErrorScene(self)
                    self._current_scene_name = "error"
                    self._pending_scene_name = None
                    self._scene_change_pending = False
                except Exception as e2:
                    print("FATAL: error scene constructor failed:", e2)
                    return
                gc.collect()

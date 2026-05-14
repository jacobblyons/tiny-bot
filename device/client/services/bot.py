"""BotService — persistent agent conversation owned by the App.

The bot lives as its own scene now (BotScene), but the conversation
state itself is service-owned so it survives scene transitions. When
the user launches an app from inside the bot, then comes back to the
bot, the previous turns are still here.

Owned state:
  - api_messages: the canonical message list sent to Anthropic
  - turns:         the per-exchange Turn objects the bot scene renders
  - system prompt, model, provider, api key

Also handles persistence (RAM cache + on-disk session file) and
context trimming. The UI (BotScene, BotInputBar) reads state from
here; it doesn't store any of it.

send() is the entry point for "user typed a message; run a turn".
It blocks until the agent loop completes. The caller passes a
`notify` callback that's invoked after every state mutation so the
scene can re-render. Network logic stays in this file, separate
from displayio.
"""
import gc
import json
import time

from engine.display.ui.models import Color
from engine.llm import anthropic, tools


SESSION_PATH = "/session.jsonl"
SESSION_MARKER = "/session.marker"

# Per-tool-result cap. Sized to comfortably fit a 12 KB read_file
# chunk plus line-number metadata.
MAX_TOOL_RESULT_BYTES = 16384

# Context-trim thresholds. The compactor folds stale write_file
# content / tool_result payloads into placeholders once the turn
# they belong to is no longer "live"; if that still leaves the
# message list over the hard cap, oldest user/assistant pairs get
# dropped.
COMPACT_PAYLOAD_MIN_BYTES = 200
HARD_TRIM_THRESHOLD_BYTES = 32 * 1024


SYSTEM_PROMPT = (
    "You are an agent running on a LilyGo T-Deck handheld terminal. Screen: "
    "320x240, touch + tiny QWERTY + trackball (no ESC key). You can read "
    "and modify the device's own code, write new apps and widgets, and "
    "reload the runtime to make changes take effect.\n\n"
    "You run as the 'bot' scene. The user reaches you by typing in the "
    "home scene's input bar, by tapping the floating [bot] bubble from "
    "any non-home scene, or via the error scene's 'ask bot to fix' "
    "button. When the bot scene closes (the [<] back button), the user "
    "returns to whichever scene launched the bot — the back target is "
    "stashed on App.bot_return_target. Because the bot is its own scene "
    "(not an overlay), the previously-running app is shut down when the "
    "user opens the bot; if you need to inspect what was on screen, call "
    "snapshot_scene which reads the stashed previous scene's group.\n\n"
    "Ownership boundary — important:\n"
    "  /client/, /engine/, /lib/     FIRMWARE territory. Pushes from the "
    "host overwrite anything here, so user-facing features you add belong "
    "in /sd/, not here. Only edit firmware files when fixing the firmware "
    "itself. The bot scene's runtime is in /client/ — editing those files "
    "while the bot is running risks bricking the chat, so if you must "
    "touch /client/ or /engine/, write the file then call restart_runtime "
    "in the SAME turn.\n"
    "  /sd/apps/, /sd/widgets/       AGENT territory. Your apps and widgets "
    "live here and survive firmware updates.\n"
    "  /code.py, /boot.py, /config.json, /.dev   protected, never write\n\n"
    "Reserved built-in scene names (do NOT overwrite, do NOT create apps "
    "with these names): config, system, home, splash, wizard, error, bot.\n\n"
    "Game primitives in engine.game — USE THESE when writing apps that "
    "need input or rendering: `Buttons`, `Stick`, `Clock`, plus "
    "`text` / `fill_rect` / `outline_rect` drawing helpers.\n\n"
    "Per-app state: engine.persistence.AppState gives apps a clean way to "
    "stash state. Two scopes:\n"
    "  AppState.SESSION    in-RAM, survives scene navigation but lost on "
    "reboot. Use for mid-game state (player position, current level, "
    "half-finished input) so the user can detour to chat and come back "
    "without losing progress.\n"
    "  AppState.PERSISTENT writes JSON to /sd/state/<name>.json with "
    "atomic tmp+rename. Use for data the user expects across reboots: "
    "high scores, todo lists, completed achievements, tuned settings.\n"
    "Apps usually want BOTH: session for in-flight state, persistent for "
    "the long-term store. See the docstring of engine/persistence.py for "
    "a snake-game example. Not every app needs SESSION — a stateless "
    "viewer is fine without it.\n\n"
    "App contract: a file at /sd/apps/<name>.py defining `class Scene` "
    "that implements IScene. The floating [bot] bubble (always-on-top "
    "button) is injected automatically by the App on non-home scenes — "
    "don't draw your own; just don't occupy the bottom-right 40x40 px "
    "or it'll sit under the bubble.\n\n"
    "Home carousel order: the launcher reads /sd/state/apps_order.json "
    "for a custom display order. Use the reorder_apps tool to change "
    "it (pass the full ordered list). Both built-in scenes (config, "
    "system) and /sd/apps/ items can be reordered — listed names "
    "appear first in the given sequence; unlisted entries fall "
    "through to the natural default (built-ins first, then apps "
    "alpha), so freshly-installed apps never disappear. The carousel "
    "auto-locks (greyed, unclickable) while you're mid-turn so the "
    "user can't accidentally launch on top of a running send.\n\n"
    "Widget contract: a file at /sd/widgets/<name>.py defining `class "
    "Widget` with build(group, x, y, w, h). Cell height varies — position "
    "content relative to the given (w, h).\n\n"
    "Working with files: read_file returns a header and numbered lines, "
    "default cap 12 KB. Use start_line/end_line for narrower windows. "
    "grep / find / stat_path are cheaper for navigation than speculative "
    "reads.\n\n"
    "snapshot_scene captures the scene that launched the bot (stashed in "
    "App.bot_previous_group). Pass format='image' for a 160x120 GIF, "
    "default is a text tree dump.\n\n"
    "run_code execs Python in the live runtime with `app`, `gc`, `os`, "
    "`sys` pre-bound. Captures stdout and returns it.\n\n"
    "After editing /client/ or /engine/ files, call restart_runtime. "
    "After editing /boot.py, call hard_reset.\n\n"
    "Before each tool call, say WHY in one short sentence. Keep prose "
    "concise (under 100 words) and avoid markdown."
)


# ---- helpers ---------------------------------------------------------------

def _wrap(text, width):
    """Greedy word-wrap. Returns list of strings (no newlines)."""
    out = []
    for para in text.split("\n"):
        if not para:
            out.append("")
            continue
        cur = ""
        for word in para.split(" "):
            while len(word) > width:
                if cur:
                    out.append(cur); cur = ""
                out.append(word[:width])
                word = word[width:]
            if not cur:
                cur = word
            elif len(cur) + 1 + len(word) <= width:
                cur = cur + " " + word
            else:
                out.append(cur); cur = word
        if cur:
            out.append(cur)
    return out


def _format_tool_list(names):
    if not names:
        return "no tools"
    counts = {}
    order = []
    for n in names:
        if n not in counts:
            order.append(n)
        counts[n] = counts.get(n, 0) + 1
    parts = []
    for n in order:
        c = counts[n]
        parts.append("{} x{}".format(n, c) if c > 1 else n)
    return "{} tools: {}".format(len(names), ", ".join(parts))


# ---- Turn ------------------------------------------------------------------

class Turn:
    """One user-assistant exchange.

    The bot scene slices `entries` for summary / detail rendering and
    consults `status` + `current_tool` for the status line.
    """
    KIND_USER = "user"
    KIND_SYSTEM = "system"

    STATUS_OPEN = "open"
    STATUS_THINKING = "thinking"
    STATUS_RUNNING = "running"
    STATUS_DONE = "done"
    STATUS_ERROR = "error"
    STATUS_INTERRUPTED = "interrupted"

    def __init__(self, index, kind="user", started_at=None, label=""):
        self.index = index
        self.kind = kind
        self.started_at = (started_at if started_at is not None
                           else time.monotonic())
        self.ended_at = None
        self.label = label
        self.entries = []         # list of (Color, text)
        self.tools_called = []    # list of tool name strings
        self.current_tool = None
        self.status = self.STATUS_OPEN

    def add_entry(self, color, text, wrap_width):
        for line in _wrap(text, wrap_width):
            self.entries.append((color, line))

    def elapsed_s(self):
        end = self.ended_at if self.ended_at is not None else time.monotonic()
        dt = end - self.started_at
        return dt if dt > 0 else 0.0

    def to_json(self):
        return {
            "index": self.index,
            "kind": self.kind,
            "label": self.label,
            "entries": [[(c.value if hasattr(c, "value") else int(c)), t]
                        for (c, t) in self.entries],
            "tools_called": list(self.tools_called),
            "status": self.status,
        }

    @classmethod
    def from_json(cls, data):
        t = cls(
            int(data.get("index", 0)),
            kind=data.get("kind", cls.KIND_USER),
            started_at=0,
            label=data.get("label", ""),
        )
        t.ended_at = 0
        for entry in data.get("entries", []):
            try:
                cv, text = entry[0], entry[1]
                t.entries.append((Color(hex=int(cv)), str(text)))
            except (TypeError, ValueError):
                continue
        t.tools_called = list(data.get("tools_called", []))
        t.status = data.get("status", cls.STATUS_DONE)
        return t


# ---- BotService ------------------------------------------------------------

class BotService:
    """Live conversation state + agent runner.

    The notify callback is invoked any time something changes that
    a UI consumer would care about (turn added, entry appended,
    status flipped, tool started). Pass a function in the
    constructor, or call `set_notify()` later.
    """

    def __init__(self, app, wrap_width=50, notify=None):
        self.app = app
        self.wrap_width = wrap_width
        self._notify = notify or (lambda: None)
        cfg = app.cfg or {}
        agent = cfg.get("agent", {})
        provider = agent.get("provider", "claude")
        providers = cfg.get("providers", {})
        self._api_key = providers.get(provider, {}).get("api_key", "")
        self._model = agent.get("model", "claude-opus-4-7")
        self._provider = provider

        self.api_messages = []
        self.turns = []
        self._restore_session()

    # ---- notification ------------------------------------------------------

    def set_notify(self, fn):
        self._notify = fn or (lambda: None)

    def _changed(self):
        try:
            self._notify()
        except Exception as e:
            # Notify failures shouldn't crash the bot — bubble up via
            # print so the user can see it in REPL but the agent loop
            # keeps running.
            print("bot notify failed:", e)

    # ---- turn management ---------------------------------------------------

    def open_system_turn(self, label="system"):
        if self.turns and self.turns[-1].kind == Turn.KIND_SYSTEM:
            return self.turns[-1]
        idx = len(self.turns)
        t = Turn(idx, kind=Turn.KIND_SYSTEM, label=label)
        self.turns.append(t)
        self._changed()
        return t

    def open_user_turn(self, user_text):
        idx = len(self.turns)
        label = user_text if len(user_text) <= 40 else user_text[:37] + "..."
        t = Turn(idx, kind=Turn.KIND_USER, label=label)
        t.add_entry(_COLOR_ACCENT, "> " + user_text, self.wrap_width)
        t.status = Turn.STATUS_THINKING
        self.turns.append(t)
        self._changed()
        return t

    def current_turn(self):
        if not self.turns:
            self.open_system_turn()
        return self.turns[-1]

    def log(self, color, text):
        self.current_turn().add_entry(color, text, self.wrap_width)
        self._changed()

    def close_current_turn(self, status=Turn.STATUS_DONE):
        t = self.current_turn()
        t.status = status
        t.ended_at = time.monotonic()
        t.current_tool = None
        self._changed()

    def has_user_turns(self):
        """Used by home to decide between idle (logo) and engaged
        (response pane) layouts."""
        for t in self.turns:
            if t.kind == Turn.KIND_USER:
                return True
        return False

    def last_user_turn(self):
        """Most recent user-kind turn, or None. Home's response pane
        only shows user turns — system-kind boot/reset turns aren't
        interesting on the home preview."""
        for t in reversed(self.turns):
            if t.kind == Turn.KIND_USER:
                return t
        return None

    # ---- session persistence ----------------------------------------------

    def _restore_session(self):
        cached = getattr(self.app, "bot_session", None)
        snapshot = cached if cached is not None else self._load_from_disk()
        if snapshot is None:
            return
        msgs = snapshot.get("messages")
        if isinstance(msgs, list):
            self.api_messages = msgs
        raw_turns = snapshot.get("turns")
        if isinstance(raw_turns, list) and raw_turns:
            self.turns = [Turn.from_json(d) for d in raw_turns]
        else:
            # Legacy shape: flat log → fold into a single "legacy"
            # system turn so resumed sessions still render.
            raw_log = snapshot.get("log")
            if isinstance(raw_log, list) and raw_log:
                t = Turn(0, kind=Turn.KIND_SYSTEM, label="legacy")
                t.ended_at = 0
                t.status = Turn.STATUS_DONE
                for entry in raw_log:
                    try:
                        cv, text = entry[0], entry[1]
                        t.entries.append((Color(hex=int(cv)), str(text)))
                    except (TypeError, ValueError):
                        continue
                self.turns = [t]

    def _load_from_disk(self):
        try:
            with open(SESSION_PATH, "r") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _normalize_messages(self):
        """Patch dangling tool_use blocks so resume doesn't 400."""
        if not self.api_messages:
            return
        last = self.api_messages[-1]
        if last.get("role") != "assistant":
            return
        content = last.get("content")
        if not isinstance(content, list):
            return
        pending = [b.get("id") for b in content
                   if b.get("type") == "tool_use" and b.get("id")]
        if not pending:
            return
        results = [
            {"type": "tool_result", "tool_use_id": tid,
             "content": "[interrupted by device reset]"}
            for tid in pending
        ]
        self.api_messages.append({"role": "user", "content": results})

    def save_session(self, persist_to_disk=False):
        self._normalize_messages()
        snapshot = {
            "messages": self.api_messages,
            "turns": [t.to_json() for t in self.turns],
        }
        self.app.bot_session = snapshot
        if persist_to_disk:
            try:
                with open(SESSION_PATH, "w") as f:
                    json.dump(snapshot, f)
            except Exception as e:
                print("session save failed:", e)

    def reset(self):
        self.api_messages = []
        self.turns = []
        self.app.bot_session = None
        try:
            import os
            os.remove(SESSION_PATH)
        except OSError:
            pass
        self.open_system_turn(label="reset")
        self.log(_COLOR_DIM, "[ session reset ]")
        self.log(_COLOR_DIM, "[ agent ready :: {} tools ]".format(
            len(tools.TOOL_SPECS)))
        self.close_current_turn()

    # ---- context trim helpers ---------------------------------------------

    def estimate_context_bytes(self):
        total = 0
        for msg in self.api_messages:
            c = msg.get("content")
            if isinstance(c, str):
                total += len(c)
            elif isinstance(c, list):
                for block in c:
                    bt = block.get("type")
                    if bt == "text":
                        total += len(block.get("text", ""))
                    elif bt == "tool_use":
                        inp = block.get("input", {})
                        for k, v in inp.items():
                            total += len(str(k))
                            total += len(str(v))
                    elif bt == "tool_result":
                        rc = block.get("content")
                        if isinstance(rc, str):
                            total += len(rc)
                        elif isinstance(rc, list):
                            for b in rc:
                                bt2 = b.get("type")
                                if bt2 == "text":
                                    total += len(b.get("text", ""))
                                elif bt2 == "image":
                                    src = b.get("source", {})
                                    total += len(src.get("data", ""))
        return total

    def _compact_history(self):
        if len(self.api_messages) < 4:
            return 0
        boundary = 0
        for i in range(len(self.api_messages) - 1, -1, -1):
            m = self.api_messages[i]
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                boundary = i
                break
        saved = 0
        for msg in self.api_messages[:boundary]:
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                bt = block.get("type")
                if bt == "tool_use":
                    inp = block.get("input")
                    if not isinstance(inp, dict):
                        continue
                    body = inp.get("content")
                    if (isinstance(body, str)
                            and len(body) > COMPACT_PAYLOAD_MIN_BYTES):
                        placeholder = "[elided {} bytes; written to {}]".format(
                            len(body), inp.get("path", "?"))
                        saved += len(body) - len(placeholder)
                        inp["content"] = placeholder
                elif bt == "tool_result":
                    rc = block.get("content")
                    if (isinstance(rc, str)
                            and len(rc) > COMPACT_PAYLOAD_MIN_BYTES):
                        placeholder = "[elided result, {} bytes]".format(len(rc))
                        saved += len(rc) - len(placeholder)
                        block["content"] = placeholder
                    elif isinstance(rc, list):
                        total = 0
                        for b in rc:
                            bt2 = b.get("type")
                            if bt2 == "text":
                                total += len(b.get("text", ""))
                            elif bt2 == "image":
                                src = b.get("source", {})
                                total += len(src.get("data", ""))
                        if total > COMPACT_PAYLOAD_MIN_BYTES:
                            placeholder = ("[elided multimodal result, "
                                           "~{} bytes]").format(total)
                            saved += total - len(placeholder)
                            block["content"] = placeholder
        return saved

    def _hard_trim(self):
        removed = 0
        while (self.estimate_context_bytes() > HARD_TRIM_THRESHOLD_BYTES
               and len(self.api_messages) > 4):
            del self.api_messages[0:2]
            removed += 2
        return removed

    def trim_after_turn(self):
        before = self.estimate_context_bytes()
        saved = self._compact_history()
        if saved > 0:
            self.log(_COLOR_DIM, "[compacted: -{} bytes]".format(saved))
        removed = self._hard_trim()
        if removed > 0:
            self.log(_COLOR_WARN,
                     "[trimmed {} old messages over cap]".format(removed))
        after = self.estimate_context_bytes()
        if saved > 0 or removed > 0:
            self.log(_COLOR_DIM,
                     "[context: {} -> {} bytes]".format(before, after))

    # ---- pause helper for rate-limit ---------------------------------------

    def countdown_wait(self, seconds, abort_check):
        """Sleep for `seconds`, polling `abort_check()` every 50 ms.

        `abort_check` is a callable returning True to bail. The bot
        scene passes a function that checks touch/kbd/tb for the
        usual back-out signals. Returns True if aborted, False if
        the wait completed normally.
        """
        remaining = seconds
        while remaining > 0:
            slice_end = time.monotonic() + 1.0
            while time.monotonic() < slice_end:
                if abort_check():
                    return True
                time.sleep(0.05)
            remaining -= 1
        return False

    # ---- agent loop -------------------------------------------------------

    def send(self, user_text, abort_check=None):
        """Run a full agent turn: append the user message, call the
        API, execute any tools, repeat until end_turn. Mutates
        api_messages + turns; the notify callback fires after every
        change so the bot scene can render mid-flight.

        `abort_check` is optional — passed through to countdown_wait
        for rate-limit handling.
        """
        self.api_messages.append({"role": "user", "content": user_text})
        turn = self.open_user_turn(user_text)
        sub_turn = 0
        api_start = 0.0
        while True:
            sub_turn += 1
            turn.status = Turn.STATUS_THINKING
            self._changed()
            api_start = time.monotonic()
            try:
                data = anthropic.send_messages(
                    self._api_key, self._model, self.api_messages,
                    max_tokens=8192, system=SYSTEM_PROMPT,
                    tools=tools.TOOL_SPECS,
                )
            except anthropic.RateLimitError as rle:
                wait_s = rle.retry_after_s
                if wait_s < 1:
                    wait_s = 1
                if wait_s > 600:
                    self.log(_COLOR_WARN,
                             "[rate limited for {}s — bailing]".format(wait_s))
                    self.close_current_turn(status=Turn.STATUS_ERROR)
                    return
                # Rate-limit pause / abort are informational, not
                # actual failures — render dim so the user only sees
                # red for true errors.
                self.log(_COLOR_DIM,
                         "[rate limited — pausing {}s "
                         "(tap [<] to abort)]".format(wait_s))
                aborted = self.countdown_wait(
                    wait_s, abort_check or (lambda: False))
                if aborted:
                    self.log(_COLOR_DIM, "[wait aborted]")
                    self.close_current_turn(status=Turn.STATUS_INTERRUPTED)
                    return
                self.log(_COLOR_DIM, "[resuming]")
                sub_turn -= 1
                continue
            except Exception as e:
                self.log(_COLOR_WARN, "[error] " + str(e)[:200])
                self.close_current_turn(status=Turn.STATUS_ERROR)
                return

            content_blocks = data.get("content", [])
            stop_reason = data.get("stop_reason", "")
            usage = data.get("usage", {})

            if stop_reason == "max_tokens":
                # Hitting max_tokens is a soft truncation, not an
                # error — dim it so red is reserved for true failures.
                self.log(_COLOR_DIM, "[hit max_tokens cap - response truncated]")
            elif stop_reason not in ("end_turn", "tool_use", ""):
                self.log(_COLOR_DIM, "[stop_reason: " + str(stop_reason) + "]")

            self.api_messages.append({"role": "assistant",
                                      "content": content_blocks})

            for block in content_blocks:
                if block.get("type") == "text":
                    self.log(_COLOR_PRIMARY, block.get("text", ""))

            if stop_reason != "tool_use":
                in_t = usage.get("input_tokens", "?")
                out_t = usage.get("output_tokens", "?")
                cache_r = usage.get("cache_read_input_tokens", 0)
                cache_w = usage.get("cache_creation_input_tokens", 0)
                self.trim_after_turn()
                ctx_bytes = self.estimate_context_bytes()
                cache_part = ""
                if cache_r or cache_w:
                    cache_part = " cache_r={} cache_w={}".format(cache_r, cache_w)
                elapsed = time.monotonic() - api_start
                self.log(_COLOR_DIM,
                         "  (in {} out {}{}; ctx {} B; api {:.1f}s)".format(
                             in_t, out_t, cache_part, ctx_bytes, elapsed))
                self.close_current_turn(status=Turn.STATUS_DONE)
                self.save_session(persist_to_disk=True)
                gc.collect()
                return

            # Tool execution batch.
            results = []
            for block in content_blocks:
                if block.get("type") != "tool_use":
                    continue
                name = block["name"]
                if name in ("launch_app", "switch_scene"):
                    # When the bot launches an app or switches scenes,
                    # remember to return to whichever scene the user
                    # was on when this send started — home if the bot
                    # is running inline on home, "bot" if running in
                    # the dedicated bot scene.
                    self.app.app_return_target = self.app._current_scene_name
                if name in ("restart_runtime", "hard_reset"):
                    try:
                        with open(SESSION_MARKER, "w") as f:
                            f.write("1")
                    except OSError:
                        pass
                    self.save_session(persist_to_disk=True)
                turn.tools_called.append(name)
                turn.current_tool = name
                turn.status = Turn.STATUS_RUNNING
                self._changed()
                result = tools.execute(name, block.get("input", {}),
                                       app=self.app)
                if isinstance(result, list):
                    is_error = False
                    error_preview = ""
                else:
                    if not isinstance(result, str):
                        result = str(result)
                    if len(result) > MAX_TOOL_RESULT_BYTES:
                        result = (result[:MAX_TOOL_RESULT_BYTES]
                                  + "...[truncated]")
                    is_error = result.startswith("ERROR")
                    error_preview = ""
                    if is_error:
                        preview = result.replace("\n", " | ")
                        if len(preview) > self.wrap_width * 2:
                            preview = preview[:self.wrap_width * 2 - 3] + "..."
                        error_preview = preview
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": result,
                })
                if is_error:
                    self.log(_COLOR_WARN, "  [{}] {}".format(name, error_preview))
                gc.collect()

            turn.current_tool = None
            self.api_messages.append({"role": "user", "content": results})
            gc.collect()
            self._changed()

            if self.app._scene_change_pending:
                self.log(_COLOR_DIM, "[scene change pending - exiting bot]")
                self.close_current_turn(status=Turn.STATUS_DONE)
                return


# Module-level colour handles. We can't import the theme directly
# without a circular dep risk if the theme grows imports later;
# instead the App injects these on first construction via the
# init_colors() helper below. Defaults match the dark theme so a
# unit test or REPL probe still renders sensibly.
_COLOR_PRIMARY = Color(hex=0xE0E8F0)
_COLOR_DIM = Color(hex=0x7A8FA8)
_COLOR_ACCENT = Color(hex=0xFFB454)
_COLOR_WARN = Color(hex=0xFF6B6B)
_COLOR_SUCCESS = Color(hex=0x5BD279)


def init_colors(primary=None, dim=None, accent=None, warn=None, success=None):
    """Let the App override the default palette once at boot."""
    global _COLOR_PRIMARY, _COLOR_DIM, _COLOR_ACCENT, _COLOR_WARN, _COLOR_SUCCESS
    if primary is not None: _COLOR_PRIMARY = primary
    if dim is not None: _COLOR_DIM = dim
    if accent is not None: _COLOR_ACCENT = accent
    if warn is not None: _COLOR_WARN = warn
    if success is not None: _COLOR_SUCCESS = success

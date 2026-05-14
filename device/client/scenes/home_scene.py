"""Home scene — the primary bot terminal.

Home owns the bot conversation flow. The user types in the input
bar at the bottom; ENTER sends the message to the agent and the
response streams into a pane in the middle of the screen. Two
layouts share the chrome + input footer; the middle band changes
based on whether the bot has any user turns yet:

  IDLE (no user turns):
    +--------------------------------------+
    | chrome                               |
    +--------------------------------------+
    |                                      |
    |      _____  ___  _   _ __   __       |
    |     |_   _||_ _|| \\ | |\\ \\ / /        |  big TINY-BOT logo
    |       | |   | | |  \\| | \\ V /  ---   |
    |       ...                            |
    |                                      |
    +--------------------------------------+
    |  [config] [system] ... apps          |  carousel near bottom
    +--------------------------------------+
    |  > ask the bot..._                   |  input bar
    +--------------------------------------+

  ENGAGED (at least one user turn in app.bot):
    +--------------------------------------+
    | chrome                               |
    +--------------------------------------+
    |  [config] [system] ... apps          |  carousel near top
    +--------------------------------------+
    |  turn N :: 12.3s :: user msg...      |
    |  recent assistant text               |  response pane
    |  ...                                 |  (tap to open the
    |  [running: read_file (3 of ?)]       |   dedicated bot scene)
    +--------------------------------------+
    |  > ask the bot..._                   |  input bar
    +--------------------------------------+

Send flow:
  - User types text and presses ENTER.
  - If home is currently IDLE, we can't render a response pane that
    isn't built yet — so we stash the text on `app.pending_bot_prompt`
    and SwitchScene("home") to ourselves. The new home instance loads
    in ENGAGED mode, drains the pending slot in OnStartup, and runs
    bot.send() against the just-built response pane.
  - If home is already ENGAGED, we call bot.send() inline — it blocks
    the App.Run loop, but the BotService's notify callback fires after
    every state change so the response pane updates mid-flight.

The dedicated bot scene is still reachable: tapping the response pane
opens it for full turn browsing / detail view. The floating [bot]
bubble on non-home scenes also switches there.
"""
import time

import displayio
from adafruit_display_shapes.rect import Rect

from engine.application import IScene

from client.services.bot import Turn, _format_tool_list, _wrap
from client.views import ChromeView, BotInputBar
from client.views.apps_carousel import AppsCarousel
from client.views.theme import (
    SCREEN_W, SCREEN_H, CHROME_H, BODY_LEFT, BODY_W,
    BG_MAIN, BG_SURFACE, BORDER, TEXT_PRIMARY, TEXT_DIM, ACCENT, WARN,
    build_logo, logo_total_w, logo_total_h,
)

from engine.display.ui.elements import Label
from engine.display.ui.models import Align, Dimensions, Position, Style


# Layout constants — fixed input + variable middle band. The
# carousel and middle band move depending on mode.
CAROUSEL_H = 70
INPUT_BAR_H = 32
INPUT_BAR_Y = SCREEN_H - INPUT_BAR_H - 2

# Idle: logo fills the area between chrome and carousel; carousel
# sits just above input.
IDLE_CAROUSEL_Y = INPUT_BAR_Y - CAROUSEL_H - 2
IDLE_LOGO_TOP = CHROME_H + 4
IDLE_LOGO_BOTTOM = IDLE_CAROUSEL_Y - 4
IDLE_LOGO_H = max(20, IDLE_LOGO_BOTTOM - IDLE_LOGO_TOP)

# Engaged: carousel sits just below chrome; response pane fills the
# rest of the body above input.
ENGAGED_CAROUSEL_Y = CHROME_H + 4
ENGAGED_PANE_TOP = ENGAGED_CAROUSEL_Y + CAROUSEL_H + 4
ENGAGED_PANE_BOTTOM = INPUT_BAR_Y - 2
ENGAGED_PANE_H = max(20, ENGAGED_PANE_BOTTOM - ENGAGED_PANE_TOP)

# Response pane internals.
PANE_HEADER_H = 14
PANE_LINE_H = 12
PANE_WRAP_WIDTH = max(20, (BODY_W - 12) // 6)

# Built-in scenes available from the carousel.
BUILTIN_APPS = (
    ("config", "config"),
    ("system", "system"),
)


# Logo + two-tone coloring live in theme so splash and home share
# them — imported above as LOGO_LINES / logo_color_for.


class HomeScene(IScene):
    KEY_BACKSPACE = 0x08
    KEY_ENTER = 0x0D
    KEY_ESC = 0x1B

    def __init__(self, app):
        self.app = app
        self.kbd = app.GetKeyboard()
        self.touch = app.GetTouch()
        self.trackball = app.GetTrackball()
        self.cfg = app.cfg
        self.rootGroup = displayio.Group()

        self._chrome = None
        self._carousel = None
        self._input_bar = None
        self._pointer = None
        self._started = False
        self._engaged = False
        # Response-pane labels (only in engaged mode).
        self._pane_rect = None
        self._pane_header_lbl = None
        self._pane_body_labels = []
        self._pane_status_lbl = None
        self._last_header_text = ""
        self._next_timer_tick = 0.0
        # Press state for carousel tap/drag.
        self._press_active = False
        self._press_start_xy = None
        self._press_total_motion = 0
        self._dragging_carousel = False
        # Pending text to send once OnStartup finishes its first paint.
        self._pending_prompt = None

    # ---- IScene -----------------------------------------------------------

    def OnStartup(self):
        # Home is a session root — clear any inherited back-override.
        self.app.app_return_target = None

        self._chrome = ChromeView(self.rootGroup,
                                  title="home",
                                  back_target=None,
                                  bot_target=None)

        # Layout mode is fixed for this scene-instance's lifetime;
        # idle→engaged transition is handled by re-entering home with
        # a pending prompt staged (see _send_inline_or_transition).
        # A staged prompt means a user turn is about to exist, so we
        # build the engaged layout up-front rather than waiting for
        # the turn to actually land in bot.turns.
        pending = getattr(self.app, "pending_bot_prompt", None)
        self._engaged = self.app.bot.has_user_turns() or bool(pending)

        if self._engaged:
            carousel_y = ENGAGED_CAROUSEL_Y
        else:
            carousel_y = IDLE_CAROUSEL_Y

        self._carousel = AppsCarousel(
            self.rootGroup,
            BODY_LEFT, carousel_y,
            BODY_W, CAROUSEL_H,
        )
        self._carousel.build(BUILTIN_APPS)

        if self._engaged:
            self._build_response_pane()
            # Wire the live-update channel.
            self.app.bot.set_notify(self._on_bot_changed)
        else:
            self._build_logo()

        theme = {
            "bg_main": BG_MAIN, "bg_surface": BG_SURFACE,
            "border": BORDER,
            "text_primary": TEXT_PRIMARY, "text_dim": TEXT_DIM,
            "accent": ACCENT, "warn": WARN, "success": ACCENT,
        }
        self._input_bar = BotInputBar(
            self.rootGroup, theme,
            x=BODY_LEFT, y=INPUT_BAR_Y, w=BODY_W, h=INPUT_BAR_H,
        )

        # Pointer is constructed last so its sprite sits on top of
        # everything inside this scene's group.
        self._pointer = self.app.GetPointer(self.rootGroup)

        # Initial response-pane paint so resumed sessions show their
        # latest turn immediately.
        if self._engaged:
            self._render_pane()

        # Drain any prompt staged by the previous home instance
        # (idle→engaged transition path) or by some other scene that
        # wants to start a turn on home. `pending` was already read
        # at the top of OnStartup for layout-mode detection.
        if pending:
            self.app.pending_bot_prompt = None
            self._pending_prompt = pending

    def OnUpdate(self, delta_time):
        if not self._started:
            self._started = True

        # Pending prompt fires on the first OnUpdate so the first paint
        # is on screen before send() blocks.
        if self._pending_prompt is not None and self._engaged:
            text = self._pending_prompt
            self._pending_prompt = None
            self._run_send_inline(text)
            return

        # Header timer tick (elapsed s while thinking/running).
        if self._engaged:
            self._tick_pane_timer()

        kbd = self.kbd.poll()
        if kbd:
            if kbd == self.KEY_ESC:
                if "wizard" in self.app._scenes:
                    self.app.SwitchScene("wizard")
                    return
            else:
                result = self._input_bar.feed_key(kbd)
                if result == "send":
                    text = self._input_bar.consume_text()
                    self._send_inline_or_transition(text)
                    return
                elif result == "open":
                    # Empty ENTER: open the full bot scene so user
                    # can browse history with the dedicated UI.
                    self.app.SwitchScene("bot")
                    return

        ev = self._pointer.poll()
        px, py = ev["x"], ev["y"]

        if ev["click"]:
            if self._input_bar.hit(px, py):
                # Tapping with buffered text sends; empty buffer opens
                # the dedicated bot scene to compose with more room.
                if self._input_bar.has_text():
                    text = self._input_bar.consume_text()
                    self._send_inline_or_transition(text)
                    return
                self.app.SwitchScene("bot")
                return
            # Tapping the response pane (engaged mode) opens the
            # dedicated bot scene with the full turn-browse UI.
            if (self._pane_rect is not None
                    and self._hit(self._pane_rect, px, py)):
                self.app.SwitchScene("bot")
                return
            self._press_active = True
            self._press_start_xy = (px, py)
            self._press_total_motion = 0
            self._dragging_carousel = False
            if self._carousel.contains(px, py):
                self._carousel.begin_drag(px)
                self._dragging_carousel = True

        if self._press_active and ev["moved"]:
            if self._press_start_xy is not None:
                sx, sy = self._press_start_xy
                m = abs(px - sx) + abs(py - sy)
                if m > self._press_total_motion:
                    self._press_total_motion = m
            if self._dragging_carousel:
                self._carousel.update_drag(px)

        if ev["release"]:
            if self._press_active:
                was_tap = self._press_total_motion < 6
                if self._dragging_carousel:
                    self._carousel.end_drag(px)
                if was_tap:
                    item = self._carousel.click_at(px, py)
                    if item is not None:
                        self._launch(item)
                        self._reset_press_state()
                        return
            self._reset_press_state()

    def OnDraw(self):
        pass

    def OnShutdown(self):
        # Detach notify so the next home/bot scene instance doesn't
        # render into our torn-down displayio tree.
        if self._engaged:
            try:
                self.app.bot.set_notify(None)
            except Exception:
                pass

    def GetRootGroup(self):
        return self.rootGroup

    # ---- layout builders ---------------------------------------------------

    def _build_logo(self):
        line_w_px = logo_total_w()
        total_h = logo_total_h()
        logo_x = (SCREEN_W - line_w_px) // 2
        logo_y = IDLE_LOGO_TOP + max(0, (IDLE_LOGO_H - total_h) // 2)
        build_logo(self.rootGroup, logo_x, logo_y)

    def _build_response_pane(self):
        """Build pre-allocated labels for the response pane. Render
        is then text-rewrite only, never displayio-tree mutation."""
        pane_x = BODY_LEFT
        pane_y = ENGAGED_PANE_TOP
        pane_w = BODY_W
        pane_h = ENGAGED_PANE_H
        pane_bg = Rect(
            pane_x, pane_y, pane_w, pane_h,
            fill=BG_SURFACE.value, outline=BORDER.value, stroke=1,
        )
        self.rootGroup.append(pane_bg)
        self._pane_rect = (pane_x, pane_y, pane_w, pane_h)

        # Header strip with turn number / elapsed / label.
        self._pane_header_lbl = Label(
            "",
            root_group=self.rootGroup,
            dimensions=Dimensions(pane_w - 12, PANE_HEADER_H),
            position=Position(pane_x + 6, pane_y + 2),
            default_style=Style(
                font_size=12, font_color=ACCENT,
                horizontal_align=Align.Start,
                vertical_align=Align.Center,
            ),
        )

        # Body rows. Reserve one row at the bottom for a status line
        # (thinking/running/done) so we don't have to re-layout when
        # status flips.
        body_top = pane_y + 2 + PANE_HEADER_H + 2
        body_h = pane_h - (body_top - pane_y) - 2
        total_rows = max(2, body_h // PANE_LINE_H)
        body_rows = total_rows - 1

        self._pane_body_labels = []
        for i in range(body_rows):
            lbl = Label(
                "",
                root_group=self.rootGroup,
                dimensions=Dimensions(pane_w - 14, PANE_LINE_H),
                position=Position(pane_x + 6,
                                  body_top + i * PANE_LINE_H),
                default_style=Style(
                    font_size=12, font_color=TEXT_PRIMARY,
                    horizontal_align=Align.Start,
                    vertical_align=Align.Start,
                ),
            )
            self._pane_body_labels.append(lbl)

        # Status row pinned to the bottom of the pane.
        self._pane_status_lbl = Label(
            "",
            root_group=self.rootGroup,
            dimensions=Dimensions(pane_w - 14, PANE_LINE_H),
            position=Position(pane_x + 6,
                              body_top + body_rows * PANE_LINE_H),
            default_style=Style(
                font_size=12, font_color=TEXT_DIM,
                horizontal_align=Align.Start,
                vertical_align=Align.Start,
            ),
        )

    # ---- send flow ---------------------------------------------------------

    def _send_inline_or_transition(self, text):
        """Decide whether to send right here (engaged) or trigger a
        scene rebuild to construct the response pane first (idle)."""
        if not text:
            self.app.SwitchScene("bot")
            return
        if self._engaged:
            self._run_send_inline(text)
            return
        # Idle: we need the engaged layout to render the response into.
        # Stash the prompt and re-enter home so OnStartup builds the
        # engaged layout, then drains the pending slot.
        self.app.pending_bot_prompt = text
        self.app.SwitchScene("home")

    def _run_send_inline(self, text):
        """Run a full agent turn for `text` inline. bot.send() blocks
        but the notify callback re-renders the response pane as state
        mutates so the user sees progress live."""
        abort_check = self._make_abort_check()
        try:
            self.app.bot.send(text, abort_check=abort_check)
        except Exception as e:
            print("bot.send error:", e)
        # Final render catches any tail state the notify loop missed.
        if not self.app._scene_change_pending:
            self._render_pane()

    def _make_abort_check(self):
        """Polled by BotService during rate-limit countdowns. Reads
        the raw input devices since the App's filtered-touch wrapper
        isn't being driven while send() blocks. ESC / BSP / chrome
        [<] / trackball click all signal abort."""
        raw_touch = self.app.GetRawTouch()
        kbd = self.app.GetKeyboard()
        tb = self.app.GetTrackball()
        # Chrome [<] is hidden on home (back_target=None), so we just
        # watch keyboard + trackball.

        def _check():
            if raw_touch.available:
                # Drain the event; we don't act on touch coords here,
                # but consuming keeps the driver state sane.
                raw_touch.read()
            t = tb.read()
            if t["click"]:
                return True
            k = kbd.poll()
            if k == self.KEY_ESC or k == self.KEY_BACKSPACE:
                return True
            return False
        return _check

    # ---- response-pane rendering ------------------------------------------

    def _on_bot_changed(self):
        """BotService notify callback. send() blocks the App.Run loop
        while it runs; render here so tool progress + assistant text
        land on screen as they happen instead of after the full turn."""
        try:
            self._render_pane()
        except Exception as e:
            print("home pane render during notify failed:", e)

    def _render_pane(self):
        if not self._engaged:
            return
        display = self.app.display
        prev = display.auto_refresh
        display.auto_refresh = False
        try:
            turn = self.app.bot.last_user_turn()
            self._render_pane_header(turn)
            self._render_pane_body(turn)
            self._render_pane_status(turn)
            self._apply_carousel_lock(turn)
        finally:
            display.refresh()
            display.auto_refresh = prev

    def _apply_carousel_lock(self, turn):
        """Lock the apps carousel while the agent is mid-turn so a
        stray tap can't launch on top of a running send."""
        busy = (turn is not None
                and turn.status in (Turn.STATUS_THINKING, Turn.STATUS_RUNNING))
        if self._carousel is not None:
            self._carousel.set_locked(busy)

    def _render_pane_header(self, turn):
        if turn is None:
            text = "(no turns yet)"
        else:
            text = "turn {} :: {:.1f}s".format(turn.index, turn.elapsed_s())
            if turn.label:
                room = PANE_WRAP_WIDTH - len(text) - 4
                if room > 8:
                    snippet = turn.label
                    if len(snippet) > room:
                        snippet = snippet[:room - 3] + "..."
                    text += " :: " + snippet
        if text != self._last_header_text:
            self._pane_header_lbl.text = text
            self._pane_header_lbl._dirty = True
            self._pane_header_lbl.draw()
            self._last_header_text = text

    def _render_pane_body(self, turn):
        body_rows = len(self._pane_body_labels)
        if turn is None:
            entries = []
        else:
            # Skip the echoed user line ("> ..."); header already
            # shows the label.
            raw = list(turn.entries)
            if raw and raw[0][1].startswith("> "):
                raw = raw[1:]
            entries = raw

        # Show the most recent body_rows entries (auto-follow tail).
        recent = entries[-body_rows:] if entries else []
        earlier_count = len(entries) - len(recent)
        rows = []
        if earlier_count > 0:
            rows.append((TEXT_DIM,
                         "({} earlier — tap to see all)".format(earlier_count)))
            if recent:
                recent = recent[1:]
        for color, text in recent:
            rows.append((color, text))
        while len(rows) < body_rows:
            rows.append((TEXT_PRIMARY, ""))
        for i, (color, text) in enumerate(rows[:body_rows]):
            self._set_label(self._pane_body_labels[i], color, text)

    def _render_pane_status(self, turn):
        if turn is None:
            color, text = TEXT_DIM, "type below to talk to the bot"
        elif turn.status == Turn.STATUS_RUNNING and turn.current_tool:
            # Tool-call progress is informational; use the orange
            # accent (not red) so red is reserved for real errors.
            color, text = ACCENT, "[running: {} ({} so far)]".format(
                turn.current_tool, len(turn.tools_called))
        elif turn.status == Turn.STATUS_THINKING:
            color, text = TEXT_DIM, "[thinking...]"
        elif turn.status == Turn.STATUS_ERROR:
            color, text = WARN, "[error — tap to see details]"
        elif turn.status == Turn.STATUS_INTERRUPTED:
            # User-initiated pause — dim, not alarming red.
            color, text = TEXT_DIM, "[interrupted]"
        elif turn.status == Turn.STATUS_DONE and turn.tools_called:
            color, text = TEXT_DIM, "[done: " + _format_tool_list(
                turn.tools_called) + "]"
        elif turn.status == Turn.STATUS_DONE:
            color, text = TEXT_DIM, "[done — tap to see full turn]"
        else:
            color, text = TEXT_DIM, ""
        self._set_label(self._pane_status_lbl, color, text)

    def _set_label(self, lbl, color, text):
        # Truncate to the pane's wrap width so long entries don't run
        # off the right edge. Wrap-to-next-line isn't needed in summary
        # view since each entry is already a single wrapped line.
        if len(text) > PANE_WRAP_WIDTH:
            text = text[:PANE_WRAP_WIDTH]
        if lbl.text != text:
            lbl.text = text
            lbl._dirty = True
        if lbl.style.font_color != color:
            lbl.style.font_color = color
            lbl._dirty = True
        lbl.draw()

    def _tick_pane_timer(self):
        """Re-render the header at ~3 Hz while a turn is in flight so
        the elapsed-seconds counter ticks visibly."""
        turn = self.app.bot.last_user_turn()
        if turn is None:
            return
        if turn.status not in (Turn.STATUS_THINKING, Turn.STATUS_RUNNING):
            return
        now = time.monotonic()
        if now < self._next_timer_tick:
            return
        self._next_timer_tick = now + 0.33
        self._render_pane_header(turn)
        display = self.app.display
        # Refresh isn't strictly needed if auto_refresh is on, but
        # explicit ensures the header tick lands even when the App
        # loop hasn't otherwise dirtied the display.
        try:
            display.refresh()
        except Exception:
            pass

    # ---- launcher / press state ------------------------------------------

    def _reset_press_state(self):
        self._press_active = False
        self._press_start_xy = None
        self._press_total_motion = 0
        self._dragging_carousel = False

    @staticmethod
    def _hit(rect, px, py):
        if rect is None or px is None or py is None:
            return False
        x, y, w, h = rect
        return x <= px < x + w and y <= py < y + h

    def _launch(self, item):
        kind, target, name, label, tile_x, tile_w = item
        if kind == "scene":
            self.app.SwitchScene(target)
            return
        if kind == "app":
            from engine.llm import tools
            result = tools.execute("launch_app", {"name": target},
                                   app=self.app)
            if isinstance(result, str) and result.startswith("ERROR"):
                self.app.bot.open_system_turn(label="launch error")
                self.app.bot.log(WARN, result[:80])
                self.app.bot.close_current_turn()

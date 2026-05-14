"""Bot scene — full-screen agent UI.

The bot is its own scene now (not an overlay), which isolates the
runtime from the apps it builds: an app crash drops to the error
scene without taking the chat with it. The user reaches the bot by
typing in home's input bar, by tapping the floating [bot] bubble
on any non-home scene, or by the error scene's "ask bot to fix"
button.

Layout (top-to-bottom):
  ChromeView      [<] back     title="bot"     <status>
  card header     turn N :: elapsed :: label
  card content    most recent assistant text (summary mode by default;
                  tap content to expand to detail view with scroll)
  card footer     [<] turn N/M [now] [>]
  input strip     > type here_ (3 lines)

The [<] back goes to whatever scene launched the bot, stashed by
the App as `app.bot_return_target`. If unset (e.g. resumed from a
fresh boot), it falls back to "home".

The scene reads bot state from `app.bot` (the shared BotService).
Network calls happen inside `bot.send()` which BLOCKS the main
loop; the bot's notify callback fires after each mutation so the
scene re-renders mid-flight (tool progress, assistant text
arriving).

`app.pending_bot_prompt` is drained on OnStartup so the error
scene's "ask bot to fix" or any other "kick off a turn without the
user typing" entry point Just Works — the bot scene loads, sends
the staged prompt, and the user sees the agent start working.
"""
import time

import displayio
from adafruit_display_shapes.rect import Rect

from engine.application import IScene
from engine.display.ui.elements import Label
from engine.display.ui.models import Align, Dimensions, Position, Style

from client.services.bot import Turn, _format_tool_list, _wrap
from client.views import ChromeView
from client.views.theme import (
    SCREEN_W, SCREEN_H, CHROME_H,
    BG_MAIN, BG_SURFACE, BORDER,
    TEXT_PRIMARY, TEXT_DIM, ACCENT, WARN, SUCCESS,
)


# Input strip — multi-line so longer follow-ups don't run off the side.
INPUT_LINES = 3
INPUT_LINE_H = 14
INPUT_AREA_H = INPUT_LINES * INPUT_LINE_H

# Card occupies the space between chrome and input.
CARD_TOP = CHROME_H + 2
CARD_BOTTOM = SCREEN_H - INPUT_AREA_H - 3
CARD_LEFT = 2
CARD_RIGHT = SCREEN_W - 2
CARD_W = CARD_RIGHT - CARD_LEFT
CARD_H = CARD_BOTTOM - CARD_TOP
CARD_HEADER_H = 18
CARD_FOOTER_H = 22
CARD_CONTENT_TOP = CARD_TOP + CARD_HEADER_H
CARD_CONTENT_BOTTOM = CARD_BOTTOM - CARD_FOOTER_H
CARD_CONTENT_H = CARD_CONTENT_BOTTOM - CARD_CONTENT_TOP

LINE_H = 12
CARD_CONTENT_ROWS = max(1, CARD_CONTENT_H // LINE_H)
WRAP_WIDTH = max(20, (CARD_W - 18) // 6)

FOOTER_BTN_W = 44
FOOTER_Y = CARD_BOTTOM - CARD_FOOTER_H
FOOTER_BTN_H = CARD_FOOTER_H - 4


class BotScene(IScene):
    KEY_BACKSPACE = 0x08
    KEY_ENTER = 0x0D
    KEY_ESC = 0x1B

    def __init__(self, app):
        self.app = app
        self.kbd = app.GetKeyboard()
        self.touch = app.GetTouch()
        self.trackball = app.GetTrackball()
        self.rootGroup = displayio.Group()
        # UI state.
        self._auto_follow = True
        self._focused_idx = max(0, len(app.bot.turns) - 1)
        self._view_mode = "summary"     # or "detail"
        self._detail_scroll = 0
        self._drag_anchor_y = None
        self._drag_anchor_offset = 0
        self._tap_start_xy = None
        self._input_buffer = []
        self._last_header_text = ""
        self._next_timer_tick = 0.0
        self._dirty = False
        self._pending_prompt = None
        # Reference to the previous scene's group so snapshot_scene
        # can dump it. Stashed by App.SwitchScene("bot") before
        # constructing us.
        self._theme = {
            "bg_main": BG_MAIN, "bg_surface": BG_SURFACE,
            "border": BORDER,
            "text_primary": TEXT_PRIMARY, "text_dim": TEXT_DIM,
            "accent": ACCENT, "warn": WARN, "success": SUCCESS,
        }
        self._chrome = None

    # ---- IScene -----------------------------------------------------------

    def OnStartup(self):
        # Chrome back-target = whatever scene launched us. App stashes
        # this on SwitchScene; if not set (fresh boot resume), home is
        # the sane default.
        back_target = getattr(self.app, "bot_return_target", None) or "home"
        self._chrome = ChromeView(self.rootGroup,
                                  title="bot",
                                  back_target=back_target,
                                  bot_target=None)

        self._build_card()
        self._build_input()

        # Wire bot notifications to this scene's renderer.
        self.app.bot.set_notify(self._on_bot_changed)

        # Drain pending prompt (from error scene / home's send).
        prompt = getattr(self.app, "pending_bot_prompt", None)
        if prompt:
            self.app.pending_bot_prompt = None
            self._pending_prompt = prompt

        # Snap focus to latest and render the current state.
        self._auto_follow = True
        self._focused_idx = max(0, len(self.app.bot.turns) - 1)
        self.render()

    def OnUpdate(self, delta_time):
        # Pending prompt fires once the first render is on screen so
        # the user sees the chrome + card before send() blocks.
        if self._pending_prompt is not None:
            text = self._pending_prompt
            self._pending_prompt = None
            self._run_send(text)
            return

        self._tick_timer()

        ev_consumed = False
        if self.touch.available:
            ev = self.touch.read()
            ev_consumed = True
            px, py = ev["x"], ev["y"]
            if ev["click"] and px is not None:
                # Chrome back first — same affordance as any other scene.
                target = self._chrome.button_hit(px, py)
                if target is not None:
                    self.app.SwitchScene(target)
                    return
                if self._hit(self._prev_rect, px, py):
                    self._step_focus(-1)
                    return
                if self._hit(self._next_rect, px, py):
                    self._step_focus(+1)
                    return
                if (not self._is_on_latest()
                        and self._hit(self._now_rect, px, py)):
                    self._jump_to_latest()
                    return
                if self._hit(self._content_rect, px, py):
                    self._drag_anchor_y = py
                    self._drag_anchor_offset = self._detail_scroll
                    self._tap_start_xy = (px, py)
            elif ev["release"]:
                if self._drag_anchor_y is not None:
                    start = self._tap_start_xy
                    if start is not None and py is not None:
                        dx = abs(px - start[0]) if px is not None else 0
                        dy = abs(py - start[1])
                        if dx + dy < 8:
                            self._toggle_view()
                    self._drag_anchor_y = None
                    self._tap_start_xy = None
            elif (self._drag_anchor_y is not None
                  and py is not None
                  and self._view_mode == "detail"):
                delta_lines = (self._drag_anchor_y - py) // LINE_H
                new_offset = self._drag_anchor_offset + delta_lines
                if new_offset != self._detail_scroll:
                    self._detail_scroll = new_offset
                    self.render()

        # Trackball click backs out to whichever scene launched us.
        tb = self.trackball.read()
        if tb["click"]:
            self.app.SwitchScene(self._chrome._back_target)
            return

        # Keyboard input.
        k = self.kbd.poll()
        if k:
            if k == self.KEY_ENTER:
                text = "".join(self._input_buffer).strip()
                self._input_buffer = []
                self._render_input()
                if text:
                    self._run_send(text)
                return
            if k == self.KEY_ESC:
                self.app.SwitchScene(self._chrome._back_target)
                return
            if k == self.KEY_BACKSPACE:
                if self._input_buffer:
                    self._input_buffer.pop()
                    self._render_input()
                else:
                    self.app.SwitchScene(self._chrome._back_target)
                    return
            elif 0x20 <= k <= 0x7E and len(self._input_buffer) < 512:
                self._input_buffer.append(chr(k))
                self._render_input()

        if self._dirty and not ev_consumed:
            self.render()

    def OnDraw(self):
        pass

    def OnShutdown(self):
        # Detach notify so the next bot scene instance (or any
        # background path) doesn't try to render into our torn-down
        # displayio tree.
        try:
            self.app.bot.set_notify(None)
        except Exception:
            pass

    def GetRootGroup(self):
        return self.rootGroup

    # ---- build phase -------------------------------------------------------

    def _build_card(self):
        t = self._theme
        self._card_border = Rect(
            CARD_LEFT, CARD_TOP, CARD_W, CARD_H,
            fill=t["bg_main"].value,
            outline=t["border"].value, stroke=1,
        )
        self.rootGroup.append(self._card_border)
        self._card_header_bg = Rect(
            CARD_LEFT + 1, CARD_TOP + 1, CARD_W - 2, CARD_HEADER_H,
            fill=t["bg_surface"].value, outline=None,
        )
        self.rootGroup.append(self._card_header_bg)
        self._card_header_lbl = Label(
            "",
            root_group=self.rootGroup,
            dimensions=Dimensions(CARD_W - 12, CARD_HEADER_H),
            position=Position(CARD_LEFT + 6, CARD_TOP + 1),
            default_style=Style(
                font_size=12, font_color=t["accent"],
                horizontal_align=Align.Start,
                vertical_align=Align.Center,
            ),
        )
        # Pre-allocated content rows so render is text rewrites only.
        self._content_labels = []
        for i in range(CARD_CONTENT_ROWS):
            lbl = Label(
                "",
                root_group=self.rootGroup,
                dimensions=Dimensions(CARD_W - 14, LINE_H),
                position=Position(CARD_LEFT + 6,
                                  CARD_CONTENT_TOP + i * LINE_H),
                default_style=Style(
                    font_size=12, font_color=t["text_primary"],
                    horizontal_align=Align.Start,
                    vertical_align=Align.Start,
                ),
            )
            self._content_labels.append(lbl)
        # Footer.
        self._footer_bg = Rect(
            CARD_LEFT + 1, FOOTER_Y, CARD_W - 2, CARD_FOOTER_H,
            fill=t["bg_surface"].value, outline=None,
        )
        self.rootGroup.append(self._footer_bg)
        # Prev button.
        self._prev_bg = Rect(
            CARD_LEFT + 2, FOOTER_Y + 2, FOOTER_BTN_W, FOOTER_BTN_H,
            fill=t["bg_main"].value, outline=t["accent"].value, stroke=1,
        )
        self.rootGroup.append(self._prev_bg)
        self._prev_lbl = Label(
            "[<]",
            root_group=self.rootGroup,
            dimensions=Dimensions(FOOTER_BTN_W, FOOTER_BTN_H),
            position=Position(CARD_LEFT + 2, FOOTER_Y + 2),
            default_style=Style(
                font_size=12, font_color=t["accent"],
                horizontal_align=Align.Center,
                vertical_align=Align.Center,
            ),
        )
        # Next button.
        self._next_bg = Rect(
            CARD_RIGHT - FOOTER_BTN_W - 2, FOOTER_Y + 2,
            FOOTER_BTN_W, FOOTER_BTN_H,
            fill=t["bg_main"].value, outline=t["accent"].value, stroke=1,
        )
        self.rootGroup.append(self._next_bg)
        self._next_lbl = Label(
            "[>]",
            root_group=self.rootGroup,
            dimensions=Dimensions(FOOTER_BTN_W, FOOTER_BTN_H),
            position=Position(CARD_RIGHT - FOOTER_BTN_W - 2, FOOTER_Y + 2),
            default_style=Style(
                font_size=12, font_color=t["accent"],
                horizontal_align=Align.Center,
                vertical_align=Align.Center,
            ),
        )
        # Now button (visible only when not on latest).
        now_x = CARD_RIGHT - 2 * FOOTER_BTN_W - 8
        self._now_bg = Rect(
            now_x, FOOTER_Y + 2, FOOTER_BTN_W, FOOTER_BTN_H,
            fill=t["bg_main"].value, outline=t["success"].value, stroke=1,
        )
        self.rootGroup.append(self._now_bg)
        self._now_lbl = Label(
            "now",
            root_group=self.rootGroup,
            dimensions=Dimensions(FOOTER_BTN_W, FOOTER_BTN_H),
            position=Position(now_x, FOOTER_Y + 2),
            default_style=Style(
                font_size=12, font_color=t["success"],
                horizontal_align=Align.Center,
                vertical_align=Align.Center,
            ),
        )
        # Indicator.
        ind_x = CARD_LEFT + FOOTER_BTN_W + 6
        ind_w = (CARD_RIGHT - FOOTER_BTN_W - 6) - ind_x - FOOTER_BTN_W - 6
        if ind_w < 60:
            ind_w = 60
        self._indicator_lbl = Label(
            "",
            root_group=self.rootGroup,
            dimensions=Dimensions(ind_w, FOOTER_BTN_H),
            position=Position(ind_x, FOOTER_Y + 2),
            default_style=Style(
                font_size=12, font_color=t["text_primary"],
                horizontal_align=Align.Center,
                vertical_align=Align.Center,
            ),
        )
        # Cache hit-test rects.
        self._prev_rect = (CARD_LEFT + 2, FOOTER_Y + 2,
                           FOOTER_BTN_W, FOOTER_BTN_H)
        self._next_rect = (CARD_RIGHT - FOOTER_BTN_W - 2, FOOTER_Y + 2,
                           FOOTER_BTN_W, FOOTER_BTN_H)
        self._now_rect = (now_x, FOOTER_Y + 2,
                          FOOTER_BTN_W, FOOTER_BTN_H)
        self._content_rect = (CARD_LEFT, CARD_CONTENT_TOP,
                              CARD_W, CARD_CONTENT_H)

    def _build_input(self):
        t = self._theme
        input_top = CARD_BOTTOM + 2
        self._input_labels = []
        for i in range(INPUT_LINES):
            lbl = Label(
                "> _" if i == 0 else "",
                root_group=self.rootGroup,
                dimensions=Dimensions(SCREEN_W - 12, INPUT_LINE_H),
                position=Position(6, input_top + i * INPUT_LINE_H),
                default_style=Style(
                    font_size=12, font_color=t["accent"],
                    horizontal_align=Align.Start,
                    vertical_align=Align.Start,
                ),
            )
            self._input_labels.append(lbl)

    # ---- notify / send -----------------------------------------------------

    def _on_bot_changed(self):
        """BotService notify callback. bot.send() blocks the App.Run
        loop while it runs, so deferring render to the next tick would
        mean a frozen UI for the whole agent turn. Render immediately
        so tool progress + assistant text land as they happen."""
        try:
            self.render()
        except Exception as e:
            print("bot scene render during notify failed:", e)

    def _run_send(self, text):
        """Run a full agent turn for `text`. The bot service's send()
        blocks; the notify callback keeps re-rendering throughout."""
        abort_check = self._make_abort_check()
        try:
            self.app.bot.send(text, abort_check=abort_check)
        except Exception as e:
            print("bot.send error:", e)
        # Render the final state — notify already fired but a final
        # paint catches any tail state the loop didn't hit.
        if not self.app._scene_change_pending:
            self.render()

    def _make_abort_check(self):
        """Closure the BotService polls during rate-limit countdowns.

        Reads the raw input devices since the App's filtered-touch
        wrapper isn't being driven while send() blocks. Tapping the
        chrome [<] button or pressing ESC/BSP signals abort.
        """
        raw_touch = self.app.GetRawTouch()
        kbd = self.app.GetKeyboard()
        tb = self.app.GetTrackball()

        def _check():
            if raw_touch.available:
                ev = raw_touch.read()
                if ev["click"] and ev["x"] is not None:
                    if self._chrome.button_hit(ev["x"], ev["y"]) is not None:
                        return True
            t = tb.read()
            if t["click"]:
                return True
            k = kbd.poll()
            if k == self.KEY_ESC or k == self.KEY_BACKSPACE:
                return True
            return False
        return _check

    # ---- rendering ---------------------------------------------------------

    def render(self):
        self._dirty = False
        display = self.app.display
        prev = display.auto_refresh
        display.auto_refresh = False
        try:
            turn = self._focused_turn()
            self._render_header(turn)
            if turn is None:
                self._clear_content()
            elif self._view_mode == "detail":
                self._render_detail(turn)
            else:
                self._render_summary(turn)
            self._render_footer(turn)
            self._render_input()
        finally:
            display.refresh()
            display.auto_refresh = prev

    def _focused_turn(self):
        turns = self.app.bot.turns
        if not turns:
            return None
        if self._auto_follow:
            return turns[-1]
        i = max(0, min(self._focused_idx, len(turns) - 1))
        return turns[i]

    def _is_on_latest(self):
        if not self.app.bot.turns:
            return True
        if self._auto_follow:
            return True
        return self._focused_idx == len(self.app.bot.turns) - 1

    def _render_header(self, turn):
        if turn is None:
            text = "(no turns yet)"
        else:
            text = "turn {} :: {:.1f}s".format(turn.index, turn.elapsed_s())
            glyph = ""
            if turn.status == Turn.STATUS_THINKING:
                glyph = " (thinking)"
            elif turn.status == Turn.STATUS_RUNNING:
                glyph = " (running)"
            elif turn.status == Turn.STATUS_ERROR:
                glyph = " (error)"
            elif turn.status == Turn.STATUS_INTERRUPTED:
                glyph = " (interrupted)"
            text += glyph
            if turn.label:
                room = WRAP_WIDTH - len(text) - 4
                if room > 10:
                    snippet = turn.label
                    if len(snippet) > room:
                        snippet = snippet[:room - 3] + "..."
                    text = text + " :: " + snippet
        if text != self._last_header_text:
            self._card_header_lbl.text = text
            self._card_header_lbl._dirty = True
            self._card_header_lbl.draw()
            self._last_header_text = text

    def _clear_content(self):
        for lbl in self._content_labels:
            if lbl.text != "":
                lbl.text = ""
                lbl._dirty = True
                lbl.draw()

    def _set_row(self, i, color, text):
        lbl = self._content_labels[i]
        if lbl.text != text:
            lbl.text = text
            lbl._dirty = True
        if lbl.style.font_color != color:
            lbl.style.font_color = color
            lbl._dirty = True
        lbl.draw()

    def _render_summary(self, turn):
        entries = turn.entries
        body_rows = CARD_CONTENT_ROWS - 1
        if body_rows < 1:
            body_rows = 1
        recent = entries[-body_rows:]
        earlier_count = len(entries) - len(recent)
        rows = []
        if earlier_count > 0:
            rows.append((self._theme["text_dim"],
                         "({} earlier in this turn)".format(earlier_count)))
            recent = recent[1:]
        for color, text in recent:
            rows.append((color, text))
        while len(rows) < body_rows:
            rows.append((self._theme["text_primary"], ""))
        for i, (color, text) in enumerate(rows[:body_rows]):
            self._set_row(i, color, text)
        status_color, status_text = self._summary_status(turn)
        self._set_row(body_rows, status_color, status_text)

    def _summary_status(self, turn):
        t = self._theme
        if turn.status == Turn.STATUS_RUNNING and turn.current_tool:
            # Running a tool is informational, not an error — render
            # as accent (orange highlight) instead of red.
            return (t["accent"],
                    "[running: {} ({} of {})]".format(
                        turn.current_tool,
                        len(turn.tools_called),
                        len(turn.tools_called) or "?"))
        if turn.status == Turn.STATUS_THINKING:
            return (t["text_dim"], "[thinking...]")
        if turn.status == Turn.STATUS_ERROR:
            return (t["warn"], "[error]")
        if turn.status == Turn.STATUS_INTERRUPTED:
            # User-initiated pause — dim, not alarming red.
            return (t["text_dim"], "[interrupted]")
        if turn.status == Turn.STATUS_DONE and turn.tools_called:
            return (t["text_dim"],
                    "[done: " + _format_tool_list(turn.tools_called) + "]")
        if turn.status == Turn.STATUS_DONE:
            return (t["text_dim"], "[done]")
        return (t["text_dim"], "")

    def _render_detail(self, turn):
        entries = turn.entries
        total = len(entries)
        max_scroll = max(0, total - CARD_CONTENT_ROWS)
        if self._detail_scroll < 0:
            self._detail_scroll = 0
        if self._detail_scroll > max_scroll:
            self._detail_scroll = max_scroll
        end = total - self._detail_scroll
        start = max(0, end - CARD_CONTENT_ROWS)
        window = entries[start:end]
        while len(window) < CARD_CONTENT_ROWS:
            window.insert(0, (self._theme["text_primary"], ""))
        for i, (color, text) in enumerate(window):
            self._set_row(i, color, text)

    def _render_footer(self, turn):
        n_turns = len(self.app.bot.turns)
        if turn is None:
            ind = "0 / 0"
        else:
            ind = "turn {} / {}".format(turn.index + 1, n_turns)
            if self._view_mode == "detail":
                total = len(turn.entries)
                if total > CARD_CONTENT_ROWS:
                    pos = total - self._detail_scroll
                    ind = "{}  [{}-{}/{}]".format(
                        ind,
                        max(1, pos - CARD_CONTENT_ROWS + 1),
                        pos,
                        total)
        if self._indicator_lbl.text != ind:
            self._indicator_lbl.text = ind
            self._indicator_lbl._dirty = True
            self._indicator_lbl.draw()
        show_now = not self._is_on_latest()
        if self._now_bg.hidden != (not show_now):
            self._now_bg.hidden = not show_now
        # Our Label wraps an underlying displayio label at
        # `_text_area`; the wrapper doesn't expose `.hidden` directly
        # so set it on the inner widget.
        if self._now_lbl._text_area.hidden != (not show_now):
            self._now_lbl._text_area.hidden = not show_now

    def _render_input(self):
        raw = "".join(self._input_buffer)
        wrapped = _wrap(raw, WRAP_WIDTH)
        if not wrapped:
            wrapped = [""]
        wrapped = wrapped[-INPUT_LINES:]
        while len(wrapped) < INPUT_LINES:
            wrapped.append("")
        last_with_content = 0
        if raw:
            for i in range(INPUT_LINES - 1, -1, -1):
                if wrapped[i]:
                    last_with_content = i
                    break
        for i, lbl in enumerate(self._input_labels):
            prefix = "> " if i == 0 else "  "
            text = prefix + wrapped[i]
            if i == last_with_content:
                text += "_"
            if lbl.text != text:
                lbl.text = text
                lbl._dirty = True
                lbl.draw()

    # ---- navigation --------------------------------------------------------

    def _step_focus(self, delta):
        turns = self.app.bot.turns
        if not turns:
            return
        base = (len(turns) - 1) if self._auto_follow else self._focused_idx
        new = max(0, min(len(turns) - 1, base + delta))
        self._auto_follow = (new == len(turns) - 1)
        self._focused_idx = new
        self._view_mode = "summary"
        self._detail_scroll = 0
        self.render()

    def _jump_to_latest(self):
        if not self.app.bot.turns:
            return
        self._auto_follow = True
        self._focused_idx = len(self.app.bot.turns) - 1
        self._view_mode = "summary"
        self._detail_scroll = 0
        self.render()

    def _toggle_view(self):
        self._view_mode = "detail" if self._view_mode == "summary" else "summary"
        self._detail_scroll = 0
        self.render()

    def _tick_timer(self):
        turn = self._focused_turn()
        if turn is None:
            return
        if turn.status not in (Turn.STATUS_THINKING, Turn.STATUS_RUNNING):
            return
        now = time.monotonic()
        if now < self._next_timer_tick:
            return
        self._next_timer_tick = now + 0.33
        self._render_header(turn)

    # ---- hit-testing -------------------------------------------------------

    @staticmethod
    def _hit(rect, px, py):
        if rect is None or px is None or py is None:
            return False
        x, y, w, h = rect
        return x <= px < x + w and y <= py < y + h

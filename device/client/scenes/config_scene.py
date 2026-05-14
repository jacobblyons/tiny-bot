"""Built-in 'config' scene: edit wifi + LLM settings post-wizard.

Mirrors the on-boarding wizard for the subset of fields users actually
need to change after first boot. Shows current values, lets the user
edit any field with the keyboard, then saves and reboots so the new
config takes effect.

UX:
  - tap a row (or trackball-select + click)  -> edit that field
  - in edit mode, type new value + ENTER     -> commit
  - tap [save & reboot]                      -> persist + microcontroller.reset()
  - tap [home] in the chrome bar             -> abandon edits, back to home

No ESC required — every exit path is touchable or covered by BSP.
"""
import time
import displayio
import microcontroller
from adafruit_display_shapes.rect import Rect
from adafruit_display_shapes.line import Line

from engine.application import IScene
from engine.display.ui.elements import Label, Select
from engine.display.ui.models import Align, Dimensions, Position, Style

from client import config
from client.views import ChromeView
from client.views.theme import (
    SCREEN_W, SCREEN_H, CHROME_H, FOOTER_H, BODY_LEFT, BODY_W,
    BG_MAIN, BG_SURFACE, BORDER, TEXT_PRIMARY, TEXT_DIM, ACCENT, SUCCESS, WARN,
)


ROW_H = 22
LIST_TOP = CHROME_H + 4
SAVE_BTN_H = 22


# (display label, path-in-cfg, kind). Kinds:
#   "text"    free-form text entry via keyboard
#   "secret"  free-form text but display masked
#   "select"  modal Select.show() picker (options come from FIELD_OPTIONS)
#   "api_key" free-form text, masked, with path computed from current provider
FIELDS = [
    ("wifi ssid",  ("wifi", "ssid"),                      "text"),
    ("wifi pass",  ("wifi", "password"),                  "secret"),
    ("provider",   ("agent", "provider"),                 "select"),
    ("model",      ("agent", "model"),                    "select"),
    ("api key",    None,                                  "api_key"),
    ("header h",   ("ui", "header_height"),               "select"),
]

PROVIDERS = ("claude", "openai")
# Preset header heights offered in the picker. theme.py clamps to
# [16, 64]; these are sensible thumb-targetable steps.
HEADER_HEIGHTS = ("20", "24", "32", "40", "48")

# Available models per provider. Keep in sync with boot_wizard_scene.MODELS;
# this list is what the Select modal offers for the "model" field.
MODELS = {
    "claude": (
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    ),
    "openai": (
        "gpt-5",
        "gpt-5-mini",
    ),
}
KEY_BACKSPACE = 0x08
KEY_ENTER = 0x0D
KEY_ESC = 0x1B


def _path_get(cfg, path):
    cur = cfg
    for p in path:
        cur = cur[p]
    return cur


def _path_set(cfg, path, value):
    cur = cfg
    for p in path[:-1]:
        cur = cur[p]
    cur[path[-1]] = value


def _api_key_path(cfg):
    return ("providers", cfg["agent"]["provider"], "api_key")


def _mask(value):
    if not value:
        return "(empty)"
    if len(value) <= 6:
        return "*" * len(value)
    return value[:3] + "*" * (len(value) - 6) + value[-3:]


class ConfigScene(IScene):
    def __init__(self, app):
        self.app = app
        self.kbd = app.GetKeyboard()
        self.touch = app.GetTouch()
        self.trackball = app.GetTrackball()
        self.rootGroup = displayio.Group()
        # Always work against a fresh load so we don't fight the wizard
        # if the user came in mid-session.
        self.cfg = config.load() or {}
        # Backfill missing branches against defaults so _path_set works
        # even on a partial config.
        self.cfg = config._merge(config.DEFAULTS, self.cfg)

        self._sel = 0
        self._editing = False
        self._edit_buf = []
        self._row_labels = []   # parallel to FIELDS
        self._chrome = None
        self._save_btn = None
        self._save_label = None
        self._status = None

        # Save-button rectangle (touch zone). Centered in the body
        # area, not the whole screen, so it doesn't drift under the
        # sidebar.
        body_cx = BODY_LEFT + BODY_W // 2
        self._save_rect = (
            body_cx - 70,
            SCREEN_H - FOOTER_H - SAVE_BTN_H - 4,
            140, SAVE_BTN_H,
        )

    # ---- layout -------------------------------------------------------------

    def OnStartup(self):
        self._chrome = ChromeView(self.rootGroup,
                                  title="config",
                                  back_target="home",
                                  bot_target="bot")

        label_w = 80
        value_x = BODY_LEFT + 8 + label_w + 4
        for i, (label, path, kind) in enumerate(FIELDS):
            row_y = LIST_TOP + i * ROW_H
            Label(
                label,
                root_group=self.rootGroup,
                dimensions=Dimensions(label_w, ROW_H),
                position=Position(BODY_LEFT + 8, row_y),
                default_style=Style(
                    font_size=12, font_color=TEXT_DIM,
                    horizontal_align=Align.Start,
                    vertical_align=Align.Center,
                ),
            )
            val_label = Label(
                "",
                root_group=self.rootGroup,
                dimensions=Dimensions(SCREEN_W - value_x - 4, ROW_H),
                position=Position(value_x, row_y),
                default_style=Style(
                    font_size=12, font_color=TEXT_PRIMARY,
                    horizontal_align=Align.Start,
                    vertical_align=Align.Center,
                ),
            )
            self._row_labels.append(val_label)

        # Save & reboot button. Drawn as a bordered rect with centered label;
        # the touch zone is the same rect (see _save_rect).
        sx, sy, sw, sh = self._save_rect
        self._save_btn = Rect(sx, sy, sw, sh,
                              fill=BG_SURFACE.value,
                              outline=ACCENT.value, stroke=1)
        self.rootGroup.append(self._save_btn)
        self._save_label = Label(
            "[ save & reboot ]",
            root_group=self.rootGroup,
            dimensions=Dimensions(sw, sh),
            position=Position(sx, sy),
            default_style=Style(
                font_size=12, font_color=ACCENT,
                horizontal_align=Align.Center,
                vertical_align=Align.Center,
            ),
        )

        # Status row below the save button — usable for "saving..." feedback.
        self._status = Label(
            "",
            root_group=self.rootGroup,
            dimensions=Dimensions(BODY_W - 12, 12),
            position=Position(BODY_LEFT + 6, SCREEN_H - FOOTER_H - 4),
            default_style=Style(
                font_size=12, font_color=TEXT_DIM,
                horizontal_align=Align.Center,
                vertical_align=Align.Start,
            ),
        )

        self._render_rows()

    # ---- rendering ----------------------------------------------------------

    def _current_value(self, idx):
        label, path, kind = FIELDS[idx]
        if kind == "api_key":
            value = _path_get(self.cfg, _api_key_path(self.cfg))
            return _mask(value)
        value = _path_get(self.cfg, path)
        if kind == "secret":
            return _mask(value)
        return value or "(empty)"

    def _render_rows(self):
        for i, lbl in enumerate(self._row_labels):
            text = self._current_value(i)
            prefix = "> " if i == self._sel else "  "
            if self._editing and i == self._sel:
                # Show the in-progress edit buffer instead of the stored value.
                kind = FIELDS[i][2]
                shown = "".join(self._edit_buf)
                if kind in ("secret", "api_key"):
                    shown = "*" * len(self._edit_buf)
                text = shown + "_"
            new = prefix + str(text)
            if lbl.text != new:
                lbl.text = new
                lbl._dirty = True
            lbl.style.font_color = ACCENT if i == self._sel else TEXT_PRIMARY
            lbl.draw()

    def _set_status(self, text, color=TEXT_DIM):
        self._status.text = text
        self._status.style.font_color = color
        self._status._dirty = True
        self._status.draw()

    # ---- input --------------------------------------------------------------

    def OnUpdate(self, delta_time):
        # Touch first (back button / row tap / save button)
        if self.touch.available:
            ev = self.touch.read()
            if ev["click"] and ev["x"] is not None:
                px, py = ev["x"], ev["y"]
                if not self._editing:
                    target = self._chrome.button_hit(px, py)
                    if target is not None:
                        self.app.SwitchScene(target)
                        return
                    if self._hit_save(px, py):
                        self._save_and_reboot()
                        return
                    row = self._hit_row(px, py)
                    if row is not None:
                        if row == self._sel:
                            self._enter_edit()
                        else:
                            self._sel = row
                            self._render_rows()
                        return

        # Trackball: navigate up/down, click = edit
        tb = self.trackball.read()
        if not self._editing and (tb["up"] or tb["down"]):
            delta = tb["down"] - tb["up"]
            self._sel = (self._sel + delta) % len(FIELDS)
            self._render_rows()
        if not self._editing and tb["click"]:
            self._enter_edit()
            return

        # Keyboard
        k = self.kbd.poll()
        if k:
            if self._editing:
                self._handle_edit_key(k)
            else:
                # BSP-on-list = exit home; ENTER = enter edit; provider toggle
                if k == KEY_BACKSPACE or k == KEY_ESC:
                    self.app.SwitchScene("home")
                    return
                if k == KEY_ENTER:
                    self._enter_edit()
                    return

    def _hit_row(self, px, py):
        if py < LIST_TOP or px < BODY_LEFT:
            return None
        idx = (py - LIST_TOP) // ROW_H
        if 0 <= idx < len(FIELDS):
            return idx
        return None

    def _hit_save(self, px, py):
        sx, sy, sw, sh = self._save_rect
        return sx <= px < sx + sw and sy <= py < sy + sh

    # ---- editing ------------------------------------------------------------

    def _enter_edit(self):
        label, path, kind = FIELDS[self._sel]
        if kind == "select":
            self._enter_select(label, path)
            return
        # text / secret / api_key: clear buffer and switch to typing
        self._editing = True
        self._edit_buf = []
        self._set_status("editing — ENTER to commit", ACCENT)
        self._render_rows()

    def _enter_select(self, label, path):
        """Open the modal Select for `path` and apply the user's pick.

        Provider and model both use this. Switching provider also resets
        model to the first option for the new provider — keeping the
        invariant that the stored model is always one the provider
        actually supports.
        """
        if path == ("agent", "provider"):
            options = list(PROVIDERS)
        elif path == ("agent", "model"):
            options = list(MODELS.get(self.cfg["agent"]["provider"], ()))
            if not options:
                self._set_status("no models for this provider", WARN)
                return
        elif path == ("ui", "header_height"):
            options = list(HEADER_HEIGHTS)
        else:
            return
        # The stored value may be an int (sidebar_width) but the Select
        # modal compares strings — coerce so the current value
        # highlights correctly when reopening the picker.
        current = _path_get(self.cfg, path)
        if not isinstance(current, str):
            current = str(current)
        picked = Select.show(
            self.rootGroup,
            title=label,
            options=options,
            current=current,
            kbd=self.kbd,
            trackball=self.trackball,
            touch=self.touch,
            backdrop=BG_MAIN,
            bg=BG_SURFACE,
            border=BORDER,
            title_color=ACCENT,
            text_color=TEXT_PRIMARY,
            text_dim=TEXT_DIM,
            accent=ACCENT,
        )
        if picked is None:
            self._set_status("cancelled")
            self._render_rows()
            return
        # Header height is the only numeric setting that flows through
        # the Select path. Convert back to int so theme.py reads the
        # right type on the next boot.
        if path == ("ui", "header_height"):
            try:
                picked_value = int(picked)
            except ValueError:
                self._set_status("invalid height", WARN)
                self._render_rows()
                return
            _path_set(self.cfg, path, picked_value)
        else:
            _path_set(self.cfg, path, picked)
        if path == ("agent", "provider"):
            # New provider — coerce model to a supported one.
            new_models = MODELS.get(picked, ())
            if new_models and self.cfg["agent"]["model"] not in new_models:
                self.cfg["agent"]["model"] = new_models[0]
        self._set_status(label + " -> " + picked, SUCCESS)
        self._render_rows()

    def _handle_edit_key(self, k):
        if k == KEY_ENTER:
            self._commit_edit()
            return
        if k == KEY_ESC:
            self._editing = False
            self._edit_buf = []
            self._set_status("cancelled")
            self._render_rows()
            return
        if k == KEY_BACKSPACE:
            if self._edit_buf:
                self._edit_buf.pop()
                self._render_rows()
            return
        if 0x20 <= k <= 0x7E:
            self._edit_buf.append(chr(k))
            self._render_rows()

    def _commit_edit(self):
        label, path, kind = FIELDS[self._sel]
        new_value = "".join(self._edit_buf)
        if kind == "api_key":
            _path_set(self.cfg, _api_key_path(self.cfg), new_value)
        else:
            _path_set(self.cfg, path, new_value)
        self._editing = False
        self._edit_buf = []
        self._set_status(label + " updated", SUCCESS)
        self._render_rows()

    # ---- save ---------------------------------------------------------------

    def _save_and_reboot(self):
        self._set_status("saving...", ACCENT)
        try:
            config.save(self.cfg)
        except Exception as e:
            self._set_status("save failed: " + str(e)[:40], WARN)
            return
        self._set_status("saved — rebooting", SUCCESS)
        # Tiny delay so the user sees the confirmation flash before reset.
        time.sleep(0.4)
        microcontroller.reset()

    def OnDraw(self):
        pass

    def OnShutdown(self):
        pass

    def GetRootGroup(self):
        return self.rootGroup

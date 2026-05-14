import time
import displayio
import microcontroller
from adafruit_display_shapes.line import Line
from adafruit_display_shapes.rect import Rect

from engine.application import IScene
from engine.display.ui.containers import AutoLayout
from engine.display.ui.elements import Label
from engine.display.ui.models import (
    Align, Dimensions, Flex, Position, Style,
)
from engine.display.ui.models.style import Direction

from client import config
from engine import wifi_helper
from client.views import ChromeView
from client.views.theme import (
    SCREEN_W, SCREEN_H, CHROME_H, FOOTER_H, BODY_INSET, BODY_LEFT, BODY_W,
    BG_MAIN, BORDER, TEXT_PRIMARY, TEXT_DIM, ACCENT, SUCCESS, WARN,
)

PROVIDERS = ("claude", "openai")
MODELS = {
    "claude": ("claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"),
    "openai": ("gpt-5", "gpt-5-mini"),
}

# Stage subtitles for the chrome bar.
STAGE_LABEL = {
    "welcome":  "1/5 boot",
    "wifi":     "2/5 wifi",
    "provider": "3/5 provider",
    "api_key":  "4/5 api key",
    "model":    "5/5 model",
    "done":     "complete",
}


def _label(root_group, text, size=12, h_align=Align.Start, dim=None, pos=None,
           color=TEXT_PRIMARY):
    return Label(
        text, root_group=root_group,
        dimensions=dim or Dimensions(SCREEN_W, 16),
        position=pos or Position(),
        default_style=Style(
            font_size=size,
            font_color=color,
            horizontal_align=h_align,
            vertical_align=Align.Center,
            padding=4,
        ),
    )


class BootWizardScene(IScene):
    def __init__(self, app):
        self.app = app
        self.kbd = app.GetKeyboard()
        self.rootGroup = displayio.Group()

        self._stage = "welcome"
        self._stage_started = False
        self._ssid = ""
        self._password = ""
        self._provider = "claude"
        self._api_key = ""
        self._model = "claude-opus-4-7"
        self._networks = []

        self._chrome = None
        self._title = None
        self._body_lines = []
        self._input_line = None
        self._hint = None
        self._page_layout = None

    def OnStartup(self):
        # No back button (no home yet) and no bot button (agent not
        # configured) — the wizard is a sequential first-boot flow.
        self._chrome = ChromeView(
            self.rootGroup,
            title="setup :: " + STAGE_LABEL[self._stage],
            back_target=None,
            bot_target=None,
        )

        # Body frame: hollow rect inset from body edges (not screen
        # edges — the sidebar lives at x < BODY_LEFT).
        frame_x = BODY_LEFT + BODY_INSET
        frame_y = CHROME_H + BODY_INSET
        frame_w = BODY_W - 2 * BODY_INSET
        frame_h = SCREEN_H - CHROME_H - FOOTER_H - 2 * BODY_INSET
        self._frame = Rect(frame_x, frame_y, frame_w, frame_h,
                           fill=BG_MAIN.value, outline=BORDER.value, stroke=1)
        self.rootGroup.append(self._frame)

        # Footer separator — only spans the body area.
        sep_y = SCREEN_H - FOOTER_H
        self._footer_sep = Line(BODY_LEFT, sep_y, SCREEN_W, sep_y, color=BORDER.value)
        self.rootGroup.append(self._footer_sep)

        # Page layout sits inside the frame with a small margin.
        body_w = frame_w - 8
        body_h = frame_h - 8
        self._page_layout = AutoLayout(
            root_group=self.rootGroup,
            position=Position(frame_x + 4, frame_y + 4),
            dimensions=Dimensions(body_w, body_h),
            default_style=Style(direction=Direction.Vertical, margin=2),
        )

        # Title row: bracketed accent text, like "[ FIRST-TIME SETUP ]".
        self._title = _label(self.rootGroup, "", size=12, h_align=Align.Center,
                             dim=Dimensions(body_w, 14, flex_y=Flex.Locked),
                             color=ACCENT)
        self._page_layout.add_element(self._title)

        # Thin spacer line under the title.
        self._title_spacer = _label(self.rootGroup, "",
                                    dim=Dimensions(body_w, 2, flex_y=Flex.Locked),
                                    color=BORDER)
        self._page_layout.add_element(self._title_spacer)

        # Body lines.
        for _ in range(5):
            lbl = _label(self.rootGroup, "",
                         dim=Dimensions(body_w, 14, flex_y=Flex.Locked),
                         color=TEXT_PRIMARY)
            self._page_layout.add_element(lbl)
            self._body_lines.append(lbl)

        # Input line (terminal-style "> _" prompt).
        self._input_line = _label(self.rootGroup, "",
                                  dim=Dimensions(body_w, 14, flex_y=Flex.Locked),
                                  color=ACCENT)
        self._page_layout.add_element(self._input_line)

        # Hint sits in the footer area below the frame.
        self._hint = _label(self.rootGroup, "",
                            dim=Dimensions(BODY_W - 12, 14, flex_y=Flex.Locked),
                            pos=Position(BODY_LEFT + 6, SCREEN_H - FOOTER_H + 2),
                            color=ACCENT)

    # ---- page rendering -----------------------------------------------------

    def _set_page(self, title, body_lines, hint=""):
        self._title.text = "[ {} ]".format(title.upper()) if title else ""
        for i, lbl in enumerate(self._body_lines):
            lbl.text = body_lines[i] if i < len(body_lines) else ""
        self._hint.text = hint
        self._input_line.text = ""
        self._flush()

    def _set_input(self, text):
        self._input_line.text = "> " + text + "_"
        self._flush()

    def _flush(self):
        # The wizard blocks on wait_key inside OnUpdate, so the main loop's
        # OnDraw won't run until the user presses something. Push pending
        # label changes to the displayio tree now so the prompt is visible
        # before we block.
        self._page_layout.draw()
        self._hint.draw()

    # ---- main loop ----------------------------------------------------------

    def OnUpdate(self, delta_time):
        if not self._stage_started:
            self._stage_started = True
            self._chrome.set_title("setup :: " + STAGE_LABEL[self._stage])
            self._run_stage()

    def _run_stage(self):
        if self._stage == "welcome":
            self._do_welcome()
        elif self._stage == "wifi":
            self._do_wifi()
        elif self._stage == "provider":
            self._do_provider()
        elif self._stage == "api_key":
            self._do_api_key()
        elif self._stage == "model":
            self._do_model()
        elif self._stage == "done":
            self._do_done()

    def _advance(self, next_stage):
        self._stage = next_stage
        self._stage_started = False

    # ---- stages -------------------------------------------------------------

    def _do_welcome(self):
        self._set_page(
            "first-time setup",
            ["",
             "cc-agent v0.1.0",
             "T-Deck terminal agent",
             "",
             ""],
            hint="[ANY KEY] continue",
        )
        self.kbd.wait_key()
        self._advance("wifi")

    def _do_wifi(self):
        boot = config.read_bootstrap_wifi()
        if boot:
            ssid, password = boot
            self._set_page("connecting wifi",
                           ["loaded /.bootstrap_wifi",
                            "(file deleted)",
                            "",
                            "ssid: " + ssid],
                           "")
            ok, msg = wifi_helper.connect(ssid, password, timeout_s=20)
            if ok:
                self._ssid, self._password = ssid, password
                self._advance("provider")
                return
            self._set_page("wifi failed",
                           ["", "reason: " + msg, "", "press any key for manual."],
                           "[ANY KEY] continue")
            self.kbd.wait_key()

        # manual flow
        while True:
            self._set_page("scanning wifi", ["...", ""], "")
            self._networks = wifi_helper.scan()
            if not self._networks:
                self._set_page("no networks",
                               ["", "press any key to retry."],
                               "[ANY KEY] retry")
                self.kbd.wait_key()
                continue
            choices = [
                "{}{} ({})".format("*" if n["secure"] else " ", n["ssid"][:24], n["rssi"])
                for n in self._networks[:5]
            ]
            idx = self._menu("pick wifi network", choices)
            if idx is None:
                continue
            chosen = self._networks[idx]
            pwd = ""
            if chosen["secure"]:
                pwd = self._input_text(
                    "wifi password",
                    ["network: " + chosen["ssid"]],
                    mask=True,
                )
                if pwd is None:
                    continue
            self._set_page("connecting", ["ssid: " + chosen["ssid"],
                                          "(up to 30s)"], "")
            ok, msg = wifi_helper.connect(chosen["ssid"], pwd, timeout_s=30)
            if ok:
                self._ssid, self._password = chosen["ssid"], pwd
                self._advance("provider")
                return
            self._set_page("connect failed",
                           ["reason: " + msg,
                            "password chars: " + str(len(pwd)),
                            "",
                            "press any key to retry."],
                           "[ANY KEY] retry")
            self.kbd.wait_key()

    def _do_provider(self):
        idx = self._menu("pick llm provider", list(PROVIDERS))
        self._provider = PROVIDERS[idx if idx is not None else 0]
        self._advance("api_key")

    def _do_api_key(self):
        boot = config.read_bootstrap_key()
        if boot:
            self._api_key = boot
            self._set_page("api key",
                           ["", "loaded /.bootstrap_key", "(file deleted)"],
                           "")
            time.sleep(0.7)
            self._advance("model")
            return
        key = self._input_text(
            "enter " + self._provider + " api key",
            ["type or paste via usb:"],
            mask=False, max_len=256,
        )
        self._api_key = key or ""
        self._advance("model")

    def _do_model(self):
        choices = list(MODELS.get(self._provider, ()))
        idx = self._menu("pick model", choices)
        self._model = choices[idx if idx is not None else 0]
        self._advance("done")

    def _do_done(self):
        cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in config.DEFAULTS.items()}
        cfg["wifi"] = {"ssid": self._ssid, "password": self._password}
        cfg["agent"]["provider"] = self._provider
        cfg["agent"]["model"] = self._model
        providers = {k: dict(v) for k, v in config.DEFAULTS["providers"].items()}
        providers[self._provider]["api_key"] = self._api_key
        cfg["providers"] = providers
        try:
            config.save(cfg)
        except OSError:
            self._set_page("save failed",
                           ["filesystem is read-only.",
                            "power-cycle without",
                            "holding the trackball,",
                            "then try setup again."],
                           "[ANY KEY] retry")
            self.kbd.wait_key()
            self._stage_started = False
            return
        self._set_page("setup complete", ["", "rebooting..."], "")
        time.sleep(0.6)
        microcontroller.reset()

    # ---- menu/input primitives (drive the existing body labels) ----

    def _menu(self, title, options):
        body = ["press 0..{} then ENTER:".format(max(0, len(options) - 1))]
        for i, opt in enumerate(options):
            body.append("  {}. {}".format(i, opt))
        self._set_page(title, body, "[0-9] pick   [ENTER] ok   [ESC] cancel")
        return self._read_index(len(options))

    def _read_index(self, n):
        def on_change(s):
            self._set_input(s)
        on_change("")
        raw = self.kbd.read_line(on_change, max_len=2)
        if raw is None or raw == "":
            return None
        try:
            i = int(raw)
        except ValueError:
            return None
        return i if 0 <= i < n else None

    def _input_text(self, title, body, mask=False, max_len=128):
        self._set_page(title, body, "[ENTER] ok   [ESC] cancel   [BKSP] delete")

        def on_change(s):
            view = s[-38:]
            self._set_input(view)
        on_change("")
        return self.kbd.read_line(on_change, mask=mask, max_len=max_len)

    def OnDraw(self):
        self._page_layout.draw()
        self._hint.draw()

    def OnShutdown(self):
        pass

    def GetRootGroup(self):
        return self.rootGroup

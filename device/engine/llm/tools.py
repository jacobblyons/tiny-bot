"""Tools the agent can call to inspect and modify the device.

Each tool is described in `TOOL_SPECS` (the `tools` array sent to the API)
and dispatched by `execute(name, inputs, app=None)`. Every tool returns a
string (success or error). Errors start with "ERROR:".

The optional `app` parameter is the running App instance — required for any
tool that needs to register scenes, switch scenes, or trigger restarts.
"""
import gc
import os
import sys

APPS_DIR = "/sd/apps"
WIDGETS_DIR = "/sd/widgets"


# Path-prefixes that the agent must not overwrite — bricking the device costs
# a re-flash. Add to this list as we add critical files.
PROTECTED_PATHS = (
    "/boot.py",
    "/code.py",
    "/.dev",
    "/config.json",
)


TOOL_SPECS = [
    {
        "name": "read_file",
        "description": (
            "Read a text file from the device's flash or SD card. "
            "Output starts with a header like "
            "'=== /path (N lines, B bytes); showing X-Y ==='. Each "
            "returned line is prefixed with its 1-based line number. "
            "Without start_line/end_line the response is capped at the "
            "first 12 KB — most source files fit in a single read at "
            "that size. For larger files the header tells you the total "
            "size and you can narrow with start_line/end_line. A "
            "typical workflow: call read_file once and only re-read "
            "with a narrower window if the first response was truncated."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path, e.g. /code.py or /sd/apps/snake.py."
                },
                "start_line": {
                    "type": "integer",
                    "description": "Optional 1-based first line to include. Omit to start at 1."
                },
                "end_line": {
                    "type": "integer",
                    "description": (
                        "Optional 1-based last line to include (inclusive). "
                        "Omit to read to EOF. The slice still caps at 12 KB; "
                        "if you get '[truncated]' the range is too wide."
                    )
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write a text file (creating it if needed). Overwrites any "
            "existing content. New apps should live under /sd/."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_dir",
        "description": "List the entries in a directory. Marks directories with a trailing '/'.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "delete_file",
        "description": "Delete a file. Won't touch protected system files.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "device_info",
        "description": "Report free RAM, wifi IP, current scene, registered scenes.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_apps",
        "description": (
            "List app modules under /sd/apps/. Returns one app name per line."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "reorder_apps",
        "description": (
            "Set the display order of the home-screen carousel. "
            "Pass `order` as a list of names — both built-in scene "
            "names (config, system) and app .py basenames are valid; "
            "they can be interleaved in any order. Listed names show "
            "first in the given sequence; unlisted entries fall "
            "through to the natural default (built-ins first, then "
            "apps alphabetically), so a freshly-installed app never "
            "disappears. Order persists to /sd/state/apps_order.json "
            "and takes effect the next time the home scene is built. "
            "To make the change visible immediately when the user is "
            "currently on home, follow this with switch_scene 'home'. "
            "Use list_apps for the app list; built-ins are: config, "
            "system."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Names in desired display order. May include "
                        "both built-in scene names and app names."
                    ),
                }
            },
            "required": ["order"],
        },
    },
    {
        "name": "launch_app",
        "description": (
            "Import an app module and switch to its Scene. The app file must "
            "be at /sd/apps/<name>.py and must define a class named `Scene` "
            "implementing the IScene interface (OnStartup/OnUpdate/OnDraw/"
            "OnShutdown/GetRootGroup, plus an `__init__(self, app)`). The "
            "scene gets registered under <name> so future switches are cheap."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "App name (the .py basename, no extension)"}
            },
            "required": ["name"],
        },
    },
    {
        "name": "switch_scene",
        "description": (
            "Switch to an already-registered scene by name. Built-ins: "
            "home, bot, config, system, wizard. Apps registered via "
            "launch_app are also available by their app name."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "install_widget",
        "description": (
            "Install (or replace) a home-screen widget. Writes the supplied "
            "Python source to /sd/widgets/<name>.py. The widget module must "
            "define `class Widget` with `__init__(self, app)`, `build(self, "
            "group, x, y, w, h)` and optionally `update(self, delta_time)`. "
            "It should also set `TITLE = '<name shown in card chrome>'`. "
            "After installing, switch to the home scene (or call switch_scene "
            "home) so the launcher picks it up. Broken widgets render an "
            "error card and won't crash the home screen."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Widget identifier (no extension, no slashes)."
                },
                "source": {
                    "type": "string",
                    "description": "Full Python source for the widget module."
                },
            },
            "required": ["name", "source"],
        },
    },
    {
        "name": "list_widgets",
        "description": "List widgets in /sd/widgets/. Returns one name per line.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "grep",
        "description": (
            "Search for a substring across text files under a path. "
            "Recursive by default. Returns one match per line as "
            "'<path>:<lineno>: <line snippet>'. Only files with known "
            "text extensions are scanned (.py, .txt, .json, .md, .toml, "
            ".cfg, .ini) — binary files are skipped. Output is capped, "
            "narrow the path if you hit '[truncated]'. Cheaper than "
            "read_file when you only need to locate something."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Substring to search for (not a regex)."
                },
                "path": {
                    "type": "string",
                    "description": "File or directory to search. Use '/' for whole device."
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Recurse into subdirectories. Defaults to true."
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "Case-sensitive match. Defaults to false."
                }
            },
            "required": ["pattern", "path"],
        },
    },
    {
        "name": "find",
        "description": (
            "Find files or directories by name under a path. The pattern "
            "is a simple glob: '*' is a wildcard, anything without '*' "
            "is a substring match against the basename. Returns one path "
            "per line; directories are marked with a trailing '/'. "
            "Examples: pattern='*.py' finds all Python files; "
            "pattern='scene' finds anything with 'scene' in the name."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob or substring to match the basename against."
                },
                "path": {
                    "type": "string",
                    "description": "Root directory to walk."
                },
                "kind": {
                    "type": "string",
                    "description": "'file', 'dir', or 'any' (default 'any')."
                }
            },
            "required": ["pattern", "path"],
        },
    },
    {
        "name": "stat_path",
        "description": (
            "Report basic info about a path: file vs directory, size in "
            "bytes, and approximate line count for files. Useful before "
            "deciding whether to read a file or narrow with line ranges."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "snapshot_scene",
        "description": (
            "Snapshot the scene that launched the bot. When the user "
            "opens the bot from inside an app, the app's displayio "
            "group is stashed as `app.bot_previous_group`. This tool "
            "walks that stashed group — no off-screen construction, "
            "no side effects. Returns an indented tree of the "
            "displayio tree (Group / Label / Rect with positions + "
            "text). Pass format='image' for a 160x120 grayscale GIF "
            "showing the rough block layout. Output capped at 8 KB. "
            "Returns ERROR if the user opened the bot from a fresh "
            "boot (no previous scene to snapshot)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "description": (
                        "'text' (default) returns the displayio tree. "
                        "'image' renders a low-res GIF showing block "
                        "layout — useful when you need to actually SEE "
                        "rather than read coordinates."
                    )
                }
            },
        },
    },
    {
        "name": "run_code",
        "description": (
            "Execute Python source in the live runtime and return what "
            "it printed (stdout + stderr, combined). Use this to inspect "
            "device state, run quick experiments, or probe hardware "
            "without writing an app file or switching scenes. The "
            "running App instance is injected as `app` in the namespace, "
            "so e.g. `print(list(app._scenes))` works directly. "
            "Anything imported or mutated persists in the current "
            "session. Caveats: runs synchronously and blocks the chat "
            "until the snippet finishes (no timeout), and exceptions "
            "are caught and returned as the traceback rather than "
            "raised. Output is capped at 8 KB."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": (
                        "Python source. Print whatever you want to see. "
                        "Multi-line is fine; use real newlines."
                    )
                }
            },
            "required": ["code"],
        },
    },
    {
        "name": "restart_runtime",
        "description": (
            "Soft-reload code.py via supervisor.reload(). Use this after "
            "writing changes to /client/, /engine/, or /harness/ files so "
            "the new code takes effect. Faster than a hard reset and "
            "preserves wifi connection state."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "hard_reset",
        "description": (
            "Full microcontroller reset. Required after editing /boot.py "
            "since boot.py only runs on cold boot. This also disconnects "
            "wifi and the USB serial link briefly."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


def _is_protected(path):
    return path in PROTECTED_PATHS


# Per-read byte cap. Bigger means fewer round-trips on multi-step tasks,
# which is the dominant cost under per-minute rate limits now that the
# static prompt prefix is cached (so only the tool-call delta counts
# per request). 12 KB covers most source files in this repo in a
# single shot; the chunked-slice path is still available for the few
# files larger than that.
_READ_CHUNK_CAP = 12288


def _number_lines(lines, start_lineno):
    """Render `lines` with 1-based line-number prefixes.

    `lines` is a list of strings without trailing newlines (the output
    of split('\\n')); `start_lineno` is the 1-based line number that
    the first element corresponds to in the original file.
    """
    return "\n".join(
        "{:4d}: {}".format(start_lineno + i, ln)
        for i, ln in enumerate(lines)
    )


def _read_file(path, start_line=None, end_line=None):
    """Read a text file with optional line-range slicing.

    Always emits a metadata header so the agent can tell at a glance
    how big the file is and what slice it's looking at — that's the
    only way a chunked-read workflow stays honest. The cheap "no range
    given" path still only reads 4 KB off disk, so default behavior
    doesn't pay for a full file slurp on every read.
    """
    try:
        size = os.stat(path)[6]
    except OSError as e:
        return "ERROR: stat {}: {}".format(path, e)

    if start_line is None and end_line is None:
        # Fast path: read up to 4 KB and report whether more remains.
        try:
            with open(path, "r") as f:
                chunk = f.read(_READ_CHUNK_CAP)
        except OSError as e:
            return "ERROR: read {}: {}".format(path, e)
        truncated = size > len(chunk)
        # Count lines visible in this chunk for the header.
        chunk_lines = chunk.split("\n")
        if truncated:
            # The chunk almost certainly ends mid-line — drop the
            # incomplete tail so the line count in the header isn't a
            # half-line off, and the agent's next read can pick up
            # cleanly at the next-line boundary.
            chunk_lines = chunk_lines[:-1]
        body = _number_lines(chunk_lines, 1)
        header = "=== {} ({} bytes{}); showing lines 1-{} ===\n".format(
            path, size,
            ", truncated at 12 KB — narrow with start_line/end_line"
            if truncated else "",
            len(chunk_lines))
        return header + body

    # Line-slice path: must read the whole file so we know the total
    # line count and can slice precisely. Acceptable cost — source
    # files on this device top out at tens of KB.
    try:
        with open(path, "r") as f:
            content = f.read()
    except OSError as e:
        return "ERROR: read {}: {}".format(path, e)
    all_lines = content.split("\n")
    total_lines = len(all_lines)
    s = start_line if start_line is not None else 1
    e = end_line if end_line is not None else total_lines
    if s < 1:
        s = 1
    if e > total_lines:
        e = total_lines
    if s > e:
        return ("ERROR: empty range start_line={} > end_line={} "
                "(file has {} lines)").format(s, e, total_lines)
    sliced = all_lines[s - 1:e]
    body = _number_lines(sliced, s)
    truncated_msg = ""
    if len(body) > _READ_CHUNK_CAP:
        body = body[:_READ_CHUNK_CAP]
        truncated_msg = ("\n...[truncated at 12 KB; pick a narrower "
                         "start_line/end_line range]")
    header = "=== {} ({} lines, {} bytes); showing lines {}-{} ===\n".format(
        path, total_lines, size, s, e)
    return header + body + truncated_msg


def _write_file(path, content):
    if _is_protected(path):
        return "ERROR: refusing to write protected path " + path
    # Ensure parent directory exists.
    if "/" in path[1:]:
        parent = path.rsplit("/", 1)[0]
        if parent and parent != "":
            try:
                os.stat(parent)
            except OSError:
                # Best-effort mkdir -p.
                cur = ""
                for part in parent.split("/"):
                    if not part:
                        continue
                    cur = cur + "/" + part
                    try:
                        os.mkdir(cur)
                    except OSError:
                        pass
    with open(path, "w") as f:
        f.write(content)
    return "wrote {} bytes to {}".format(len(content), path)


def _list_dir(path):
    entries = []
    for name in os.listdir(path):
        full = (path.rstrip("/") + "/" + name) if path != "/" else "/" + name
        try:
            st = os.stat(full)
            is_dir = (st[0] & 0x4000) != 0
            size = st[6]
        except OSError:
            is_dir, size = False, 0
        if is_dir:
            entries.append(name + "/")
        else:
            entries.append("{} ({}B)".format(name, size))
    if not entries:
        return "(empty)"
    return "\n".join(sorted(entries))


def _delete_file(path):
    if _is_protected(path):
        return "ERROR: refusing to delete protected path " + path
    os.remove(path)
    return "deleted " + path


def _device_info(app):
    gc.collect()
    free = gc.mem_free()
    try:
        import wifi
        ip = str(wifi.radio.ipv4_address) if wifi.radio.ipv4_address else "(none)"
    except Exception:
        ip = "?"
    scenes = "(unknown)"
    current = "(unknown)"
    if app is not None:
        try:
            scenes = ", ".join(sorted(app._scenes.keys()))
            current = app._current_scene_name
        except Exception:
            pass
    return ("free_mem: {}\nwifi_ip: {}\ncurrent_scene: {}\nscenes: {}"
            .format(free, ip, current, scenes))


def _list_apps():
    try:
        names = []
        for entry in os.listdir(APPS_DIR):
            if entry.endswith(".py"):
                names.append(entry[:-3])
            elif "." not in entry:
                # Could be a package directory.
                try:
                    os.stat(APPS_DIR + "/" + entry + "/__init__.py")
                    names.append(entry)
                except OSError:
                    pass
        if not names:
            return "(no apps in {} yet)".format(APPS_DIR)
        return "\n".join(sorted(names))
    except OSError as e:
        return "ERROR: {} not accessible ({}). Is the SD card mounted?".format(APPS_DIR, e)


APPS_ORDER_PATH = "/sd/state/apps_order.json"


def _reorder_apps(order):
    """Persist a custom app order to /sd/state/apps_order.json.

    The carousel's `discover_apps` reads this file: listed apps appear
    first in the given sequence; unlisted apps fall through to alpha
    ordering. Validation: every entry must be a non-empty string with
    no '/' or leading '.'. Apps that don't exist on disk yet are kept
    in the list anyway (the agent might be staging an order ahead of
    a future install).
    """
    import json
    if not isinstance(order, list):
        return "ERROR: order must be a list of app names"
    cleaned = []
    seen = set()
    for n in order:
        if not isinstance(n, str) or not n:
            return "ERROR: order entries must be non-empty strings"
        if "/" in n or n.startswith("."):
            return "ERROR: invalid app name {!r}".format(n)
        if n in seen:
            return "ERROR: duplicate app name in order: {!r}".format(n)
        seen.add(n)
        cleaned.append(n)

    # Best-effort mkdir for /sd/state.
    try:
        os.stat("/sd/state")
    except OSError:
        try:
            os.mkdir("/sd/state")
        except OSError as e:
            return "ERROR: could not create /sd/state: {}".format(e)

    tmp = APPS_ORDER_PATH + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(cleaned, f)
        os.rename(tmp, APPS_ORDER_PATH)
    except (OSError, ValueError) as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return "ERROR: write {}: {}".format(APPS_ORDER_PATH, e)

    return ("wrote order ({} entries) to {}. The home carousel will "
            "use this order next time it builds. Call switch_scene "
            "'home' to refresh immediately.").format(
                len(cleaned), APPS_ORDER_PATH)


def _launch_app(app, name):
    if app is None:
        return "ERROR: launch_app needs app context"
    if not name or "/" in name or name.startswith("."):
        return "ERROR: invalid app name '{}'".format(name)
    # Drop any cached version so edits are picked up.
    if name in sys.modules:
        del sys.modules[name]
    try:
        mod = __import__(name)
    except Exception as e:
        # Broad catch: a SyntaxError or attribute error at import time
        # is just as fatal as an ImportError for our purposes.
        return "ERROR: import failed: {}: {}".format(type(e).__name__, e)
    cls = getattr(mod, "Scene", None)
    if cls is None:
        return "ERROR: {} has no `Scene` class".format(name)
    try:
        app.RegisterScene(name, cls)
    except ValueError as e:
        # Reserved name guard — see App.RESERVED_SCENES.
        return "ERROR: {}".format(e)
    app.SwitchScene(name)
    return "registered and switching to scene '{}'".format(name)


def _switch_scene(app, name):
    if app is None:
        return "ERROR: switch_scene needs app context"
    # "chat" is a legacy alias for "bot"; App.SwitchScene maps it.
    if name == "chat":
        app.SwitchScene("bot")
        return "switching to scene 'bot' (chat is a legacy alias)"
    if name not in app._scenes:
        return "ERROR: unknown scene '{}'. Known: {}".format(
            name, ", ".join(sorted(app._scenes.keys())))
    app.SwitchScene(name)
    return "switching to scene '{}'".format(name)


def _install_widget(name, source):
    if not name or "/" in name or name.startswith("."):
        return "ERROR: invalid widget name '{}'".format(name)
    # Best-effort mkdir for /sd/widgets/.
    try:
        os.stat(WIDGETS_DIR)
    except OSError:
        try:
            os.mkdir(WIDGETS_DIR)
        except OSError as e:
            return "ERROR: could not create {}: {}".format(WIDGETS_DIR, e)
    path = WIDGETS_DIR + "/" + name + ".py"
    with open(path, "w") as f:
        f.write(source)
    # Drop any cached module so a re-install picks up new source.
    if name in sys.modules:
        del sys.modules[name]
    return ("wrote {} bytes to {}. "
            "switch_scene home to see it on the launcher.").format(len(source), path)


def _list_widgets():
    try:
        names = []
        for entry in os.listdir(WIDGETS_DIR):
            if entry.endswith(".py") and not entry.startswith("_"):
                names.append(entry[:-3])
        if not names:
            return "(no widgets in {} yet)".format(WIDGETS_DIR)
        return "\n".join(sorted(names))
    except OSError:
        return "(no widgets dir yet — install_widget will create it)"


# File extensions considered text-y enough to scan with grep. Anything
# else is presumably binary (mpy, png, font blobs) and skipped silently.
_TEXT_EXTS = (".py", ".txt", ".json", ".md", ".toml", ".cfg", ".ini")

# Output budget for grep/find. Sized below MAX_TOOL_RESULT_BYTES so the
# agent gets a clean "[truncated]" hint rather than a hard cut.
_SEARCH_RESULT_CAP = 8000
_GREP_MAX_HITS = 100
_FIND_MAX_HITS = 200


def _iter_files(path, recursive=True):
    """Yield every file path under `path`. If `path` is itself a file,
    yields just that path. Directories themselves are not yielded —
    callers that need them (find) walk separately."""
    try:
        st = os.stat(path)
    except OSError:
        return
    if (st[0] & 0x4000) == 0:
        yield path
        return
    if not recursive:
        try:
            entries = os.listdir(path)
        except OSError:
            return
        for name in entries:
            full = (path.rstrip("/") + "/" + name) if path != "/" else "/" + name
            try:
                sst = os.stat(full)
            except OSError:
                continue
            if (sst[0] & 0x4000) == 0:
                yield full
        return
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            entries = os.listdir(cur)
        except OSError:
            continue
        for name in entries:
            full = (cur.rstrip("/") + "/" + name) if cur != "/" else "/" + name
            try:
                sst = os.stat(full)
            except OSError:
                continue
            if (sst[0] & 0x4000) != 0:
                stack.append(full)
            else:
                yield full


def _glob_match(pattern, name):
    """Tiny glob matcher. '*' is the only wildcard; patterns without
    '*' are treated as substring matches (so the agent doesn't have
    to spell out '*foo*' constantly)."""
    if "*" not in pattern:
        return pattern in name
    parts = pattern.split("*")
    if parts[0] and not name.startswith(parts[0]):
        return False
    if parts[-1] and not name.endswith(parts[-1]):
        return False
    pos = 0
    for p in parts:
        if not p:
            continue
        idx = name.find(p, pos)
        if idx < 0:
            return False
        pos = idx + len(p)
    return True


def _grep(pattern, path, recursive=True, case_sensitive=False):
    if not pattern:
        return "ERROR: pattern is required"
    needle = pattern if case_sensitive else pattern.lower()
    hits = []
    bytes_so_far = 0
    files_scanned = 0
    truncated = False
    for full in _iter_files(path, recursive=recursive):
        # Filter by extension — keeps us from streaming megabytes of
        # binary blobs (mpy modules, font assets) line by line.
        if "." not in full:
            continue
        ext = "." + full.rsplit(".", 1)[1].lower()
        if ext not in _TEXT_EXTS:
            continue
        files_scanned += 1
        try:
            with open(full, "r") as f:
                lineno = 0
                for line in f:
                    lineno += 1
                    line = line.rstrip("\n").rstrip("\r")
                    hay = line if case_sensitive else line.lower()
                    if needle in hay:
                        snippet = line if len(line) <= 120 else line[:117] + "..."
                        entry = "{}:{}: {}".format(full, lineno, snippet)
                        hits.append(entry)
                        bytes_so_far += len(entry) + 1
                        if (len(hits) >= _GREP_MAX_HITS
                                or bytes_so_far >= _SEARCH_RESULT_CAP):
                            truncated = True
                            break
        except (OSError, UnicodeError):
            # Best-effort: a single unreadable file shouldn't fail the
            # whole search. UnicodeError catches the rare binary file
            # that sneaks past the extension filter.
            continue
        if truncated:
            break
    if not hits:
        return "(no matches; scanned {} files under {})".format(
            files_scanned, path)
    out = "\n".join(hits)
    if truncated:
        out += "\n...[truncated; narrow the path or pattern]"
    return out


def _find(pattern, path, kind="any"):
    if not pattern:
        return "ERROR: pattern is required"
    if kind not in ("any", "file", "dir"):
        return "ERROR: kind must be 'any', 'file', or 'dir'"
    hits = []
    truncated = False
    # Walk the tree iteratively so deeply nested trees don't blow the stack.
    try:
        os.stat(path)
    except OSError as e:
        return "ERROR: stat {}: {}".format(path, e)
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            st = os.stat(cur)
        except OSError:
            continue
        is_dir = (st[0] & 0x4000) != 0
        # Don't try to match the root path itself — the user just told us
        # where to start, so reporting it as a hit would be noise.
        if cur != path:
            basename = cur.rsplit("/", 1)[-1]
            type_ok = (kind == "any"
                       or (kind == "file" and not is_dir)
                       or (kind == "dir" and is_dir))
            if type_ok and _glob_match(pattern, basename):
                hits.append(cur + ("/" if is_dir else ""))
                if len(hits) >= _FIND_MAX_HITS:
                    truncated = True
                    break
        if is_dir:
            try:
                entries = os.listdir(cur)
            except OSError:
                continue
            for name in entries:
                full = (cur.rstrip("/") + "/" + name) if cur != "/" else "/" + name
                stack.append(full)
    if not hits:
        return "(no matches under {})".format(path)
    out = "\n".join(sorted(hits))
    if truncated:
        out += "\n...[truncated; narrow the path or pattern]"
    return out


def _stat_path(path):
    try:
        st = os.stat(path)
    except OSError as e:
        return "ERROR: stat {}: {}".format(path, e)
    is_dir = (st[0] & 0x4000) != 0
    size = st[6]
    if is_dir:
        try:
            count = len(os.listdir(path))
        except OSError:
            count = "?"
        return "{} (dir, {} entries)".format(path, count)
    # Approximate line count: scan in chunks counting newlines. Cheap
    # even on the biggest source files we see here.
    lines = 0
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(2048)
                if not chunk:
                    break
                lines += chunk.count(b"\n")
    except OSError:
        lines = "?"
    return "{} (file, {} bytes, ~{} lines)".format(path, size, lines)


# Output cap for run_code. Sized below MAX_TOOL_RESULT_BYTES so the
# agent sees a clean "[truncated]" rather than a hard cut mid-line.
_RUN_CODE_OUT_CAP = 8192


_SNAPSHOT_OUT_CAP = 8192


def _dump_display_node(node, depth, out):
    """Recursively render a displayio node as text.

    A node is treated as a Label leaf if it has a string `.text`
    attribute — that catches `adafruit_display_text.label.Label`
    (which is itself a Group subclass, so we'd otherwise recurse
    into its internal bitmap children which aren't user-meaningful).
    """
    indent = "  " * depth
    text_attr = getattr(node, "text", None)
    if isinstance(text_attr, str):
        cname = type(node).__name__
        x = getattr(node, "x", "?")
        y = getattr(node, "y", "?")
        shown = text_attr if len(text_attr) <= 80 else text_attr[:77] + "..."
        out.append("{}{} @ ({},{}) text={!r}".format(
            indent, cname, x, y, shown))
        return
    import displayio
    if isinstance(node, displayio.Group):
        try:
            n = len(node)
        except Exception:
            n = 0
        x = getattr(node, "x", 0)
        y = getattr(node, "y", 0)
        out.append("{}Group({} children) @ ({},{})".format(indent, n, x, y))
        for i in range(n):
            try:
                _dump_display_node(node[i], depth + 1, out)
            except Exception as e:
                out.append("{}  <child {} unreadable: {}>".format(
                    indent, i, e))
        return
    # Generic leaf (Rect/Line/Circle wrap a TileGrid; TileGrid itself,
    # raw Bitmap, OnDiskBitmap, etc.).
    cname = type(node).__name__
    x = getattr(node, "x", "?")
    y = getattr(node, "y", "?")
    extras = []
    for attr in ("width", "height", "tile_width", "tile_height"):
        v = getattr(node, attr, None)
        if isinstance(v, int):
            short = attr[0] if "_" not in attr else attr.split("_")[1][0]
            extras.append("{}={}".format(short, v))
    extra = (" " + " ".join(extras)) if extras else ""
    out.append("{}{} @ ({},{}){}".format(indent, cname, x, y, extra))


# Image-snapshot config. Small target dimensions keep the bitmap +
# GIF inside the device's tight RAM budget; the bot doesn't need
# pixel fidelity to see "the widget overlaps the carousel".
_SNAP_IMG_W = 160
_SNAP_IMG_H = 120
_SNAP_IMG_PATH = "/snapshot.gif"
_DEVICE_W = 320
_DEVICE_H = 240


def _rgb_to_luminance(rgb_int):
    """Standard Y' luminance from an RGB888 int. Returns 0-255."""
    r = (rgb_int >> 16) & 0xFF
    g = (rgb_int >> 8) & 0xFF
    b = rgb_int & 0xFF
    return (r * 299 + g * 587 + b * 114) // 1000


def _tilegrid_luminance(tg):
    """Pick a representative luminance for a TileGrid.

    Most of our shapes (Rect, Line) store the fill at palette[1]
    with index 0 reserved transparent. If palette[1] isn't usable,
    fall back to scanning the palette for any non-transparent slot.
    """
    palette = getattr(tg, "pixel_shader", None)
    if palette is None:
        return 200  # bright default
    try:
        n = len(palette)
    except Exception:
        n = 0
    for i in range(1, n):
        try:
            if palette.is_transparent(i):
                continue
            return _rgb_to_luminance(palette[i])
        except Exception:
            continue
    # Nothing non-transparent above 0 — try slot 0 itself.
    try:
        return _rgb_to_luminance(palette[0])
    except Exception:
        return 200


def _walk_render(node, bmp, ox, oy, sx, sy):
    """Walk a displayio node and stamp each TileGrid as a filled
    rectangle into `bmp`, scaled by (sx, sy) and offset by (ox, oy).

    We treat Labels (Group subclasses) the same as Groups — their
    internal glyph TileGrids fall out naturally as small rectangles,
    which is exactly what we want for visualizing "there's text here".
    """
    import displayio
    import bitmaptools

    if isinstance(node, displayio.Group):
        gx = ox + getattr(node, "x", 0)
        gy = oy + getattr(node, "y", 0)
        try:
            n = len(node)
        except Exception:
            return
        for i in range(n):
            try:
                _walk_render(node[i], bmp, gx, gy, sx, sy)
            except Exception:
                continue
        return

    if isinstance(node, displayio.TileGrid):
        # Absolute pixel rectangle of this tile grid on the source
        # 320x240 canvas. tile_width/height × width/height in tiles
        # gives the on-screen extent.
        try:
            tx = ox + node.x
            ty = oy + node.y
            tw = node.tile_width * node.width
            th = node.tile_height * node.height
        except Exception:
            return
        # Scale to destination bitmap and clamp inside its bounds.
        dx1 = int(tx * sx)
        dy1 = int(ty * sy)
        dx2 = int((tx + tw) * sx)
        dy2 = int((ty + th) * sy)
        if dx2 <= dx1:
            dx2 = dx1 + 1
        if dy2 <= dy1:
            dy2 = dy1 + 1
        if dx1 < 0:
            dx1 = 0
        if dy1 < 0:
            dy1 = 0
        if dx2 > _SNAP_IMG_W:
            dx2 = _SNAP_IMG_W
        if dy2 > _SNAP_IMG_H:
            dy2 = _SNAP_IMG_H
        if dx2 <= dx1 or dy2 <= dy1:
            return
        lum = _tilegrid_luminance(node)
        try:
            bitmaptools.fill_region(bmp, dx1, dy1, dx2, dy2, lum)
        except Exception:
            pass


def _render_scene_gif(group):
    """Render `group` to a downsampled grayscale GIF and return the
    base64-encoded bytes. Writes to /snapshot.gif as an intermediate."""
    import displayio
    import bitmaptools
    import gifio
    import binascii

    bmp = displayio.Bitmap(_SNAP_IMG_W, _SNAP_IMG_H, 256)
    # Dark background — matches the theme's BG_MAIN so the image
    # reads roughly like the real screen at a glance.
    bitmaptools.fill_region(bmp, 0, 0, _SNAP_IMG_W, _SNAP_IMG_H, 20)
    sx = _SNAP_IMG_W / _DEVICE_W
    sy = _SNAP_IMG_H / _DEVICE_H
    _walk_render(group, bmp, 0, 0, sx, sy)
    # Delete any prior snapshot file so the writer starts clean.
    try:
        os.remove(_SNAP_IMG_PATH)
    except OSError:
        pass
    writer = gifio.GifWriter(
        _SNAP_IMG_PATH, _SNAP_IMG_W, _SNAP_IMG_H,
        displayio.Colorspace.L8, dither=False,
    )
    try:
        writer.add_frame(bmp, 0.1)
    finally:
        try:
            writer.deinit()
        except Exception:
            pass
    # Read back the encoded GIF and base64 it. Done in a single read —
    # snapshot files top out at ~15 KB so this fits easily in RAM.
    with open(_SNAP_IMG_PATH, "rb") as f:
        raw = f.read()
    return binascii.b2a_base64(raw, newline=False).decode("ascii"), len(raw)


def _snapshot_scene(app, format="text"):
    """Dump the displayio tree of the scene that launched the bot.

    When the user opens the bot from inside an app, App.SwitchScene
    stashes the launching scene's root group on `app.bot_previous_group`
    before tearing the scene down. We walk that stashed group — no
    off-screen construction, no side effects.
    """
    if app is None:
        return "ERROR: snapshot_scene needs app context"
    scene_group = getattr(app, "bot_previous_group", None)
    if scene_group is None:
        return ("ERROR: no previous scene to snapshot. The bot was opened "
                "from a fresh boot or the previous scene's group is no "
                "longer available.")
    out = []
    out.append("=== snapshot: previous scene (before bot) ===")
    _dump_display_node(scene_group, 0, out)
    text = "\n".join(out)
    if len(text) > _SNAPSHOT_OUT_CAP:
        text = text[:_SNAPSHOT_OUT_CAP] + "\n...[truncated]"

    if format == "image":
        gc.collect()
        try:
            b64, raw_len = _render_scene_gif(scene_group)
        except Exception as e:
            return ("ERROR: image render failed: {}: {}\n--- text tree ---\n"
                    + text).format(type(e).__name__, e)
        gc.collect()
        return [
            {"type": "text",
             "text": "{}\n--- gif: {}x{} L8, {} bytes ---".format(
                 text, _SNAP_IMG_W, _SNAP_IMG_H, raw_len)},
            {"type": "image", "source": {
                "type": "base64",
                "media_type": "image/gif",
                "data": b64,
            }},
        ]

    return text


def _run_code(app, source):
    """Exec `source` in a scratch namespace, capturing whatever it prints.

    CircuitPython makes `sys.stdout` read-only, so the usual
    "redirect stdout to a StringIO" trick won't work — we have to
    intercept `print` itself. We inject a captured-print into the
    exec namespace that writes into our buffer; user code that calls
    `print(...)` resolves the builtin via the namespace and hits ours
    first. (Native modules that print internally still go to real
    stdout, but for diagnostic snippets this is what we want.)

    On exception we append the traceback so the agent can see exactly
    where the snippet died. The runtime is shared — imports, side
    effects, and mutations persist after this returns.
    """
    if not isinstance(source, str) or not source:
        return "ERROR: code is required (string)"
    import io
    import sys
    buf = io.StringIO()

    def _captured_print(*args, **kwargs):
        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        # The `file=` kwarg is intentionally ignored; everything routes
        # to our buffer so the agent always gets the output back.
        buf.write(sep.join(str(a) for a in args))
        buf.write(end)

    # Pre-seed the namespace so common entry points (`app`, `gc`, `os`,
    # `sys`) don't need an `import` line for one-liners. `print` is
    # overridden to our capturing version.
    ns = {
        "__name__": "__main__",
        "app": app,
        "gc": gc,
        "os": os,
        "sys": sys,
        "print": _captured_print,
    }
    err_repr = None
    try:
        exec(source, ns)
    except Exception as e:
        err_repr = "{}: {}".format(type(e).__name__, e)
        try:
            import traceback
            traceback.print_exception(
                type(e), e,
                getattr(e, "__traceback__", None),
                file=buf,
            )
        except Exception:
            # Some CP traceback shapes refuse the kwarg form; fall back
            # to a repr so the agent at least sees what failed.
            buf.write("\n[traceback unavailable]\n")
            buf.write(repr(e))
    out = buf.getvalue()
    truncated = False
    if len(out) > _RUN_CODE_OUT_CAP:
        out = out[:_RUN_CODE_OUT_CAP]
        truncated = True
    if not out and err_repr is None:
        return "(no output)"
    if err_repr is not None:
        prefix = "ERROR: " + err_repr + "\n--- output ---\n"
        return prefix + out + ("\n...[truncated]" if truncated else "")
    return out + ("\n...[truncated]" if truncated else "")


def _restart_runtime():
    import supervisor
    # Schedule a soft-reload. This raises an exception out of code.py to
    # the supervisor, which then re-runs code.py with fresh imports.
    supervisor.reload()
    return "reloading..."  # never actually returned


def _hard_reset():
    import microcontroller
    microcontroller.reset()
    return "resetting..."  # never actually returned


def execute(name, inputs, app=None):
    """Dispatch a tool call. Always returns a string."""
    try:
        if name == "read_file":
            return _read_file(
                inputs["path"],
                start_line=inputs.get("start_line"),
                end_line=inputs.get("end_line"),
            )
        if name == "write_file":
            return _write_file(inputs["path"], inputs["content"])
        if name == "list_dir":
            return _list_dir(inputs["path"])
        if name == "delete_file":
            return _delete_file(inputs["path"])
        if name == "device_info":
            return _device_info(app)
        if name == "list_apps":
            return _list_apps()
        if name == "reorder_apps":
            return _reorder_apps(inputs.get("order"))
        if name == "launch_app":
            return _launch_app(app, inputs["name"])
        if name == "switch_scene":
            return _switch_scene(app, inputs["name"])
        if name == "install_widget":
            return _install_widget(inputs["name"], inputs["source"])
        if name == "list_widgets":
            return _list_widgets()
        if name == "grep":
            return _grep(
                inputs["pattern"],
                inputs["path"],
                recursive=inputs.get("recursive", True),
                case_sensitive=inputs.get("case_sensitive", False),
            )
        if name == "find":
            return _find(
                inputs["pattern"],
                inputs["path"],
                kind=inputs.get("kind", "any"),
            )
        if name == "stat_path":
            return _stat_path(inputs["path"])
        if name == "run_code":
            return _run_code(app, inputs["code"])
        if name == "snapshot_scene":
            return _snapshot_scene(
                app, format=inputs.get("format", "text"),
            )
        if name == "restart_runtime":
            return _restart_runtime()
        if name == "hard_reset":
            return _hard_reset()
        return "ERROR: unknown tool '{}'".format(name)
    except Exception as e:
        return "ERROR: {}: {}".format(type(e).__name__, e)

import json
import os

CONFIG_PATH = "/config.json"
BOOTSTRAP_KEY_PATH = "/.bootstrap_key"
BOOTSTRAP_WIFI_PATH = "/.bootstrap_wifi"

DEFAULTS = {
    "wifi": {"ssid": "", "password": ""},
    "agent": {
        "provider": "claude",
        "model": "claude-opus-4-7",
        "thinking_budget_tokens": 32000,
        "max_tokens": 8192,
    },
    "providers": {
        "claude": {
            "api_key": "",
            "base_url": "https://api.anthropic.com",
            "version": "2023-06-01",
        },
        "openai": {
            "api_key": "",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-5",
        },
    },
    "device": {
        "timezone_offset_minutes": 0,
        "display_brightness": 80,
    },
    "ui": {
        # Height of the top chrome header (back + title + bot buttons).
        # Bigger = easier to thumb. theme.py clamps to a sane range.
        "header_height": 32,
    },
    "session": {
        "log_path": "/session.jsonl",
        "max_history_messages": 200,
        "archive_dir": "/sd/history",
    },
}


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _merge(base, override):
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def exists():
    return _exists(CONFIG_PATH)


def load():
    if not exists():
        return None
    with open(CONFIG_PATH, "r") as f:
        user = json.load(f)
    return _merge(DEFAULTS, user)


def save(cfg):
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f)
    os.rename(tmp, CONFIG_PATH)


def is_configured(cfg):
    if not cfg:
        return False
    if not cfg["wifi"]["ssid"]:
        return False
    provider = cfg["agent"]["provider"]
    if not cfg["providers"].get(provider, {}).get("api_key"):
        return False
    return True


def read_bootstrap_key():
    if not _exists(BOOTSTRAP_KEY_PATH):
        return None
    with open(BOOTSTRAP_KEY_PATH, "r") as f:
        key = f.read().strip()
    try:
        os.remove(BOOTSTRAP_KEY_PATH)
    except OSError:
        pass
    return key or None


def read_bootstrap_wifi():
    if not _exists(BOOTSTRAP_WIFI_PATH):
        return None
    with open(BOOTSTRAP_WIFI_PATH, "r") as f:
        lines = f.read().split("\n")
    try:
        os.remove(BOOTSTRAP_WIFI_PATH)
    except OSError:
        pass
    ssid = lines[0].strip() if lines else ""
    password = lines[1].strip() if len(lines) > 1 else ""
    if not ssid:
        return None
    return (ssid, password)

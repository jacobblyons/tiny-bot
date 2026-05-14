  ```
   _____  ___  _   _ __   __      ____    ___   _____
  |_   _||_ _|| \ | |\ \ / /     | __ )  / _ \ |_   _|
    | |   | | |  \| | \ V /  --- |  _ \ | | | |  | |
    | |   | | | |\  |  | |       | |_) || |_| |  | |
    |_|  |___||_| \_|  |_|       |____/  \___/   |_|
  ```
A Claude-Code-style agent harness running entirely on a LilyGo T-Deck.

The agent is a background service. The chat UI is just one app among many; the
agent keeps running across UI reloads and survives hard resets by replaying its
session log from flash. The model can install new apps at runtime by writing
files to the SD card.

## Hardware

- LilyGo T-Deck (ESP32-S3, 8MB PSRAM, 16MB flash, 320x240 ST7789, QWERTY, trackball)
- microSD card (any size; used for apps and bulk data)

## Layout

```
device/                    # everything that runs on the T-Deck
  boot.py                  # MicroPython boot hook
  main.py                  # imports os and starts it
  config.json.example      # copy to config.json on flash, or let the wizard create it
  harness/                 # core services (top-level on the device's flash, hot-reloadable per module)
    __init__.py            # boot orchestration: load config / run wizard / start services
    config.py              # config load/save
    wifi.py                # connect, scan, signal
    boot_wizard.py         # first-boot WiFi + API key flow
    launcher.py            # home screen + app grid (phase 6)
    agent/                 # phase 3+
    ui/
      drivers/             # display, keyboard, trackball, sd
scripts/
  push_files.ps1           # mpremote-based push to a connected device
  flash_firmware.md        # how to flash MicroPython itself
```

## Phase 1 status

Currently bringing up: display, keyboard, trackball, SD, WiFi, boot wizard,
config persistence. End state: power on with a fresh device, walk through the
wizard on the device's own keyboard, save config, reboot into a stub home
screen.

## Setup

1. Flash MicroPython onto the T-Deck — see `scripts/flash_firmware.md`.
2. Install `mpremote` on your laptop: `pip install mpremote`.
3. Plug the T-Deck in, find its COM port (e.g. `COM7`).
4. Push the project: `./scripts/push_files.ps1 -Port COM7`.
5. Reset the device. The boot wizard runs on first power-on.

## Configuration

The wizard creates `/config.json` on the device's flash. To edit by hand, see
`device/config.json.example`. The API key is stored as plain text — if you lose
the device, rotate the key.

### Bootstrapping the API key over USB

Typing an 80-character API key on a thumb keyboard is unpleasant. If you copy a
key file to `/.bootstrap_key` before running the wizard, it'll pick that up
instead and delete the file:

```powershell
Set-Content -Path key.txt -Value "sk-ant-..." -NoNewline
mpremote connect COM7 cp key.txt :.bootstrap_key
mpremote connect COM7 reset
```

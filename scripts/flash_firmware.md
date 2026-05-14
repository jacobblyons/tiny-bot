# Flashing MicroPython onto the T-Deck

The T-Deck uses ESP32-S3-WROOM-1. Use the official MicroPython ESP32-S3 build
with SPIRAM support (the T-Deck has 8MB octal PSRAM).

## One-time

```powershell
pip install esptool mpremote
```

## Get the firmware

Download the latest stable ESP32_GENERIC_S3 build from
<https://micropython.org/download/ESP32_GENERIC_S3/>. Pick the `SPIRAM_OCT`
variant. Save it as `firmware.bin` next to this file.

## Find the COM port

Plug the T-Deck in via USB-C. In an admin PowerShell:

```powershell
Get-PnpDevice -Class Ports | Where-Object { $_.FriendlyName -match 'USB' }
```

Note the `COMx` number.

## Erase + flash

```powershell
$port = "COM7"  # adjust
esptool.py --chip esp32s3 --port $port erase_flash
esptool.py --chip esp32s3 --port $port --baud 921600 write_flash -z 0 firmware.bin
```

## Verify

```powershell
mpremote connect $port repl
```

You should land in a `>>>` MicroPython prompt. Ctrl-X to exit.

## Push the harness

```powershell
./scripts/push_files.ps1 -Port $port
```

## Reset

Press the reset button on the T-Deck (or `mpremote connect $port reset`). The
boot wizard runs on first power-on with no `config.json`.

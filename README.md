# G Hub Lite

A small settings app for Linux for two Logitech devices: the **G305** wireless mouse and the
**G533** wireless headset. Built for Zorin OS 18 (Ubuntu 24.04 base); it should work on other
GNOME desktops with PipeWire.

This is an independent hobby project. It is not made, endorsed or supported by Logitech, and
"G Hub" is Logitech's name for its own software.

## What it does

**G305 mouse**

- DPI steps, the active step and the step used at switch-on
- Polling rate
- Button assignments: clicks, DPI actions, a key or shortcut, or off
- A Custom buttons switch to swap between the normal buttons and your own set
- Macros (typed by a small background helper, since the mouse cannot store them from Linux)
- Battery level

**G533 headset**

- Volume, microphone level and sidetone
- 10-band equalizer with presets
- A Cinematic profile for films
- Automatic switch-off time
- Battery level

## Install

Needs Python 3 with GTK 4 and libadwaita (already on Zorin 18 and Ubuntu 24.04).

```sh
sh install.sh
```

The installer asks for your password. It installs `ratbagd`, adds udev rules so your login can
talk to the two devices, starts the macro helper, and adds "G Hub Lite" to the app menu.

To run it without the menu entry:

```sh
python3 ghub.py
```

## Self-checks

No hardware is needed for these.

```sh
python3 test_backends.py
python3 test_eq.py
./test_ui.sh
```

## How it works

See [docs/design.md](docs/design.md): the mouse goes through `ratbagd`, the headset through
`/dev/hidraw` (protocol ported from HeadsetControl), and the equalizer through PipeWire's
filter-chain service.

## Limits

- Only these two devices.
- No surround sound, no G Shift layer, no adding or removing DPI steps.
- Macros replay with a fixed 30 ms gap between keys and only work while you are logged in.

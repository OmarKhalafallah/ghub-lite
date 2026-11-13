#!/usr/bin/env python3
"""Mouse macros for the G305.

The mouse itself can only hold one key or shortcut per button (ratbagd 0.17 never writes a
real macro to it). So a macro button is saved in the mouse as a spare key, F14-F19, and this
helper, running in the background, types the recorded keys whenever that spare key arrives.

install.sh runs it as a service:  python3 macros.py
"""
import json
import os
import subprocess
import time

CONFIG = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "ghub-lite.json")
UNIT = "ghub-lite-macros.service"
KEYS, MACRO = 4, 5  # mapping kinds: KEYS is ratbagd's, MACRO exists only in this app
PRESS, RELEASE = 1, 2
TRIGGERS = (184, 185, 186, 187, 188, 189)  # F14-F19, one per mouse button. Not F13: GNOME opens Settings on it
MAX_EVENTS = 100
GAP = 0.03  # seconds between replayed key events
# shortcut: one fixed gap, not the timing you typed with; record real delays if a game needs them


def clean(events):
    """Recorded (kind, key) events -> a tuple that always lets go of every key it pressed."""
    out, down = [], []
    for kind, code in events:
        kind, code = int(kind), int(code)
        if kind == PRESS and code not in down and len(out) + len(down) + 2 <= MAX_EVENTS:
            down.append(code)  # a key held down repeats; only its first press counts
            out.append((PRESS, code))
        elif kind == RELEASE and code in down:
            down.remove(code)
            out.append((RELEASE, code))
    return tuple(out + [(RELEASE, code) for code in reversed(down)])


def encode(maps):
    """What the app shows -> (what the mouse stores, {spare key: events} for this helper)."""
    buttons, table = [], {}
    for i, (kind, value) in enumerate(maps):
        if kind == MACRO:
            table[str(TRIGGERS[i])] = [list(event) for event in value]
            buttons.append((KEYS, (TRIGGERS[i],)))
        else:
            buttons.append((kind, value))
    return buttons, table


def decode(buttons, table):
    """The reverse: a button holding a spare key that has a macro is shown as that macro."""
    maps = []
    for kind, value in buttons:
        events = ()
        if kind == KEYS and len(value) == 1 and isinstance(table, dict):
            try:
                events = clean(table.get(str(value[0])) or ())
            except (TypeError, ValueError):
                pass  # damaged settings file: show the plain key
        maps.append((MACRO, events) if events else (kind, value))
    return maps


def helper_running():
    try:
        return subprocess.run(["systemctl", "--user", "is-active", "--quiet", UNIT], timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _saved(code):
    try:
        with open(CONFIG) as f:
            return clean(json.load(f)["macros"][str(code)])
    except (OSError, ValueError, KeyError, TypeError):
        return ()


def _find(evdev):
    """The G305's input node. It sends pointer movement and keys through the same one."""
    for path in evdev.list_devices():
        device = evdev.InputDevice(path)
        if "G305" in device.name:
            return device
        device.close()
    return None


def main():
    import evdev  # installed with ratbagd
    key = evdev.ecodes.EV_KEY
    try:
        out = evdev.UInput(name="G Hub Lite macros")
    except OSError as e:
        raise SystemExit(f"Cannot create a virtual keyboard ({e}). Run install.sh once.")
    while True:
        device = _find(evdev)
        if not device:  # receiver unplugged, or no permission yet
            time.sleep(3)
            continue
        try:
            for event in device.read_loop():
                if event.type == key and event.value == 1 and event.code in TRIGGERS:
                    for kind, code in _saved(event.code):  # read each time: the app may have changed it
                        out.write(key, code, 1 if kind == PRESS else 0)
                        out.syn()
                        time.sleep(GAP)
        except OSError:  # the mouse went away
            time.sleep(3)


if __name__ == "__main__":
    main()

"""Self-check for the logic that needs no hardware. Run: python3 test_backends.py"""
import g533
import mouse

# --- G533 packets (bytes from HeadsetControl 3.0.0 logitech_g533.c)
assert g533.battery_packet() == bytes([0x11, 0xFF, 0x07, 0x01]) + bytes(16)
assert g533.auto_off_packet(30) == bytes([0x11, 0xFF, 0x07, 0x21, 30]) + bytes(15)
assert g533.auto_off_packet(500)[4] == 90 and g533.auto_off_packet(-1)[4] == 0

head = bytes([0xFF, 0x0B, 0x00, 0xFF, 0x04, 0x0E, 0xFF, 0x05, 0x01, 0x04, 0x00])
for level, device_value in ((0, 200), (50, 227), (100, 255), (999, 255), (-5, 200)):
    report = g533.sidetone_report(level)
    assert len(report) == 64 and report[:11] == head and report[11] == device_value, level
assert g533.HIDIOCSFEATURE_64 == (3 << 30) | (64 << 16) | (ord("H") << 8) | 0x06

# --- battery curve: clamped, never goes up as voltage goes down
assert g533.percent(4200) == 100 and g533.percent(4012) == 100
assert g533.percent(3850) == 72 and g533.percent(3618) == 10
assert g533.percent(2000) == 0
levels = [g533.percent(mv) for mv in range(4300, 2900, -1)]
assert all(0 <= x <= 100 for x in levels)
assert all(a >= b - 1 for a, b in zip(levels, levels[1:])), "curve jumps upward"

# --- replies
reply = bytes([0x11, 0xFF, 0x07, 0x01, 0x0F, 0x0A, 0x01])  # 3850 mV, idle
assert g533.parse_battery(reply) == (72, False)
assert g533.parse_battery(reply[:6] + b"\x03") == (72, True)
for bad in (bytes([0x11, 0xFF, 0xFF, 0x07, 0x01, 0x05, 0x00]), bytes(7), b"\x11\xff"):
    try:
        g533.parse_battery(bad)
        raise AssertionError(f"accepted {bad!r}")
    except g533.HeadsetError:
        pass

request = g533.battery_packet()
assert g533.is_reply(reply, request)
assert g533.is_reply(bytes([0x11, 0xFF, 0xFF, 0x07, 0x01, 0x05, 0x00]), request)      # its error
assert not g533.is_reply(bytes([0x11, 0xFF, 0x07, 0x21, 0, 0, 0]), request)           # auto-off ack
assert not g533.is_reply(bytes([0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]), request)  # volume key
assert not g533.is_reply(b"\x11\xff", request)

# --- mouse
allowed = list(range(200, 12001, 50))
assert mouse.snap(820, allowed) == 800 and mouse.snap(99999, allowed) == 12000 and mouse.snap(0, allowed) == 200

# buttons: mappings as ratbagd sends them, and the shapes we send back
assert mouse.parse_mapping((1, 1)) == (mouse.BUTTON, 1)
assert mouse.parse_mapping((2, 1073741831)) == mouse.ACTIONS[5][1]      # what the real DPI button reports
assert mouse.parse_mapping((4, [(1, 29), (1, 46), (2, 46), (2, 29)])) == (mouse.KEYS, (29, 46))
assert mouse.parse_mapping((1000, 0)) == (mouse.UNKNOWN, 0)
assert mouse.key_events((29, 46)) == [(1, 29), (1, 46), (2, 46), (2, 29)]
assert mouse.key_label((29, 46)) == "Ctrl + C" and mouse.key_label((59,)) == "F1"
assert len({mapping for _label, mapping in mouse.ACTIONS}) == len(mouse.ACTIONS)
stock = [(1, 1), (1, 2), (1, 3), (1, 4), (1, 5), mouse.ACTIONS[5][1]]
mouse.check_buttons(stock)
for bad in ([(1, 2)] * 6, stock[:5] + [(mouse.KEYS, (29,))], stock[:5] + [(mouse.KEYS, ())]):
    try:
        mouse.check_buttons(bad)
        raise AssertionError(f"accepted {bad!r}")
    except mouse.MouseError:
        pass
assert mouse.battery_fraction("85%") == 0.85 and mouse.battery_fraction("Full") == 1.0
assert mouse.battery_fraction(None) is None and mouse.battery_fraction("Weird") is None

# --- headset audio
import audio
dump = """[
 {"id": 70, "info": {"props": {"media.class": "Audio/Sink", "node.name": "alsa_output.usb-Logitech_G533_Gaming_Headset-00.analog-stereo"}}},
 {"id": 68, "info": {"props": {"media.class": "Audio/Source", "node.name": "alsa_input.usb-Logitech_G533_Gaming_Headset-00.mono-fallback"}}},
 {"id": 90, "info": {"props": {"media.class": "Audio/Sink", "node.name": "ghub_lite_eq", "node.description": "G533 Equalizer"}}},
 {"id": 51, "info": {"props": {"media.class": "Audio/Sink", "node.name": "alsa_output.pci-0000_00_1f.3.analog-stereo"}}},
 {"id": 67, "info": {"props": {"device.description": "G533 dongle"}}},
 {"id": 5, "info": null}
]"""
found = audio.headset_nodes(dump)
assert found["sink"][0] == 70 and found["source"][0] == 68, found
assert audio.headset_nodes("[]") == {}
assert audio.parse_volume("Volume: 0.76\n") == (76, False)
assert audio.parse_volume("Volume: 1.00 [MUTED]\n") == (100, True)

# --- macros
import json
import macros
assert mouse.DEFAULT_BUTTONS == stock
typed = [(1, 42), (1, 35), (1, 35), (2, 35), (2, 42), (2, 99), (1, 23)]   # Shift+H with key repeat, a stray release, I left held
assert macros.clean(typed) == ((1, 42), (1, 35), (2, 35), (2, 42), (1, 23), (2, 23))
long = macros.clean([(1, k) for k in range(300)])
assert len(long) <= macros.MAX_EVENTS and sum(1 for k, _c in long if k == 1) == sum(1 for k, _c in long if k == 2)
maps = stock[:5] + [(macros.MACRO, ((1, 35), (2, 35)))]
buttons, table = macros.encode(maps)
assert buttons == stock[:5] + [(mouse.KEYS, (189,))] and table == {"189": [[1, 35], [2, 35]]}
mouse.check_buttons(buttons)
assert macros.decode(buttons, json.loads(json.dumps(table))) == maps
assert macros.decode(buttons, {}) == buttons and macros.decode(buttons, None) == buttons   # no table: a plain key
assert macros.decode(buttons, {"189": "junk"}) == buttons
assert len(set(macros.TRIGGERS)) == 6 and 183 not in macros.TRIGGERS

print("ok")

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

print("ok")

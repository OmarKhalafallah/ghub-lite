"""Logitech G533 headset over /dev/hidraw. Stdlib only.

Protocol ported from HeadsetControl 3.0.0 (src/devices/logitech_g533.c), the
long-tested C driver. Battery read confirmed on the real headset (2026-11-13) and
both report formats match its HID descriptor; sidetone and auto-off writes untried.

Check it by hand with the headset on:  python3 g533.py
"""
import fcntl
import glob
import os
import select
import threading
import time

HID_ID = "0003:0000046D:00000A66"
HIDIOCSFEATURE_64 = 0xC0404806  # _IOC(READ|WRITE, 'H', 0x06, 64)
_lock = threading.Lock()  # one request at a time, so replies can't cross


class HeadsetError(Exception):
    pass


def packet(*cmd):
    return bytes([0x11, 0xFF, *cmd]).ljust(20, b"\0")


def battery_packet():
    return packet(0x07, 0x01)


def sidetone_report(level):
    """64-byte feature report (report id 0xFF). level is 0-100."""
    level = max(0, min(100, int(level)))
    head = [0xFF, 0x0B, 0, 0xFF, 0x04, 0x0E, 0xFF, 0x05, 0x01, 0x04, 0x00, 200 + level * 55 // 100]
    return bytes(head).ljust(64, b"\0")


def auto_off_packet(minutes):
    return packet(0x07, 0x21, max(0, min(90, int(minutes))))


def percent(mv):
    """Battery percent from millivolts. Curve fitted upstream to real G533 discharge data."""
    if mv <= 3618:
        level = int(0.017547 * mv - 53.258578)
    elif mv > 4011:
        level = 100
    else:
        poly = round(-0.0000010876 * mv**3 + 0.0122392434 * mv**2 - 45.6420832787 * mv + 56445.8517589238)
        level = (poly - 25) * 80 // 75 + 20
    return max(0, min(100, level))


def parse_battery(reply):
    """-> (percent, charging). Raises HeadsetError when the headset is off."""
    if len(reply) < 7 or reply[2] == 0xFF:
        raise HeadsetError("Headset is switched off")
    mv = reply[4] << 8 | reply[5]
    if mv < 3000:  # not a real Li-ion reading
        raise HeadsetError("Headset is switched off")
    return percent(mv), reply[6] == 0x03


def is_reply(reply, request):
    """True if `reply` answers `request` (same feature+function), or is its HID++ error."""
    if len(reply) < 7 or reply[0] != 0x11:
        return False
    return reply[2:4] == request[2:4] or (reply[2] == 0xFF and reply[3] == request[2])


def find_node():
    found = []
    for sysdir in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            with open(sysdir + "/device/uevent") as f:
                if HID_ID not in f.read().upper():
                    continue
            with open(sysdir + "/device/report_descriptor", "rb") as f:
                vendor_page = b"\x06\x43\xff" in f.read()
        except OSError:
            continue
        # prefer the interface that declares vendor usage page 0xff43
        found.append((not vendor_page, "/dev/" + os.path.basename(sysdir)))
    return min(found)[1] if found else None


def _open():
    node = find_node()
    if not node:
        raise HeadsetError("Headset receiver not found. Is it plugged in?")
    try:
        return os.open(node, os.O_RDWR)
    except PermissionError:
        raise HeadsetError("No permission to talk to the headset. Run install.sh once.")
    except OSError as e:
        raise HeadsetError(f"Cannot open headset: {e.strerror}")


def _request(pkt):
    """Write a HID++ long report and return the matching reply."""
    with _lock:
        fd = _open()
        try:
            while select.select([fd], [], [], 0)[0]:  # drop stale reports
                os.read(fd, 64)
            os.write(fd, pkt)
            deadline = time.monotonic() + 1.0
            while (left := deadline - time.monotonic()) > 0:
                if not select.select([fd], [], [], left)[0]:
                    break
                reply = os.read(fd, 64)
                if is_reply(reply, pkt):
                    if reply[2] == 0xFF:
                        raise HeadsetError("Headset is switched off")
                    return reply
            raise HeadsetError("Headset is switched off")
        except OSError as e:
            raise HeadsetError(f"Headset I/O failed: {e.strerror}")
        finally:
            os.close(fd)


def battery():
    return parse_battery(_request(battery_packet()))


def set_sidetone(level):
    with _lock:
        fd = _open()
        try:
            fcntl.ioctl(fd, HIDIOCSFEATURE_64, sidetone_report(level))
        except OSError as e:
            raise HeadsetError(f"Headset I/O failed: {e.strerror}")
        finally:
            os.close(fd)


def set_auto_off(minutes):
    _request(auto_off_packet(minutes))


if __name__ == "__main__":
    print("node:", find_node())
    print("battery (percent, charging):", battery())

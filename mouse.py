"""Logitech G305 through ratbagd (D-Bus, system bus) plus the kernel's battery node."""
import glob

from gi.repository import Gio, GLib

BUS = "org.freedesktop.ratbag1"
ROOT = "/org/freedesktop/ratbag1"

# ratbagd mapping types. A mapping here is (type, value); for KEYS the value is a tuple of
# Linux key codes held together, modifiers first, e.g. (29, 46) for Ctrl+C.
OFF, BUTTON, SPECIAL, KEYS, UNKNOWN = 0, 1, 2, 4, 1000
_S = 1 << 30  # ratbag's special-action base; the real mouse reports _S + 7 for its DPI button
PHYSICAL = ["Left button", "Right button", "Wheel click", "Back side button", "Forward side button", "DPI button"]
# Only actions the G305's onboard memory understands (libratbag hidpp20_profiles_specials).
ACTIONS = [
    ("Left click", (BUTTON, 1)), ("Right click", (BUTTON, 2)), ("Middle click", (BUTTON, 3)),
    ("Back", (BUTTON, 4)), ("Forward", (BUTTON, 5)),
    ("Next DPI step", (SPECIAL, _S + 7)), ("DPI up", (SPECIAL, _S + 9)), ("DPI down", (SPECIAL, _S + 10)),
    ("DPI shift while held", (SPECIAL, _S + 11)), ("Default DPI", (SPECIAL, _S + 12)),
    ("Scroll left", (SPECIAL, _S + 2)), ("Scroll right", (SPECIAL, _S + 3)),
]
DEFAULT_BUTTONS = [action for _label, action in ACTIONS[:6]]  # what each button does out of the box
MODIFIERS = {29: "Ctrl", 97: "Ctrl", 42: "Shift", 54: "Shift", 56: "Alt", 100: "Alt", 125: "Super", 126: "Super"}
BATTERY_FRACTION = {"Full": 1.0, "High": 0.75, "Normal": 0.5, "Low": 0.2, "Critical": 0.05}


class MouseError(Exception):
    pass


def snap(value, allowed):
    """Nearest value the mouse actually supports."""
    return min(allowed, key=lambda a: abs(a - value))


def key_label(keys):
    """(29, 46) -> 'Ctrl + C'."""
    try:
        from evdev import ecodes  # installed with ratbagd
        table = ecodes.KEY
    except ImportError:
        table = {}
    parts = []
    for code in keys:
        name = table.get(code, f"key {code}")
        name = name if isinstance(name, str) else name[-1]
        parts.append(MODIFIERS.get(code) or name.removeprefix("KEY_").replace("_", " ").capitalize())
    return " + ".join(parts) or "No key"


def parse_mapping(raw):
    """ratbagd's (type, value) -> our mapping. A macro becomes the keys it presses, in order."""
    kind, value = raw
    if kind == KEYS:
        return (KEYS, tuple(code for event, code in value if event == 1))
    if kind in (BUTTON, SPECIAL):
        return (kind, value)
    return (UNKNOWN, 0)  # ratbagd reports a disabled button the same way as one it can't describe


def key_events(keys):
    """Press in order, release in reverse: the shape libratbag turns into key + modifiers."""
    return [(1, k) for k in keys] + [(2, k) for k in reversed(keys)]


def check_buttons(buttons):
    if (BUTTON, 1) not in buttons:
        raise MouseError("Keep at least one button as Left click, or you could not click anything.")
    for kind, value in buttons:
        if kind == KEYS and not any(k not in MODIFIERS for k in value):
            raise MouseError("A keyboard assignment needs a key, not only Ctrl, Shift, Alt or Super.")


def battery():
    """'85%' / 'Normal' / None. The kernel's hid-logitech-hidpp driver does the work."""
    for node in glob.glob("/sys/class/power_supply/hidpp_battery_*"):
        try:
            with open(node + "/model_name") as f:
                if "G305" not in f.read():
                    continue
            for name, suffix in (("capacity", "%"), ("capacity_level", "")):
                try:
                    with open(f"{node}/{name}") as f:
                        return f.read().strip() + suffix
                except OSError:
                    pass
        except OSError:
            pass
    return None


def battery_fraction(text):
    """0..1 for a bar, or None when unknown."""
    if not text:
        return None
    if text.endswith("%"):
        return int(text[:-1]) / 100
    return BATTERY_FRACTION.get(text)


def _proxy(path, iface):
    return Gio.DBusProxy.new_for_bus_sync(
        Gio.BusType.SYSTEM, Gio.DBusProxyFlags.NONE, None, BUS, path, f"{BUS}.{iface}", None)


def _get(proxy, name):
    value = proxy.get_cached_property(name)
    if value is None:
        raise MouseError(f"ratbagd did not report '{name}'. Is the mouse switched on?")
    return value.unpack()


def _set(proxy, name, variant):
    proxy.call_sync("org.freedesktop.DBus.Properties.Set",
                    GLib.Variant("(ssv)", (proxy.get_interface_name(), name, variant)),
                    Gio.DBusCallFlags.NONE, -1, None)


def _call(proxy, method):
    """ratbagd methods return 0 on success."""
    (code,) = proxy.call_sync(method, None, Gio.DBusCallFlags.NONE, -1, None).unpack()
    if code != 0:
        raise MouseError(f"The mouse rejected {method} (code {code}). Nothing was saved.")


class Mouse:
    """Snapshot of the active onboard profile. Build a new one to re-read."""

    def __init__(self):
        try:
            manager = _proxy(ROOT, "Manager")
            if not manager.get_name_owner():
                raise MouseError("ratbagd is not running. Run install.sh once.")
            for path in _get(manager, "Devices"):
                self._dev = _proxy(path, "Device")
                if "4074" in _get(self._dev, "Model") or "G305" in _get(self._dev, "Name"):
                    break
            else:
                # the kernel lists a paired G305 even when the mouse itself is off or flat
                if glob.glob("/sys/bus/hid/devices/*:046D:4074.*"):
                    raise MouseError("The G305 is paired but not answering. Give it a charged battery and "
                                     "switch it on. If this message stays, unplug and replug its receiver.")
                raise MouseError("G305 not found. Is its receiver plugged in?")
            profiles = [_proxy(p, "Profile") for p in _get(self._dev, "Profiles")]
            self._profile = next((p for p in profiles if _get(p, "IsActive")), profiles[0])
            # shortcut: only DPI steps already enabled on the mouse (dpi > 0) are editable.
            # ratbagd 0.17 can switch a step on but never off again (0 is not an accepted
            # value), so adding steps is left out until ratbagd grows a per-step disable.
            self._steps = []
            for path in _get(self._profile, "Resolutions"):
                step = _proxy(path, "Resolution")
                if self._dpi(step) > 0:
                    self._steps.append(step)
            if not self._steps:
                raise MouseError("The mouse reported no DPI steps.")
            self.dpis = [self._dpi(s) for s in self._steps]
            self.allowed = sorted(_get(self._steps[0], "Resolutions")) or sorted(self.dpis)
            self.active = next((i for i, s in enumerate(self._steps) if _get(s, "IsActive")), 0)
            self.default = next((i for i, s in enumerate(self._steps) if _get(s, "IsDefault")), 0)
            self.rate = _get(self._profile, "ReportRate")
            self.rates = sorted(_get(self._profile, "ReportRates"))
            self._buttons = [_proxy(p, "Button") for p in _get(self._profile, "Buttons")]
            self.buttons = [parse_mapping(_get(b, "Mapping")) for b in self._buttons]
        except GLib.Error as e:
            raise MouseError(f"ratbagd error: {e.message}")

    def on_resync(self, callback):
        """ratbagd emits Resync when a commit failed after Commit() already returned."""
        self._dev.connect("g-signal", lambda _p, _sender, signal, _args: signal == "Resync" and callback())

    @staticmethod
    def _dpi(step):
        value = _get(step, "Resolution")  # variant holding u, or (uu) for separate x/y
        return value[0] if isinstance(value, tuple) else value

    def apply(self, dpis, active, default, rate, buttons):
        """Write changed values and commit them to the mouse's onboard memory."""
        check_buttons(buttons)  # before touching anything
        try:
            for step, old, new in zip(self._steps, self.dpis, dpis):
                new = snap(new, self.allowed)
                if new != old:
                    _set(step, "Resolution", GLib.Variant("v", GLib.Variant("u", new)))
            if active != self.active:
                _call(self._steps[active], "SetActive")
            if default != self.default:
                _call(self._steps[default], "SetDefault")
            if rate != self.rate:
                _set(self._profile, "ReportRate", GLib.Variant("u", rate))
            for button, old, (kind, value) in zip(self._buttons, self.buttons, buttons):
                if (kind, value) == old or kind == UNKNOWN:
                    continue
                if kind == OFF:
                    _call(button, "Disable")
                elif kind == KEYS:
                    inner = GLib.Variant("a(uu)", key_events(value))
                    _set(button, "Mapping", GLib.Variant("(uv)", (KEYS, inner)))
                else:
                    _set(button, "Mapping", GLib.Variant("(uv)", (kind, GLib.Variant("u", value))))
            _call(self._dev, "Commit")
        except GLib.Error as e:
            raise MouseError(f"Could not save to the mouse: {e.message}")

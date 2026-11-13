"""Logitech G305 through ratbagd (D-Bus, system bus) plus the kernel's battery node."""
import glob

from gi.repository import Gio, GLib

BUS = "org.freedesktop.ratbag1"
ROOT = "/org/freedesktop/ratbag1"


class MouseError(Exception):
    pass


def snap(value, allowed):
    """Nearest value the mouse actually supports."""
    return min(allowed, key=lambda a: abs(a - value))


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
            # shortcut: only DPI steps already enabled on the mouse (dpi > 0) are editable;
            # adding/removing steps needs ratbagd's per-step enable flag, do it if wanted.
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
            self.rate = _get(self._profile, "ReportRate")
            self.rates = sorted(_get(self._profile, "ReportRates"))
        except GLib.Error as e:
            raise MouseError(f"ratbagd error: {e.message}")

    def on_resync(self, callback):
        """ratbagd emits Resync when a commit failed after Commit() already returned."""
        self._dev.connect("g-signal", lambda _p, _sender, signal, _args: signal == "Resync" and callback())

    @staticmethod
    def _dpi(step):
        value = _get(step, "Resolution")  # variant holding u, or (uu) for separate x/y
        return value[0] if isinstance(value, tuple) else value

    def apply(self, dpis, active, rate):
        """Write changed values and commit them to the mouse's onboard memory."""
        try:
            for step, old, new in zip(self._steps, self.dpis, dpis):
                new = snap(new, self.allowed)
                if new != old:
                    _set(step, "Resolution", GLib.Variant("v", GLib.Variant("u", new)))
            if active != self.active:
                _call(self._steps[active], "SetActive")
            if rate != self.rate:
                _set(self._profile, "ReportRate", GLib.Variant("u", rate))
            _call(self._dev, "Commit")
        except GLib.Error as e:
            raise MouseError(f"Could not save to the mouse: {e.message}")

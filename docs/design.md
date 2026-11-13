# G Hub Lite — design

A small local desktop app for Zorin OS 18 that replaces Logitech G Hub for
exactly two devices: the **G305** wireless mouse and the **G533** wireless
headset. One user, one laptop. Not distributed.

## Goals (v1)

| Device | Feature | How |
|---|---|---|
| G305 | Show battery | read `/sys/class/power_supply/hidpp_battery_*` (kernel `hid-logitech-hidpp` already exposes it) |
| G305 | Edit the DPI steps of the active onboard profile, choose the active step | `ratbagd` over D-Bus |
| G305 | Set polling rate (125/250/500/1000 Hz) | `ratbagd` over D-Bus |
| G533 | Show battery % and charging state | HID++ over `/dev/hidraw` |
| G533 | Set sidetone level (0–100) | HID feature report over `/dev/hidraw` |
| G533 | Set auto power-off (0–90 min, 0 = never) | HID++ over `/dev/hidraw` |

## Non-goals

- Any other Logitech device.
- G305 button remapping and multiple profiles (Piper already does this on top
  of the same `ratbagd`; add later if wanted).
- G533 equalizer and DTS surround: G Hub does these in software on the PC, not
  in the headset. On Linux that is a PipeWire filter job, a separate project.
- G533 lighting: no known open protocol for it.
- Background daemon, tray icon, per-game profiles, cloud, macros.

## Stack

- Python 3 + GTK4 + libadwaita through PyGObject. All already installed on
  Zorin 18; no pip packages.
- `ratbagd` 0.17 from apt (`sudo apt install ratbagd`). It already implements
  the G305's HID++ 2.0 onboard-profile protocol (device file
  `logitech-g305.device`, USB id `046d:4074`), and its D-Bus policy allows
  normal users to call it.
- Headset: no packaged tool exists, so talk to it directly. Stdlib only
  (`os.open` on the hidraw node), no `hidapi`.

## Files

```
ghub.py          GTK window: two pages (Mouse, Headset), a refresh timer
mouse.py         ratbagd D-Bus client + sysfs battery
g533.py          hidraw discovery + HID++ packets + battery curve
test_backends.py asserts for the pure logic (packets, parsing, battery curve)
install.sh       apt install ratbagd, udev rule for the headset, .desktop launcher
```

## G533 protocol (ported from HeadsetControl 3.0.0, `src/devices/logitech_g533.c`)

The current HeadsetControl C++ rewrite frames sidetone differently from the
long-tested C driver; this app follows the C driver. Byte offsets are 0-based.

- USB id `046d:0a66`. Find the node by scanning
  `/sys/class/hidraw/*/device/uevent` for `HID_ID=0003:0000046D:00000A66`;
  if several match, take the one whose `device/report_descriptor` contains
  `06 43 ff` (vendor usage page `0xff43`).
- Battery: `os.write` the 20-byte report `11 ff 07 01` (zero-padded). Read
  with a 1 s `select` deadline, accepting only a report that echoes `07 01`
  in bytes 2–3, or the HID++ error frame `11 ff ff 07 …`. Bytes 4–5 = voltage
  in mV (big-endian), byte 6 = `03` when charging. Error frame, timeout, or a
  voltage under 3000 mV = "headset is switched off". Percent uses upstream's
  curve fitted to real discharge data, clamped to 0–100.
- Sidetone: a 64-byte **feature report** sent with the `HIDIOCSFEATURE` ioctl:
  `ff 0b 00 ff 04 0e ff 05 01 04 00 <v>`, `v` = 200 + level·55//100.
- Auto-off: 20-byte report `11 ff 07 21 <minutes>`, reply matched as above.
- One request at a time (a lock); the node is opened per request.
- The device cannot report the current sidetone or auto-off value, so the app
  stores the last value it successfully sent in `~/.config/ghub-lite.json`
  (keys `sidetone`, `auto_off`) and shows that. Values are sent 400 ms after
  the control stops changing. They are not re-sent when the headset reconnects.

## Mouse (ratbagd D-Bus, system bus, name `org.freedesktop.ratbag1`)

- `Manager.Devices` → pick the device whose `Model` contains `4074` (or `Name` contains "G305").
- `Device.Profiles` → the profile with `IsActive`.
- `Profile.Resolutions` → each has `Resolution` (variant: `u` or `(uu)`),
  `Resolutions` (allowed DPI list), `IsActive`, `SetActive()`.
- `Profile.ReportRate` / `ReportRates`.
- Only steps the mouse already has enabled (DPI > 0) are shown. Values snap to
  the nearest entry of `Resolutions` on apply.
- Properties are written and `Device.Commit()` called together, only on the
  **Apply** button (it writes to the mouse's flash). `Commit()` returns before
  the write happens; a failure arrives later as the `Resync` signal, on which
  the app shows a message and re-reads the mouse.
- The page is rebuilt only when the mouse appears or after an apply, so the
  refresh timer never wipes unsaved edits.

## Permissions

- hidraw nodes are root-only by default. `install.sh` adds
  `/etc/udev/rules.d/70-g533.rules`:
  `KERNEL=="hidraw*", ATTRS{idVendor}=="046d", ATTRS{idProduct}=="0a66", TAG+="uaccess"`
  then reloads udev and re-triggers hidraw devices.
- The app never runs as root.

## Behaviour when a device is missing

Each page shows a plain status row instead of controls: "Mouse not found —
is the receiver plugged in?", "ratbagd is not running — run install.sh",
"Headset is switched off", "No permission — run install.sh". One 10 s timer
re-checks both devices, so plugging in later just works; a tick is skipped
while the previous one is still running. Device I/O runs in a worker thread
and updates widgets only through `GLib.idle_add`.

## Risks / unverified

- G533: battery read confirmed on the real headset (2026-11-13), and its HID
  descriptor declares both report formats used here (output `0x11` 19 bytes,
  feature `0xff` 63 bytes). Sidetone and auto-off writes are still untried.
- G305: reading confirmed on the real mouse (2026-11-13): battery level, four DPI
  steps, polling rate. Writing (Apply) is still untried.
- ratbagd 0.17 only probes mice at start-up or receiver plug-in (confirmed: a mouse
  switched on later was invisible until ratbagd was restarted). `install.sh` adds
  `/etc/udev/rules.d/70-g305-ratbagd.rules`, which restarts ratbagd when the kernel
  adds a `hidpp_battery_*` entry. That rule itself has not been seen firing yet.
- The G305 reports battery as a level (Full/Normal/Low), not a percentage.
- `headsetcontrol` is not in Zorin 18's apt repositories, which is why the
  headset is driven directly.
- `Commit()` writes to the mouse's onboard memory. A wrong value is recoverable
  (re-apply, or reset in G Hub on Windows) but it is a hardware write.

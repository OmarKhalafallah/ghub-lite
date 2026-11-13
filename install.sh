#!/bin/sh
# One-time setup for G Hub Lite. Safe to run again.
set -e
here=$(cd "$(dirname "$0")" && pwd)

# Mouse: ratbagd speaks the G305's protocol.
sudo apt install -y ratbagd

# Headset: let the logged-in user (not everyone) talk to the G533 receiver.
echo 'KERNEL=="hidraw*", ATTRS{idVendor}=="046d", ATTRS{idProduct}=="0a66", TAG+="uaccess"' |
    sudo tee /etc/udev/rules.d/70-g533.rules >/dev/null

# Mouse: ratbagd only looks for mice when it starts or a receiver is plugged in, so a
# G305 switched on later stays invisible. Restart ratbagd when the mouse comes alive
# (the kernel adds its battery entry at that moment).
echo 'ACTION=="add", SUBSYSTEM=="power_supply", KERNEL=="hidpp_battery_*", RUN+="/usr/bin/systemctl try-restart --no-block ratbagd.service"' |
    sudo tee /etc/udev/rules.d/70-g305-ratbagd.rules >/dev/null

# Macros: a background helper reads the keys the G305 sends and types the recorded ones
# through a virtual keyboard. Only the logged-in user gets access, and only to these two.
printf '%s\n' \
    'SUBSYSTEM=="input", KERNEL=="event*", ATTRS{name}=="Logitech G305", TAG+="uaccess"' \
    'SUBSYSTEM=="misc", KERNEL=="uinput", TAG+="uaccess", OPTIONS+="static_node=uinput"' |
    sudo tee /etc/udev/rules.d/70-ghub-lite-macros.rules >/dev/null
sudo udevadm control --reload
sudo udevadm trigger --subsystem-match=hidraw --subsystem-match=input --subsystem-match=misc

mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/ghub-lite-macros.service" <<UNIT
[Unit]
Description=G Hub Lite mouse macros

[Service]
ExecStart=/usr/bin/python3 "$here/macros.py"
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
systemctl --user enable ghub-lite-macros.service
systemctl --user restart ghub-lite-macros.service

mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/ghub-lite.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=G Hub Lite
Comment=Settings for the Logitech G305 mouse and G533 headset
Exec=python3 "$here/ghub.py"
Icon=$here/icon.svg
StartupWMClass=local.ghublite
Categories=Settings;HardwareSettings;
DESKTOP

echo "Done. Open 'G Hub Lite' from the app menu."

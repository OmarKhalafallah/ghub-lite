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
sudo udevadm control --reload
sudo udevadm trigger --subsystem-match=hidraw

mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/ghub-lite.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=G Hub Lite
Comment=Settings for the Logitech G305 mouse and G533 headset
Exec=python3 "$here/ghub.py"
Icon=input-gaming
Categories=Settings;HardwareSettings;
DESKTOP

echo "Done. Open 'G Hub Lite' from the app menu."

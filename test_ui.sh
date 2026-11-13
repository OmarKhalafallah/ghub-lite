#!/bin/sh
# Runs test_ui.py inside GTK's headless Broadway display, so no window appears on screen.
cd "$(dirname "$0")" || exit 1
[ -n "$1" ] && mkdir -p "$1"
gtk4-broadwayd :7 >/dev/null 2>&1 &
display=$!
sleep 1
output=$(GDK_BACKEND=broadway BROADWAY_DISPLAY=:7 timeout 120 python3 -u test_ui.py "$@" 2>&1 | grep -v "without a current allocation")
kill $display 2>/dev/null
echo "$output"
[ -n "$2" ] || echo "$output" | grep -q "^failed: 0 of"

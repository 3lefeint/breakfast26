#!/usr/bin/env bash
# Sets up a Linux machine to start Breakfast with its own dart detection or with the board manager: the udev rule that hands the cameras
# to Breakfast, the compose override, the switch script, two desktop shortcuts, and for Autodarts version 1 the polkit rule. Run it as
# the user of the machine; it asks for the sudo password where it writes below /etc and /usr/local. It starts and stops nothing.
#
#   tools/detection_host/install.sh [APP_DIR]       APP_DIR is the checkout with docker-compose.yml (default ~/apps/breakfast26)
#
# The cameras need no questions here: the rule puts every camera into /dev/breakfast-video/, named after its USB port without the bus
# number (which changes between boots and updates). Which camera is camera 1 to 3 is chosen in Breakfast under Settings.
# Settings (environment, for tests): BIN_DIR, DESKTOP_DIR, APPS_DIR, UDEV_RULE, VIDEO_HELPER, POLKIT_RULE, SUDO.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="${1:-${APP_DIR:-$HOME/apps/breakfast26}}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
DESKTOP_DIR="${DESKTOP_DIR:-$HOME/Desktop}"
APPS_DIR="${APPS_DIR:-$HOME/.local/share/applications}"
UDEV_RULE="${UDEV_RULE:-/etc/udev/rules.d/99-breakfast-cameras.rules}"
VIDEO_HELPER="${VIDEO_HELPER:-/usr/local/bin/breakfast-video-node}"
POLKIT_RULE="${POLKIT_RULE:-/etc/polkit-1/rules.d/50-breakfast-detect.rules}"
SUDO="${SUDO:-sudo}"

[ -f "$APP_DIR/docker-compose.yml" ] || { echo "no docker-compose.yml in $APP_DIR: give the folder of the checkout as the argument" >&2; exit 1; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

{
  echo "# Hands the cameras to Breakfast: one node per camera in /dev/breakfast-video/, named after its USB port. Written by install.sh."
  echo "SUBSYSTEM==\"video4linux\", ATTR{index}==\"0\", ACTION==\"add|change\", RUN+=\"$VIDEO_HELPER add %k %M %m\""
  echo "SUBSYSTEM==\"video4linux\", ACTION==\"remove\", RUN+=\"$VIDEO_HELPER remove %M %m\""
} > "$tmp/rule"
$SUDO install -m 755 "$HERE/breakfast-video-node.sh" "$VIDEO_HELPER"
$SUDO install -m 644 "$tmp/rule" "$UDEV_RULE"
$SUDO udevadm control --reload-rules
$SUDO udevadm trigger --subsystem-match=video4linux
echo "cameras: $UDEV_RULE fills /dev/breakfast-video (helper $VIDEO_HELPER); choose them in Breakfast under Settings"

if systemctl cat autodarts.service >/dev/null 2>&1; then      # version 1: a system unit, a normal user needs the rule to start and stop it
  sed "s/BOARD_USER/$(id -un)/" "$HERE/50-breakfast-detect.rules" > "$tmp/polkit"
  $SUDO install -m 644 "$tmp/polkit" "$POLKIT_RULE"
  echo "polkit rule: $POLKIT_RULE"
fi

mkdir -p "$BIN_DIR"
install -m 755 "$HERE/breakfast-mode.sh" "$HERE/breakfast-mode-shortcut.sh" "$BIN_DIR/"
install -m 644 "$HERE/docker-compose.override.yml" "$APP_DIR/docker-compose.override.yml"
echo "scripts: $BIN_DIR, compose override: $APP_DIR/docker-compose.override.yml"

shortcut() {          # $1 = file name, $2 = title, $3 = mode
  cat > "$tmp/$1" <<DESK
[Desktop Entry]
Type=Application
Name=$2
Exec=env APP_DIR=$APP_DIR $BIN_DIR/breakfast-mode-shortcut.sh $3
Terminal=false
Icon=input-gaming
DESK
  local dir
  for dir in "$APPS_DIR" "$DESKTOP_DIR"; do
    [ -d "$dir" ] || mkdir -p "$dir"
    install -m 755 "$tmp/$1" "$dir/$1"
  done
}
shortcut breakfast-own-detection.desktop "Breakfast (own dart detection)" own
shortcut breakfast-board-manager.desktop "Breakfast (board manager)" autodarts
echo "shortcuts: $DESKTOP_DIR and $APPS_DIR"
echo "next: rebuild Breakfast (docker compose up -d --build in $APP_DIR), then start it with one of the shortcuts."

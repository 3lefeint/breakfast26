#!/usr/bin/env bash
# Sets up a Linux machine to start Breakfast with its own dart detection or with the board manager: fixed names for the three cameras,
# the compose override that maps them, the switch script, two desktop shortcuts, and for Autodarts version 1 the polkit rule. Run it as
# the user of the machine; it asks for the sudo password where it writes below /etc. It starts and stops nothing.
#
#   tools/detection_host/install.sh [APP_DIR]       APP_DIR is the checkout with docker-compose.yml (default ~/apps/breakfast26)
#
# The cameras get their names by USB port (a camera moved to another port needs this script again): it asks you to unplug each camera
# one after the other and plug it in again, and reads the port from what disappeared. Camera 1 is the first position of your board,
# camera 3 the third. INSTALL_PORTS="1-1.1.1 1-1.1.2 1-1.1.3" gives the three ports and skips the questions.
# Settings (environment, for tests): BIN_DIR, DESKTOP_DIR, APPS_DIR, UDEV_RULE, POLKIT_RULE, SUDO.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="${1:-${APP_DIR:-$HOME/apps/breakfast26}}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
DESKTOP_DIR="${DESKTOP_DIR:-$HOME/Desktop}"
APPS_DIR="${APPS_DIR:-$HOME/.local/share/applications}"
UDEV_RULE="${UDEV_RULE:-/etc/udev/rules.d/99-breakfast-cameras.rules}"
POLKIT_RULE="${POLKIT_RULE:-/etc/polkit-1/rules.d/50-breakfast-detect.rules}"
SUDO="${SUDO:-sudo}"

[ -f "$APP_DIR/docker-compose.yml" ] || { echo "no docker-compose.yml in $APP_DIR: give the folder of the checkout as the argument" >&2; exit 1; }

video_ports() {       # the USB ports of the cameras that are plugged in now (the video node with index 0 of each)
  local node
  for node in /sys/class/video4linux/video*; do
    [ -e "$node" ] || continue
    [ "$(cat "$node/index" 2>/dev/null)" = 0 ] || continue
    basename "$(readlink -f "$node/device/..")"
  done | sort -u
}

ask_port() {          # $1 = number of the camera; prints its USB port
  local before after gone
  before="$(video_ports)"
  read -rp "Unplug camera $1 of 3, then press Enter: " _ >&2
  after="$(video_ports)"
  gone="$(comm -23 <(echo "$before") <(echo "$after"))"
  if [ "$(echo "$gone" | grep -c .)" != 1 ]; then
    echo "expected one camera to disappear, saw: ${gone:-none}" >&2
    read -rp "Plug it in again, then press Enter: " _ >&2
    return 1
  fi
  read -rp "Plug it in again, then press Enter: " _ >&2
  echo "$gone"
}

if [ -n "${INSTALL_PORTS:-}" ]; then
  read -r -a ports <<< "$INSTALL_PORTS"
else
  ports=()
  for i in 1 2 3; do
    until port="$(ask_port "$i")"; do echo "again" >&2; done
    ports+=("$port")
  done
fi
[ "${#ports[@]}" -eq 3 ] || { echo "three ports are needed, got ${#ports[@]}" >&2; exit 1; }
for p in "${ports[@]}"; do [[ "$p" =~ ^[0-9]+-[0-9.]+$ ]] || { echo "not a USB port: $p" >&2; exit 1; }; done
[ "$(printf '%s\n' "${ports[@]}" | sort -u | wc -l)" -eq 3 ] || { echo "the three cameras must be on three different ports" >&2; exit 1; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

{
  echo "# Fixed names for the three board cameras, one per USB port. Written by install.sh; run it again when a camera moves to another port."
  for i in 0 1 2; do
    echo "SUBSYSTEM==\"video4linux\", ATTR{index}==\"0\", KERNELS==\"${ports[$i]}\", SYMLINK+=\"breakfast-cam$i\""
  done
} > "$tmp/rule"
$SUDO install -m 644 "$tmp/rule" "$UDEV_RULE"
$SUDO udevadm control --reload-rules
$SUDO udevadm trigger --subsystem-match=video4linux
echo "camera names: $UDEV_RULE (/dev/breakfast-cam0 to 2)"

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

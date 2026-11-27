#!/bin/sh
# Called by the udev rule that install.sh writes: keeps /dev/breakfast-video/ in step with the cameras that are plugged in. Each
# camera gets a node named after its USB port without the bus number (1.1.1 for port 1-1.1.1), so the name survives a reboot or an
# update that renumbers the buses. Breakfast mounts the folder and reads the cameras from it; the folder is also there when a camera is not.
#
#   breakfast-video-node.sh add <kernel name> <major> <minor>      a camera appeared (video14, 81, 14)
#   breakfast-video-node.sh remove <major> <minor>                 a camera went away
#
# BREAKFAST_VIDEO_DIR sets the folder, BREAKFAST_VIDEO_GROUP the group of the nodes (default video), BREAKFAST_SYSFS the video4linux folder of sysfs (for tests).
SYSFS="${BREAKFAST_SYSFS:-/sys/class/video4linux}"
DIR="${BREAKFAST_VIDEO_DIR:-/dev/breakfast-video}"
GROUP="${BREAKFAST_VIDEO_GROUP:-video}"

case "$1" in
  add)
    port="$(basename "$(readlink -f "$SYSFS/$2/device/..")")"
    port="${port#*-}"
    case "$port" in ""|*[!0-9.]*) exit 0 ;; esac            # not a camera on a USB port
    mkdir -p "$DIR" && chmod 755 "$DIR"
    rm -f "$DIR/$port"
    mknod -m 0660 "$DIR/$port" c "$3" "$4" && chgrp "$GROUP" "$DIR/$port"
    ;;
  remove)
    for node in "$DIR"/*; do
      [ -e "$node" ] || continue
      [ "$(stat -c '%t:%T' "$node")" = "$(printf '%x:%x' "$2" "$3")" ] && rm -f "$node"
    done
    ;;
  *) echo "usage: $0 add <kernel name> <major> <minor> | remove <major> <minor>" >&2; exit 2 ;;
esac
exit 0

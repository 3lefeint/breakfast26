#!/usr/bin/env bash
# Starts and stops the dart detection stack on the board host (called by breakfast-detect.service, or by hand).
#
#   breakfast-detect-host.sh start     find the cameras by USB port, (re)create the stack
#   breakfast-detect-host.sh stop      take the stack down (the cameras are free again)
#   breakfast-detect-host.sh resolve   print the CAM0..CAM2 device nodes (what `start` would use), start nothing
#
# The device numbers /dev/videoN change with the order of plugging and after a reboot, a container keeps the numbers it was created with:
# so the stack is created again at every start, with the numbers the USB ports have right now.
# Settings (from /etc/default/breakfast-detect or the environment):
#   DETECT_DIR     folder with the compose file (default /opt/breakfast-detect)
#   CAM_PATHS      the three capture nodes under /dev/v4l/by-path, space separated (required; `ls /dev/v4l/by-path` lists them)
#   V4L_DIR        /dev/v4l/by-path, only changed by the tests
set -euo pipefail

DETECT_DIR="${DETECT_DIR:-/opt/breakfast-detect}"
V4L_DIR="${V4L_DIR:-/dev/v4l/by-path}"
CAM_PATHS="${CAM_PATHS:-}"
COMPOSE="docker-compose.detection.yml"
WAIT_S="${WAIT_S:-30}"

resolve() {
  local i=0 name node
  [ -n "$CAM_PATHS" ] || { echo "CAM_PATHS is not set: name the three cameras of this board in /etc/default/breakfast-detect" >&2; return 1; }
  for name in $CAM_PATHS; do
    node="$(readlink -f "$V4L_DIR/$name" 2>/dev/null || true)"
    if [ -z "$node" ] || [ ! -e "$node" ]; then
      echo "camera $i not found: $V4L_DIR/$name" >&2
      return 1
    fi
    echo "CAM$i=$node"
    i=$((i + 1))
  done
  [ "$i" -eq 3 ] || { echo "three cameras are needed, CAM_PATHS has $i" >&2; return 1; }
}

wait_for_cameras() {
  # after a boot the USB cameras may take a moment to show up
  local waited=0
  [ -n "$CAM_PATHS" ] || { resolve; return 1; }
  until resolve >/dev/null 2>&1; do
    [ "$waited" -ge "$WAIT_S" ] && { resolve >/dev/null; return 1; }
    sleep 1
    waited=$((waited + 1))
  done
}

case "${1:-}" in
  resolve)
    resolve
    ;;
  start)
    wait_for_cameras
    cd "$DETECT_DIR"
    env $(resolve | tr '\n' ' ') docker compose -f "$COMPOSE" up -d --force-recreate
    ;;
  stop)
    cd "$DETECT_DIR"
    docker compose -f "$COMPOSE" down
    ;;
  *)
    echo "usage: $0 start|stop|resolve" >&2
    exit 2
    ;;
esac

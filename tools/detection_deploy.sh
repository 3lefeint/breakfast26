#!/usr/bin/env bash
# Deploy the dart detection test stack (docker-compose.detection.yml) to the board host and start or stop it.
#
#   DETECT_HOST=user@board-host tools/detection_deploy.sh prepare # build here, copy the image and the files there (starts nothing)
#   DETECT_HOST=user@board-host CAM_PATHS='<name> <name> <name>' tools/detection_deploy.sh up   # start the stack there (Autodarts must be stopped)
#   DETECT_HOST=user@board-host tools/detection_deploy.sh down
#   DETECT_HOST=user@board-host tools/detection_deploy.sh logs
#
# The image is built on this machine and copied over (docker save | docker load), so the board host needs no build tools and no
# internet. The data folder (`data-detect/` next to the compose file on the host) is created from DETECT_DATA (a folder with
# config.toml and detection/calib_model.json) only where a file is missing: a calibration saved on the host is never overwritten.
# Autodarts is NOT touched here: it has to be stopped before `up` (it holds the cameras). `prepare` starts nothing.
set -euo pipefail

HOST="${DETECT_HOST:?set DETECT_HOST to user@host}"
DIR="${DETECT_DIR:-breakfast-detect}"
DATA="${DETECT_DATA:-data/detect-deploy}"
COMPOSE="docker-compose.detection.yml"
cd "$(dirname "$0")/.."

case "${1:-}" in
  prepare)
    docker build -t breakfast-detect:poc .
    docker save breakfast-detect:poc | ssh "$HOST" docker load
    ssh "$HOST" "mkdir -p $DIR/data-detect/detection"
    scp -q "$COMPOSE" "$HOST:$DIR/$COMPOSE"
    for f in config.toml detection/calib_model.json; do
      ssh "$HOST" "test -e $DIR/data-detect/$f" || scp -q "$DATA/$f" "$HOST:$DIR/data-detect/$f"
    done
    ;;
  up)
    # the capture node of each camera, found by its USB port (the numbers of /dev/videoN change with the order of plugging)
    read -r -a cams <<< "${CAM_PATHS:?set CAM_PATHS to the three capture nodes under /dev/v4l/by-path of the board host, space separated}"
    [ "${#cams[@]}" -eq 3 ] || { echo "three cameras are needed, CAM_PATHS has ${#cams[@]}" >&2; exit 2; }
    ssh "$HOST" "cd $DIR && \
      CAM0=\$(readlink -f /dev/v4l/by-path/${cams[0]}) \
      CAM1=\$(readlink -f /dev/v4l/by-path/${cams[1]}) \
      CAM2=\$(readlink -f /dev/v4l/by-path/${cams[2]}) \
      docker compose -f $COMPOSE up -d --force-recreate"
    ;;
  down)
    ssh "$HOST" "cd $DIR && docker compose -f $COMPOSE down"
    ;;
  logs)
    ssh "$HOST" "cd $DIR && docker compose -f $COMPOSE logs --tail 80 -f"
    ;;
  *)
    echo "usage: $0 prepare|up|down|logs" >&2
    exit 2
    ;;
esac

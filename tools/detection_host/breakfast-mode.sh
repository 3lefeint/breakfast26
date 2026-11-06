#!/usr/bin/env bash
# Switches the Breakfast of the board host between its own dart detection and Autodarts.
#
#   breakfast-mode.sh own         stop Autodarts, `[cameras] enabled = true`, restart Breakfast: it reads the cameras itself
#   breakfast-mode.sh autodarts   `[cameras] enabled = false`, restart Breakfast, start Autodarts: the way it was before
#   breakfast-mode.sh status      what the config, Autodarts and the container say now
#   --force                       switch although a match is running (a restart ends it, the match lives in memory)
#
# `own` needs the board model in data/detection/calib_model.json (copy it, together with tracker_settings.json, from the stack that was
# calibrated). Only the one line `enabled` of `[cameras]` in data/config.toml is changed (the section is added when it is missing); the config is
# copied to config.toml.before-mode first. The stats.db is not touched. Autodarts is started and stopped through systemd, which
# the polkit rule of tools/detection_host/README.md allows for the user of the host.
# Settings (environment): APP_DIR (default ~/apps/breakfast26), CONTAINER (breakfast), API (http://127.0.0.1:8080), AUTODARTS (autodarts.service).
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/apps/breakfast26}"
CONTAINER="${CONTAINER:-breakfast}"
API="${API:-http://127.0.0.1:8080}"
AUTODARTS="${AUTODARTS:-autodarts.service}"
CONFIG="$APP_DIR/data/config.toml"

mode="${1:-}"; force=0
[ "${2:-}" = "--force" ] && force=1

cameras_flag() {      # true, false or "none" (no section / no line)
  python3 - "$CONFIG" <<'PY'
import re, sys
section, value = None, "none"
for line in open(sys.argv[1]):
    s = line.strip()
    if s.startswith("["):
        section = s
    elif section == "[cameras]":
        m = re.match(r"enabled\s*=\s*(true|false)", s)
        if m:
            value = m.group(1)
print(value)
PY
}

set_cameras() {       # $1 = true | false
  cp -p "$CONFIG" "$CONFIG.before-mode"
  python3 - "$CONFIG" "$1" <<'PY'
import os, re, sys
path, value = sys.argv[1], sys.argv[2]
lines = open(path).read().split("\n")
start = next((i for i, l in enumerate(lines) if l.strip() == "[cameras]"), None)
if start is None:
    while lines and lines[-1] == "":
        lines.pop()
    lines += ["", "[cameras]", f"enabled = {value}", 'dir = "detection"',
              'devices = ["/dev/cam0", "/dev/cam1", "/dev/cam2"]', "diag_port = 8770", "max_rate = 15", ""]
else:
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
    at = next((i for i in range(start + 1, end) if re.match(r"\s*enabled\s*=", lines[i])), None)
    if at is None:
        lines.insert(start + 1, f"enabled = {value}")
    else:
        lines[at] = f"enabled = {value}"
tmp = path + ".new"
open(tmp, "w").write("\n".join(lines))
os.replace(tmp, path)
PY
}

match_running() {     # a running match lives in the memory of the container; a restart would end it
  local body
  body="$(curl -fsS --max-time 5 "$API/api/state" 2>/dev/null)" || return 1
  python3 -c '
import json, sys
d = json.loads(sys.stdin.read())
g, e = d.get("game") or {}, d.get("elimination") or {}
sys.exit(0 if g.get("match_started") or e.get("active") else 1)' <<<"$body"
}

guard() {
  if [ "$force" = 0 ] && match_running; then
    echo "a match is running on $API: finish it or use --force (the restart ends it)" >&2
    exit 1
  fi
}

case "$mode" in
  own)
    [ -f "$CONFIG" ] || { echo "no config at $CONFIG" >&2; exit 1; }
    [ -f "$APP_DIR/data/detection/calib_model.json" ] || { echo "no board model at $APP_DIR/data/detection/calib_model.json: copy it there first (the detection cannot start without it)" >&2; exit 1; }
    guard
    systemctl stop "$AUTODARTS"          # the cameras are free only after this
    set_cameras true
    docker restart "$CONTAINER" >/dev/null
    echo "own dart detection: Autodarts stopped, $CONTAINER restarted with [cameras] enabled = true"
    ;;
  autodarts)
    [ -f "$CONFIG" ] || { echo "no config at $CONFIG" >&2; exit 1; }
    guard
    set_cameras false
    docker restart "$CONTAINER" >/dev/null   # lets go of the cameras
    systemctl start "$AUTODARTS"
    echo "Autodarts: [cameras] enabled = false, $CONTAINER restarted, Autodarts started"
    ;;
  status)
    echo "config:     [cameras] enabled = $(cameras_flag)"
    echo "autodarts:  $(systemctl is-active "$AUTODARTS" || true)"
    echo "container:  $(docker inspect -f '{{.State.Status}} since {{.State.StartedAt}}' "$CONTAINER" 2>/dev/null || echo missing)"
    ;;
  *)
    echo "usage: $0 own|autodarts|status [--force]" >&2
    exit 2
    ;;
esac

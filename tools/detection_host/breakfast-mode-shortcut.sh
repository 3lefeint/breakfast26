#!/usr/bin/env bash
# What the two desktop shortcuts run: breakfast-mode.sh with a window instead of terminal output. Nothing is shown when it worked,
# except a line that starts with "note:" (for example that the Autodarts app has to be quit by hand); an error is shown with its text.
#
#   breakfast-mode-shortcut.sh own | autodarts
#
# The window is made by kdialog, else zenity, else xmessage (the first one that is installed); without any of them the text goes to stderr.
# Settings (environment): MODE_SCRIPT (default: breakfast-mode.sh next to this file).
set -u

here="$(dirname "$(readlink -f "$0")")"
script="${MODE_SCRIPT:-$here/breakfast-mode.sh}"

show() {      # $1 = error | info, $2 = text
  if command -v kdialog >/dev/null 2>&1; then
    kdialog --title Breakfast "--$([ "$1" = error ] && echo error || echo msgbox)" "$2"
  elif command -v zenity >/dev/null 2>&1; then
    zenity "--$1" --title=Breakfast --text="$2"
  elif command -v xmessage >/dev/null 2>&1; then
    xmessage -center "$2"
  else
    echo "$2" >&2
  fi
}

out="$("$script" "$@" 2>&1)" && status=0 || status=$?
if [ "$status" != 0 ]; then
  show error "${out:-breakfast-mode.sh failed (exit $status)}"
  exit "$status"
fi
notes="$(printf '%s\n' "$out" | grep '^note:' || true)"
[ -z "$notes" ] || show info "$notes"

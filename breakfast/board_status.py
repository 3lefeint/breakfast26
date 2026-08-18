"""Board-status resolution — shared between the cloud connection
(autodarts_client.py) and the local board connection (source_direct.py).

Confirmed against a real local board WS capture: Autodarts' own `status`
field (e.g. "Takeout", "Takeout in progress", "Throw") is already the
right vocabulary and is used directly, unmodified — no renaming into a
separate display vocabulary. The board stays in status "Takeout" the
instant the turn-ending dart registers and remains there through the
physical takeout; only "Throw" moves it back to ready/green.

Only events that don't carry a status field at all fall back to the
name-based map below.
"""

_BOARD_STATUS_MAP = {
    "Takeout started": "Takeout Started",
    "Takeout finished": "Takeout Finished",
    "Manual reset": "Manual reset",
    "Stopped": "Board Stopped",
    "Started": "Board Started",
    "Starting": "Board Starting",
    "Stopping": "Board Stopping",
    "Disconnected": "Board Disconnected",
    "Calibration started": "Calibration Started",
    "Calibration finished": "Calibration Finished",
}

# Fires once per detected dart while already in a known mode, not on a
# mode change — expected at high frequency during normal play, so it's
# excluded from the "unexpected event" logging in callers.
_BOARD_EVENTS_IGNORED = {"Throw detected"}


def resolve(event_name: str, raw_status: str | None = None) -> str | None:
    if raw_status:
        return raw_status
    return _BOARD_STATUS_MAP.get(event_name)


def is_ignorable(event_name: str) -> bool:
    return event_name in _BOARD_EVENTS_IGNORED

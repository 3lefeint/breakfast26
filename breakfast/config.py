"""Load, merge, and persist configuration for Breakfast."""

import logging
import tomllib
import tomli_w
from pathlib import Path

_DEFAULT_PATH = Path("config.toml")

# Fields that can be changed at runtime without restarting the service.
RUNTIME_FIELDS = {"log_level", "language"}


def load(path: str | Path | None = None) -> dict:
    """Return config dict from a TOML file, or {} if the file does not exist."""
    p = Path(path) if path else _DEFAULT_PATH
    if not p.exists():
        return {}
    with open(p, "rb") as f:
        return tomllib.load(f)


def merge(args, cfg: dict) -> None:
    """Fill None fields in *args* from *cfg*, then apply hardcoded fallbacks.

    Priority: CLI value > config file value > hardcoded default.
    Only fields that are None (or False for boolean flags) are overwritten.
    """
    if not cfg:
        _apply_defaults(args)
        return

    mode_cfg = cfg.get(getattr(args, "mode", None) or "", {})
    mqtt = cfg.get("mqtt", {})
    web  = cfg.get("web",  {})
    audio  = cfg.get("audio",  {})
    record = cfg.get("record", {})

    def _fill(attr: str, *candidates):
        """Set args.attr to the first non-None candidate value if attr is None."""
        if getattr(args, attr, None) is None:
            for v in candidates:
                if v is not None:
                    setattr(args, attr, v)
                    return

    # direct mode
    _fill("email",         mode_cfg.get("email"))
    _fill("password",      mode_cfg.get("password"))
    _fill("board_id",      mode_cfg.get("board_id"))
    _fill("board_ws_url",  mode_cfg.get("board_ws_url"))
    _fill("board_manager_url", mode_cfg.get("board_manager_url"))

    # shared
    _fill("record",        record.get("file"), mode_cfg.get("record"))
    _fill("audio_dir",     audio.get("dir"),   mode_cfg.get("audio_dir"))
    _fill("audio_profile", audio.get("profile"))

    # mqtt
    _fill("mqtt_host",       mqtt.get("host"))
    _fill("mqtt_port",       mqtt.get("port"))
    _fill("mqtt_username",   mqtt.get("username"))
    _fill("mqtt_password",   mqtt.get("password"))
    _fill("mqtt_base_topic", mqtt.get("base_topic"))

    # web
    _fill("web_port", web.get("port"))

    # stats
    stats_cfg = cfg.get("stats", {})
    _fill("stats_db", stats_cfg.get("db"))
    _fill("stats_timezone", stats_cfg.get("timezone"))

    # logging
    log_cfg = cfg.get("logging", {})
    _fill("log_level",  log_cfg.get("level"))
    _fill("log_file",   log_cfg.get("file"))
    if getattr(args, "log_events", None) is None:
        v = log_cfg.get("events")
        if v is not None:
            args.log_events = bool(v)

    # replay
    _fill("file",  record.get("file"), mode_cfg.get("file"))
    _fill("speed", mode_cfg.get("speed"))

    _apply_defaults(args)


def write(path: str | Path, updates: dict) -> None:
    """Deep-merge *updates* into the existing TOML at *path* and write it back.

    *updates* must be structured by TOML section (e.g. {"mqtt": {"host": "…"}}).
    Existing keys not in *updates* are preserved; missing sections are created.
    A value of `None` removes that key from its section entirely — TOML has
    no null type, so this is the only way for a caller (the Settings UI's
    PATCH /api/config) to actually clear an optional field, rather than
    writing back an empty string that would just linger in the file forever.
    Comments in the original file are lost (tomllib is read-only).
    """
    p = Path(path)
    existing: dict = {}
    if p.exists():
        with open(p, "rb") as f:
            existing = tomllib.load(f)
    for section, values in updates.items():
        if isinstance(values, dict):
            target = existing.setdefault(section, {})
            for key, value in values.items():
                if value is None:
                    target.pop(key, None)
                else:
                    target[key] = value
        else:
            existing[section] = values
    with open(p, "wb") as f:
        tomli_w.dump(existing, f)


def apply_runtime(log_updates: dict) -> None:
    """Apply runtime-changeable logging settings immediately (no restart needed)."""
    level = log_updates.get("log_level") or log_updates.get("level")
    if level:
        numeric = getattr(logging, level.upper(), None)
        if numeric is not None:
            logging.root.setLevel(numeric)


def _apply_defaults(args) -> None:
    """Apply hardcoded fallbacks for fields that are still None after merging."""
    if getattr(args, "mqtt_port", None) is None:
        args.mqtt_port = 1883
    if getattr(args, "mqtt_base_topic", None) is None:
        args.mqtt_base_topic = "autodarts"
    if getattr(args, "speed", None) is None:
        args.speed = 1.0
    if getattr(args, "stats_db", None) is None:
        args.stats_db = "stats.db"
    if getattr(args, "stats_timezone", None) is None:
        args.stats_timezone = "UTC"
    if getattr(args, "log_level", None) is None:
        args.log_level = "INFO"
    if getattr(args, "log_events", None) is None:
        args.log_events = False
    if getattr(args, "board_ws_url", None) is None:
        args.board_ws_url = "ws://localhost:3180/api/events"

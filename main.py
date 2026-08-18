import argparse
import logging
import os
import sys

from breakfast import __release_date__, __version__
from breakfast import config as cfg_mod
from breakfast.source_replay import run_replay
from breakfast.source_direct import run_direct

log = logging.getLogger(__name__)

# Plain ASCII on purpose (no unicode box-drawing) — renders identically in
# any terminal, `docker logs`, `journalctl`, or a plain log file regardless
# of locale/encoding.
_BANNER = r"""
 ____                  _     __          _
| __ ) _ __ ___  __ _ | | __/ _| __ _ __| |_
|  _ \| '__/ _ \/ _` || |/ / |_ / _` / _` __|
| |_) | | |  __/ (_| ||   <|  _| (_| \__ \|_
|____/|_|  \___|\__,_||_|\_\_|  \__,_|___/\__|

                 .----------------.
              .-'   \    |    /   '-.
            .'       \   |   /       '.
           /----------\--+--/----------\
          |            \ | /            |
          |------------- X -------------|
          |            / | \            |
           \----------/--+--\----------/
            '.       /   |   \       .'
              '-.   /    |    \   .-'
                 '----------------'
                        ||
                        ||
"""


def _log_startup_banner() -> None:
    # One multi-line log.info() call rather than one per line, so the
    # timestamp/level/logger-name prefix only appears once at the very top
    # instead of before every single banner line.
    log.info(_BANNER)
    log.info("Breakfast v%s (%s)", __version__, __release_date__)


class _ColorFormatter(logging.Formatter):
    """Colorizes just the [levelname] tag, not the whole line — keeps long
    DEBUG lines with embedded values readable while severity still stands
    out at a glance.

    Always on regardless of sys.stderr.isatty(): this app's primary
    "interactive terminal" in practice is `docker logs -f`/`docker compose
    logs -f`, where stderr is a pipe from Python's point of view even
    though a human is watching it live — isatty() would be False there,
    defeating the point entirely for the main real-world case. NO_COLOR
    (no-color.org) is the explicit opt-out instead, checked by the caller.
    """

    _COLORS = {
        logging.DEBUG: "\033[34m",       # blue
        logging.INFO: "\033[32m",        # green
        logging.WARNING: "\033[33m",     # yellow
        logging.ERROR: "\033[38;5;208m",  # orange (no standard 8-color orange)
        logging.CRITICAL: "\033[31m",    # red — logging.FATAL is the same level, not a separate one
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self._COLORS.get(record.levelno)
        if not color:
            return super().format(record)
        # Mutate/restore rather than build a fresh copy — record.levelname
        # is shared across every handler attached to the logger (e.g. the
        # plain file handler below), so a permanent change here would leak
        # ANSI codes into the file log too.
        original = record.levelname
        record.levelname = f"{color}{original}{self._RESET}"
        try:
            return super().format(record)
        finally:
            record.levelname = original


def _setup_logging(level_name: str, log_file: str | None = None) -> None:
    level = getattr(logging, (level_name or "INFO").upper(), logging.INFO)
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    formatter_cls = logging.Formatter if os.environ.get("NO_COLOR") else _ColorFormatter
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter_cls(fmt, datefmt="%H:%M:%S"))
    root.addHandler(stream_handler)

    if log_file:
        # Always plain — raw ANSI escape codes in a text file/grep/editor
        # just look like garbage, unlike an interactive terminal.
        fh = logging.FileHandler(log_file)
        fh.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))
        root.addHandler(fh)


def _add_mqtt_args(parser):
    parser.add_argument("--no-mqtt", action="store_true", default=False,
                         help="Disable MQTT/Home Assistant/LED output entirely — "
                              "Elimination/scoreboard/caller work fully without it "
                              "(same effect as config.toml [mqtt] enabled = false)")
    parser.add_argument("--mqtt-host",       default=None)
    parser.add_argument("--mqtt-port",       type=int, default=None)
    parser.add_argument("--mqtt-username",   default=None)
    parser.add_argument("--mqtt-password",   default=None)
    parser.add_argument("--mqtt-base-topic", default=None)


def main():
    # ── Step 1: find --config before the subcommand ──────────────────────────
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default=None, metavar="FILE")
    pre_args, _ = pre.parse_known_args()

    cfg_path = pre_args.config or "config.toml"
    cfg = cfg_mod.load(cfg_path)

    # ── Step 2: inject mode from config if not given on CLI ──────────────────
    cfg_mode = cfg.get("mode", "")
    known_modes = ("direct", "replay", "voicepack")
    if cfg_mode in ("direct", "replay") \
            and not any(a in sys.argv[1:] for a in known_modes):
        sys.argv.insert(1, cfg_mode)

    # ── Step 3: full argument parse ──────────────────────────────────────────
    parser = argparse.ArgumentParser(
        description="Breakfast — bridge Autodarts game events to MQTT and Web UI",
    )
    parser.add_argument(
        "--config", default=None, metavar="FILE",
        help="Path to TOML config file (default: config.toml)",
    )
    parser.add_argument(
        "--stats-db", default=None, metavar="FILE",
        help="SQLite file for session/player stats (default: stats.db, 'none' to disable)",
    )
    parser.add_argument(
        "--log-level", default=None, metavar="LEVEL",
        help="Log level: DEBUG, INFO, WARNING, ERROR (default: INFO)",
    )
    parser.add_argument(
        "--log-file", default=None, metavar="FILE",
        help="Write log output to this file in addition to stderr",
    )
    parser.add_argument(
        "--log-events", default=None, action="store_true",
        help="Log each incoming game event at INFO level (default: off)",
    )
    sub = parser.add_subparsers(dest="mode")

    # direct
    direct = sub.add_parser(
        "direct",
        help="Connect directly to Autodarts cloud (no darts-caller required)",
    )
    direct.add_argument("--email",         default=None, help="Autodarts account email")
    direct.add_argument("--password",      default=None, help="Autodarts account password")
    direct.add_argument("--board-id",      default=None, help="Autodarts board ID")
    direct.add_argument("--record",        default=None)
    direct.add_argument("--audio-dir",     default=None, metavar="DIR")
    direct.add_argument("--audio-profile", default=None, metavar="NAME",
                        help="Voice-pack profile under <audio-dir>/profiles/ (own set is the fallback)")
    direct.add_argument("--no-caller",     action="store_true", default=False,
                        help="Disable voice calls (audio stays available for elimination); "
                             "fine-tuning via [caller] in config.toml")
    direct.add_argument("--web-port",      type=int, default=None, metavar="PORT")
    direct.add_argument("--board-ws-url",  default=None, metavar="URL",
                        help="Local Autodarts board WebSocket URL "
                             "(default: ws://localhost:3180/api/events; "
                             "override e.g. ws://host.docker.internal:3180/api/events "
                             "or ws://autodarts:3180/api/events when containerized)")
    direct.add_argument("--board-manager-url", default=None, metavar="URL",
                        help="Override the Web UI's board-manager link "
                             "(default: auto-resolved from the Autodarts cloud API; "
                             "set this for a home-lab reverse-proxy domain)")
    _add_mqtt_args(direct)

    # replay
    replay = sub.add_parser("replay", help="Replay a recorded session file")
    replay.add_argument("--file",          default=None)
    replay.add_argument("--speed",         type=float, default=None)
    replay.add_argument("--audio-dir",     default=None, metavar="DIR")
    replay.add_argument("--audio-profile", default=None, metavar="NAME",
                        help="Voice-pack profile under <audio-dir>/profiles/ (own set is the fallback)")
    replay.add_argument("--no-caller",     action="store_true", default=False,
                        help="Disable voice calls during the replay")
    replay.add_argument("--web-port",   type=int, default=None, metavar="PORT")
    replay.add_argument("--wait-audio", action="store_true", default=False,
                        help="Wait for a browser on /audio before starting the replay")
    _add_mqtt_args(replay)

    # voicepack
    vp = sub.add_parser(
        "voicepack",
        help="List or install downloadable voice packs (third-party CDN — "
             "nothing is downloaded without --install)",
    )
    vp.add_argument("--list",      action="store_true", help="List downloadable packs")
    vp.add_argument("--installed", action="store_true", help="List installed packs")
    vp.add_argument("--install",   default=None, metavar="NAME",
                    help="Download and install a pack into <audio-dir>/profiles/NAME/")
    vp.add_argument("--url",       default=None, metavar="URL_OR_FILE",
                    help="Override the pack source (URL or local zip)")
    vp.add_argument("--force",     action="store_true", help="Reinstall over an existing pack")
    vp.add_argument("--audio-dir", default=None, metavar="DIR")

    args = parser.parse_args()

    # ── Step 4: fill missing args from config, apply hardcoded defaults ──────
    cfg_mod.merge(args, cfg)

    # ── Step 5: configure logging ────────────────────────────────────────────
    _setup_logging(args.log_level, getattr(args, "log_file", None))
    _log_startup_banner()

    # [caller] section is passed through as a dict; --no-caller overrides
    caller_cfg = dict(cfg.get("caller") or {})
    if getattr(args, "no_caller", False):
        caller_cfg["enabled"] = False

    # MQTT/HA/LED output: an explicit, disableable feature area rather than
    # an implicit side-effect of leaving [mqtt] host blank.
    mqtt_enabled = bool(cfg.get("mqtt", {}).get("enabled", True))
    if getattr(args, "no_mqtt", False):
        mqtt_enabled = False

    # ── Step 6: dispatch ─────────────────────────────────────────────────────
    if args.mode == "direct":
        for flag, val in (("--email", args.email), ("--password", args.password),
                          ("--board-id", args.board_id)):
            if not val:
                direct.error(f"{flag} is required (or set [direct] in config.toml)")
        run_direct(
            email=args.email,
            password=args.password,
            board_id=args.board_id,
            record_file=args.record,
            mqtt_enabled=mqtt_enabled,
            mqtt_host=args.mqtt_host,
            mqtt_port=args.mqtt_port,
            mqtt_username=args.mqtt_username,
            mqtt_password=args.mqtt_password,
            mqtt_base_topic=args.mqtt_base_topic,
            audio_dir=args.audio_dir,
            audio_profile=args.audio_profile,
            caller_cfg=caller_cfg,
            web_port=args.web_port,
            stats_db=args.stats_db,
            log_events=args.log_events,
            config_path=cfg_path,
            board_ws_url=args.board_ws_url,
            board_manager_url=args.board_manager_url,
        )
    elif args.mode == "voicepack":
        from breakfast import voicepack
        if args.list:
            for name in sorted(voicepack.AVAILABLE_PROFILES):
                print(name)
            return
        if not args.audio_dir:
            vp.error("--audio-dir is required (or set [audio] dir in config.toml)")
        if args.installed:
            for name in voicepack.list_profiles(args.audio_dir):
                print(name)
        elif args.install:
            path = voicepack.install_profile(args.audio_dir, args.install,
                                             url=args.url, force=args.force)
            print(f"Installed: {path}")
            print(f"Activate with: [audio] profile = \"{args.install}\" "
                  f"(or --audio-profile)")
        else:
            vp.error("one of --list, --installed, --install NAME is required")
    elif args.mode == "replay":
        if not args.file:
            replay.error("--file is required (or set [record] file in config.toml)")
        run_replay(
            file=args.file,
            speed=args.speed,
            mqtt_enabled=mqtt_enabled,
            mqtt_host=args.mqtt_host,
            mqtt_port=args.mqtt_port,
            mqtt_username=args.mqtt_username,
            mqtt_password=args.mqtt_password,
            mqtt_base_topic=args.mqtt_base_topic,
            audio_dir=args.audio_dir,
            audio_profile=args.audio_profile,
            caller_cfg=caller_cfg,
            web_port=args.web_port,
            wait_audio=args.wait_audio,
            config_path=cfg_path,
            log_events=args.log_events,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

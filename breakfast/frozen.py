"""The standalone build (PyInstaller): where its files live and how the process is kept running.

Layout next to `breakfast.exe`:

    breakfast.exe, _internal/     the program (replaced by an update)
    data/                         config.toml, stats.db, sounds/, ... (never touched by an update)
    update/                       a downloaded release, the backup and the update log

The program runs from the `data/` folder, so every relative default (config.toml, stats.db,
sounds/) lands there, the same as the `data/` directory of the Docker setup.

`breakfast.exe` starts itself a second time as the real app (`BREAKFAST_CHILD`), and the first
process only watches it: the Restart button of the web UI ends the app with exit code 0 and
nothing else would start it again, and an update has to replace the program files, which a
running executable cannot do to itself.
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

log = logging.getLogger(__name__)

CHILD_ENV = "BREAKFAST_CHILD"
CRASH_DELAY_S = 5

_FIRST_RUN_CONFIG = """\
# Breakfast configuration. Enter your Autodarts account under
# Settings → Autodarts Source in the web UI, then use Restart.
mode = "direct"

[direct]
email = ""
password = ""
board_id = ""

[web]
port = 8080

[audio]
dir = "sounds"
"""


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def is_child() -> bool:
    return os.environ.get(CHILD_ENV) == "1"


def install_dir() -> Path:
    return Path(sys.executable).resolve().parent


def data_dir() -> Path:
    return install_dir() / "data"


def update_dir() -> Path:
    return install_dir() / "update"


def bundled_dir() -> Path:
    """Where PyInstaller unpacks the bundled files (`_internal` next to the executable)."""
    return Path(getattr(sys, "_MEIPASS", install_dir()))


def prepare(config_name: str = "config.toml") -> bool:
    """Run from the data folder, put the bundled ffmpeg on the PATH and write a first
    configuration if there is none. Returns True if the configuration was just created."""
    data = data_dir()
    (data / "sounds").mkdir(parents=True, exist_ok=True)
    os.chdir(data)
    ffmpeg = bundled_dir() / "ffmpeg"
    if ffmpeg.is_dir():
        os.environ["PATH"] = str(ffmpeg) + os.pathsep + os.environ.get("PATH", "")
    config = data / config_name
    if config.exists():
        return False
    config.write_text(_FIRST_RUN_CONFIG, encoding="utf-8")
    return True


def configured_port(config_path: Path | None = None) -> int:
    import tomllib
    path = config_path or (data_dir() / "config.toml")
    try:
        with open(path, "rb") as f:
            return int(tomllib.load(f).get("web", {}).get("port", 8080))
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return 8080


def handoff_file() -> Path:
    return update_dir() / "handoff.json"


def handoff_pending() -> bool:
    return handoff_file().exists()


def _open_settings_later(port: int, delay: float = 3.0) -> None:
    def go():
        time.sleep(delay)
        try:
            webbrowser.open(f"http://localhost:{port}/#settings")
        except Exception:
            log.debug("Could not open the browser", exc_info=True)
    threading.Thread(target=go, daemon=True).start()


def supervise(first_run: bool = False) -> int:
    """Run the app as a child process until it is stopped.

    The child ends with exit code 0 when the Restart button was used, and then starts again
    at once. Any other exit code is a crash and starts it again after a short pause. Ctrl+C
    stops the child and returns. An update that was handed over to its script (see
    self_update.py) ends the loop, the script starts the new version.
    """
    env = dict(os.environ, **{CHILD_ENV: "1"})
    handoff_file().unlink(missing_ok=True)      # a leftover of an update that has been completed
    if first_run:
        _open_settings_later(configured_port())
    while True:
        child = subprocess.Popen([sys.executable, *sys.argv[1:]], env=env)
        try:
            code = child.wait()
        except KeyboardInterrupt:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
            return 0
        if handoff_pending():
            log.info("Update handed over, leaving the supervisor")
            return 0
        if code == 0:
            log.info("Restart requested, starting again")
            continue
        log.warning("Breakfast ended with code %s, starting again in %ss", code, CRASH_DELAY_S)
        try:
            time.sleep(CRASH_DELAY_S)
        except KeyboardInterrupt:
            return code


def write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            # Windows refuses to replace a file that a reader (the status poll, a virus scanner)
            # has open at that moment; it is free again within a moment
            if attempt == 19:
                raise
            time.sleep(0.05)

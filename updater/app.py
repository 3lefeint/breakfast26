"""Self-update helper service.

Runs as a Docker sibling to the main `breakfast` container (not inside
it), specifically so it keeps running while `breakfast` is mid-rebuild/
restart — the main container can't safely orchestrate tearing down and
rebuilding itself.

Reachable only over the compose-internal network (no published port in
docker-compose.yml) — nothing outside the `breakfast` container can reach
this API at all, so no auth is needed here. The Docker socket is mounted
in, which is effectively host-root, so every endpoint below runs a fixed,
hardcoded command sequence only — never a caller-supplied string — so
that socket access doesn't turn into a general remote-shell surface.
"""

import asyncio
import logging
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import uvicorn
from fastapi import FastAPI

log = logging.getLogger("updater")


class _ColorFormatter(logging.Formatter):
    """Same formatter as main.py's — duplicated rather than imported since
    this service is deliberately standalone (its own Dockerfile doesn't
    copy the `breakfast` package in at all, to keep it minimal)."""

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
        original = record.levelname
        record.levelname = f"{color}{original}{self._RESET}"
        try:
            return super().format(record)
        finally:
            record.levelname = original

# Same absolute path on both sides of the `${PWD}:${PWD}` bind mount in
# docker-compose.yml — required so `docker compose` commands run in here
# (which control the *host's* daemon via the mounted socket) resolve
# relative volume paths the same way the host itself would.
REPO_DIR = os.environ.get("REPO_DIR") or os.getcwd()
BREAKFAST_HEALTH_URL = os.environ.get("BREAKFAST_HEALTH_URL", "http://breakfast:8080/api/health")
STATS_DB = Path(os.environ.get("STATS_DB") or Path(REPO_DIR) / "data" / "stats.db")
BACKUPS_KEPT = 3
HEALTH_TIMEOUT_S = 90
HEALTH_POLL_INTERVAL_S = 2
# The port Breakfast is published on at the host: `BREAKFAST_PORT` in the untracked `.env` next to the compose file
# (`"${BREAKFAST_PORT:-8080}:8080"`), the port inside the container stays 8080.
ENV_FILE = Path(REPO_DIR) / ".env"
COMPOSE_FILE = Path(REPO_DIR) / "docker-compose.yml"
PORT_VAR = "BREAKFAST_PORT"
DEFAULT_PORT = 8080
PORT_MIN, PORT_MAX = 1024, 65535

app = FastAPI(title="breakfast-updater", docs_url=None, redoc_url=None)

_state = {"phase": "idle", "detail": None, "started_at": None}
_state_lock = threading.Lock()
_port_state = {"phase": "idle", "detail": None}

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _parse_semver(version: str | None) -> tuple[int, int, int] | None:
    if not version:
        return None
    m = _SEMVER_RE.match(version)
    return tuple(int(x) for x in m.groups()) if m else None


def _pick_latest_tag(tags: list[str]) -> str | None:
    """tags are full tag names (e.g. 'v0.2.0'); returns the highest by semver."""
    candidates = [(_parse_semver(t[1:]), t) for t in tags if t.startswith("v")]
    candidates = [(key, t) for key, t in candidates if key]
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][1]


def _is_update_available(current: str | None, latest: str | None) -> bool:
    current_key = _parse_semver(current)
    latest_key = _parse_semver(latest)
    return bool(latest_key and (current_key is None or latest_key > current_key))


def _run(*args, timeout=120):
    return subprocess.run(
        args, cwd=REPO_DIR, capture_output=True, text=True, timeout=timeout, check=True,
    )


def _fetch_and_list_tags() -> list[str]:
    # The repository is public: `origin` is fetched over HTTPS without credentials
    # (docker-compose.yml rewrites an SSH origin address to HTTPS for this container).
    _run("git", "fetch", "--tags", "--force", "origin", "master")
    # --merged origin/master, not a plain `-l` listing: a repo whose history
    # was ever rewritten/squashed (this one has been) can still have old
    # pre-rewrite tags sitting on the remote that are no longer ancestors of
    # the current branch at all. Picking the numerically-highest tag without
    # this filter can select a tag `master` will never actually reach —
    # `_wait_healthy()` would then wait forever for a version that checking
    # out `master` can never produce, and "fail" into a pointless rollback.
    return _run("git", "tag", "--merged", "origin/master", "-l", "v*").stdout.split()


def _latest_tag() -> str | None:
    return _pick_latest_tag(_fetch_and_list_tags())


def _current_version() -> str:
    r = requests.get(BREAKFAST_HEALTH_URL, timeout=5)
    r.raise_for_status()
    return r.json()["version"]


def _backup_db(version: str) -> Path | None:
    """Copy the statistics database before an update from *version* into `backups/` next to it, with SQLite's backup
    API (consistent while the app runs), and keep the last few. The same as breakfast/db_backup.py: this service
    does not carry the `breakfast` package. None when there is no database file."""
    if not STATS_DB.is_file():
        return None
    directory = STATS_DB.parent / "backups"
    directory.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = directory / f"{STATS_DB.stem}-v{version}-{stamp}.db"
    src = sqlite3.connect(f"file:{STATS_DB}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    pattern = re.compile(rf"^{re.escape(STATS_DB.stem)}-v[\w.]+-\d{{8}}-\d{{6}}\.db$")
    for old in sorted((p for p in directory.iterdir() if pattern.match(p.name)), key=lambda p: p.name, reverse=True)[BACKUPS_KEPT:]:
        old.unlink(missing_ok=True)
    return target


def _restore_db(backup: Path) -> None:
    """Put the copy back as the database; its write-ahead files belong to the state that is replaced."""
    shutil.copyfile(backup, STATS_DB)
    for suffix in ("-wal", "-shm"):
        Path(f"{STATS_DB}{suffix}").unlink(missing_ok=True)


def _wait_healthy(expected_version: str, timeout=HEALTH_TIMEOUT_S) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(BREAKFAST_HEALTH_URL, timeout=3)
            if r.status_code == 200 and r.json().get("version") == expected_version:
                return True
        except requests.RequestException:
            pass
        time.sleep(HEALTH_POLL_INTERVAL_S)
    return False


def _set_phase(phase: str, detail: str | None = None) -> None:
    with _state_lock:
        _state["phase"] = phase
        _state["detail"] = detail
    log.info("phase=%s detail=%s", phase, detail)


def _self_restart() -> None:
    # Recreating this container from inside itself kills the very process
    # running the command halfway through (compose stops the old container
    # after creating the new one, which then never starts). A detached
    # helper container, started from this same image, does the recreate
    # instead and outlives the container it replaces.
    try:
        image = _run("docker", "inspect", "--format", "{{.Image}}", socket.gethostname()).stdout.strip()
        _run(
            "docker", "run", "-d", "--rm",
            "--entrypoint", "docker",
            "-v", "/var/run/docker.sock:/var/run/docker.sock",
            "-v", f"{REPO_DIR}:{REPO_DIR}",
            "-w", REPO_DIR,
            "-e", f"PWD={REPO_DIR}",
            image,
            "compose", "up", "-d", "--build", "updater",
            timeout=60,
        )
    except Exception:
        # Best-effort — the main app's update already succeeded and was
        # already reported as such; worst case this needs one manual
        # `docker compose up -d --build updater` on the host.
        log.exception("self-restart after successful update failed")


def _run_apply() -> None:
    try:
        previous_version = _current_version()
        last_good = _run("git", "rev-parse", "HEAD").stdout.strip()

        _set_phase("checking")
        latest = _latest_tag()
        if not latest:
            _set_phase("failed", "no release tag found on origin")
            return
        target_version = latest[1:]
        if not _is_update_available(previous_version, target_version):
            _set_phase("failed", f"already on the latest version ({previous_version})")
            return

        _set_phase("backing_up")
        try:
            db_copy = _backup_db(previous_version)
        except Exception as e:
            _set_phase("failed", f"the backup of the statistics database failed, nothing was changed: {e}")
            return

        _set_phase("fetching")
        _run("git", "fetch", "origin", "master")
        _run("git", "checkout", "master")
        _run("git", "reset", "--hard", "FETCH_HEAD")

        _set_phase("building")
        _run("docker", "compose", "up", "-d", "--build", "breakfast", timeout=600)

        _set_phase("health_checking")
        if _wait_healthy(target_version):
            _set_phase("done", latest)
            threading.Thread(target=_self_restart, daemon=True).start()
            return

        _set_phase("rolling_back", f"{latest} did not come up healthy")
        _run("git", "reset", "--hard", last_good)
        if db_copy:
            _run("docker", "compose", "stop", "breakfast", timeout=120)
            _restore_db(db_copy)
        _run("docker", "compose", "up", "-d", "--build", "breakfast", timeout=600)
        if _wait_healthy(previous_version):
            _set_phase("rolled_back", f"update to {latest} failed its health check, reverted to {previous_version}"
                                      + (" and the statistics database was restored" if db_copy else ""))
        else:
            _set_phase("failed", f"rollback to {previous_version} also failed its health check — needs a manual look")
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()[:500]
        _set_phase("failed", f"command failed ({' '.join(e.cmd)}): {stderr}")
    except Exception as e:
        log.exception("update failed")
        _set_phase("failed", str(e))


@app.get("/check")
async def check():
    log.debug("Update check requested")
    try:
        current = await asyncio.to_thread(_current_version)
    except Exception as e:
        return {"error": f"could not reach breakfast: {e}"}
    try:
        latest = await asyncio.to_thread(_latest_tag)
    except subprocess.CalledProcessError as e:
        return {"error": f"git fetch failed: {(e.stderr or '').strip()[:300]}"}
    if not latest:
        return {"error": "no release tag found on origin"}
    latest_version = latest[1:]
    return {
        "current": current,
        "latest": latest_version,
        "update_available": _is_update_available(current, latest_version),
    }


@app.post("/apply")
async def apply():
    log.debug("Apply requested")
    with _state_lock:
        if _state["phase"] not in ("idle", "done", "rolled_back", "failed"):
            return {"ok": False, "error": "an update is already in progress"}
        _state["phase"] = "starting"
        _state["detail"] = None
        _state["started_at"] = time.time()
    threading.Thread(target=_run_apply, daemon=True).start()
    return {"ok": True}


def _compose_has_port_variable() -> bool:
    """False for a checkout whose compose file still has the fixed 8080:8080 (before the update that brings the variable)."""
    try:
        return PORT_VAR in COMPOSE_FILE.read_text()
    except OSError:
        return False


def _read_env_lines() -> list[str] | None:
    try:
        return ENV_FILE.read_text().splitlines()
    except OSError:
        return None


def _env_port(lines: list[str] | None) -> int:
    for line in lines or []:
        key, sep, value = line.partition("=")
        if sep and key.strip() == PORT_VAR and value.strip().isdigit():
            return int(value.strip())
    return DEFAULT_PORT


def _write_env_port(lines: list[str] | None, port: int) -> None:
    """Set BREAKFAST_PORT in `.env`, every other line stays as it is."""
    kept = [line for line in lines or [] if line.partition("=")[0].strip() != PORT_VAR]
    ENV_FILE.write_text("\n".join([*kept, f"{PORT_VAR}={port}"]) + "\n")


def _restore_env(lines: list[str] | None) -> None:
    if lines is None:
        ENV_FILE.unlink(missing_ok=True)
    else:
        ENV_FILE.write_text("\n".join(lines) + ("\n" if lines else ""))


# Exit code of the bind probe when the port is taken (anything else that fails means the probe itself did not work).
_PORT_TAKEN = 3


def _port_free(port: int) -> bool | None:
    """Whether the host can still bind *port*: a short container from this image on the host network tries it.
    None when the probe could not run (the recreate then decides)."""
    probe = ("import socket, sys\n"
             "s = socket.socket()\n"
             f"try: s.bind(('0.0.0.0', {port}))\n"
             f"except OSError: sys.exit({_PORT_TAKEN})\n")
    try:
        image = _run("docker", "inspect", "--format", "{{.Image}}", socket.gethostname()).stdout.strip()
        _run("docker", "run", "--rm", "--network", "host", "--entrypoint", "python", image, "-c", probe, timeout=60)
        return True
    except subprocess.CalledProcessError as e:
        return False if e.returncode == _PORT_TAKEN else None
    except Exception:
        return None


def _set_port_phase(phase: str, detail: str | None = None) -> None:
    with _state_lock:
        _port_state["phase"] = phase
        _port_state["detail"] = detail
    log.info("port phase=%s detail=%s", phase, detail)


def _run_port_change(previous: list[str] | None, port: int) -> None:
    """Recreate `breakfast` with the new published port; on a failure put the old `.env` back and recreate again."""
    try:
        _set_port_phase("recreating")
        _run("docker", "compose", "up", "-d", "breakfast", timeout=300)
        _set_port_phase("done", str(port))
    except Exception as e:
        stderr = (getattr(e, "stderr", "") or str(e)).strip()[:300]
        log.exception("port change failed")
        try:
            _restore_env(previous)
            _run("docker", "compose", "up", "-d", "breakfast", timeout=300)
        except Exception:
            log.exception("restoring the old port failed")
        _set_port_phase("failed", stderr)


@app.get("/port")
async def get_port():
    log.debug("Port requested")
    with _state_lock:
        state = dict(_port_state)
    return {"port": _env_port(_read_env_lines()), "supported": _compose_has_port_variable(), **state}


@app.post("/port")
async def set_port(body: dict):
    port = body.get("port")
    if not isinstance(port, int) or isinstance(port, bool) or not PORT_MIN <= port <= PORT_MAX:
        return {"ok": False, "code": "invalid", "error": f"the port must be a number from {PORT_MIN} to {PORT_MAX}"}
    if not _compose_has_port_variable():
        return {"ok": False, "code": "unsupported", "error": "the compose file has no port setting yet, update first"}
    with _state_lock:
        if _state["phase"] not in ("idle", "done", "rolled_back", "failed") \
                or _port_state["phase"] == "recreating":
            return {"ok": False, "code": "busy", "error": "an update or a port change is in progress"}
        _port_state["phase"] = "recreating"
        _port_state["detail"] = None
    previous = _read_env_lines()
    if port == _env_port(previous):
        _set_port_phase("idle")
        return {"ok": False, "code": "same", "error": "that port is already set"}
    if await asyncio.to_thread(_port_free, port) is False:
        _set_port_phase("idle")
        return {"ok": False, "code": "in_use", "error": f"port {port} is already in use on this machine"}
    _write_env_port(previous, port)
    threading.Thread(target=_run_port_change, args=(previous, port), daemon=True).start()
    return {"ok": True}


@app.get("/status")
async def status():
    log.debug("Status requested")
    with _state_lock:
        return dict(_state)


if __name__ == "__main__":
    level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handler = logging.StreamHandler()
    formatter_cls = logging.Formatter if os.environ.get("NO_COLOR") else _ColorFormatter
    handler.setFormatter(formatter_cls(fmt, datefmt="%H:%M:%S"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(level)
    uvicorn.run(app, host="0.0.0.0", port=8090, log_level="warning")

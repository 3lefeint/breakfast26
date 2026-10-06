"""Self-update of the standalone Windows build (the counterpart of the Docker `updater` service).

The release workflow attaches `breakfast-windows-vX.Y.Z.zip` (one folder `breakfast/` with
`breakfast.exe` and `_internal/`) and `breakfast-windows-vX.Y.Z.zip.sha256` to every GitHub
release. An update downloads and verifies the zip, unpacks it next to the installation and
hands over to a small batch script, which only starts once the old program has ended (a running
executable cannot replace its own files):

    1. back up the installation (everything but `data/` and `update/`)
    2. copy the new version over it
    3. start it and wait for /api/health to report the new version
    4. if that does not happen in time, restore the backup and start the old version again

The script does the health check and the rollback itself, so a new version that cannot start at
all is rolled back as well. It writes the outcome to `update/status.json`, which the web UI reads
after the restart.
"""

import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import requests

from breakfast import frozen

log = logging.getLogger(__name__)

RELEASE_API = os.environ.get(
    "BREAKFAST_RELEASE_API", "https://api.github.com/repos/3lefeint/breakfast26/releases/latest")
EXE_NAME = "breakfast.exe"
ASSET_RE = re.compile(r"^breakfast-windows-v(\d+\.\d+\.\d+)\.zip$")
_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_ACTIVE_PHASES = ("starting", "checking", "fetching", "verifying", "installing")
NO_BUILD = "no Windows build has been published yet"
HEALTH_TRIES = 45          # 45 tries, 2 s apart: the new version has 90 s to answer

_lock = threading.Lock()


# ── versions and releases ────────────────────────────────────────────────────

def parse_semver(version: str | None):
    m = _SEMVER_RE.match(version or "")
    return tuple(int(x) for x in m.groups()) if m else None


def is_newer(current: str | None, latest: str | None) -> bool:
    latest_key = parse_semver(latest)
    current_key = parse_semver(current)
    return bool(latest_key and (current_key is None or latest_key > current_key))


def latest_release() -> dict | None:
    """The newest release with a Windows build: version, zip name and urls of the zip and of its
    checksum. None if the release has no such asset."""
    r = requests.get(RELEASE_API, headers={"Accept": "application/vnd.github+json"}, timeout=15)
    if r.status_code == 404:      # GitHub answers 404 while the repository has no release at all
        return None
    r.raise_for_status()
    release = r.json()
    assets = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}
    for name, url in assets.items():
        m = ASSET_RE.match(name)
        if m and name + ".sha256" in assets:
            return {"version": m.group(1), "zip_name": name, "zip_url": url,
                    "sha_url": assets[name + ".sha256"],
                    "page": release.get("html_url")}
    return None


def check(current: str) -> dict:
    try:
        release = latest_release()
    except Exception as e:
        return {"error": f"could not reach GitHub: {e}"}
    if not release:
        return {"error": NO_BUILD}
    return {"current": current, "latest": release["version"],
            "update_available": is_newer(current, release["version"])}


# ── status ───────────────────────────────────────────────────────────────────

def _status_file() -> Path:
    return frozen.update_dir() / "status.json"


def _set_phase(phase: str, detail: str | None = None) -> None:
    frozen.write_json_atomic(_status_file(), {"phase": phase, "detail": detail, "at": time.time()})
    log.info("update phase=%s detail=%s", phase, detail)


def status() -> dict:
    import json
    try:
        return json.loads(_status_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"phase": "idle", "detail": None}


# ── download and unpack ──────────────────────────────────────────────────────

def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            shutil.copyfileobj(r.raw, f)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify(zip_path: Path, checksum_text: str) -> bool:
    """The checksum file holds `<sha256>  <file name>` (the output of sha256sum)."""
    expected = (checksum_text.split() or [""])[0].lower()
    return bool(expected) and _sha256(zip_path) == expected


def unpack(zip_path: Path, staging: Path) -> Path:
    """Unpack into *staging* and return the folder that holds `breakfast.exe`. Refuses a zip
    whose entries would land outside of *staging*."""
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    root = staging.resolve()
    with zipfile.ZipFile(zip_path) as z:
        for member in z.namelist():
            target = (staging / member).resolve()
            if root != target and root not in target.parents:
                raise ValueError(f"unsafe path in the update archive: {member}")
        z.extractall(staging)
    for candidate in (staging / "breakfast", staging):
        if (candidate / EXE_NAME).is_file():
            return candidate
    raise ValueError(f"the update archive has no {EXE_NAME}")


# ── the script that swaps the files ──────────────────────────────────────────

def build_script() -> str:
    """The batch script. Arguments: install dir, new files, backup dir, pid to wait for, port,
    expected version."""
    return r'''@echo off
setlocal enableextensions
set "INSTALL=%~1"
set "NEWFILES=%~2"
set "BACKUP=%~3"
set "PARENT=%~4"
set "PORT=%~5"
set "VERSION=%~6"
set "STATUS=%INSTALL%\update\status.json"
set "LOG=%INSTALL%\update\update.log"
set "KEEP=/XD data update"
set "QUIET=/NFL /NDL /NJH /NJS /NP"

echo [%date% %time%] update to %VERSION%, waiting for process %PARENT% >> "%LOG%"
set /a WAITED=0
:wait
powershell -NoProfile -Command "if (Get-Process -Id %PARENT% -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >> "%LOG%" 2>&1
if errorlevel 1 goto parent_gone
set /a WAITED+=1
if %WAITED% GEQ 60 (
  echo [%date% %time%] process %PARENT% did not end, stopping it >> "%LOG%"
  taskkill /F /T /PID %PARENT% >> "%LOG%" 2>&1
  ping -n 3 127.0.0.1 >nul
  goto parent_gone
)
ping -n 2 127.0.0.1 >nul
goto wait
:parent_gone

echo [%date% %time%] backing up >> "%LOG%"
if exist "%BACKUP%" rmdir /s /q "%BACKUP%"
robocopy "%INSTALL%" "%BACKUP%" /MIR %KEEP% %QUIET% >> "%LOG%" 2>&1
if errorlevel 8 goto backup_failed

echo [%date% %time%] installing >> "%LOG%"
robocopy "%NEWFILES%" "%INSTALL%" /MIR %KEEP% %QUIET% >> "%LOG%" 2>&1
if errorlevel 8 goto restore

echo [%date% %time%] starting the new version >> "%LOG%"
start "" "%INSTALL%\breakfast.exe"

set /a TRIES=0
:poll
set /a TRIES+=1
powershell -NoProfile -Command "try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:%PORT%/api/health' -TimeoutSec 3; if ($r.version -eq '%VERSION%') { exit 0 } else { exit 1 } } catch { exit 1 }"
if not errorlevel 1 goto ok
if %TRIES% GEQ __HEALTH_TRIES__ goto restore
ping -n 3 127.0.0.1 >nul
goto poll

:ok
echo [%date% %time%] new version is healthy >> "%LOG%"
>"%STATUS%" echo {"phase":"done","detail":"v%VERSION%"}
rmdir /s /q "%BACKUP%" 2>nul
rmdir /s /q "%INSTALL%\update\staging" 2>nul
goto end

:restore
echo [%date% %time%] the new version did not come up, restoring the backup >> "%LOG%"
taskkill /F /T /IM breakfast.exe >nul 2>&1
ping -n 3 127.0.0.1 >nul
robocopy "%BACKUP%" "%INSTALL%" /MIR %KEEP% %QUIET% >> "%LOG%" 2>&1
>"%STATUS%" echo {"phase":"rolled_back","detail":"v%VERSION% did not pass its health check, the previous version is back"}
start "" "%INSTALL%\breakfast.exe"
goto end

:backup_failed
echo [%date% %time%] the backup failed, nothing was changed >> "%LOG%"
>"%STATUS%" echo {"phase":"failed","detail":"the backup of the installation failed, nothing was changed"}
start "" "%INSTALL%\breakfast.exe"

:end
endlocal
'''.replace("__HEALTH_TRIES__", str(HEALTH_TRIES))


def _spawn_script(script: Path, args: list) -> None:
    """Start the script detached, so it outlives this process (and its supervisor)."""
    quoted = " ".join(f'"{a}"' for a in [script, *args])
    cmd = f'cmd.exe /d /s /c "{quoted}"'
    flags = 0
    if sys.platform == "win32":
        flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                 | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000))
    kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        subprocess.Popen(cmd, creationflags=flags, **kwargs)
    except OSError:
        # a job that does not allow a breakaway
        subprocess.Popen(cmd, creationflags=flags & ~0x01000000, **kwargs)


def _leave_for_handoff() -> None:
    threading.Timer(1.0, lambda: os._exit(0)).start()


# ── the update itself ────────────────────────────────────────────────────────

def apply(current: str, *, spawn=_spawn_script, leave=_leave_for_handoff) -> dict:
    """Start an update in the background. *spawn* and *leave* exist for the tests."""
    with _lock:
        current_status = status()
        # a phase that has not changed for a quarter of an hour is a leftover of a crash
        if (current_status.get("phase") in _ACTIVE_PHASES
                and time.time() - current_status.get("at", 0) < 900):
            return {"ok": False, "error": "an update is already in progress"}
        _set_phase("starting")
    threading.Thread(target=_run, args=(current, spawn, leave), daemon=True).start()
    return {"ok": True}


def _run(current: str, spawn, leave) -> None:
    try:
        _set_phase("checking")
        release = latest_release()
        if not release:
            _set_phase("failed", NO_BUILD)
            return
        if not is_newer(current, release["version"]):
            _set_phase("failed", f"already on the latest version ({current})")
            return

        _set_phase("fetching", release["zip_name"])
        work = frozen.update_dir() / "download"
        zip_path = work / release["zip_name"]
        _download(release["zip_url"], zip_path)
        checksum = requests.get(release["sha_url"], timeout=30)
        checksum.raise_for_status()

        _set_phase("verifying")
        if not verify(zip_path, checksum.text):
            _set_phase("failed", "the checksum of the download does not match")
            return

        _set_phase("installing")
        new_files = unpack(zip_path, frozen.update_dir() / "staging")
        shutil.rmtree(work, ignore_errors=True)

        script = frozen.update_dir() / "apply-update.cmd"
        script.write_text(build_script(), encoding="utf-8")
        frozen.write_json_atomic(frozen.handoff_file(), {"version": release["version"]})
        spawn(script, [frozen.install_dir(), new_files, frozen.update_dir() / "backup",
                       os.getppid(), frozen.configured_port(), release["version"]])
        leave()
    except Exception as e:
        log.exception("update failed")
        try:
            frozen.handoff_file().unlink(missing_ok=True)
        except OSError:
            pass
        _set_phase("failed", str(e))

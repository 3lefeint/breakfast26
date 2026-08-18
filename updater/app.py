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
import subprocess
import threading
import time

import requests
import uvicorn
from fastapi import FastAPI

log = logging.getLogger("updater")

# Same absolute path on both sides of the `${PWD}:${PWD}` bind mount in
# docker-compose.yml — required so `docker compose` commands run in here
# (which control the *host's* daemon via the mounted socket) resolve
# relative volume paths the same way the host itself would.
REPO_DIR = os.environ.get("REPO_DIR") or os.getcwd()
BREAKFAST_HEALTH_URL = os.environ.get("BREAKFAST_HEALTH_URL", "http://breakfast:8080/api/health")
HEALTH_TIMEOUT_S = 90
HEALTH_POLL_INTERVAL_S = 2

app = FastAPI(title="breakfast-updater", docs_url=None, redoc_url=None)

_state = {"phase": "idle", "detail": None, "started_at": None}
_state_lock = threading.Lock()

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
    # Auth is via GIT_SSH_COMMAND + the read-only deploy key mounted in by
    # docker-compose.yml (this repo is private) — plain `origin` works
    # transparently once that's set up, no URL rewriting needed here.
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
    try:
        _run("docker", "compose", "up", "-d", "--build", "updater", timeout=300)
    except Exception:
        # Best-effort — the main app's update already succeeded and was
        # already reported as such; worst case this needs one manual
        # `docker compose up -d --build updater` over Tailscale.
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
        _run("docker", "compose", "up", "-d", "--build", "breakfast", timeout=600)
        if _wait_healthy(previous_version):
            _set_phase("rolled_back", f"update to {latest} failed its health check, reverted to {previous_version}")
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
    with _state_lock:
        if _state["phase"] not in ("idle", "done", "rolled_back", "failed"):
            return {"ok": False, "error": "an update is already in progress"}
        _state["phase"] = "starting"
        _state["detail"] = None
        _state["started_at"] = time.time()
    threading.Thread(target=_run_apply, daemon=True).start()
    return {"ok": True}


@app.get("/status")
async def status():
    with _state_lock:
        return dict(_state)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    uvicorn.run(app, host="0.0.0.0", port=8090, log_level="warning")

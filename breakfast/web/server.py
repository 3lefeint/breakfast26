"""FastAPI web server — real-time browser UI for Breakfast."""

import asyncio
import logging
import os
import threading
import time
import tomllib
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from breakfast import __release_date__, __version__
from breakfast import config as cfg_mod
from breakfast import known_players as kp

log = logging.getLogger(__name__)

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# Vite/Svelte build output (frontend/ -> breakfast/web/dist via the
# Dockerfile's node builder stage) — cut over as of this version, replacing
# the old hand-written templates entirely.
_DIST_DIR             = os.path.join(os.path.dirname(__file__), "dist")
_DIST_INDEX_PATH      = os.path.join(_DIST_DIR, "index.html")
_DIST_TV_HTML_PATH    = os.path.join(_DIST_DIR, "tv.html")
_DIST_AUDIO_HTML_PATH = os.path.join(_DIST_DIR, "audio.html")

# ── Shared state (injected via wire()) ───────────────────────────────────────

_game_state = None
_elim_ctrl = None
_cloud_client = None
_stats_tracker = None
_stats_db = None
_mqtt_pub = None
_start_time: float = time.time()
_config_path: str | None = None
_audio_engine = None
_board_manager_url: str | None = None
_voicepack_status = {"running": False, "done": 0, "skipped": 0, "total": 0, "error": None}
_dev_demo = None

# ── WebSocket broadcaster ─────────────────────────────────────────────────────

_loop: asyncio.AbstractEventLoop | None = None
_clients: set[WebSocket] = set()
_audio_clients: set[WebSocket] = set()
_last_payload: dict = {}


def wire(game_state, elim_ctrl,
         cloud_client=None, stats_tracker=None, mqtt_pub=None, config_path=None,
         audio_engine=None, board_manager_url: str | None = None, dev_demo=None):
    global _game_state, _elim_ctrl, _cloud_client, _stats_tracker, \
           _stats_db, _mqtt_pub, _config_path, _audio_engine, _board_manager_url, \
           _dev_demo
    _game_state = game_state
    _elim_ctrl = elim_ctrl
    _cloud_client = cloud_client
    _stats_tracker = stats_tracker
    _stats_db = stats_tracker._db if stats_tracker else None
    _mqtt_pub = mqtt_pub
    _config_path = config_path
    _audio_engine = audio_engine
    _board_manager_url = board_manager_url
    _dev_demo = dev_demo


def _build_payload() -> dict:
    game_snap = _game_state.snapshot() if _game_state else {}
    if _elim_ctrl and _elim_ctrl.game:
        elim_snap = _elim_ctrl.game.snapshot()
    elif _elim_ctrl:
        elim_snap = {"active": False}
    else:
        elim_snap = None
    session_stats = _stats_tracker.computed_session_stats() if _stats_tracker else {}
    known_players = kp.load(_stats_db)
    return {
        "game": game_snap,
        "elimination": elim_snap,
        "known_players": known_players,
        "hidden_players": _stats_db.hidden_players() if _stats_db else [],
        "elimination_wins": kp.load_wins(_stats_db),
        "x01_wins": kp.load_x01_wins(_stats_db),
        "players_missing_audio": (
            [n for n in known_players if not _audio_engine.has_audio(n.lower())]
            if _audio_engine else []
        ),
        "has_cloud_control": _cloud_client is not None,
        "session_stats": session_stats,
        "voicepack_generation": _voicepack_status,
        "dev_demo": _dev_demo.status() if _dev_demo else None,
    }


async def _send_to(clients: set, data: dict):
    dead = set()
    for ws in clients:
        try:
            await ws.send_json(data)
        except Exception:
            dead.add(ws)
    clients.difference_update(dead)


def push():
    """Call from any thread after state changes to push to all browser clients."""
    global _last_payload
    _last_payload = _build_payload()
    if _loop and _loop.is_running() and _clients:
        asyncio.run_coroutine_threadsafe(_send_to(_clients, _last_payload), _loop)


def push_sound(instruction: dict):
    """Call from any thread to send a play instruction to audio-role clients."""
    if _loop and _loop.is_running() and _audio_clients:
        asyncio.run_coroutine_threadsafe(_send_to(_audio_clients, instruction), _loop)


def audio_client_count() -> int:
    return len(_audio_clients)


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="Breakfast", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
if os.path.isdir(os.path.join(_DIST_DIR, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(_DIST_DIR, "assets")), name="assets")


@app.get("/", response_class=HTMLResponse)
async def index():
    with open(_DIST_INDEX_PATH, encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/tv", response_class=HTMLResponse)
async def tv():
    with open(_DIST_TV_HTML_PATH, encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/audio", response_class=HTMLResponse)
async def audio_page():
    with open(_DIST_AUDIO_HTML_PATH, encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(os.path.join(_STATIC_DIR, "favicon.ico"))


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    _clients.add(ws)
    # Only clients that opted in via /ws?role=audio receive play instructions,
    # so a phone glancing at the scoreboard doesn't start blaring calls.
    if ws.query_params.get("role") == "audio":
        _audio_clients.add(ws)
    try:
        await ws.send_json(_last_payload if _last_payload else _build_payload())
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(ws)
        _audio_clients.discard(ws)


@app.get("/api/sound/{filename}")
async def get_sound(filename: str, v: str | None = None):
    if not _audio_engine:
        raise HTTPException(status_code=404, detail="no audio engine configured")
    path = _audio_engine.resolve(filename)
    if not path:
        raise HTTPException(status_code=404, detail="unknown sound file")
    # The same filename (e.g. "matchon.mp3") can resolve to a different file
    # depending on the active [audio] profile, so the browser must not keep a
    # stale cached response after a profile change — but the profile can't
    # change without a full restart (it's not in config.py's RUNTIME_FIELDS),
    # so instead of forbidding all caching, the frontend appends `?v=` (see
    # AudioEngine.version, a hash of the resolved dir search path) to every
    # sound URL. `v` isn't used for resolution — it exists only so the URL
    # itself changes when the profile changes, which is all a cache needs to
    # invalidate correctly. This lets repeated sounds (e.g. a called number)
    # be served from cache instead of re-fetched every time.
    return FileResponse(path, media_type="audio/mpeg", headers={
        "Cache-Control": "public, max-age=31536000, immutable",
    })


# ── REST: state ───────────────────────────────────────────────────────────────

@app.get("/api/state")
async def get_state():
    return _build_payload()


@app.get("/api/health")
async def get_health():
    return {
        "version": __version__,
        "release_date": __release_date__,
        "uptime_s": round(time.time() - _start_time, 1),
        "mqtt": {
            "connected": _mqtt_pub.connected if _mqtt_pub else None,
        },
        "autodarts": {
            "connected": _cloud_client.connected if _cloud_client else None,
            "match_active": _cloud_client._match_active if _cloud_client else None,
            **(_cloud_client.match_status() if _cloud_client else {}),
        },
        "stats_db": {
            "enabled": _stats_db is not None,
        },
    }


@app.get("/api/board-address")
async def get_board_address():
    """Local Autodarts board manager URL, for a jump-off link in the UI.

    An explicit `[direct] board_manager_url` override always wins (e.g. a
    home-lab reverse-proxy domain); otherwise resolved from the Autodarts
    cloud API via the connected client — no DNS/cert needed, works
    unmodified at a clubhouse with neither.
    """
    if _board_manager_url:
        return {"address": _board_manager_url}
    if not _cloud_client:
        return {"address": None}
    address = await asyncio.to_thread(_cloud_client._get_board_address)
    return {"address": address}


# ── REST: board / match control ───────────────────────────────────────────────

def _run_in_thread(fn):
    threading.Thread(target=fn, daemon=True).start()


@app.post("/api/control/undo")
async def control_undo():
    if not _cloud_client:
        return {"error": "cloud control not available"}
    _run_in_thread(_cloud_client.undo_throw)
    return {"ok": True}


@app.post("/api/control/next-player")
async def control_next_player():
    if not _cloud_client:
        return {"error": "cloud control not available"}
    _run_in_thread(_cloud_client.next_player)
    return {"ok": True}


@app.post("/api/control/next-game")
async def control_next_game():
    if not _cloud_client:
        return {"error": "cloud control not available"}
    _run_in_thread(_cloud_client.next_game)
    return {"ok": True}


@app.post("/api/control/reset-board")
async def control_reset_board():
    if not _cloud_client:
        return {"error": "cloud control not available"}
    _run_in_thread(_cloud_client.reset_board)
    return {"ok": True}


@app.post("/api/control/force-clear-match")
async def control_force_clear_match():
    """Manually unblock Elimination/freeplay when a match on the Autodarts
    side was abandoned (no finish/delete event ever arrives)."""
    if not _cloud_client:
        return {"error": "cloud control not available"}
    _run_in_thread(_cloud_client.force_clear_match)
    return {"ok": True}


@app.post("/api/control/restart")
async def control_restart():
    """Deliberately exit the whole process — everything else
    (MQTT, board WS, web server) runs as daemon threads off this one, so
    killing it is enough. Relies on the surrounding supervisor
    (docker-compose's `restart: unless-stopped`, systemd, etc.) to bring
    it back up; a bare `python main.py` run with no supervisor just stops.
    Delayed so this response reaches the browser before the process dies."""
    log.info("Restart requested via UI")
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return {"ok": True}


class CorrectThrowBody(BaseModel):
    dart: int   # 1, 2, or 3
    field: str  # e.g. "T20", "D16", "25", "0"


@app.post("/api/control/correct-throw")
async def control_correct_throw(body: CorrectThrowBody):
    if not _cloud_client:
        return {"error": "cloud control not available"}
    if body.dart not in (1, 2, 3):
        return {"error": "dart must be 1, 2, or 3"}
    _run_in_thread(lambda: _cloud_client.correct_throw(body.dart, body.field))
    return {"ok": True}


# ── REST: elimination ─────────────────────────────────────────────────────────

class StartBody(BaseModel):
    players: list[str]
    lives: int = 3


class CorrectBody(BaseModel):
    total: int


class CorrectDartBody(BaseModel):
    dart: int   # 1, 2, or 3
    field: str  # e.g. "T20", "D16", "25", "50", "0"


@app.post("/api/elimination/start")
async def elim_start(body: StartBody):
    if not _elim_ctrl:
        return {"error": "no elimination controller"}
    players = [p.strip() for p in body.players if p.strip()]
    if len(players) < 2:
        return {"error": "need at least 2 players"}
    _elim_ctrl.start(players, max(1, body.lives))
    return {"ok": True}


@app.post("/api/elimination/stop")
async def elim_stop():
    if _elim_ctrl:
        _elim_ctrl.stop()
    return {"ok": True}


@app.post("/api/elimination/correct")
async def elim_correct(body: CorrectBody):
    if _elim_ctrl and _elim_ctrl.game:
        _elim_ctrl.game.correct_turn(body.total)
    return {"ok": True}


@app.post("/api/elimination/correct-dart")
async def elim_correct_dart(body: CorrectDartBody):
    if body.dart not in (1, 2, 3):
        return {"error": "dart must be 1, 2, or 3"}
    if _elim_ctrl and _elim_ctrl.game:
        _elim_ctrl.game.correct_current_dart(body.dart - 1, body.field)
    return {"ok": True}


# ── REST: stats ──────────────────────────────────────────────────────────────

@app.get("/api/stats/players")
async def stats_players():
    if not _stats_db:
        return []
    return _stats_db.all_players_stats()


@app.get("/api/stats/player/{name}")
async def stats_player(name: str):
    if not _stats_db:
        return {}
    return _stats_db.player_stats(name) or {}


@app.get("/api/stats/matches")
async def stats_matches():
    if not _stats_db:
        return []
    return _stats_db.recent_matches()


@app.get("/api/stats/match/{match_id}")
async def stats_match(match_id: str):
    if not _stats_db:
        return {}
    return _stats_db.match_stats(match_id)


@app.delete("/api/stats/player/{name}")
async def stats_delete_player(name: str):
    if not _stats_db:
        return {"error": "stats not enabled"}
    _stats_db.delete_player(name)
    return {"ok": True}


@app.get("/api/stats/dashboard/{name}")
async def stats_dashboard(name: str, points_start: int | None = None):
    """Advanced per-player dashboard — one bundled fetch."""
    if not _stats_db:
        return {}
    return _stats_db.player_dashboard(name, points_start=points_start)


# ── REST: leaderboard ────────────────────────────────────────────────────────

@app.get("/api/leaderboard")
async def get_leaderboard(
    metric: str = Query(default="avg3"),
    limit: int = Query(default=10, ge=1, le=100),
):
    if not _stats_db:
        return []
    try:
        return _stats_db.leaderboard(metric, limit)
    except ValueError:
        return []


# ── REST: config ─────────────────────────────────────────────────────────────

_MASK = "●●●●●"
_SECRET_KEYS = {"password"}


def _mask(d: dict, keys: set) -> dict:
    return {k: (_MASK if k in keys and v else v) for k, v in d.items()}


@app.get("/api/config")
async def get_config():
    if not _config_path:
        return {"error": "config path not available"}
    raw = cfg_mod.load(_config_path)
    mqtt = raw.get("mqtt", {})
    log  = raw.get("logging", {})
    stats = raw.get("stats", {})
    web  = raw.get("web", {})
    direct = raw.get("direct", {})
    audio = raw.get("audio", {})
    caller = raw.get("caller", {})
    record = raw.get("record", {})
    return {
        "mode": raw.get("mode"),
        "mqtt": _mask({
            "enabled":    mqtt.get("enabled", True),
            "host":       mqtt.get("host"),
            "port":       mqtt.get("port", 1883),
            "username":   mqtt.get("username"),
            "password":   mqtt.get("password"),
            "base_topic": mqtt.get("base_topic", "autodarts"),
        }, _SECRET_KEYS),
        "logging": {
            "level":  log.get("level", "INFO"),
            "file":   log.get("file"),
            "events": log.get("events", False),
        },
        "stats": {
            "db": stats.get("db", "stats.db"),
        },
        "web": {
            "port":         web.get("port", 8080),
            "theme":        web.get("theme", "default"),
            "accent_color": web.get("accent_color"),
        },
        "direct": _mask({
            "email":         direct.get("email"),
            "password":      direct.get("password"),
            "board_id":      direct.get("board_id"),
            "board_ws_url":  direct.get("board_ws_url", "ws://localhost:3180/api/events"),
            "board_manager_url": direct.get("board_manager_url"),
        }, _SECRET_KEYS),
        "audio": {
            "dir":     audio.get("dir"),
            "profile": audio.get("profile"),
        },
        "caller": {
            "enabled":         caller.get("enabled", True),
            "per_dart":        caller.get("per_dart", True),
            "turn_total":      caller.get("turn_total", True),
            "checkout_limit":  caller.get("checkout_limit", 1),
            "announce_change": caller.get("announce_change", False),
            "call_player":     caller.get("call_player", True),
            "ambient_volume":  caller.get("ambient_volume", 0.6),
            "call_misses":     caller.get("call_misses", True),
        },
        "record": {
            "file": record.get("file"),
        },
        "runtime_fields": list(cfg_mod.RUNTIME_FIELDS),
        # Read-only — not part of the editable Settings form. True when
        # either `[dev] enabled = true` in config.toml, or the version-tap
        # runtime unlock (POST /api/dev/unlock) fired this session. Only
        # gates whether the Settings "Dev" tab (and its /api/dev/demo/*
        # endpoints) are exposed.
        "dev": {
            "enabled": _dev_enabled(raw),
        },
    }


@app.patch("/api/config")
async def patch_config(body: dict):
    if not _config_path:
        return {"error": "config path not available"}

    # Strip masked placeholders so secrets aren't overwritten with "●●●●●"
    def _clean(section: dict) -> dict:
        return {k: v for k, v in section.items() if v != _MASK}

    updates: dict = {}
    changed_non_runtime: list[str] = []

    for section, values in body.items():
        if not isinstance(values, dict):
            continue
        cleaned = _clean(values)
        if not cleaned:
            continue
        updates[section] = cleaned
        for key in cleaned:
            flat = key if section == "logging" else f"{section}.{key}"
            if key not in cfg_mod.RUNTIME_FIELDS:
                changed_non_runtime.append(flat)

    cfg_mod.write(_config_path, updates)
    cfg_mod.apply_runtime(updates.get("logging", {}))

    return {"saved": True, "restart_required": changed_non_runtime}


# ── REST: voice pack ──────────────────────────────────────────────────────────

def _run_async_in_thread(coro_fn):
    threading.Thread(target=lambda: asyncio.run(coro_fn()), daemon=True).start()


class VoicepackGenerateBody(BaseModel):
    force: bool = False


@app.post("/api/voicepack/generate")
async def voicepack_generate(body: VoicepackGenerateBody):
    """Regenerate the voice pack — force=False only fills in
    missing keys (fast), force=True re-generates everything, including
    keys whose text changed since the last generation (slow, several
    minutes for the full pack)."""
    if _voicepack_status["running"]:
        return {"error": "generation already running"}
    if not _audio_engine:
        return {"error": "audio not configured"}

    from tools.generate_voicepack import run as generate_run

    plan_path = Path(__file__).resolve().parents[2] / "tools" / "voicepack_leni.toml"
    with open(plan_path, "rb") as f:
        plan = tomllib.load(f)
    name = plan["voice"].split("-")[-1].removesuffix("Neural").lower()
    cfg = cfg_mod.load(_config_path) if _config_path else {}
    audio_dir = cfg.get("audio", {}).get("dir", "sounds")
    out_dir = Path(audio_dir) / "profiles" / name

    _voicepack_status.update(running=True, done=0, skipped=0, total=0, error=None)
    push()

    async def task():
        def on_progress(done, skipped, total):
            _voicepack_status.update(done=done, skipped=skipped, total=total)
            push()
        try:
            await generate_run(plan, out_dir, only=None, force=body.force,
                                dry_run=False, trim=True, on_progress=on_progress)
        except Exception as e:
            log.exception("Voice-pack generation failed")
            _voicepack_status["error"] = str(e)
        finally:
            _voicepack_status["running"] = False
            push()

    _run_async_in_thread(task)
    return {"ok": True}


# ── REST: dev demo ────────────────────────────────────────────────────────────

# In-memory only — never written to config.toml, so it always resets to
# False on the next process restart (the Android "tap the version number"
# pattern: unlocked for this running instance only, never persisted).
_dev_unlocked = False


def _dev_enabled(raw: dict | None = None) -> bool:
    if _dev_unlocked:
        return True
    if raw is None:
        if not _config_path:
            return False
        raw = cfg_mod.load(_config_path)
    return bool(raw.get("dev", {}).get("enabled", False))


@app.post("/api/dev/unlock")
async def dev_unlock():
    """Runtime-only Dev-tab unlock, triggered by repeatedly tapping the
    version number in the Home footer — no config.toml write, so it's gone
    again the next time the process restarts."""
    global _dev_unlocked
    _dev_unlocked = True
    return {"unlocked": True}


@app.post("/api/dev/demo/x01")
async def dev_demo_x01():
    if not _dev_enabled():
        return {"started": False, "error": "[dev] not enabled in config"}
    if not _dev_demo:
        return {"started": False, "error": "demo unavailable"}
    started, error = _dev_demo.start_x01()
    if started:
        push()
    return {"started": started, "error": error}


@app.post("/api/dev/demo/elimination")
async def dev_demo_elimination():
    if not _dev_enabled():
        return {"started": False, "error": "[dev] not enabled in config"}
    if not _dev_demo:
        return {"started": False, "error": "demo unavailable"}
    started, error = _dev_demo.start_elimination()
    if started:
        push()
    return {"started": started, "error": error}


# ── REST: players ─────────────────────────────────────────────────────────────

class PlayerBody(BaseModel):
    name: str


@app.get("/api/players")
async def list_players():
    return kp.load(_stats_db)


@app.post("/api/players")
async def add_player(body: PlayerBody):
    name = body.name.strip()
    if not name:
        return {"error": "empty name"}
    return kp.add(name, _stats_db)


class HiddenBody(BaseModel):
    hidden: bool


@app.patch("/api/players/{name}/hidden")
async def set_player_hidden(name: str, body: HiddenBody):
    """Hide/unhide a player from the Players tab and from
    leaderboard()/all_players_stats() (same flag controls both) —
    non-destructive and reversible, unlike DELETE /api/stats/player/{name}."""
    if not _stats_db:
        return {"error": "stats not enabled"}
    _stats_db.upsert_player(name, hidden=body.hidden)
    return {"ok": True}


@app.get("/api/players/hidden")
async def hidden_players():
    if not _stats_db:
        return []
    return _stats_db.hidden_players()


# ── Startup ───────────────────────────────────────────────────────────────────

def start(port: int = 8080):
    global _loop
    _loop = asyncio.new_event_loop()

    def run():
        asyncio.set_event_loop(_loop)
        config = uvicorn.Config(
            app, host="0.0.0.0", port=port, log_level="warning", loop="none"
        )
        server = uvicorn.Server(config)
        server.install_signal_handlers = lambda: None
        _loop.run_until_complete(server.serve())

    threading.Thread(target=run, daemon=True, name="web-server").start()
    log.info("Web UI at http://0.0.0.0:%s", port)

"""FastAPI web server — real-time browser UI for Breakfast."""

import asyncio
import logging
import os
import re
import tempfile
import threading
import time
import tomllib
from pathlib import Path

import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from breakfast import __release_date__, __version__
from breakfast import achievement_sounds as ach_sounds
from breakfast import achievements as ach_mod
from breakfast import config as cfg_mod
from breakfast import changelog as changelog_mod
from breakfast import joke as joke_mod
from breakfast import known_players as kp
from breakfast import online as online_mod
from breakfast import frozen, self_update
from breakfast import voicepack
from breakfast import voicepack_editor as ve
from breakfast import voicepack_overlay as vo
from breakfast import checkout_routes as co_routes
from breakfast.checkout_training import RANGES as CHECKOUT_RANGES

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
_tb_ctrl = None
_killer_ctrl = None
_ft_ctrl = None
_co_ctrl = None
_bb_ctrl = None
_online = None
_cloud_client = None
_stats_tracker = None
_stats_db = None
_mqtt_pub = None
_start_time: float = time.time()
_config_path: str | None = None
_CHANGELOG_PATH = Path(__file__).resolve().parents[2] / "CHANGELOG.md"
_audio_engine = None
_board_manager_url: str | None = None
_voicepack_status = {"running": False, "done": 0, "skipped": 0, "total": 0, "error": None}
_dev_demo = None

# ── WebSocket broadcaster ─────────────────────────────────────────────────────

_loop: asyncio.AbstractEventLoop | None = None
_clients: set[WebSocket] = set()
_audio_clients: set[WebSocket] = set()


def wire(game_state, elim_ctrl,
         cloud_client=None, stats_tracker=None, mqtt_pub=None, config_path=None,
         audio_engine=None, board_manager_url: str | None = None, dev_demo=None,
         tb_ctrl=None, killer_ctrl=None, ft_ctrl=None, bb_ctrl=None, co_ctrl=None):
    global _game_state, _elim_ctrl, _tb_ctrl, _killer_ctrl, _ft_ctrl, _bb_ctrl, _co_ctrl, _cloud_client, _stats_tracker, \
           _stats_db, _mqtt_pub, _config_path, _audio_engine, _board_manager_url, \
           _dev_demo, _online
    _game_state = game_state
    _elim_ctrl = elim_ctrl
    _tb_ctrl = tb_ctrl
    _killer_ctrl = killer_ctrl
    _ft_ctrl = ft_ctrl
    _co_ctrl = co_ctrl
    _bb_ctrl = bb_ctrl
    _online = online_mod.OnlineSession(elim_ctrl, on_change=push) if elim_ctrl else None
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
    if _tb_ctrl and _tb_ctrl.game:
        tb_snap = _tb_ctrl.game.snapshot()
    elif _tb_ctrl:
        tb_snap = {"active": False}
    else:
        tb_snap = None
    if _killer_ctrl and _killer_ctrl.game:
        killer_snap = _killer_ctrl.game.snapshot()
    elif _killer_ctrl:
        killer_snap = {"active": False}
    else:
        killer_snap = None
    if _ft_ctrl and _ft_ctrl.game:
        ft_snap = _ft_ctrl.game.snapshot()
    elif _ft_ctrl:
        ft_snap = {"active": False}
    else:
        ft_snap = None
    if _bb_ctrl and _bb_ctrl.game:
        bb_snap = _bb_ctrl.game.snapshot()
    elif _bb_ctrl:
        bb_snap = {"active": False}
    else:
        bb_snap = None
    if _co_ctrl and _co_ctrl.game:
        co_snap = _co_ctrl.game.snapshot()
    elif _co_ctrl:
        co_snap = {"active": False}
    else:
        co_snap = None
    session_stats = _stats_tracker.computed_session_stats() if _stats_tracker else {}
    known_players = kp.load(_stats_db)
    return {
        "game": game_snap,
        "board_darts": _game_state.board_darts.snapshot() if _game_state else None,
        "elimination": elim_snap,
        "target_battle": tb_snap,
        "killer": killer_snap,
        "field_training": ft_snap,
        "black_belt": bb_snap,
        "checkout_training": co_snap,
        "known_players": known_players,
        "hidden_players": _stats_db.hidden_players() if _stats_db else [],
        "player_colors": _stats_db.player_colors() if _stats_db else {},
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
        "online": _online.status() if _online and _online.active else None,
    }


def _move_board_dart(index: int, field: str):
    """Show a corrected dart at the center of its new field."""
    if _game_state and _game_state.board_darts.override(index, field):
        push()


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
    if _loop and _loop.is_running() and _clients:
        asyncio.run_coroutine_threadsafe(_send_to(_clients, _build_payload()), _loop)


def push_sound(instruction: dict):
    """Call from any thread to send a play instruction to audio-role clients."""
    if _loop and _loop.is_running() and _audio_clients:
        asyncio.run_coroutine_threadsafe(_send_to(_audio_clients, instruction), _loop)


def push_achievement(message: dict):
    """Call from any thread to tell every browser client about an earned achievement."""
    if _loop and _loop.is_running() and _clients:
        asyncio.run_coroutine_threadsafe(_send_to(_clients, message), _loop)


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
    role = ws.query_params.get("role")
    if role == "audio":
        _audio_clients.add(ws)
    log.info("WS connected (role=%s, clients=%d)", role or "default", len(_clients))
    try:
        await ws.send_json(_build_payload())
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(ws)
        _audio_clients.discard(ws)
        log.info("WS disconnected (role=%s, clients=%d)", role or "default", len(_clients))


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


@app.get("/api/changelog")
async def get_changelog():
    """CHANGELOG.md as versions with their sections, for the About page."""
    try:
        text = _CHANGELOG_PATH.read_text(encoding="utf-8")
    except OSError:
        return {"versions": []}
    return {"versions": changelog_mod.parse_changelog(text)}


SUPPORTED_LANGUAGES = ("en", "de")


_AURORA_KEYS = ("aurora_base", "aurora_1", "aurora_2", "aurora_3")
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
AURORA_PALETTES = ("northern", "ember", "lavender", "graphite", "sakura")
# [web] settings of the look that are whole numbers: (lowest, highest, default)
_LOOK_NUMBERS = {
    "aurora_speed": (25, 300, 100),         # % of the normal speed of the drift
    "aurora_intensity": (30, 115, 100),     # % of the normal strength of the color areas
    "aurora_blur": (30, 200, 100),          # % of the normal softness
    "aurora_pause_idle": (0, 240, 0),       # minutes without input until the aurora stops, 0 = never
    "glass_strength": (50, 200, 100),       # % of the normal milkiness of the glass panels
    "bar_opacity": (50, 100, 92),           # % the top bar covers the page that scrolls under it
}


def _look_number(web: dict, key: str) -> int:
    low, high, default = _LOOK_NUMBERS[key]
    value = web.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high else default


def _bad_look_value(key: str, value):
    """The error message for a [web] look setting that is out of range, or None if it is fine."""
    if value is None:
        return None
    if key in _AURORA_KEYS and not _HEX_COLOR.match(str(value)):
        return f"{key} must be a color like #1a2b3c"
    if key in _LOOK_NUMBERS:
        low, high, _ = _LOOK_NUMBERS[key]
        if not (isinstance(value, int) and not isinstance(value, bool) and low <= value <= high):
            return f"{key} must be a whole number from {low} to {high}"
    if key == "aurora_palette" and value not in ("", *AURORA_PALETTES):
        return "aurora_palette must be one of: " + ", ".join(AURORA_PALETTES)
    if key == "aurora_streaks" and not isinstance(value, bool):
        return "aurora_streaks must be true or false"
    return None


@app.get("/api/appearance")
async def get_appearance():
    """The look every page applies at start: the theme and the accent color, the colors of the
    aurora (None = the one of the theme) and whether the aurora moves."""
    web = (cfg_mod.load(_config_path) if _config_path else {}).get("web", {})
    return {
        "theme": web.get("theme", "default"),
        "accent_color": web.get("accent_color"),
        "aurora_animation": bool(web.get("aurora_animation", True)),
        "aurora": {key.removeprefix("aurora_"): (web.get(key) or None) for key in _AURORA_KEYS},
        "palette": web.get("aurora_palette") if web.get("aurora_palette") in AURORA_PALETTES else None,
        "streaks": bool(web.get("aurora_streaks", True)),
        "speed": _look_number(web, "aurora_speed"),
        "intensity": _look_number(web, "aurora_intensity"),
        "blur": _look_number(web, "aurora_blur"),
        "pause_idle": _look_number(web, "aurora_pause_idle"),
        "glass": _look_number(web, "glass_strength"),
        "bar": _look_number(web, "bar_opacity"),
    }


@app.get("/api/language")
async def get_language():
    """The language of the interface, `[web] language`; anything unknown falls back to English."""
    raw = cfg_mod.load(_config_path) if _config_path else {}
    language = raw.get("web", {}).get("language", "en")
    return {"language": language if language in SUPPORTED_LANGUAGES else "en",
            "supported": list(SUPPORTED_LANGUAGES)}


@app.get("/api/joke")
async def get_joke():
    """Joke of the day; `[web] joke_of_the_day = false` turns it off and makes no outbound call."""
    raw = cfg_mod.load(_config_path) if _config_path else {}
    if not raw.get("web", {}).get("joke_of_the_day", True):
        return {"enabled": False, "joke": None, "source": None}
    return {"enabled": True, **await asyncio.to_thread(joke_mod.joke_of_the_day)}


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
    log.debug("Undo requested")
    if not _cloud_client:
        return {"error": "cloud control not available"}
    _run_in_thread(_cloud_client.undo_throw)
    return {"ok": True}


@app.post("/api/control/next-player")
async def control_next_player():
    log.debug("Next player requested")
    if not _cloud_client:
        return {"error": "cloud control not available"}
    _run_in_thread(_cloud_client.next_player)
    return {"ok": True}


@app.post("/api/control/next-game")
async def control_next_game():
    log.debug("Next game requested")
    if not _cloud_client:
        return {"error": "cloud control not available"}
    _run_in_thread(_cloud_client.next_game)
    return {"ok": True}


@app.post("/api/control/reset-board")
async def control_reset_board():
    log.debug("Reset board requested")
    if not _cloud_client:
        return {"error": "cloud control not available"}
    _run_in_thread(_cloud_client.reset_board)
    return {"ok": True}


@app.post("/api/control/force-clear-match")
async def control_force_clear_match():
    """Manually unblock Elimination/freeplay when a match on the Autodarts
    side was abandoned (no finish/delete event ever arrives)."""
    log.info("Force-clear-match requested via UI")
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
    log.debug("Correct-throw requested: dart=%s field=%s", body.dart, body.field)
    if not _cloud_client:
        return {"error": "cloud control not available"}
    if body.dart not in (1, 2, 3):
        return {"error": "dart must be 1, 2, or 3"}
    _run_in_thread(lambda: _cloud_client.correct_throw(body.dart, body.field))
    _move_board_dart(body.dart - 1, body.field)
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
    # elimination.py's own EliminationGame logs the "Game started" INFO
    # milestone once it actually starts — this is just the REST-layer
    # entry, not a duplicate of that.
    log.debug("Elimination start requested: players=%s lives=%s", body.players, body.lives)
    if not _elim_ctrl:
        return {"error": "no elimination controller"}
    if _online and _online.active:
        return {"error": "an online match is open, leave it first"}
    if _tb_ctrl and _tb_ctrl.active:
        return {"error": "a Target Battle is running, stop it first"}
    if _killer_ctrl and _killer_ctrl.active:
        return {"error": "a Killer game is running, stop it first"}
    if _ft_ctrl and _ft_ctrl.active:
        return {"error": "a Field Training run is open, stop it first"}
    if _bb_ctrl and _bb_ctrl.active:
        return {"error": "a Black Belt run is open, stop it first"}
    if _co_ctrl and _co_ctrl.active:
        return {"error": "a Checkout Training run is open, stop it first"}
    players = [p.strip() for p in body.players if p.strip()]
    if len(players) < 2:
        return {"error": "need at least 2 players"}
    _elim_ctrl.start(players, max(1, body.lives))
    return {"ok": True}


@app.post("/api/elimination/stop")
async def elim_stop():
    log.debug("Elimination stop requested")
    if _online and _online.active:
        await asyncio.to_thread(_online.leave)
    if _elim_ctrl:
        _elim_ctrl.stop()
    return {"ok": True}


@app.post("/api/elimination/correct")
async def elim_correct(body: CorrectBody):
    log.debug("Elimination correct requested: total=%s", body.total)
    if _elim_ctrl and _elim_ctrl.game:
        _elim_ctrl.game.correct_turn(body.total)
    return {"ok": True}


@app.post("/api/elimination/undo")
async def elim_undo():
    log.debug("Elimination undo requested")
    if not (_elim_ctrl and _elim_ctrl.game):
        return {"error": "no active or finished game"}
    if _elim_ctrl.game.online:
        return {"error": "undo is not available in an online match yet"}
    if not _elim_ctrl.game.undo():
        return {"error": "nothing to undo"}
    return {"ok": True}


@app.post("/api/elimination/correct-dart")
async def elim_correct_dart(body: CorrectDartBody):
    log.debug("Elimination correct-dart requested: dart=%s field=%s", body.dart, body.field)
    if body.dart not in (1, 2, 3):
        return {"error": "dart must be 1, 2, or 3"}
    if _elim_ctrl and _elim_ctrl.game:
        _elim_ctrl.game.correct_current_dart(body.dart - 1, body.field)
    _move_board_dart(body.dart - 1, body.field)
    return {"ok": True}


@app.post("/api/elimination/correct-last-dart")
async def elim_correct_last_dart(body: CorrectDartBody):
    """Correct a dart of the last finished turn, also after it ended the match."""
    log.debug("Elimination correct-last-dart requested: dart=%s field=%s", body.dart, body.field)
    if body.dart not in (1, 2, 3):
        return {"error": "dart must be 1, 2, or 3"}
    if not (_elim_ctrl and _elim_ctrl.game):
        return {"error": "no active or finished game"}
    if _elim_ctrl.game.online:
        return {"error": "correcting a finished turn is not available in an online match yet"}
    if not _elim_ctrl.game.correct_last_dart(body.dart - 1, body.field):
        return {"error": "no turn to correct"}
    _move_board_dart(body.dart - 1, body.field)
    return {"ok": True}


# ── REST: target battle ───────────────────────────────────────────────────────

class TargetBattleStartBody(BaseModel):
    players: list[str]
    rounds: int = 10
    targets: list[int] | None = None     # one target per round, None for a random one each round
    scoring: str = "standard"            # standard, singles, doubles or triples
    tiebreak: bool = False


@app.post("/api/target-battle/start")
async def tb_start(body: TargetBattleStartBody):
    log.debug("Target Battle start requested: players=%s rounds=%s scoring=%s",
              body.players, body.rounds, body.scoring)
    if not _tb_ctrl:
        return {"error": "no target battle controller"}
    if _online and _online.active:
        return {"error": "an online match is open, leave it first"}
    if _elim_ctrl and _elim_ctrl.active:
        return {"error": "an Elimination game is running, stop it first"}
    if _killer_ctrl and _killer_ctrl.active:
        return {"error": "a Killer game is running, stop it first"}
    if _ft_ctrl and _ft_ctrl.active:
        return {"error": "a Field Training run is open, stop it first"}
    if _bb_ctrl and _bb_ctrl.active:
        return {"error": "a Black Belt run is open, stop it first"}
    if _co_ctrl and _co_ctrl.active:
        return {"error": "a Checkout Training run is open, stop it first"}
    players = [p.strip() for p in body.players if p.strip()]
    try:
        _tb_ctrl.start(players, rounds=body.rounds, targets=body.targets,
                       scoring=body.scoring, tiebreak=body.tiebreak)
    except ValueError as e:
        return {"error": str(e)}
    return {"ok": True}


@app.post("/api/target-battle/stop")
async def tb_stop():
    log.debug("Target Battle stop requested")
    if _tb_ctrl:
        _tb_ctrl.stop()
    return {"ok": True}


@app.post("/api/target-battle/correct")
async def tb_correct(body: CorrectBody):
    log.debug("Target Battle correct requested: total=%s", body.total)
    if _tb_ctrl and _tb_ctrl.game:
        _tb_ctrl.game.correct_turn(body.total)
    return {"ok": True}


@app.post("/api/target-battle/undo")
async def tb_undo():
    log.debug("Target Battle undo requested")
    if not (_tb_ctrl and _tb_ctrl.game):
        return {"error": "no active or finished game"}
    if not _tb_ctrl.game.undo():
        return {"error": "nothing to undo"}
    return {"ok": True}


@app.post("/api/target-battle/correct-dart")
async def tb_correct_dart(body: CorrectDartBody):
    log.debug("Target Battle correct-dart requested: dart=%s field=%s", body.dart, body.field)
    if body.dart not in (1, 2, 3):
        return {"error": "dart must be 1, 2, or 3"}
    if _tb_ctrl and _tb_ctrl.game:
        _tb_ctrl.game.correct_current_dart(body.dart - 1, body.field)
    _move_board_dart(body.dart - 1, body.field)
    return {"ok": True}


# ── REST: killer ──────────────────────────────────────────────────────────────

class KillerStartBody(BaseModel):
    players: list[str]
    own_goal: bool = False     # a valid hit on the own number costs an active killer a life
    singles: bool = False      # singles take lives too, not only doubles
    bull_off: bool = True      # the closest dart at the bull starts
    throw_numbers: bool = True # everybody throws a dart for their number, else they are drawn


@app.post("/api/killer/start")
async def killer_start(body: KillerStartBody):
    log.debug("Killer start requested: players=%s own_goal=%s singles=%s",
              body.players, body.own_goal, body.singles)
    if not _killer_ctrl:
        return {"error": "no killer controller"}
    if _online and _online.active:
        return {"error": "an online match is open, leave it first"}
    if _elim_ctrl and _elim_ctrl.active:
        return {"error": "an Elimination game is running, stop it first"}
    if _tb_ctrl and _tb_ctrl.active:
        return {"error": "a Target Battle is running, stop it first"}
    if _ft_ctrl and _ft_ctrl.active:
        return {"error": "a Field Training run is open, stop it first"}
    if _bb_ctrl and _bb_ctrl.active:
        return {"error": "a Black Belt run is open, stop it first"}
    if _co_ctrl and _co_ctrl.active:
        return {"error": "a Checkout Training run is open, stop it first"}
    players = [p.strip() for p in body.players if p.strip()]
    try:
        _killer_ctrl.start(players, own_goal=body.own_goal, singles=body.singles,
                           bull_off=body.bull_off, throw_numbers=body.throw_numbers)
    except ValueError as e:
        return {"error": str(e)}
    return {"ok": True}


@app.post("/api/killer/stop")
async def killer_stop():
    log.debug("Killer stop requested")
    if _killer_ctrl:
        _killer_ctrl.stop()
    return {"ok": True}


@app.post("/api/killer/undo")
async def killer_undo():
    log.debug("Killer undo requested")
    if not (_killer_ctrl and _killer_ctrl.game):
        return {"error": "no active or finished game"}
    if not _killer_ctrl.game.undo():
        return {"error": "nothing to undo"}
    return {"ok": True}


@app.post("/api/killer/correct-dart")
async def killer_correct_dart(body: CorrectDartBody):
    """Correct a dart of the turn in progress."""
    log.debug("Killer correct-dart requested: dart=%s field=%s", body.dart, body.field)
    if body.dart not in (1, 2, 3):
        return {"error": "dart must be 1, 2, or 3"}
    if _killer_ctrl and _killer_ctrl.game:
        _killer_ctrl.game.correct_current_dart(body.dart - 1, body.field)
    _move_board_dart(body.dart - 1, body.field)
    return {"ok": True}


@app.post("/api/killer/correct-last-dart")
async def killer_correct_last_dart(body: CorrectDartBody):
    """Correct a dart of the last finished turn, also after it ended the game."""
    log.debug("Killer correct-last-dart requested: dart=%s field=%s", body.dart, body.field)
    if body.dart not in (1, 2, 3):
        return {"error": "dart must be 1, 2, or 3"}
    if not (_killer_ctrl and _killer_ctrl.game):
        return {"error": "no active or finished game"}
    if not _killer_ctrl.game.correct_last_dart(body.dart - 1, body.field):
        return {"error": "no turn to correct"}
    return {"ok": True}


# ── REST: field training ──────────────────────────────────────────────────────

class FieldTrainingStartBody(BaseModel):
    player: str
    field: int                 # 1 to 20, or 25 for the bull
    darts: int | None = None   # None for the standard number: 100 at a number, 50 at the bull


@app.post("/api/field-training/start")
async def ft_start(body: FieldTrainingStartBody):
    log.debug("Field Training start requested: player=%s field=%s darts=%s",
              body.player, body.field, body.darts)
    if not _ft_ctrl:
        return {"error": "no field training controller"}
    if _online and _online.active:
        return {"error": "an online match is open, leave it first"}
    if _elim_ctrl and _elim_ctrl.active:
        return {"error": "an Elimination game is running, stop it first"}
    if _tb_ctrl and _tb_ctrl.active:
        return {"error": "a Target Battle is running, stop it first"}
    if _killer_ctrl and _killer_ctrl.active:
        return {"error": "a Killer game is running, stop it first"}
    if _bb_ctrl and _bb_ctrl.active:
        return {"error": "a Black Belt run is open, stop it first"}
    if _co_ctrl and _co_ctrl.active:
        return {"error": "a Checkout Training run is open, stop it first"}
    try:
        _ft_ctrl.start(body.player, body.field, darts=body.darts)
    except ValueError as e:
        return {"error": str(e)}
    return {"ok": True}


@app.post("/api/field-training/stop")
async def ft_stop():
    log.debug("Field Training stop requested")
    if _ft_ctrl:
        _ft_ctrl.stop()
    return {"ok": True}


@app.post("/api/field-training/finish")
async def ft_finish():
    """End the run early and keep what was thrown as practice; a run without a dart is dropped."""
    log.debug("Field Training finish requested")
    if not _ft_ctrl:
        return {"error": "no field training controller"}
    if not _ft_ctrl.finish_early():
        _ft_ctrl.stop()
    return {"ok": True}


@app.post("/api/field-training/undo")
async def ft_undo():
    log.debug("Field Training undo requested")
    if not (_ft_ctrl and _ft_ctrl.game):
        return {"error": "no active or finished run"}
    if not _ft_ctrl.game.undo():
        return {"error": "nothing to undo"}
    return {"ok": True}


@app.post("/api/field-training/correct-dart")
async def ft_correct_dart(body: CorrectDartBody):
    log.debug("Field Training correct-dart requested: dart=%s field=%s", body.dart, body.field)
    if body.dart not in (1, 2, 3):
        return {"error": "dart must be 1, 2, or 3"}
    if _ft_ctrl and _ft_ctrl.game:
        _ft_ctrl.game.correct_current_dart(body.dart - 1, body.field)
    _move_board_dart(body.dart - 1, body.field)
    return {"ok": True}


# ── REST: black belt ──────────────────────────────────────────────────────────

class BlackBeltStartBody(BaseModel):
    player: str
    backwards: bool = False    # D20 down to D1, the bull's eye still last


@app.post("/api/black-belt/start")
async def bb_start(body: BlackBeltStartBody):
    log.debug("Black Belt start requested: player=%s backwards=%s", body.player, body.backwards)
    if not _bb_ctrl:
        return {"error": "no black belt controller"}
    if _online and _online.active:
        return {"error": "an online match is open, leave it first"}
    if _elim_ctrl and _elim_ctrl.active:
        return {"error": "an Elimination game is running, stop it first"}
    if _tb_ctrl and _tb_ctrl.active:
        return {"error": "a Target Battle is running, stop it first"}
    if _killer_ctrl and _killer_ctrl.active:
        return {"error": "a Killer game is running, stop it first"}
    if _ft_ctrl and _ft_ctrl.active:
        return {"error": "a Field Training run is open, stop it first"}
    if _co_ctrl and _co_ctrl.active:
        return {"error": "a Checkout Training run is open, stop it first"}
    try:
        _bb_ctrl.start(body.player, backwards=body.backwards)
    except ValueError as e:
        return {"error": str(e)}
    return {"ok": True}


@app.post("/api/black-belt/stop")
async def bb_stop():
    log.debug("Black Belt stop requested")
    if _bb_ctrl:
        _bb_ctrl.stop()
    return {"ok": True}


@app.post("/api/black-belt/finish")
async def bb_finish():
    """End the run and keep what was thrown; a run without a dart is dropped."""
    log.debug("Black Belt finish requested")
    if not _bb_ctrl:
        return {"error": "no black belt controller"}
    if not _bb_ctrl.finish_early():
        _bb_ctrl.stop()
    return {"ok": True}


@app.post("/api/black-belt/undo")
async def bb_undo():
    log.debug("Black Belt undo requested")
    if not (_bb_ctrl and _bb_ctrl.game):
        return {"error": "no active or finished run"}
    if not _bb_ctrl.game.undo():
        return {"error": "nothing to undo"}
    return {"ok": True}


@app.post("/api/black-belt/correct-dart")
async def bb_correct_dart(body: CorrectDartBody):
    log.debug("Black Belt correct-dart requested: dart=%s field=%s", body.dart, body.field)
    if body.dart not in (1, 2, 3):
        return {"error": "dart must be 1, 2, or 3"}
    if _bb_ctrl and _bb_ctrl.game:
        _bb_ctrl.game.correct_current_dart(body.dart - 1, body.field)
    _move_board_dart(body.dart - 1, body.field)
    return {"ok": True}


# ── REST: online Elimination ─────────────────────────────────────────────────

class OnlineCreateBody(BaseModel):
    password: str
    site: str | None = None


class OnlineJoinBody(OnlineCreateBody):
    code: str


class OnlinePlayersBody(BaseModel):
    players: list[str]


class OnlineStartBody(BaseModel):
    lives: int = 3
    order: list[str]


class OnlineDecisionBody(BaseModel):
    choice: str


def _online_settings() -> tuple[str | None, str | None]:
    raw = cfg_mod.load(_config_path) if _config_path else {}
    section = raw.get("online", {})
    return section.get("relay_url") or None, section.get("site_name") or None


@app.get("/api/online")
async def online_status():
    relay_url, site_name = _online_settings()
    return {"configured": bool(relay_url), "site_name": site_name,
            "status": _online.status() if _online and _online.active else None}


async def _online_call(fn, *args):
    if not _online:
        return {"error": "online play is not available"}
    try:
        result = await asyncio.to_thread(fn, *args)
    except online_mod.RelayError as e:
        return {"error": str(e)}
    return {"ok": True, **({"code": result} if isinstance(result, str) else {})}


@app.post("/api/online/create")
async def online_create(body: OnlineCreateBody):
    relay_url, site_name = _online_settings()
    site = (body.site or site_name or "").strip()
    if not relay_url:
        return {"error": "set the relay address in Settings first"}
    if not site:
        return {"error": "give this site a name"}
    if _elim_ctrl and _elim_ctrl.game and _elim_ctrl.game.state == "playing":
        return {"error": "a game is running, stop it first"}
    return await _online_call(_online.create, relay_url, site, body.password)


@app.post("/api/online/join")
async def online_join(body: OnlineJoinBody):
    relay_url, site_name = _online_settings()
    site = (body.site or site_name or "").strip()
    if not relay_url:
        return {"error": "set the relay address in Settings first"}
    if not site:
        return {"error": "give this site a name"}
    if _elim_ctrl and _elim_ctrl.game and _elim_ctrl.game.state == "playing":
        return {"error": "a game is running, stop it first"}
    return await _online_call(_online.join, relay_url, body.code, site, body.password)


@app.post("/api/online/players")
async def online_players(body: OnlinePlayersBody):
    return await _online_call(_online.set_players, [p.strip() for p in body.players if p.strip()])


@app.post("/api/online/start")
async def online_start(body: OnlineStartBody):
    return await _online_call(_online.start, body.lives, body.order)


@app.post("/api/online/decision")
async def online_decision(body: OnlineDecisionBody):
    return await _online_call(_online.decide, body.choice)


@app.post("/api/online/rematch")
async def online_rematch():
    return await _online_call(_online.rematch)


@app.post("/api/online/leave")
async def online_leave():
    result = await _online_call(_online.leave)
    if _elim_ctrl and _elim_ctrl.game and _elim_ctrl.game.online:
        _elim_ctrl.stop()
    return result


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


@app.get("/api/achievements/{name}")
async def achievements_player(name: str):
    engine = _stats_db.achievement_engine if _stats_db else None
    return {"player": name, "achievements": engine.overview(name) if engine else []}


@app.get("/api/stats/matches")
async def stats_matches(mode: str | None = Query(default=None, pattern="^(x01|elimination|target_battle|killer|field_training|black_belt|checkout_training)$")):
    if not _stats_db:
        return []
    return _stats_db.recent_matches(mode=mode)


@app.get("/api/stats/x01/overview")
async def stats_x01_overview():
    if not _stats_db:
        return {"summary": {}, "records": {}}
    return _stats_db.x01_overview()


@app.get("/api/stats/elimination/overview")
async def stats_elimination_overview():
    if not _stats_db:
        return {"summary": {}, "head_to_head": [], "game_lengths": [],
                "records": {"highest_score": None, "highest_lost_score": None}, "players": []}
    form = _stats_db.elimination_form()
    return {
        "summary": _stats_db.elimination_summary(),
        "head_to_head": _stats_db.elimination_head_to_head(),
        "game_lengths": _stats_db.elimination_game_lengths(),
        "records": _stats_db.elimination_records(),
        "players": [
            {**p, "form": form.get(p["player"], {"games": [], "current_streak": 0, "best_streak": 0})}
            for p in _stats_db.all_elimination_stats()
        ],
    }


@app.get("/api/stats/target-battle/overview")
async def stats_target_battle_overview(scoring: str = Query(default="standard", pattern="^(standard|singles|doubles|triples)$")):
    if not _stats_db:
        return {"scoring": scoring, "summary": {}, "records": {"best_game": None, "best_turn": None},
                "players": [], "head_to_head": []}
    return _stats_db.target_battle_overview(scoring)


@app.get("/api/stats/killer/overview")
async def stats_killer_overview():
    if not _stats_db:
        return {}
    return _stats_db.killer_overview()


@app.get("/api/stats/field-training/overview")
async def stats_field_training_overview():
    if not _stats_db:
        return {"players": []}
    return _stats_db.field_training_overview()


@app.get("/api/stats/checkout-training/overview")
async def stats_checkout_training_overview():
    if not _stats_db:
        return {"players": []}
    return _stats_db.checkout_training_overview()


@app.get("/api/stats/black-belt/overview")
async def stats_black_belt_overview():
    if not _stats_db:
        return {"players": []}
    return _stats_db.black_belt_overview()


@app.get("/api/stats/match/{match_id}")
async def stats_match(match_id: str):
    if not _stats_db:
        return {}
    return _stats_db.match_stats(match_id)


@app.delete("/api/stats/player/{name}")
async def stats_delete_player(name: str):
    # Destructive and irreversible (unlike hiding) — worth INFO, not DEBUG.
    log.info("Deleting player stats: %s", name)
    if not _stats_db:
        return {"error": "stats not enabled"}
    _stats_db.delete_player(name)
    push()
    return {"ok": True}


@app.get("/api/stats/dashboard/{name}")
async def stats_dashboard(
    name: str,
    points_start: int | None = None,
    mode: str = Query(default="all", pattern="^(all|x01|elimination)$"),
):
    """Advanced per-player dashboard — one bundled fetch."""
    if not _stats_db:
        return {}
    return _stats_db.player_dashboard(name, points_start=points_start, mode=mode)


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


@app.get("/api/voice-packs")
async def get_voice_packs():
    """Installed voice-pack profile names under the configured `[audio] dir`
    — lets the Settings form offer a dropdown instead of a free-text field
    the user has to already know the exact folder name for."""
    if not _config_path:
        return {"profiles": []}
    raw = cfg_mod.load(_config_path)
    audio_dir = raw.get("audio", {}).get("dir")
    if not audio_dir:
        return {"profiles": []}
    return {"profiles": voicepack.list_profiles(audio_dir)}


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
            "timezone": stats.get("timezone"),
        },
        "web": {
            "port":         web.get("port", 8080),
            "theme":        web.get("theme", "default"),
            "accent_color": web.get("accent_color"),
            "joke_of_the_day": web.get("joke_of_the_day", True),
            "language":     web.get("language", "en"),
            "aurora_animation": bool(web.get("aurora_animation", True)),
            **{key: web.get(key) for key in _AURORA_KEYS},
            "aurora_palette": web.get("aurora_palette") if web.get("aurora_palette") in AURORA_PALETTES else "",
            "aurora_streaks": bool(web.get("aurora_streaks", True)),
            **{key: _look_number(web, key) for key in _LOOK_NUMBERS},
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
            "announce_change": caller.get("announce_change", True),
            "call_player":     caller.get("call_player", True),
            "ambient_volume":  caller.get("ambient_volume", 0.6),
            "call_misses":     caller.get("call_misses", True),
        },
        "record": {
            "file": record.get("file"),
        },
        "online": {
            "relay_url": raw.get("online", {}).get("relay_url"),
            "site_name": raw.get("online", {}).get("site_name"),
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
    changed_keys: list[str] = []
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
            changed_keys.append(flat)
            if key not in cfg_mod.RUNTIME_FIELDS:
                changed_non_runtime.append(flat)

    # Key names only, never values — matches the masking discipline
    # /api/config's own response already applies to secret fields.
    log.debug("Config PATCH requested: keys=%s", changed_keys)

    for key, value in updates.get("web", {}).items():
        problem = _bad_look_value(key, value)
        if problem:
            return {"saved": False, "error": problem}

    cfg_mod.write(_config_path, updates)
    cfg_mod.apply_runtime(updates.get("logging", {}))

    log.info("Config saved: keys=%s restart_required=%s", changed_keys, changed_non_runtime)
    return {"saved": True, "restart_required": changed_non_runtime}


# ── REST: voice pack ──────────────────────────────────────────────────────────

def _run_async_in_thread(coro_fn):
    threading.Thread(target=lambda: asyncio.run(coro_fn()), daemon=True).start()


_TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"


def _voicepack_plans() -> dict[str, Path]:
    """Every plan file `tools/voicepack_*.toml`, by the name of the profile folder it generates."""
    plans = {}
    for path in sorted(_TOOLS_DIR.glob("voicepack_*.toml")):
        try:
            with open(path, "rb") as f:
                voice = tomllib.load(f)["voice"]
        except (OSError, tomllib.TOMLDecodeError, KeyError):
            continue
        plans[voice.split("-")[-1].removesuffix("Neural").lower()] = path
    return plans


def _voicepack_plan_path(pack: str | None = None) -> Path | None:
    """The plan of *pack*; without one the plan of the active `[audio] profile`, else the first
    plan found. None if there is no such plan."""
    plans = _voicepack_plans()
    if pack is None:
        cfg = cfg_mod.load(_config_path) if _config_path else {}
        active = cfg.get("audio", {}).get("profile")
        pack = active if active in plans else next(iter(plans), None)
    return plans.get(pack)


def _voicepack_overlay_file(pack_name: str) -> Path | None:
    """The private player-name file of a pack, next to `config.toml`; None without a config file."""
    return vo.overlay_path(Path(_config_path).parent, pack_name) if _config_path else None


def _voicepack_doc(pack: str | None, overlay: bool = True):
    """(plan path, parsed plan) for *pack*, or (None, error answer). With *overlay* the private
    player names are merged in, for everything but writing a plan: never save that copy."""
    path = _voicepack_plan_path(pack)
    if path is None:
        return None, {"error": "unknown voice pack" if pack else "no voice-pack plan"}
    doc = ve.load_plan(path)
    file = _voicepack_overlay_file(ve.profile_dir_name(doc)) if overlay else None
    if file is not None:
        try:
            doc = ve.merge_overlay(doc, vo.read_entries(file))
        except ValueError as e:
            return None, {"error": f"private player file: {e}"}
    return path, doc


def _voicepack_save(plan_path: Path, doc, group_name: str):
    """Write the edited *doc*: the private file for the player names, else the plan. Returns an
    error answer or None."""
    if group_name != vo.PLAYER_GROUP:
        ve.save_plan(plan_path, doc)
        return None
    file = _voicepack_overlay_file(ve.profile_dir_name(doc))
    if file is None:
        return {"error": "no config file, so no place for the private player names"}
    try:
        ve.write_overlay(file, ve.overlay_changes(ve.load_plan(plan_path), doc))
    except ValueError as e:
        return {"error": str(e)}
    return None


def _voicepack_out_dir(profile_name: str) -> Path:
    cfg = cfg_mod.load(_config_path) if _config_path else {}
    audio_dir = cfg.get("audio", {}).get("dir", "sounds")
    return Path(audio_dir) / "profiles" / profile_name


class VoicepackGenerateBody(BaseModel):
    force: bool = False
    pack: str | None = None


@app.get("/api/voicepack/packs")
async def voicepack_packs():
    """The packs the Voice Pack tab can edit: one per plan file, with the one to start on."""
    plans = _voicepack_plans()
    default = _voicepack_plan_path(None)
    default_name = next((n for n, p in plans.items() if p == default), None)
    packs = []
    for name, path in plans.items():
        with open(path, "rb") as f:
            voice = tomllib.load(f)["voice"]
        packs.append({"name": name, "voice": voice, "plan": path.name})
    return {"packs": packs, "default": default_name}


@app.post("/api/voicepack/generate")
async def voicepack_generate(body: VoicepackGenerateBody):
    """Regenerate the voice pack — force=False only fills in
    missing keys (fast), force=True re-generates everything, including
    keys whose text changed since the last generation (slow, several
    minutes for the full pack)."""
    log.debug("Voice-pack generate requested: force=%s", body.force)
    if _voicepack_status["running"]:
        return {"error": "generation already running"}
    if not _audio_engine:
        return {"error": "audio not configured"}

    from tools.generate_voicepack import run as generate_run

    plan_path = _voicepack_plan_path(body.pack)
    if plan_path is None:
        return {"error": "unknown voice pack" if body.pack else "no voice-pack plan"}
    with open(plan_path, "rb") as f:
        plan = tomllib.load(f)
    name = plan["voice"].split("-")[-1].removesuffix("Neural").lower()
    file = _voicepack_overlay_file(name)
    if file is not None:
        try:
            vo.merge_into_plan(plan, vo.read_entries(file))
        except ValueError as e:
            return {"error": f"private player file: {e}"}
    out_dir = _voicepack_out_dir(name)

    _voicepack_status.update(running=True, done=0, skipped=0, total=0, error=None)
    log.info("Voice-pack generation started (force=%s)", body.force)
    push()

    async def task():
        def on_progress(done, skipped, total):
            _voicepack_status.update(done=done, skipped=skipped, total=total)
            push()
        try:
            await generate_run(plan, out_dir, only=None, force=body.force,
                                dry_run=False, trim=True, on_progress=on_progress)
            log.info("Voice-pack generation finished: done=%d skipped=%d",
                      _voicepack_status["done"], _voicepack_status["skipped"])
        except Exception as e:
            log.exception("Voice-pack generation failed")
            _voicepack_status["error"] = str(e)
        finally:
            _voicepack_status["running"] = False
            push()

    _run_async_in_thread(task)
    return {"ok": True}


@app.get("/api/voicepack/groups")
async def voicepack_groups(pack: str | None = None):
    plan_path, doc = _voicepack_doc(pack)
    if plan_path is None:
        return doc
    return {"groups": ve.list_groups(doc)}


@app.get("/api/voicepack/entries")
async def voicepack_entries(group: str, pack: str | None = None):
    plan_path, doc = _voicepack_doc(pack)
    if plan_path is None:
        return doc
    entries = ve.list_entries(doc, group, _voicepack_out_dir(ve.profile_dir_name(doc)))
    if entries is None:
        return {"error": "unknown group"}
    return {"entries": entries}


@app.get("/api/voicepack/file/{filename}")
async def voicepack_file(filename: str, pack: str | None = None):
    """Serves an already-generated variant file straight from the plan's
    own output directory — independent of AudioEngine/the currently active
    `[audio] profile`, so browsing/listening in the editor works the same
    whether or not this pack happens to be the one currently in use."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=404, detail="unknown sound file")
    plan_path, doc = _voicepack_doc(pack)
    if plan_path is None:
        raise HTTPException(status_code=404, detail="unknown voice pack")
    path = _voicepack_out_dir(ve.profile_dir_name(doc)) / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="unknown sound file")
    return FileResponse(path, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


class VoicepackPreviewBody(BaseModel):
    group: str
    text: str
    pack: str | None = None


@app.post("/api/voicepack/preview")
async def voicepack_preview(body: VoicepackPreviewBody):
    """Synthesize *text* on the fly with *group*'s voice/rate/pitch/volume,
    for a "how would this sound" check before saving — writes to a scratch
    file that's deleted right after the response is sent, never touches the
    plan or the profile directory."""
    if not body.text.strip():
        return {"error": "text is required"}
    plan_path, doc = _voicepack_doc(body.pack)
    if plan_path is None:
        return doc
    groups = {g["name"]: g for g in doc["group"]}
    if body.group not in groups:
        return {"error": "unknown group"}
    group = next(g for g in doc["group"] if g["name"] == body.group)
    rate = group.get("rate", "+0%")
    pitch = group.get("pitch", "+0Hz")
    volume = group.get("volume", "+0%")

    from tools.generate_voicepack import synthesize

    fd, tmp_path = tempfile.mkstemp(suffix=".mp3", prefix="voicepack-preview-")
    os.close(fd)
    dest = Path(tmp_path)
    try:
        await synthesize(doc["voice"], body.text, rate, pitch, volume, dest, trim=True)
    except Exception as e:
        dest.unlink(missing_ok=True)
        log.warning("Voice-pack preview synth failed: %s", e)
        return {"error": f"synthesis failed: {e}"}
    return FileResponse(
        dest, media_type="audio/mpeg", headers={"Cache-Control": "no-store"},
        background=BackgroundTask(dest.unlink, missing_ok=True),
    )


class VoicepackEntryBody(BaseModel):
    group: str
    key: str
    variants: list[str]
    pack: str | None = None


@app.post("/api/voicepack/entries")
async def voicepack_save_entry(body: VoicepackEntryBody):
    """Add or replace a key's variants: synthesizes every variant file,
    updates the plan (comment-preserving), and prunes any now-stale
    trailing file from a previously longer variant list."""
    key = body.key.strip()
    variants = [v.strip() for v in body.variants if v.strip()]
    if not key:
        return {"error": "key is required"}
    if not variants:
        return {"error": "at least one variant is required"}

    plan_path, doc = _voicepack_doc(body.pack, overlay=body.group == vo.PLAYER_GROUP)
    if plan_path is None:
        return doc
    groups = {g["name"]: g for g in doc["group"]}
    group = groups.get(body.group)
    if group is None:
        return {"error": "unknown group"}
    if "range" in group:
        try:
            key = str(int(key))
        except ValueError:
            return {"error": "key must be a whole number for this group"}

    prosody = ve.entry_prosody(doc, body.group, key)
    out_dir = _voicepack_out_dir(ve.profile_dir_name(doc))
    result = ve.upsert_entry(doc, body.group, key, variants)

    try:
        await ve.synthesize_entry(doc["voice"], prosody["rate"], prosody["pitch"],
                                   prosody["volume"], out_dir, result["stem"], variants)
    except Exception as e:
        log.warning("Voice-pack entry synth failed for key=%s: %s", key, e)
        return {"error": f"synthesis failed: {e}"}

    ve.prune_extra_variant_files(out_dir, result["stem"], keep_count=len(variants))
    error = _voicepack_save(plan_path, doc, body.group)
    if error:
        return error
    if _audio_engine:
        _audio_engine.invalidate(result["stem"])
    log.info("Voice-pack entry saved: group=%s key=%s variants=%d", body.group, key, len(variants))
    return {"ok": True}


class VoicepackDeleteVariantBody(BaseModel):
    group: str
    key: str
    variant_index: int
    pack: str | None = None


@app.delete("/api/voicepack/entries")
async def voicepack_delete_variant(body: VoicepackDeleteVariantBody):
    """Remove one variant, renumbering the remaining higher-indexed files
    down so none of them silently fall past AudioEngine's gap-stops-the-
    scan cutoff — and keeps the plan's variants list in sync."""
    plan_path, doc = _voicepack_doc(body.pack, overlay=body.group == vo.PLAYER_GROUP)
    if plan_path is None:
        return doc
    out_dir = _voicepack_out_dir(ve.profile_dir_name(doc))
    result = ve.remove_variant(doc, body.group, body.key, body.variant_index)
    if result is None:
        return {"error": "entry not found"}

    error = _voicepack_save(plan_path, doc, body.group)
    if error:
        return error
    ve.renumber_after_delete(out_dir, result["stem"], body.variant_index, result["new_count"])
    if _audio_engine:
        _audio_engine.invalidate(result["stem"])
    log.info("Voice-pack variant deleted: group=%s key=%s index=%d",
              body.group, body.key, body.variant_index)
    return {"ok": True}


# ── REST: checkout training ───────────────────────────────────────────────────

class CheckoutTrainingStartBody(BaseModel):
    player: str
    range: str | None = None       # low (2 to 40), mid (41 to 100), high (101 to 170) or all
    low: int = 2                   # used when no named range is given
    high: int = 170
    attempts: int = 10
    show_route: bool = False


@app.post("/api/checkout-training/start")
async def co_start(body: CheckoutTrainingStartBody):
    log.debug("Checkout Training start requested: player=%s range=%s attempts=%s", body.player, body.range, body.attempts)
    if not _co_ctrl:
        return {"error": "no checkout training controller"}
    if _online and _online.active:
        return {"error": "an online match is open, leave it first"}
    for ctrl, message in ((_elim_ctrl, "an Elimination game is running, stop it first"),
                          (_tb_ctrl, "a Target Battle is running, stop it first"),
                          (_killer_ctrl, "a Killer game is running, stop it first"),
                          (_ft_ctrl, "a Field Training run is open, stop it first"),
                          (_bb_ctrl, "a Black Belt run is open, stop it first")):
        if ctrl and ctrl.active:
            return {"error": message}
    if body.range is not None and body.range not in CHECKOUT_RANGES:
        return {"error": "range must be low, mid, high or all"}
    low, high = CHECKOUT_RANGES[body.range] if body.range else (body.low, body.high)
    try:
        _co_ctrl.start(body.player, low=low, high=high, attempts=body.attempts, show_route=body.show_route)
    except ValueError as e:
        return {"error": str(e)}
    return {"ok": True}


@app.post("/api/checkout-training/stop")
async def co_stop():
    log.debug("Checkout Training stop requested")
    if _co_ctrl:
        _co_ctrl.stop()
    return {"ok": True}


@app.post("/api/checkout-training/finish")
async def co_finish():
    """End the run early and keep the attempts so far; a run without a finished attempt is dropped."""
    log.debug("Checkout Training finish requested")
    if not _co_ctrl:
        return {"error": "no checkout training controller"}
    if not _co_ctrl.finish_early():
        _co_ctrl.stop()
    return {"ok": True}


@app.post("/api/checkout-training/undo")
async def co_undo():
    log.debug("Checkout Training undo requested")
    if not (_co_ctrl and _co_ctrl.game):
        return {"error": "no active or finished run"}
    if not _co_ctrl.game.undo():
        return {"error": "nothing to undo"}
    return {"ok": True}


@app.post("/api/checkout-training/correct-dart")
async def co_correct_dart(body: CorrectDartBody):
    log.debug("Checkout Training correct-dart requested: dart=%s field=%s", body.dart, body.field)
    if body.dart not in (1, 2, 3):
        return {"error": "dart must be 1, 2, or 3"}
    if _co_ctrl and _co_ctrl.game:
        _co_ctrl.game.correct_current_dart(body.dart - 1, body.field)
    _move_board_dart(body.dart - 1, body.field)
    return {"ok": True}


# The pure side of the trainer, for the route quiz and the setup shots (no darts, also on a phone).

_FIELD_PATTERN = "^(S([1-9]|1[0-9]|20)|D([1-9]|1[0-9]|20)|T([1-9]|1[0-9]|20)|25|50|0)$"


@app.get("/api/checkout/random")
async def checkout_random(low: int = Query(2, ge=2, le=170), high: int = Query(170, ge=2, le=170),
                          avoid: int | None = None):
    """A finishable score from low to high, not *avoid* if another is left."""
    try:
        score = co_routes.draw(low, high, avoid=(avoid,) if avoid else ())
    except ValueError as e:
        return {"error": str(e)}
    return {"score": score}


@app.get("/api/checkout/route")
async def checkout_route(score: int = Query(..., ge=1, le=999)):
    """The standard route of a score, how many darts it takes at the least and which first darts are valid."""
    return {"score": score, "finishable": co_routes.finishable(score), "route": co_routes.standard_route(score),
            "darts": co_routes.darts_to_finish(score), "first_darts": co_routes.valid_first_darts(score)}


class CheckoutJudgeBody(BaseModel):
    score: int
    field: str = Field(pattern=_FIELD_PATTERN)


@app.post("/api/checkout/judge")
async def checkout_judge(body: CheckoutJudgeBody):
    """Route quiz: how a first dart at a score is rated, "standard", "valid" or "invalid"."""
    if not co_routes.finishable(body.score):
        return {"error": "that score cannot be finished with three darts"}
    return {"verdict": co_routes.judge_first_dart(body.score, body.field), "route": co_routes.standard_route(body.score)}


class CheckoutSetupBody(BaseModel):
    score: int
    fields: list[str] = Field(max_length=3)


@app.post("/api/checkout/setup")
async def checkout_setup(body: CheckoutSetupBody):
    """Setup shots: what is left of a score after the darts, and what that rest allows."""
    if any(not re.match(_FIELD_PATTERN, f) for f in body.fields):
        return {"error": "unknown field"}
    after = co_routes.after_darts(body.score, body.fields)
    left = 3 - len(body.fields)
    allowed = None
    if after["state"] == "open" and left > 0:
        allowed = co_routes.darts_to_finish(after["rest"], left)
    return {**after, "darts_left": left, "darts_to_finish": allowed,
            "route": co_routes.standard_route(after["rest"]) if allowed else None,
            "best_first": co_routes.standard_route(body.score)}


# ── REST: achievement sounds ─────────────────────────────────────────────────

def assigned_achievement_sounds(achievement_id: str) -> list:
    """The files assigned to an achievement in `config.toml` that exist, for the unlock sound. Read
    from the file each time, so a change on the page takes effect without a restart."""
    if not (_config_path and _audio_engine):
        return []
    return ach_sounds.files_for(_audio_engine, cfg_mod.load(_config_path), achievement_id)


def _admin_locked():
    """The admin area opens like the Dev tab: `[dev] enabled`, or the version-number tap."""
    if not _dev_enabled():
        return {"error": "locked: unlock the Dev tab first"}
    if not (_config_path and _audio_engine):
        return {"error": "no config file or sound directory"}
    return None


@app.get("/api/admin/achievement-sounds")
async def admin_achievement_sounds():
    locked = _admin_locked()
    if locked:
        return locked
    return ach_sounds.overview(_audio_engine, cfg_mod.load(_config_path), ach_mod.ACHIEVEMENTS)


class AchievementSoundsBody(BaseModel):
    files: list[str] = []      # an empty list clears the assignment


@app.put("/api/admin/achievement-sounds/{achievement_id}")
async def admin_set_achievement_sounds(achievement_id: str, body: AchievementSoundsBody):
    locked = _admin_locked()
    if locked:
        return locked
    if achievement_id not in ach_mod.BY_ID:
        return {"error": "unknown achievement"}
    unknown = [f for f in body.files if not ach_sounds.playable(_audio_engine, f)]
    if unknown:
        return {"error": f"not a sound of the achievements folder: {', '.join(unknown)}"}
    stored = ach_sounds.set_assignment(_config_path, achievement_id, list(dict.fromkeys(body.files)))
    log.info("Achievement sound set: %s -> %s", achievement_id, stored)
    return {"ok": True, "assigned": stored}


class RenameSoundBody(BaseModel):
    name: str


@app.patch("/api/admin/achievement-sounds/files/{filename}")
async def admin_rename_achievement_sound(filename: str, body: RenameSoundBody):
    """Rename a file of the achievements folder, also in the assignments that use it."""
    locked = _admin_locked()
    if locked:
        return locked
    problem = ach_sounds.rename_file(_audio_engine, _config_path, filename, body.name)
    if problem:
        return {"error": problem}
    log.info("Achievement sound renamed: %s -> %s", filename, body.name)
    return {"ok": True, "file": body.name}


@app.delete("/api/admin/achievement-sounds/files/{filename}")
async def admin_delete_achievement_sound(filename: str):
    """Delete a file of the achievements folder and take it out of the assignments."""
    locked = _admin_locked()
    if locked:
        return locked
    problem = ach_sounds.delete_file(_audio_engine, _config_path, filename)
    if problem:
        return {"error": problem}
    log.info("Achievement sound deleted: %s", filename)
    return {"ok": True}


@app.post("/api/admin/achievement-sounds/upload")
async def admin_upload_achievement_sound(request: Request, name: str = Query(...)):
    """Upload an mp3 into the achievements folder; the file is the request body."""
    locked = _admin_locked()
    if locked:
        return locked
    data = await request.body()
    problem = ach_sounds.save_upload(_audio_engine, name, data)
    if problem:
        return {"error": problem}
    log.info("Achievement sound uploaded: %s (%d bytes)", name, len(data))
    return {"ok": True, "file": name}


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
    log.info("Dev tab unlocked for this run (version-number tap)")
    return {"unlocked": True}


@app.post("/api/dev/demo/x01")
async def dev_demo_x01():
    log.debug("X01 demo requested")
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
    log.debug("Elimination demo requested")
    if not _dev_enabled():
        return {"started": False, "error": "[dev] not enabled in config"}
    if not _dev_demo:
        return {"started": False, "error": "demo unavailable"}
    started, error = _dev_demo.start_elimination()
    if started:
        push()
    return {"started": started, "error": error}


# ── REST: self-update ────────────────────────────────────────────────────────

# `updater` is the compose service name — only resolvable over the
# compose-internal network the two containers share, see docker-compose.yml.
_UPDATER_URL = os.environ.get("BREAKFAST_UPDATER_URL", "http://updater:8090")


def _updater_get(path: str) -> dict:
    r = requests.get(f"{_UPDATER_URL}{path}", timeout=10)
    r.raise_for_status()
    return r.json()


def _updater_post(path: str) -> dict:
    r = requests.post(f"{_UPDATER_URL}{path}", timeout=10)
    r.raise_for_status()
    return r.json()


@app.get("/api/updates/check")
async def updates_check():
    log.debug("Update check requested")
    if frozen.is_frozen():
        return await asyncio.to_thread(self_update.check, __version__)
    try:
        return await asyncio.to_thread(_updater_get, "/check")
    except Exception as e:
        log.warning("Updater unreachable on /check: %s", e)
        return {"error": f"updater unreachable: {e}"}


@app.post("/api/updates/apply")
async def updates_apply():
    log.info("Update apply requested via UI")
    if frozen.is_frozen():
        return self_update.apply(__version__)
    try:
        return await asyncio.to_thread(_updater_post, "/apply")
    except Exception as e:
        log.warning("Updater unreachable on /apply: %s", e)
        return {"error": f"updater unreachable: {e}"}


@app.get("/api/updates/status")
async def updates_status():
    log.debug("Update status requested")
    if frozen.is_frozen():
        return self_update.status()
    try:
        return await asyncio.to_thread(_updater_get, "/status")
    except Exception as e:
        log.warning("Updater unreachable on /status: %s", e)
        return {"error": f"updater unreachable: {e}"}


# ── REST: players ─────────────────────────────────────────────────────────────

class PlayerBody(BaseModel):
    name: str


@app.get("/api/players")
async def list_players():
    return kp.load(_stats_db)


@app.post("/api/players")
async def add_player(body: PlayerBody):
    log.debug("Add player requested: %s", body.name)
    name = body.name.strip()
    if not name:
        return {"error": "empty name"}
    players = kp.add(name, _stats_db)
    push()
    return players


class HiddenBody(BaseModel):
    hidden: bool


@app.patch("/api/players/{name}/hidden")
async def set_player_hidden(name: str, body: HiddenBody):
    """Hide/unhide a player from the Players tab and from
    leaderboard()/all_players_stats() (same flag controls both) —
    non-destructive and reversible, unlike DELETE /api/stats/player/{name}."""
    log.info("Player %s: %s", "hidden" if body.hidden else "unhidden", name)
    if not _stats_db:
        return {"error": "stats not enabled"}
    _stats_db.upsert_player(name, hidden=body.hidden)
    push()
    return {"ok": True}


class ColorBody(BaseModel):
    color: str | None = None


@app.patch("/api/players/{name}/color")
async def set_player_color(name: str, body: ColorBody):
    """Set a player's color (`#rrggbb`), or clear it with `null`. Games use it to draw the
    player's darts; a player without one gets a random color for the game."""
    if not _stats_db:
        return {"error": "stats not enabled"}
    try:
        found = _stats_db.set_player_color(name, body.color)
    except ValueError as e:
        return {"error": str(e)}
    if not found:
        return {"error": "unknown player"}
    log.info("Player %s: color %s", name, body.color or "cleared")
    push()
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

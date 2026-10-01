"""Direct Autodarts cloud client: auth + cloud WebSocket + event translation.

Translates raw Autodarts match-state snapshots into the same event format that
state.py.update() expects (identical to what darts-caller broadcasts).
"""

import base64
import json
import logging
import queue
import threading
import time
from datetime import datetime, timedelta

import requests
import websocket

from breakfast import board_status
from breakfast.dartboard import field_centers

log = logging.getLogger(__name__)

_AUTODARTS_WS_URL = "wss://api.autodarts.io/ms/v0/subscribe"
_BOARDS_URL = "https://api.autodarts.io/bs/v0/boards/"
_MATCHES_URL = "https://api.autodarts.io/gs/v0/matches/"
_LOGIN_URL = "https://api.autodarts.io/auth/v1/login"
_REFRESH_URL = "https://api.autodarts.io/auth/v1/refresh"

# Center of every field in Autodarts' board coordinates, used by correct_throw()
# to PATCH a throw and by board_darts to place a corrected dart.
_FIELD_COORDS: dict[str, dict] = field_centers()


class _AuthClient:
    """Authenticates against api.autodarts.io/auth/v1 and keeps the token fresh.

    Login: POST /auth/v1/login  {"email": ..., "password": ...}
    Refresh: POST /auth/v1/refresh  {"refresh_token": ...}
    Token expires_in: 900 s → we refresh at 90 % (~810 s).
    user_id is decoded directly from the JWT sub claim.
    """

    _FRACTION = 0.9
    _TICK = 60

    def __init__(self, email: str, password: str):
        self._email = email
        self._password = password
        self._lock = threading.Lock()
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: datetime | None = None
        self._running = False
        self.user_id: str | None = None

    # ------------------------------------------------------------------ public

    @property
    def access_token(self) -> str | None:
        with self._lock:
            return self._access_token

    def login(self) -> None:
        """Raises on failure — callers own the retry/backoff decision."""
        self._login()
        self.user_id = self._jwt_sub(self._access_token)

    def start(self) -> None:
        self._running = True
        threading.Thread(target=self._loop, daemon=True, name="autodarts-token").start()

    def stop(self) -> None:
        self._running = False

    # ----------------------------------------------------------------- internal

    @staticmethod
    def _jwt_sub(token: str) -> str:
        payload = token.split(".")[1]
        padding = (4 - len(payload) % 4) % 4
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * padding))
        return data["sub"]

    def _apply(self, resp: dict) -> None:
        with self._lock:
            self._access_token = resp["access_token"]
            self._refresh_token = resp.get("refresh_token", self._refresh_token)
            self._expires_at = datetime.now() + timedelta(
                seconds=int(self._FRACTION * resp.get("expires_in", 900))
            )

    def _login(self) -> None:
        resp = requests.post(
            _LOGIN_URL,
            json={"email": self._email, "password": self._password, "client_id": "autodarts-play"},
            timeout=15,
        )
        resp.raise_for_status()
        self._apply(resp.json())

    def _refresh(self) -> None:
        with self._lock:
            rt = self._refresh_token
        # The refresh endpoint rejects requests without client_id
        # (400 "client_id is required"), same client as the login.
        resp = requests.post(
            _REFRESH_URL,
            json={"refresh_token": rt, "client_id": "autodarts-play"},
            timeout=15,
        )
        resp.raise_for_status()
        self._apply(resp.json())

    def _loop(self) -> None:
        while self._running:
            try:
                with self._lock:
                    expires_at = self._expires_at
                if expires_at and datetime.now() >= expires_at:
                    try:
                        self._refresh()
                    except Exception:
                        log.warning("Token refresh failed, re-logging in…")
                        self._login()
            except Exception:
                with self._lock:
                    self._access_token = None
                log.warning("Token renewal failed")
            time.sleep(self._TICK)


def _remaining_scores_dict(m):
    """Convert gameScores list → {player1: "501", player2: "501", ...}."""
    scores = m.get("gameScores") or []
    return {f"player{i + 1}": str(int(s)) for i, s in enumerate(scores[:6])}


class AutodartsCloudClient:
    """Connects to the Autodarts cloud WebSocket and translates match-state snapshots
    into darts-caller-compatible events, delivered via the on_event callback."""

    def __init__(self, *, email: str, password: str, board_id: str, on_event):
        self._board_id = board_id
        self._on_event = on_event

        self._auth = _AuthClient(email, password)
        self._login_ok = False

        # Connection state
        self._ws_connected = False

        # Match tracking
        self._match_lock = threading.Lock()
        self._current_match = None
        self._match_active = False
        self._last_message = None
        self._index_name: dict[str, int] = {}

        # Per-turn X01 state (reset at each new turn / match)
        self._proc_lock = threading.Lock()
        self._prev_throws_count = 0
        self._dart_cumulative = [0, 0, 0]
        self._is_game_finished = False
        self._last_points: str | None = None

        # Wall-clock timestamps used to detect an abandoned match (started on
        # the Autodarts side but never properly finished/deleted there, so no
        # "finish"/"delete" event ever arrives to clear self._match_active).
        self._match_started_at: float | None = None
        self._last_activity_at: float | None = None

        # Incoming WS messages, drained in order by a single worker thread
        self._msg_queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._worker_lock = threading.Lock()

        # Cached local board address (fetched lazily)
        self._board_address: str | None = None

        self._attempt_login()

    # ------------------------------------------------------------------ public

    @property
    def connected(self) -> bool:
        return self._ws_connected

    @property
    def logged_in(self) -> bool:
        return self._login_ok

    def start(self):
        if not self._login_ok:
            return
        self._auth.start()
        self._connect()

    # ----------------------------------------------------------------- internal

    def _attempt_login(self):
        try:
            self._auth.login()
            self._login_ok = True
            log.info("Token OK (%s…), user=%s",
                      (self._auth.access_token or "")[:8], self._auth.user_id)
        except Exception as e:
            log.warning("Autodarts login failed (%s: %s) — starting without cloud "
                        "connection, retrying in background", type(e).__name__, e)
            threading.Thread(target=self._login_retry_loop, daemon=True,
                              name="autodarts-login-retry").start()

    def _login_retry_loop(self):
        delay = 5
        while not self._login_ok:
            time.sleep(delay)
            try:
                self._auth.login()
                self._login_ok = True
                log.info("Autodarts login succeeded on retry (user=%s)", self._auth.user_id)
                self.start()
            except Exception as e:
                log.warning("Autodarts login retry failed (%s: %s), backing off %ds",
                            type(e).__name__, e, delay)
                delay = min(delay * 2, 60)

    def _emit_dart_thrown(self, n, throws, remaining, cum_points, common, m):
        """Emit dart{n}-thrown if n > _prev_throws_count (the dart hasn't been emitted yet)."""
        if n <= 0 or n <= self._prev_throws_count or not throws:
            return
        seg = throws[n - 1].get("segment", {})
        if n == 1:
            dart_value = cum_points
            self._dart_cumulative[0] = cum_points
        elif n == 2:
            dart_value = cum_points - self._dart_cumulative[0]
            self._dart_cumulative[1] = cum_points
        else:
            dart_value = cum_points - self._dart_cumulative[1]
            self._dart_cumulative[2] = cum_points
        self._last_points = str(cum_points)
        self._prev_throws_count = n
        self._emit({
            **common,
            "event": f"dart{n}-thrown",
            "game": {
                "mode": m.get("variant"),
                "pointsLeft": str(remaining),
                "dartNumber": str(n),
                "dartValue": str(dart_value),
                "fieldName": str(seg.get("name", "")).lower(),
                "fieldNumber": seg.get("number"),
                "fieldMultiplier": seg.get("multiplier", 0),
                "type": str(seg.get("bed", "")).lower(),
            },
        })

    # ------------------------------------------------------------------ control

    def undo_throw(self):
        self._match_post("undo")

    def next_player(self):
        self._match_post("players/next")

    def next_game(self):
        self._match_post("games/next")

    def correct_throw(self, dart_number: int, field: str):
        """PATCH a throw to correct its detected value.

        dart_number: 1, 2, or 3 (1-based)
        field: field name as shown on board — e.g. 'T20', 'D16', 'S5', '25', '50', '0' (miss)
        """
        with self._match_lock:
            mid = self._current_match
        if not mid:
            log.warning("No active match, cannot PATCH throw")
            return
        key = field.upper() if field != "0" else "0"
        coords = _FIELD_COORDS.get(key)
        if coords is None:
            log.warning("Unknown field '%s'", field)
            return
        idx = str(dart_number - 1)  # 0-based index for API
        data = {"changes": {idx: {"coords": coords, "type": "normal"}}}
        try:
            res = requests.patch(
                f"{_MATCHES_URL}{mid}/throws",
                headers={**self._auth_header(), "Content-Type": "application/json"},
                json=data,
                timeout=5,
            )
            log.info("Corrected throw D%s=%s → %s", dart_number, field, res.status_code)
            if not res.ok:
                log.warning("Throw correction rejected: %s", (res.text or "")[:300])
        except Exception as e:
            log.error("Throw correction failed: %s", e)

    def match_status(self) -> dict:
        """Snapshot for /api/health: lets the UI warn about a match that looks
        abandoned (open on the Autodarts side, no activity for a long time)."""
        with self._match_lock:
            active = self._match_active
            match_id = self._current_match
            started_at = self._match_started_at
            last = self._last_activity_at
        return {
            "match_id": match_id if active else None,
            "match_started_at": started_at if active else None,
            "seconds_since_activity": (time.time() - last) if (active and last) else None,
        }

    def force_clear_match(self) -> bool:
        """Manually mark the current match as ended in Breakfast's own tracking.

        For matches abandoned on the Autodarts side (app closed without a
        proper finish, so no "finish"/"delete" event ever arrives): this
        doesn't touch the Autodarts cloud match itself, it only clears the
        local state.match_started gate that otherwise blocks Elimination/
        freeplay board processing forever.
        """
        with self._match_lock:
            if not self._match_active:
                return False
            mid = self._current_match
            self._current_match = None
            self._match_active = False
            self._last_message = None
            self._index_name = {}
            self._match_started_at = None
            self._last_activity_at = None
        log.warning("Match force-cleared by user (id=%s)", mid)
        self._emit({"event": "match-ended"})
        return True

    def reset_board(self):
        addr = self._get_board_address()
        if not addr:
            log.warning("Board address unknown, cannot reset")
            return
        try:
            requests.post(f"{addr}/api/reset", timeout=5)
            log.info("Board reset sent")
        except Exception as e:
            log.error("Board reset failed: %s", e)

    def _match_post(self, path: str):
        with self._match_lock:
            mid = self._current_match
        if not mid:
            log.warning("No active match, cannot POST %s", path)
            return
        try:
            res = requests.post(
                f"{_MATCHES_URL}{mid}/{path}",
                headers=self._auth_header(),
                timeout=5,
            )
            log.info("%s → %s", path, res.status_code)
        except Exception as e:
            log.error("%s failed: %s", path, e)

    def _get_board_address(self) -> str | None:
        if self._board_address:
            return self._board_address
        try:
            res = requests.get(
                _BOARDS_URL + self._board_id,
                headers=self._auth_header(),
                timeout=5,
            ).json()
            ip = res.get("ip")
            if ip:
                self._board_address = ip
                log.info("Board address: %s", ip)
            return self._board_address
        except Exception as e:
            log.error("Could not fetch board address: %s", e)
            return None

    # ----------------------------------------------------------------- internal

    def _auth_header(self):
        return {"Authorization": f"Bearer {self._auth.access_token}"}

    def _connect(self):
        def run():
            log.info("Connecting to %s", _AUTODARTS_WS_URL)
            try:
                ws = websocket.WebSocketApp(
                    _AUTODARTS_WS_URL,
                    header=self._auth_header(),
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=lambda ws, e: log.error("WS error: %s: %s", type(e).__name__, e),
                    # Reconnect happens below after run_forever() returns —
                    # only mark the connection state here (visible in /api/health).
                    on_close=self._mark_closed,
                )
                ws.run_forever()
                log.debug("run_forever() returned")
            except Exception as e:
                log.error("WS thread crashed: %s: %s", type(e).__name__, e)
            time.sleep(3)
            self._connect()

        threading.Thread(target=run, daemon=True, name="autodarts-ws").start()

    def _on_open(self, ws):
        self._ws_connected = True
        log.info("WS open, subscribing…")
        try:
            # Resume any active match
            try:
                res = requests.get(
                    _BOARDS_URL + self._board_id, headers=self._auth_header(), timeout=10
                ).json()
                if res.get("matchId"):
                    self._subscribe_match({"event": "start", "id": res["matchId"]}, ws)
            except Exception as e:
                log.warning("Fetch active match failed: %s", e)

            ws.send(json.dumps({
                "channel": "autodarts.boards",
                "type": "subscribe",
                "topic": f"{self._board_id}.matches",
            }))
            ws.send(json.dumps({
                "channel": "autodarts.users",
                "type": "subscribe",
                "topic": f"{self._auth.user_id}.events",
            }))
            log.info("Connected (board=%s)", self._board_id)
        except Exception as e:
            log.error("_on_open error: %s: %s", type(e).__name__, e)

    def _mark_closed(self, ws, code, msg):
        # Was never wired before (a debug lambda shadowed it), so
        # /api/health kept showing "connected" after a drop.
        self._ws_connected = False
        log.warning("WS closed (%s: %s), reconnecting…", code, msg)

    def _on_message(self, ws, raw):
        # Messages are queued and handled by one worker thread so they are
        # processed strictly in arrival order — GameState and StatsTracker hold
        # unsynchronized per-match state that concurrent handlers would corrupt.
        self._ensure_worker()
        self._msg_queue.put((ws, raw))

    def _ensure_worker(self):
        with self._worker_lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(
                    target=self._worker_loop, daemon=True, name="autodarts-msg")
                self._worker.start()

    def _worker_loop(self):
        while True:
            ws, raw = self._msg_queue.get()
            try:
                self._process_message(ws, raw)
            except Exception as e:
                log.error("Message processing error: %s", e)
            finally:
                self._msg_queue.task_done()

    def _process_message(self, ws, raw):
        m = json.loads(raw)
        channel = m.get("channel", "")

        if channel == "autodarts.matches":
            self._handle_match_state(m.get("data", {}))

        elif channel == "autodarts.boards":
            data = m.get("data", {})
            self._forward_board_status(data.get("event", ""), data.get("status"))
            self._subscribe_match(data, ws)

        elif channel == "autodarts.users":
            # Lobby handling omitted — not needed here
            pass

    # -------------------------------------------------------- board/match lifecycle

    def _forward_board_status(self, event_name, raw_status=None):
        status = board_status.resolve(event_name, raw_status)
        if status:
            self._emit({"event": "Board Status", "data": {"status": status}})
        elif event_name and not board_status.is_ignorable(event_name):
            # Previously silently dropped — any board event Autodarts sends
            # that isn't already accounted for should be visible somewhere
            # rather than vanish without a trace.
            log.info("Unmapped board event: %r", event_name)

    def _subscribe_match(self, m, ws):
        evt = m.get("event")

        if evt == "start":
            match_id = m.get("id")
            log.info("Match started (id=%s)", match_id)
            with self._match_lock:
                self._current_match = match_id
                self._match_active = True
                self._last_message = None
                self._index_name = {}
                self._match_started_at = time.time()
                self._last_activity_at = self._match_started_at

            with self._proc_lock:
                self._reset_turn_state()
                self._is_game_finished = False

            ws.send(json.dumps({
                "channel": "autodarts.boards",
                "type": "subscribe",
                "topic": f"{self._board_id}.events",
            }))
            ws.send(json.dumps({
                "channel": "autodarts.matches",
                "type": "subscribe",
                "topic": f"{match_id}.state",
            }))

            self._emit_match_started(match_id)

        elif evt in ("finish", "delete"):
            with self._match_lock:
                if not self._match_active:
                    return
                if self._current_match != m.get("id"):
                    return
                mid = self._current_match
                self._current_match = None
                self._match_active = False
                self._match_started_at = None
                self._last_activity_at = None
            log.info("Match ended (id=%s, event=%s)", mid, evt)

            ws.send(json.dumps({
                "channel": "autodarts.matches",
                "type": "unsubscribe",
                "topic": f"{mid}.state",
            }))
            ws.send(json.dumps({
                "channel": "autodarts.boards",
                "type": "unsubscribe",
                "topic": f"{self._board_id}.events",
            }))
            self._emit({"event": "match-ended"})

    def _emit_match_started(self, match_id):
        try:
            res = requests.get(
                _MATCHES_URL + match_id, headers=self._auth_header(), timeout=10
            ).json()
        except Exception as e:
            log.error("Fetch match %s failed: %s", match_id, e)
            return

        players = res.get("players", [])
        self._map_players(players)

        player_index = res.get("player", 0)
        player_name = (
            str(players[player_index]["name"]).lower() if player_index < len(players) else None
        )
        settings = res.get("settings", {})
        base_key = "target" if "target" in settings else "baseScore"
        points_start = settings.get(base_key)

        self._emit({
            "event": "match-started",
            "id": match_id,
            "player": player_name,
            "playerIndex": str(player_index),
            "game": {
                "mode": res.get("variant"),
                "pointsStart": str(points_start) if points_start is not None else None,
                "special": None,
            },
            "remainingScores": _remaining_scores_dict(res),
        })

    # -------------------------------------------------------- match state routing

    def _handle_match_state(self, data):
        if not data:
            return

        # Deduplicate
        with self._match_lock:
            if not self._match_active or self._current_match is None:
                return
            if data.get("id") != self._current_match:
                return
            if self._index_name == {} and data.get("players"):
                self._map_players(data["players"])
            if data.get("turns"):
                data["turns"][0].pop("id", None)
                data["turns"][0].pop("createdAt", None)
            if self._last_message == data:
                return
            self._last_message = data
            self._last_activity_at = time.time()

        time.sleep(0.01)

        variant = data.get("variant", "")
        with self._proc_lock:
            if variant in ("X01", "Random Checkout"):
                self._process_x01(data)
            elif variant == "Cricket":
                self._process_cricket(data)
            # Other variants (ATC, RTW, Bermuda, etc.) can be added here

    def _map_players(self, players):
        for i, p in enumerate(players):
            name = p.get("name")
            if name:
                self._index_name[str(name).lower()] = i

    # -------------------------------------------------------- X01 translation

    def _reset_turn_state(self):
        self._prev_throws_count = 0
        self._dart_cumulative = [0, 0, 0]
        self._last_points = None

    def _process_x01(self, m):
        players = m.get("players", [])
        player_index = m.get("player", 0)
        if player_index >= len(players):
            return

        p = players[player_index]
        player_name = str(p.get("name", "")).lower()
        is_bot = p.get("cpuPPR") is not None

        scores = m.get("gameScores") or []
        remaining = int(scores[player_index]) if player_index < len(scores) else 0
        remaining_scores = _remaining_scores_dict(m)

        turns = m.get("turns") or []
        if not turns:
            return
        turn = turns[0]
        throws = turn.get("throws") or []
        cum_points = int(turn.get("points", 0))
        busted = turn.get("busted") is True

        winner = m.get("winner", -1)
        game_winner = m.get("gameWinner", -1)

        settings = m.get("settings", {})
        base_key = "target" if "target" in settings else "baseScore"
        base_score = settings.get(base_key, 0)

        n = len(throws)
        gameon = (scores and int(scores[0]) == base_score) and n == 0
        matchon = gameon and m.get("leg", 1) == 1 and m.get("set", 1) == 1

        common = {
            "player": player_name,
            "playerIndex": str(player_index),
            "playerIsBot": str(is_bot),
            "remainingScores": remaining_scores,
        }

        # 1. Darts pulled (player change or post-finish cleanup)
        if n == 0 and (self._prev_throws_count > 0 or self._is_game_finished):
            if self._last_points == "B":
                bust_flag, last_pts = "True", "0"
            else:
                bust_flag, last_pts = "False", self._last_points or "0"
            self._emit({
                **common,
                "event": "darts-pulled",
                "game": {
                    "mode": m.get("variant"),
                    "pointsLeft": str(remaining),
                    "dartsThrown": str(self._prev_throws_count),
                    "dartsThrownValue": last_pts,
                    "busted": bust_flag,
                },
            })
            self._reset_turn_state()
            self._is_game_finished = False
            return

        # 2. Game-on / match-on
        if gameon:
            self._reset_turn_state()
            self._is_game_finished = False
            if not matchon:
                self._emit({
                    **common,
                    "event": "game-started",
                    "game": {
                        "mode": m.get("variant"),
                        "pointsStart": str(base_score),
                        "special": None,
                    },
                    "remainingScores": remaining_scores,
                })
            return

        # 3. Match won
        if winner != -1 and not self._is_game_finished:
            self._emit_dart_thrown(n, throws, remaining, cum_points, common, m)
            self._is_game_finished = True
            winner_name = str(players[winner].get("name", "")).lower() if 0 <= winner < len(players) else None
            game_data = {
                "mode": m.get("variant"),
                "dartsThrownValue": str(cum_points),
                "leg": m.get("leg", 1),
                "winner": winner_name,
            }
            if throws:
                seg = throws[-1].get("segment", {})
                game_data.update({
                    "fieldName": str(seg.get("name", "")).lower(),
                    "fieldNumber": seg.get("number"),
                    "fieldMultiplier": seg.get("multiplier"),
                    "type": str(seg.get("bed", "")).lower(),
                })
            self._emit({**common, "event": "match-won", "game": game_data})
            return

        # 4. Game won (leg/set won, match continues)
        if game_winner != -1 and not self._is_game_finished:
            self._emit_dart_thrown(n, throws, remaining, cum_points, common, m)
            self._is_game_finished = True
            gw_name = str(players[game_winner].get("name", "")).lower() if 0 <= game_winner < len(players) else None
            game_data = {
                "mode": m.get("variant"),
                "dartsThrownValue": str(cum_points),
                "leg": m.get("leg", 1),
                "winner": gw_name,
            }
            if throws:
                seg = throws[-1].get("segment", {})
                game_data.update({
                    "fieldName": str(seg.get("name", "")).lower(),
                    "fieldNumber": seg.get("number"),
                    "fieldMultiplier": seg.get("multiplier"),
                })
            self._emit({**common, "event": "game-won", "game": game_data})
            return

        # 5. Busted
        if busted and not self._is_game_finished:
            self._last_points = "B"
            self._prev_throws_count = n
            game_data = {"mode": m.get("variant"), "busted": "True"}
            if throws:
                seg = throws[-1].get("segment", {})
                game_data.update({
                    "field_name": str(seg.get("name", "")).lower(),
                    "field_number": seg.get("number"),
                    "field_multiplier": seg.get("multiplier"),
                    "type": str(seg.get("bed", "")).lower(),
                })
            self._emit({**common, "event": "busted", "game": game_data})
            return

        # 5.5 Undo or PATCH correction: re-emit all current throws from scratch
        #   - undo:       n < prev (dart digitally removed)
        #   - correction: n == prev but cumulative points changed (PATCH .../throws)
        undo = 0 < n < self._prev_throws_count
        corrected = (
            n > 0
            and n == self._prev_throws_count
            and cum_points != self._dart_cumulative[n - 1]
        )
        if undo or corrected:
            total_turn_pts = int(turn.get("points", 0))
            original_remaining = remaining + total_turn_pts
            self._reset_turn_state()
            cum = 0
            for i, throw_data in enumerate(throws[:n]):
                seg = throw_data.get("segment", {})
                number = int(seg.get("number", 0) or 0)
                multiplier = int(seg.get("multiplier", 0) or 0)
                dart_val = number * multiplier
                cum += dart_val
                dart_n = i + 1
                self._dart_cumulative[i] = cum
                self._prev_throws_count = dart_n
                self._last_points = str(cum)
                self._emit({
                    **common,
                    "event": f"dart{dart_n}-thrown",
                    "game": {
                        "mode": m.get("variant"),
                        "pointsLeft": str(original_remaining - cum),
                        "dartNumber": str(dart_n),
                        "dartValue": str(dart_val),
                        "fieldName": str(seg.get("name", "")).lower(),
                        "fieldNumber": number,
                        "fieldMultiplier": multiplier,
                        "type": str(seg.get("bed", "")).lower(),
                    },
                })
            if n == 3:
                self._emit({
                    **common,
                    "event": "darts-thrown",
                    "game": {
                        "mode": m.get("variant"),
                        "pointsLeft": str(remaining),
                        "dartNumber": "3",
                        "dartValue": str(cum),
                    },
                })
            return

        # 6. Dart thrown (n increased)
        if n > self._prev_throws_count and n >= 1:
            self._emit_dart_thrown(n, throws, remaining, cum_points, common, m)

            if n == 3:
                self._emit({
                    **common,
                    "event": "darts-thrown",
                    "game": {
                        "mode": m.get("variant"),
                        "pointsLeft": str(remaining),
                        "dartNumber": "3",
                        "dartValue": str(cum_points),
                    },
                })

    # -------------------------------------------------------- Cricket translation

    def _process_cricket(self, m):
        players = m.get("players", [])
        player_index = m.get("player", 0)
        if player_index >= len(players):
            return

        p = players[player_index]
        player_name = str(p.get("name", "")).lower()
        is_bot = p.get("cpuPPR") is not None

        turns = m.get("turns") or []
        if not turns:
            return
        turn = turns[0]
        throws = turn.get("throws") or []
        busted = turn.get("busted") is True

        winner = m.get("winner", -1)
        game_winner = m.get("gameWinner", -1)

        common = {
            "player": player_name,
            "playerIndex": str(player_index),
            "playerIsBot": str(is_bot),
        }

        CRICKET_FIELDS = {15, 16, 17, 18, 19, 20, 25}
        n = len(throws)

        # Darts pulled
        if n == 0 and (self._prev_throws_count > 0 or self._is_game_finished):
            self._emit({
                **common,
                "event": "darts-pulled",
                "game": {
                    "mode": m.get("variant"),
                    "pointsLeft": "0",
                    "dartsThrown": "3",
                    "dartsThrownValue": self._last_points or "0",
                    "busted": "True" if self._last_points == "B" else "False",
                },
            })
            self._reset_turn_state()
            self._is_game_finished = False
            return

        if winner != -1 and not self._is_game_finished:
            self._is_game_finished = True
            throw_pts = sum(
                t["segment"]["number"] * t["segment"]["multiplier"]
                for t in throws
                if t.get("segment", {}).get("number") in CRICKET_FIELDS
            )
            self._emit({**common, "event": "match-won",
                        "game": {"mode": m.get("variant"), "dartsThrownValue": throw_pts}})
            return

        if game_winner != -1 and not self._is_game_finished:
            self._is_game_finished = True
            throw_pts = sum(
                t["segment"]["number"] * t["segment"]["multiplier"]
                for t in throws
                if t.get("segment", {}).get("number") in CRICKET_FIELDS
            )
            self._emit({**common, "event": "game-won",
                        "game": {"mode": m.get("variant"), "dartsThrownValue": throw_pts}})
            return

        if busted and not self._is_game_finished:
            self._last_points = "B"
            self._prev_throws_count = n
            self._emit({**common, "event": "busted", "game": {"mode": m.get("variant")}})
            return

        if 0 < n < self._prev_throws_count:
            self._prev_throws_count = n
            return

        if n == 3 and n > self._prev_throws_count:
            throw_pts = sum(
                t["segment"]["number"] * t["segment"]["multiplier"]
                for t in throws
                if t.get("segment", {}).get("number") in CRICKET_FIELDS
            )
            self._last_points = str(throw_pts)
            self._prev_throws_count = 3
            self._emit({
                **common,
                "event": "darts-thrown",
                "game": {
                    "mode": m.get("variant"),
                    "dartNumber": "3",
                    "dartValue": throw_pts,
                },
            })
        elif n > self._prev_throws_count:
            self._prev_throws_count = n

    # ----------------------------------------------------------------- emit

    def _emit(self, event):
        try:
            self._on_event(event)
        except Exception as e:
            log.error("Emit error: %s", e, exc_info=True)

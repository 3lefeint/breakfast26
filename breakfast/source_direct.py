import json
import logging
import threading
import time
from urllib.parse import urlsplit

import requests
import websocket

from breakfast import board_status
from breakfast.state import GameState

log = logging.getLogger(__name__)
from breakfast.recorder import Recorder
from breakfast.output_console import print_state
from breakfast.mqtt_output import MqttPublisher, NullMqttPublisher
from breakfast.elimination import EliminationController
from breakfast.black_belt import BlackBeltController
from breakfast.warm_up import WarmUpController
from breakfast.field_training import FieldTrainingController
from breakfast.checkout_training import CheckoutTrainingController
from breakfast.target_battle import TargetBattleController
from breakfast.killer import KillerController
from breakfast.x01_game import X01Controller
from breakfast.tournament import TournamentController
from breakfast.resume import ResumeOffers
from breakfast.autodarts_client import AutodartsCloudClient
from breakfast.dev_demo import DemoRunner

DEFAULT_BOARD_WS_URL = "ws://localhost:3180/api/events"


def _dart_value(throw):
    seg = throw.get("segment", {})
    multiplier = seg.get("multiplier")
    if not multiplier:  # 0 (miss) or None → 0 points
        return 0
    return (seg.get("number") or 0) * multiplier


def _handle_board_message(data, state, mqtt_pub, elim_ctrl, audio, prev_count, tb_ctrl=None,
                          killer_ctrl=None, ft_ctrl=None, bb_ctrl=None, co_ctrl=None, x01_ctrl=None, wu_ctrl=None):
    """Process one board-WS state message. Returns the new prev_count.

    Split out from _start_board_ws()'s on_message closure so this logic is
    unit-testable without a real WebSocket thread.
    """
    # Board status regardless of game mode — this local connection is
    # active for X01/Freeplay/Elimination alike, unlike the cloud
    # channel (autodarts_client.py), which only relays board-status
    # events once a real Autodarts cloud match has started, so it
    # never fires during Freeplay/Elimination at all.
    new_status = board_status.resolve(data.get("event", ""), data.get("status"))
    if new_status:
        changed = new_status != state.board_status
        evt = state.update({"event": "Board Status", "data": {"status": new_status}})
        if evt:
            if mqtt_pub and changed:
                mqtt_pub.publish_board_status(evt)
            from breakfast.web import server as web
            web.push()

    count = data.get("numThrows", 0)
    throws = data.get("throws") or []

    # While a bot throws, or a player at another site of an online match, the board shows their darts and the real,
    # empty board must not wipe them.
    foreign = (getattr(getattr(x01_ctrl, "bots", None), "playing", False)
               or getattr(elim_ctrl, "remote_turn_active", lambda: False)())
    if not foreign and state.board_darts.update(throws if count else []):
        from breakfast.web import server as web
        web.push()

    # A match played in Breakfast sets `match_started` like an Autodarts match, so it is asked first.
    if x01_ctrl and x01_ctrl.active:
        x01_ctrl.on_board_state(count, throws)
        return count

    if state.match_started:
        return count

    try:
        if elim_ctrl and elim_ctrl.active:
            elim_ctrl.on_board_state(count, throws)
        elif tb_ctrl and tb_ctrl.active:
            tb_ctrl.on_board_state(count, throws)
        elif killer_ctrl and killer_ctrl.active:
            killer_ctrl.on_board_state(count, throws)
        elif ft_ctrl and ft_ctrl.active:
            ft_ctrl.on_board_state(count, throws)
        elif bb_ctrl and bb_ctrl.active:
            bb_ctrl.on_board_state(count, throws)
        elif wu_ctrl and wu_ctrl.active:
            wu_ctrl.on_board_state(count, throws)
        elif co_ctrl and co_ctrl.active:
            co_ctrl.on_board_state(count, throws)
        else:
            is_new_dart = count > prev_count
            if count != prev_count and mqtt_pub:
                mqtt_pub.publish_freeplay(count, throws)
            if audio and is_new_dart and 1 <= count <= len(throws):
                # Same simple call style as elimination.py — freeplay has
                # no caller/ambient machinery, just a miss comment per
                # dart and the turn total once all 3 are down.
                if _dart_value(throws[count - 1]) == 0:
                    audio.play("miss", prob=0.35)
                if count == 3:
                    audio.play(str(sum(_dart_value(t) for t in throws)))
    except Exception:
        log.exception("Board WS handler error")

    return count


def _board_state_url(board_ws_url):
    """The board manager's `/api/state` next to its event stream (ws://host:3180/api/events)."""
    parts = urlsplit(board_ws_url)
    return f"{'https' if parts.scheme == 'wss' else 'http'}://{parts.netloc}/api/state"


def _fetch_board_status(state, board_ws_url, mqtt_pub=None):
    """The event stream says nothing when it opens, so a board that stopped before Breakfast started (camera standby)
    would stay unknown: ask for its status once."""
    try:
        status = requests.get(_board_state_url(board_ws_url), timeout=5).json().get("status")
    except Exception as e:
        log.debug("Board status not available: %s", e)
        return
    evt = status and state.update({"event": "Board Status", "data": {"status": status}})
    if evt:
        if mqtt_pub:
            mqtt_pub.publish_board_status(evt)
        from breakfast.web import server as web
        web.push()


class _Reconnect:
    """The retries of a connection that is kept up for ever: the first failure of an outage is logged, the repeats go to
    debug, the delay doubles up to a minute, and one line says when the connection is back."""

    MIN, MAX = 3, 60

    def __init__(self, name):
        self.name = name
        self.since = None
        self.delay = self.MIN

    def failed(self, reason):
        if self.since is None:
            self.since = time.time()
            log.warning("%s lost: %s", self.name, reason)
        else:
            log.debug("%s still down: %s", self.name, reason)

    def opened(self):
        if self.since is not None:
            log.info("%s restored after %ds", self.name, time.time() - self.since)
            self.since = None
        self.delay = self.MIN

    def next_delay(self):
        delay, self.delay = self.delay, min(self.delay * 2, self.MAX)
        return delay


def _start_board_ws(state, mqtt_pub, elim_ctrl=None, board_ws_url=DEFAULT_BOARD_WS_URL, audio=None,
                    tb_ctrl=None, killer_ctrl=None, ft_ctrl=None, bb_ctrl=None, co_ctrl=None, x01_ctrl=None,
                    wu_ctrl=None):
    """Background thread: local board WebSocket for Elimination, Target Battle, Killer and freeplay."""
    prev_count = 0

    def on_message(ws, message):
        nonlocal prev_count
        try:
            msg = json.loads(message)
        except Exception:
            return
        if msg.get("type") != "state":
            return
        prev_count = _handle_board_message(
            msg.get("data", {}), state, mqtt_pub, elim_ctrl, audio, prev_count, tb_ctrl, killer_ctrl, ft_ctrl, bb_ctrl, co_ctrl,
            x01_ctrl, wu_ctrl=wu_ctrl)

    def set_connected(connected):
        if state.board_darts.set_connected(connected):
            from breakfast.web import server as web
            web.push()
        if connected:
            threading.Thread(target=_fetch_board_status, args=(state, board_ws_url, mqtt_pub), daemon=True).start()

    reconnect = _Reconnect("Board stream")

    def opened(ws):
        reconnect.opened()
        set_connected(True)

    def run():
        while True:
            try:
                ws = websocket.WebSocketApp(
                    board_ws_url, on_message=on_message, on_open=opened,
                    on_error=lambda ws, e: reconnect.failed(f"{type(e).__name__}: {e}"),
                    on_close=lambda ws, code, msg: reconnect.failed(f"closed ({code})"))
                ws.run_forever()
            except Exception as e:
                reconnect.failed(f"{type(e).__name__}: {e}")
            set_connected(False)
            time.sleep(reconnect.next_delay())

    threading.Thread(target=run, daemon=True).start()


def run_direct(email, password, board_id, record_file=None,
               mqtt_enabled=True, mqtt_host=None, mqtt_port=1883, mqtt_username=None,
               mqtt_password=None, mqtt_base_topic="autodarts",
               audio_dir=None, audio_profile=None, caller_cfg=None,
               web_port=None,
               stats_db=None, stats_timezone="UTC", log_events=False, config_path=None,
               board_ws_url=DEFAULT_BOARD_WS_URL, board_manager_url=None):

    from breakfast.web import server as web
    from breakfast.achievements import AchievementEngine
    from breakfast.stats import StatsDB, StatsTracker

    state = GameState()
    recorder = Recorder(record_file) if record_file else None
    mqtt_pub = None
    stats_tracker = None
    stats_db_instance = None
    achievements = None

    if stats_db and stats_db.lower() != "none":
        stats_db_instance = StatsDB(stats_db, tz=stats_timezone)
        achievements = AchievementEngine(stats_db_instance).attach()
        stats_tracker = StatsTracker(stats_db_instance)

    audio = None
    caller = None
    if audio_dir:
        from breakfast import caller as caller_mod
        from breakfast import voicepack
        from breakfast.audio_engine import AudioEngine
        audio = AudioEngine(voicepack.search_dirs(audio_dir, audio_profile),
                            broadcast=web.push_sound)
        caller = caller_mod.from_config(audio, caller_cfg)
    elif caller_cfg:
        log.warning("[caller] is configured but [audio] dir is not set — "
                    "voice caller disabled")

    if achievements:
        achievements.announce(web.push_achievement, audio, sounds=web.assigned_achievement_sounds)

    if mqtt_enabled and mqtt_host:
        mqtt_pub = MqttPublisher(
            host=mqtt_host,
            port=mqtt_port,
            username=mqtt_username,
            password=mqtt_password,
            base_topic=mqtt_base_topic,
        )

    # Elimination is built against the mqtt_pub-shaped interface regardless of
    # whether MQTT/HA/LED output is configured — a NullMqttPublisher makes it
    # a no-op sink so Elimination/scoreboard/caller work fully without any
    # MQTT setup, MQTT becoming purely an optional additional output.
    elim_ctrl = EliminationController(
        mqtt_pub or NullMqttPublisher(), mqtt_base_topic, stats_db=stats_db_instance,
        audio=audio, on_change=web.push,
    )
    tb_ctrl = TargetBattleController(
        mqtt_pub or NullMqttPublisher(), mqtt_base_topic, stats_db=stats_db_instance,
        audio=audio, on_change=web.push,
    )
    killer_ctrl = KillerController(
        mqtt_pub or NullMqttPublisher(), mqtt_base_topic, stats_db=stats_db_instance,
        audio=audio, on_change=web.push,
    )
    ft_ctrl = FieldTrainingController(
        mqtt_pub or NullMqttPublisher(), mqtt_base_topic, stats_db=stats_db_instance,
        audio=audio, on_change=web.push,
    )
    bb_ctrl = BlackBeltController(
        mqtt_pub or NullMqttPublisher(), mqtt_base_topic, stats_db=stats_db_instance,
        audio=audio, on_change=web.push,
    )
    wu_ctrl = WarmUpController(
        mqtt_pub or NullMqttPublisher(), mqtt_base_topic, stats_db=stats_db_instance,
        audio=audio, on_change=web.push,
    )
    co_ctrl = CheckoutTrainingController(
        mqtt_pub or NullMqttPublisher(), mqtt_base_topic, stats_db=stats_db_instance,
        audio=audio, on_change=web.push,
    )
    # The events of a match played in Breakfast go through the same function as those of an Autodarts match,
    # see on_event() below.
    x01_ctrl = X01Controller(lambda data: process_event(data), stats_db=stats_db_instance, audio=audio,
                             on_change=web.push)
    def show_bot_darts(throws):
        if state.board_darts.update(throws, bot=True):
            web.push()
    x01_ctrl.bots.on_darts = show_bot_darts

    def show_remote_darts(throws):
        if state.board_darts.update(throws, remote=True):
            web.push()
    elim_ctrl.on_remote_darts = show_remote_darts
    tournament_ctrl = TournamentController(x01_ctrl, stats_db=stats_db_instance, on_change=web.push)
    resume_offers = ResumeOffers(
        stats_db_instance, {"X01": x01_ctrl, "Elimination": elim_ctrl, "Killer": killer_ctrl}, tournament=tournament_ctrl,
        board_darts=state.board_darts, on_change=web.push) if stats_db_instance else None
    _start_board_ws(state, mqtt_pub, elim_ctrl, board_ws_url=board_ws_url, audio=audio, tb_ctrl=tb_ctrl,
                    killer_ctrl=killer_ctrl, ft_ctrl=ft_ctrl, bb_ctrl=bb_ctrl, co_ctrl=co_ctrl, x01_ctrl=x01_ctrl,
                    wu_ctrl=wu_ctrl)

    def process_event(data):
        if recorder:
            recorder.write(data)
        if log_events:
            ev = data.get("event", "?")
            pl = data.get("player") or ""
            if isinstance(pl, dict):
                pl = pl.get("name", "")
            log.info("Event: %s  player=%s", ev, pl)
        evt = state.update(data)
        if caller and not data.get("silent"):      # a corrected turn of a match played here makes no calls
            caller.on_event(evt, state.snapshot())
        if stats_tracker:
            stats_tracker.process(data)
        if log_events:
            print_state(state)
        if mqtt_pub:
            try:
                if evt:
                    mqtt_pub.publish_event(evt)
                mqtt_pub.publish_state(state.snapshot())
            except Exception as e:
                log.error("MQTT publish error: %s", e)
        web.push()

    def on_event(data):
        """The events of an external match (the cloud, the demo). They are ignored while a match is played
        in Breakfast: that one has priority."""
        if x01_ctrl.match_active:
            return
        process_event(data)

    # Without an account (a first start of the standalone build) there is no cloud client: only
    # the web UI runs until the account is entered in Settings and the app is restarted.
    def on_turn_darts(throws):
        """The board view of a match played in Autodarts follows its darts: those found by the cameras, those added or
        corrected by hand, numbered by their place in the turn."""
        from breakfast.board_darts import _dart
        darts = None if throws is None else [{"n": i + 1, **_dart(t)} for i, t in enumerate(throws)]
        if state.cloud_darts != darts:
            state.cloud_darts = darts
            web.push()

    client = None
    if email and password and board_id:
        client = AutodartsCloudClient(
            email=email,
            password=password,
            board_id=board_id,
            on_event=on_event,
            on_turn_darts=on_turn_darts,
        )

    # Wired unconditionally (harmless if never triggered) — server.py's
    # /api/dev/demo/* endpoints check the [dev] enabled config flag before
    # ever calling into this, so there's no need to thread that flag through
    # run_direct()'s own signature just to decide whether to build it.
    dev_demo = DemoRunner(on_x01_event=on_event, elim_ctrl=elim_ctrl, game_state=state)

    web.wire(state, elim_ctrl, cloud_client=client,
             stats_tracker=stats_tracker, mqtt_pub=mqtt_pub,
             config_path=config_path, audio_engine=audio,
             board_manager_url=board_manager_url, dev_demo=dev_demo, tb_ctrl=tb_ctrl, killer_ctrl=killer_ctrl, ft_ctrl=ft_ctrl, bb_ctrl=bb_ctrl, co_ctrl=co_ctrl,
             x01_ctrl=x01_ctrl, tournament_ctrl=tournament_ctrl, wu_ctrl=wu_ctrl, resume_offers=resume_offers)
    if web_port:
        web.start(web_port)
        web.start_update_check()
        web.start_circle_sync()
        web.start_voicepack_auto_generate()

    if client:
        log.info("Connecting to Autodarts cloud (board=%s)", board_id)
        client.start()
    else:
        log.warning("No Autodarts account configured, not connecting to the cloud")

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        pass

import json
import logging
import threading
import time

import websocket

from breakfast.state import GameState

log = logging.getLogger(__name__)
from breakfast.recorder import Recorder
from breakfast.output_console import print_state
from breakfast.mqtt_output import MqttPublisher, NullMqttPublisher
from breakfast.elimination import EliminationController
from breakfast.autodarts_client import AutodartsCloudClient
from breakfast.dev_demo import DemoRunner

DEFAULT_BOARD_WS_URL = "ws://localhost:3180/api/events"


def _start_board_ws(state, mqtt_pub, elim_ctrl=None, board_ws_url=DEFAULT_BOARD_WS_URL):
    """Background thread: local board WebSocket for elimination and freeplay."""
    prev_count = 0

    def on_message(ws, message):
        nonlocal prev_count
        try:
            msg = json.loads(message)
        except Exception:
            return
        if msg.get("type") != "state":
            return

        data = msg.get("data", {})
        count = data.get("numThrows", 0)
        throws = data.get("throws") or []

        if state.match_started:
            prev_count = count
            return

        try:
            if elim_ctrl and elim_ctrl.active:
                elim_ctrl.on_board_state(count, throws)
            elif count != prev_count and mqtt_pub:
                mqtt_pub.publish_freeplay(count, throws)
        except Exception:
            log.exception("Board WS handler error")

        prev_count = count

    def run():
        while True:
            try:
                ws = websocket.WebSocketApp(board_ws_url, on_message=on_message)
                ws.run_forever()
            except Exception as e:
                log.warning("Board WS error: %s", e)
            time.sleep(3)

    threading.Thread(target=run, daemon=True).start()


def run_direct(email, password, board_id, record_file=None,
               mqtt_enabled=True, mqtt_host=None, mqtt_port=1883, mqtt_username=None,
               mqtt_password=None, mqtt_base_topic="autodarts",
               audio_dir=None, audio_profile=None, caller_cfg=None,
               web_port=None,
               stats_db=None, log_events=False, config_path=None,
               board_ws_url=DEFAULT_BOARD_WS_URL, board_manager_url=None):

    from breakfast.web import server as web
    from breakfast.stats import StatsDB, StatsTracker

    state = GameState()
    recorder = Recorder(record_file) if record_file else None
    mqtt_pub = None
    stats_tracker = None
    stats_db_instance = None

    if stats_db and stats_db.lower() != "none":
        stats_db_instance = StatsDB(stats_db)
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
    _start_board_ws(state, mqtt_pub, elim_ctrl, board_ws_url=board_ws_url)

    def on_event(data):
        if recorder:
            recorder.write(data)
        if log_events:
            ev = data.get("event", "?")
            pl = data.get("player") or ""
            if isinstance(pl, dict):
                pl = pl.get("name", "")
            log.info("Event: %s  player=%s", ev, pl)
        evt = state.update(data)
        if caller:
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

    client = AutodartsCloudClient(
        email=email,
        password=password,
        board_id=board_id,
        on_event=on_event,
    )

    # Wired unconditionally (harmless if never triggered) — server.py's
    # /api/dev/demo/* endpoints check the [dev] enabled config flag before
    # ever calling into this, so there's no need to thread that flag through
    # run_direct()'s own signature just to decide whether to build it.
    dev_demo = DemoRunner(on_x01_event=on_event, elim_ctrl=elim_ctrl, game_state=state)

    web.wire(state, elim_ctrl, cloud_client=client,
             stats_tracker=stats_tracker, mqtt_pub=mqtt_pub,
             config_path=config_path, audio_engine=audio,
             board_manager_url=board_manager_url, dev_demo=dev_demo)
    if web_port:
        web.start(web_port)

    log.info("Connecting to Autodarts cloud (board=%s)", board_id)
    client.start()

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        pass

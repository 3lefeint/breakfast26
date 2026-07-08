import json
import logging
import time

from breakfast.state import GameState
from breakfast.output_console import print_state
from breakfast.mqtt_output import MqttPublisher

log = logging.getLogger(__name__)


def run_replay(file, speed, mqtt_enabled=True, mqtt_host=None, mqtt_port=1883,
               mqtt_username=None, mqtt_password=None, mqtt_base_topic="autodarts",
               audio_dir=None, audio_profile=None, caller_cfg=None,
               web_port=None, wait_audio=False, config_path=None, log_events=False):
    from breakfast.web import server as web

    state = GameState()
    mqtt_pub = None

    if mqtt_enabled and mqtt_host:
        mqtt_pub = MqttPublisher(
            host=mqtt_host,
            port=mqtt_port,
            username=mqtt_username,
            password=mqtt_password,
            base_topic=mqtt_base_topic,
        )

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

    if web_port:
        web.wire(state, None, None, config_path=config_path, audio_engine=audio)
        web.start(web_port)
        log.info("Web UI: http://localhost:%d  (audio page: /audio)", web_port)

    if wait_audio:
        if not web_port:
            log.warning("--wait-audio has no effect without a web port")
        else:
            log.info("Waiting for an audio client on /audio before replaying ...")
            while web.audio_client_count() == 0:
                time.sleep(0.3)
            log.info("Audio client connected, starting replay")

    with open(file) as f:
        for line in f:
            entry = json.loads(line)
            data = entry["payload"]

            evt = state.update(data)
            if caller:
                caller.on_event(evt, state.snapshot())
            if log_events:
                print_state(state)

            if mqtt_pub:
                if evt:
                    mqtt_pub.publish_event(evt)
                mqtt_pub.publish_state(state.snapshot())
            if web_port:
                web.push()

            time.sleep(1 / speed)

    if web_port:
        log.info("Replay finished — web server still running, Ctrl-C to exit")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            pass

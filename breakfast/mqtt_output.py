import json
import logging
import threading
import time
import paho.mqtt.client as mqtt

log = logging.getLogger(__name__)


def _publish(client, topic, payload, retain=True):
    if payload is None:
        payload = ""
    elif isinstance(payload, bool):
        payload = "true" if payload else "false"
    elif isinstance(payload, (dict, list)):
        payload = json.dumps(payload, ensure_ascii=False)
    else:
        payload = str(payload)
    client.publish(topic, payload, retain=retain)


class MqttPublisher:
    def __init__(self, host, port=1883, username=None, password=None, base_topic="autodarts"):
        self.host = host
        self.port = port
        self.base_topic = base_topic.rstrip("/")
        self._subscriptions = {}
        self._connected = False
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        if username:
            self.client.username_pw_set(username, password)
        self.client.loop_start()
        try:
            self.client.connect(host, port, 60)
            log.info("Connected to MQTT broker %s:%s", host, port)
        except OSError as e:
            # Broker unreachable at startup (wrong network, DNS hiccup, broker
            # down, ...) — don't crash the whole app over an optional output
            # channel. Fall back to the same retry-with-backoff loop already
            # used for a connection that drops later; everything except
            # MQTT/Home Assistant/ESPHome output works normally in the
            # meantime (self._connected stays False until it succeeds).
            log.warning(
                "MQTT broker %s:%s unreachable at startup (%s) — retrying in "
                "the background", host, port, e,
            )
            threading.Thread(target=self._reconnect_loop, daemon=True).start()

    @property
    def connected(self) -> bool:
        return self._connected

    def subscribe(self, topic, callback):
        self.client.subscribe(topic)
        self._subscriptions[topic] = callback

    def _on_connect(self, client, userdata, connect_flags, reason_code, properties):
        rc = getattr(reason_code, "value", reason_code)
        self._connected = rc == 0

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        self._connected = False
        rc = getattr(reason_code, "value", reason_code)
        if rc != 0:
            log.warning("MQTT disconnected unexpectedly (rc=%s), reconnecting…", rc)
            threading.Thread(target=self._reconnect_loop, daemon=True).start()

    def _reconnect_loop(self):
        delay = 1
        while True:
            try:
                self.client.reconnect()
                self._connected = True
                log.info("MQTT reconnected to %s:%s", self.host, self.port)
                return
            except Exception as e:
                log.warning("MQTT reconnect failed (%s), retry in %ds", e, delay)
                time.sleep(delay)
                delay = min(delay * 2, 60)

    def _on_message(self, client, userdata, message):
        cb = self._subscriptions.get(message.topic)
        if cb:
            try:
                cb(message.payload.decode())
            except Exception as e:
                log.error("MQTT handler error [%s]: %s", message.topic, e)

    def publish_event(self, event):
        """Publish a non-retained real-time event to autodarts/events/{type}.

        These are atomic single-message events for ESPHome/other consumers that
        need all relevant data in one payload without retained-topic ordering races.
        """
        if not event:
            return
        event_type = event.get("type", "unknown")
        topic = f"{self.base_topic}/events/{event_type}"
        payload = json.dumps(event, ensure_ascii=False)
        self.client.publish(topic, payload, retain=False)

    def publish_state(self, snapshot):
        """Publish retained state topics for Home Assistant sensors."""
        base = self.base_topic

        _publish(self.client, f"{base}/board/status", snapshot["board_status"])
        _publish(self.client, f"{base}/match/started", snapshot["match_started"])
        _publish(self.client, f"{base}/match/id", snapshot["match_id"])
        _publish(self.client, f"{base}/match/game_mode", snapshot["game_mode"])
        _publish(self.client, f"{base}/match/points_start", snapshot["points_start"])
        _publish(self.client, f"{base}/match/special", snapshot["special"])
        _publish(self.client, f"{base}/match/last_event", snapshot["last_event"])
        _publish(self.client, f"{base}/current/player_index", snapshot["active_player_index"])
        _publish(self.client, f"{base}/current/player_name", snapshot["active_player_name"])
        _publish(self.client, f"{base}/current/throw_seq", snapshot.get("throw_seq"))

        current = snapshot.get("current") or {}
        _publish(self.client, f"{base}/current/remaining", current.get("remaining"))
        _publish(self.client, f"{base}/current/turn_score", current.get("turn_score"))
        _publish(self.client, f"{base}/current/turn_active", current.get("turn_active"))
        _publish(self.client, f"{base}/current/is_bust", current.get("is_bust"))
        _publish(self.client, f"{base}/current/last_is_miss", current.get("last_is_miss"))
        _publish(self.client, f"{base}/current/throw1_raw", current.get("throw1_raw"))
        _publish(self.client, f"{base}/current/throw2_raw", current.get("throw2_raw"))
        _publish(self.client, f"{base}/current/throw3_raw", current.get("throw3_raw"))
        _publish(self.client, f"{base}/current/throw1_points", current.get("throw1_points"))
        _publish(self.client, f"{base}/current/throw2_points", current.get("throw2_points"))
        _publish(self.client, f"{base}/current/throw3_points", current.get("throw3_points"))
        _publish(self.client, f"{base}/current/last_field_name", current.get("last_field_name"))
        _publish(self.client, f"{base}/current/last_field_number", current.get("last_field_number"))
        _publish(self.client, f"{base}/current/last_field_multiplier", current.get("last_field_multiplier"))
        _publish(self.client, f"{base}/current/last_dart_number", current.get("last_dart_number"))
        _publish(self.client, f"{base}/current/last_dart_value", current.get("last_dart_value"))

        _publish(self.client, f"{base}/remaining_scores/json", snapshot.get("remaining_scores", {}))
        _publish(self.client, f"{base}/players/json", snapshot.get("players", {}))
        _publish(self.client, f"{base}/state/json", snapshot)

        for idx, player in snapshot.get("players", {}).items():
            pbase = f"{base}/players/{idx}"
            _publish(self.client, f"{pbase}/name", player.get("name"))
            _publish(self.client, f"{pbase}/is_bot", player.get("is_bot"))
            _publish(self.client, f"{pbase}/remaining", player.get("remaining"))
            _publish(self.client, f"{pbase}/turn_score", player.get("turn_score"))
            _publish(self.client, f"{pbase}/turn_active", player.get("turn_active"))
            _publish(self.client, f"{pbase}/is_bust", player.get("is_bust"))
            _publish(self.client, f"{pbase}/last_is_miss", player.get("last_is_miss"))
            _publish(self.client, f"{pbase}/throw1_raw", player.get("throw1_raw"))
            _publish(self.client, f"{pbase}/throw2_raw", player.get("throw2_raw"))
            _publish(self.client, f"{pbase}/throw3_raw", player.get("throw3_raw"))
            _publish(self.client, f"{pbase}/throw1_points", player.get("throw1_points"))
            _publish(self.client, f"{pbase}/throw2_points", player.get("throw2_points"))
            _publish(self.client, f"{pbase}/throw3_points", player.get("throw3_points"))
            _publish(self.client, f"{pbase}/last_field_name", player.get("last_field_name"))
            _publish(self.client, f"{pbase}/last_field_number", player.get("last_field_number"))
            _publish(self.client, f"{pbase}/last_field_multiplier", player.get("last_field_multiplier"))
            _publish(self.client, f"{pbase}/last_dart_number", player.get("last_dart_number"))
            _publish(self.client, f"{pbase}/last_dart_value", player.get("last_dart_value"))

    def publish_freeplay(self, count, throws):
        """Publish freeplay state when no match is active.

        Uses separate autodarts/freeplay/ topics to avoid interfering with
        game state. ESPHome reads these directly via MQTT subscriptions.
        """
        base = f"{self.base_topic}/freeplay"
        _publish(self.client, f"{base}/count", count)
        total = 0
        for i in range(1, 4):
            if i <= len(throws):
                seg = throws[i - 1].get("segment", {})
                name = seg.get("name") or ""
                value = (seg.get("number") or 0) * (seg.get("multiplier") or 1)
                total += value
            else:
                name = ""
                value = 0
            _publish(self.client, f"{base}/throw{i}_name", name)
            _publish(self.client, f"{base}/throw{i}_value", value)
        _publish(self.client, f"{base}/total", total)

        if count > 0 and throws:
            seg = throws[-1].get("segment", {})
            self.client.publish(
                f"{self.base_topic}/events/freeplay_dart",
                json.dumps({"segment": seg.get("name", ""), "count": count}),
                retain=False,
            )

    def close(self):
        time.sleep(0.1)
        self.client.loop_stop()
        self.client.disconnect()


class NullMqttPublisher:
    """No-op stand-in for `MqttPublisher`, used when MQTT/HA/LED output is
    disabled (no `[mqtt] host`, or `[mqtt] enabled = false`).

    Elimination is built against the same `mqtt_pub`-shaped interface
    (`.client.publish(...)`, `.subscribe(...)`) regardless of whether a
    broker is configured, so its game logic never has to special-case "no
    MQTT" — MQTT becomes a purely optional additional output rather than a
    prerequisite for Elimination to run at all.
    """

    class _NullClient:
        def publish(self, *args, **kwargs):
            pass

    def __init__(self):
        self.client = self._NullClient()

    @property
    def connected(self) -> bool:
        return False

    def subscribe(self, topic, callback):
        pass

    def publish_event(self, event):
        pass

    def publish_state(self, snapshot):
        pass

    def publish_freeplay(self, count, throws):
        pass

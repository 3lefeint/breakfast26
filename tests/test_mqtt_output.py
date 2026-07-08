from unittest.mock import MagicMock

from breakfast.mqtt_output import MqttPublisher, NullMqttPublisher


class FakeThread:
    """Captures the target instead of actually running it, so tests are
    deterministic and don't race a real background thread."""
    started = []

    def __init__(self, target=None, daemon=None):
        self.target = target
        FakeThread.started.append(target)

    def start(self):
        pass


class TestMqttPublisherStartup:
    def test_unreachable_broker_does_not_raise(self, monkeypatch):
        FakeThread.started = []
        fake_client = MagicMock()
        fake_client.connect.side_effect = OSError("Network is unreachable")
        monkeypatch.setattr("breakfast.mqtt_output.mqtt.Client", lambda *a, **k: fake_client)
        monkeypatch.setattr("breakfast.mqtt_output.threading.Thread", FakeThread)

        pub = MqttPublisher("unreachable.example", 1883)

        assert pub.connected is False
        fake_client.loop_start.assert_called_once()
        # falls back to the same retry-with-backoff loop used for a later drop
        assert FakeThread.started == [pub._reconnect_loop]

    def test_successful_connect_does_not_start_reconnect_loop(self, monkeypatch):
        FakeThread.started = []
        fake_client = MagicMock()  # connect() succeeds by default (no side_effect)
        monkeypatch.setattr("breakfast.mqtt_output.mqtt.Client", lambda *a, **k: fake_client)
        monkeypatch.setattr("breakfast.mqtt_output.threading.Thread", FakeThread)

        MqttPublisher("broker.example", 1883)

        fake_client.connect.assert_called_once_with("broker.example", 1883, 60)
        assert FakeThread.started == []


class TestNullMqttPublisher:
    """No-op stand-in used when MQTT/HA/LED output is disabled —
    Elimination is built against the same interface either way."""

    def test_connected_is_false(self):
        assert NullMqttPublisher().connected is False

    def test_client_publish_is_a_silent_no_op(self):
        pub = NullMqttPublisher()
        pub.client.publish("some/topic", "payload", retain=True)   # must not raise

    def test_subscribe_and_publish_methods_are_no_ops(self):
        pub = NullMqttPublisher()
        pub.subscribe("some/topic", lambda payload: 1 / 0)   # callback never runs
        pub.publish_event({"type": "dart"})
        pub.publish_state({"board_status": None, "current": {}, "players": {}})
        pub.publish_freeplay(1, [])

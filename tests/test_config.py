import logging
import tomllib
from types import SimpleNamespace

import tomli_w

from breakfast.config import load, write, apply_runtime, merge


class TestConfigLoad:
    def test_load_missing_file(self, tmp_path):
        result = load(tmp_path / "nonexistent.toml")
        assert result == {}

    def test_load_existing(self, tmp_path):
        path = tmp_path / "config.toml"
        with open(path, "wb") as f:
            tomli_w.dump({"mqtt": {"host": "broker", "port": 1883}}, f)
        result = load(path)
        assert result["mqtt"]["host"] == "broker"
        assert result["mqtt"]["port"] == 1883


class TestConfigWrite:
    def test_write_creates_file(self, tmp_path):
        path = tmp_path / "config.toml"
        write(path, {"mqtt": {"host": "myhost"}})
        assert path.exists()
        with open(path, "rb") as f:
            result = tomllib.load(f)
        assert result["mqtt"]["host"] == "myhost"

    def test_write_deep_merges(self, tmp_path):
        path = tmp_path / "config.toml"
        with open(path, "wb") as f:
            tomli_w.dump({"mqtt": {"port": 1883}}, f)
        write(path, {"mqtt": {"host": "myhost"}})
        with open(path, "rb") as f:
            result = tomllib.load(f)
        assert result["mqtt"]["host"] == "myhost"
        assert result["mqtt"]["port"] == 1883   # preserved

    def test_write_preserves_other_sections(self, tmp_path):
        path = tmp_path / "config.toml"
        with open(path, "wb") as f:
            tomli_w.dump({"mqtt": {"host": "broker"}, "logging": {"level": "INFO"}}, f)
        write(path, {"logging": {"level": "DEBUG"}})
        with open(path, "rb") as f:
            result = tomllib.load(f)
        assert result["mqtt"]["host"] == "broker"   # unchanged
        assert result["logging"]["level"] == "DEBUG"

    def test_write_overwrites_scalar(self, tmp_path):
        path = tmp_path / "config.toml"
        with open(path, "wb") as f:
            tomli_w.dump({"mqtt": {"host": "old"}}, f)
        write(path, {"mqtt": {"host": "new"}})
        with open(path, "rb") as f:
            result = tomllib.load(f)
        assert result["mqtt"]["host"] == "new"

    def test_write_none_value_removes_key(self, tmp_path):
        path = tmp_path / "config.toml"
        with open(path, "wb") as f:
            tomli_w.dump({"mqtt": {"host": "old", "port": 1883}}, f)
        write(path, {"mqtt": {"host": None}})
        with open(path, "rb") as f:
            result = tomllib.load(f)
        assert "host" not in result["mqtt"]
        assert result["mqtt"]["port"] == 1883   # untouched key preserved

    def test_write_none_value_for_missing_key_is_a_no_op(self, tmp_path):
        path = tmp_path / "config.toml"
        write(path, {"mqtt": {"host": None}})
        with open(path, "rb") as f:
            result = tomllib.load(f)
        assert "host" not in result.get("mqtt", {})


class TestMergeBoardWsUrl:
    def test_defaults_to_localhost(self):
        args = SimpleNamespace(mode="direct", board_ws_url=None)
        merge(args, {})
        assert args.board_ws_url == "ws://localhost:3180/api/events"

    def test_config_file_value_used(self):
        args = SimpleNamespace(mode="direct", board_ws_url=None)
        cfg = {"direct": {"board_ws_url": "ws://autodarts:3180/api/events"}}
        merge(args, cfg)
        assert args.board_ws_url == "ws://autodarts:3180/api/events"

    def test_cli_value_wins_over_config_file(self):
        args = SimpleNamespace(mode="direct", board_ws_url="ws://cli-override:3180/api/events")
        cfg = {"direct": {"board_ws_url": "ws://autodarts:3180/api/events"}}
        merge(args, cfg)
        assert args.board_ws_url == "ws://cli-override:3180/api/events"


class TestMergeBoardManagerUrl:
    def test_defaults_to_none(self):
        args = SimpleNamespace(mode="direct", board_manager_url=None)
        merge(args, {})
        assert args.board_manager_url is None

    def test_config_file_value_used(self):
        args = SimpleNamespace(mode="direct", board_manager_url=None)
        cfg = {"direct": {"board_manager_url": "https://dart-machine.example.com/"}}
        merge(args, cfg)
        assert args.board_manager_url == "https://dart-machine.example.com/"

    def test_cli_value_wins_over_config_file(self):
        args = SimpleNamespace(mode="direct", board_manager_url="https://cli-override.example.com/")
        cfg = {"direct": {"board_manager_url": "https://dart-machine.example.com/"}}
        merge(args, cfg)
        assert args.board_manager_url == "https://cli-override.example.com/"


class TestApplyRuntime:
    def test_apply_runtime_sets_log_level(self):
        original = logging.root.level
        try:
            apply_runtime({"log_level": "DEBUG"})
            assert logging.root.level == logging.DEBUG
        finally:
            logging.root.setLevel(original)

    def test_apply_runtime_unknown_level_no_crash(self):
        original = logging.root.level
        try:
            apply_runtime({"log_level": "NOTAVALIDLEVEL"})
            # should not raise, just silently ignore
        finally:
            logging.root.setLevel(original)

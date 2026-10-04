import asyncio

from breakfast import config as cfg_mod
from breakfast.web import server


def test_patch_config_never_logs_secret_values(tmp_path, caplog):
    config_path = tmp_path / "config.toml"
    cfg_mod.write(str(config_path), {})
    server.wire(None, None, config_path=str(config_path))
    try:
        with caplog.at_level("DEBUG"):
            res = asyncio.run(server.patch_config({
                "mqtt": {"password": "super-secret-value", "host": "10.0.0.5"},
            }))

        assert res["saved"] is True
        log_text = caplog.text
        assert "super-secret-value" not in log_text
        # Key names are fine to log — that's what makes the log line useful.
        assert "mqtt.password" in log_text
        assert "mqtt.host" in log_text
    finally:
        server.wire(None, None)


def test_the_timezone_is_null_until_one_is_configured(tmp_path):
    config_path = tmp_path / "config.toml"
    cfg_mod.write(str(config_path), {})
    server.wire(None, None, config_path=str(config_path))
    try:
        assert asyncio.run(server.get_config())["stats"]["timezone"] is None
        asyncio.run(server.patch_config({"stats": {"timezone": "Europe/Zurich"}}))
        assert asyncio.run(server.get_config())["stats"]["timezone"] == "Europe/Zurich"
    finally:
        server.wire(None, None)

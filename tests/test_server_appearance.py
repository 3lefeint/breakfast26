import asyncio

import pytest

from breakfast import config as cfg_mod
from breakfast.web import server


@pytest.fixture
def configure(tmp_path):
    path = tmp_path / "config.toml"

    def go(web=None):
        cfg_mod.write(str(path), {"web": web or {"port": 8080}})
        server.wire(None, None, config_path=str(path))
    yield go
    server.wire(None, None)


class TestAppearance:
    def test_the_defaults(self, configure):
        configure()
        assert asyncio.run(server.get_appearance()) == {
            "theme": "default", "accent_color": None, "aurora_animation": True,
            "aurora": {"base": None, "1": None, "2": None, "3": None},
            "palette": None, "streaks": True, "speed": 100, "intensity": 100, "blur": 100,
            "pause_idle": 0, "glass": 100, "bar": 92}

    def test_the_aurora_can_be_switched_off(self, configure):
        configure({"aurora_animation": False})
        assert asyncio.run(server.get_appearance())["aurora_animation"] is False

    def test_theme_accent_and_aurora_colors_come_from_the_config(self, configure):
        configure({"theme": "sunset", "accent_color": "#ff8800", "aurora_base": "#010203", "aurora_2": "#0a0b0c"})
        res = asyncio.run(server.get_appearance())
        assert res["theme"] == "sunset" and res["accent_color"] == "#ff8800"
        assert res["aurora"] == {"base": "#010203", "1": None, "2": "#0a0b0c", "3": None}

    def test_aurora_colors_are_stored_and_cleared_without_a_restart(self, configure):
        configure()
        res = asyncio.run(server.patch_config({"web": {"aurora_1": "#112233"}}))
        assert res == {"saved": True, "restart_required": []}
        assert asyncio.run(server.get_appearance())["aurora"]["1"] == "#112233"
        asyncio.run(server.patch_config({"web": {"aurora_1": None}}))
        assert asyncio.run(server.get_appearance())["aurora"]["1"] is None

    @pytest.mark.parametrize("bad", ["red", "#12", "#12345g", "url(x)", "#1234567"])
    def test_a_value_that_is_no_color_is_refused(self, configure, bad):
        configure()
        res = asyncio.run(server.patch_config({"web": {"aurora_3": bad}}))
        assert res["saved"] is False and "aurora_3" in res["error"]
        assert asyncio.run(server.get_appearance())["aurora"]["3"] is None

    def test_the_setting_is_part_of_the_config_and_applies_without_a_restart(self, configure):
        configure({"aurora_animation": False})
        assert asyncio.run(server.get_config())["web"]["aurora_animation"] is False
        res = asyncio.run(server.patch_config({"web": {"aurora_animation": True}}))
        assert res == {"saved": True, "restart_required": []}


class TestLook:
    def test_values_come_from_the_config(self, configure):
        configure({"aurora_palette": "ember", "aurora_streaks": False, "aurora_speed": 150, "aurora_intensity": 60,
                   "aurora_blur": 80, "aurora_pause_idle": 10, "glass_strength": 130, "bar_opacity": 70})
        res = asyncio.run(server.get_appearance())
        assert (res["palette"], res["streaks"], res["speed"], res["intensity"], res["blur"],
                res["pause_idle"], res["glass"], res["bar"]) == ("ember", False, 150, 60, 80, 10, 130, 70)

    def test_a_value_out_of_range_or_unknown_in_the_file_falls_back_to_the_default(self, configure):
        configure({"aurora_palette": "neon", "aurora_speed": 9999, "bar_opacity": "high"})
        res = asyncio.run(server.get_appearance())
        assert res["palette"] is None and res["speed"] == 100 and res["bar"] == 92

    def test_every_setting_applies_without_a_restart_and_a_default_can_be_removed(self, configure):
        configure()
        body = {"aurora_palette": "sakura", "aurora_streaks": False, "aurora_speed": 200, "aurora_intensity": 50,
                "aurora_blur": 120, "aurora_pause_idle": 5, "glass_strength": 150, "bar_opacity": 80}
        assert asyncio.run(server.patch_config({"web": body})) == {"saved": True, "restart_required": []}
        assert asyncio.run(server.get_appearance())["speed"] == 200
        asyncio.run(server.patch_config({"web": {key: None for key in body}}))
        res = asyncio.run(server.get_appearance())
        assert res["palette"] is None and res["streaks"] is True and res["speed"] == 100

    @pytest.mark.parametrize("key,bad", [
        ("aurora_speed", 24), ("aurora_speed", 301), ("aurora_speed", "fast"), ("aurora_speed", True),
        ("aurora_intensity", 29), ("aurora_blur", 201), ("glass_strength", 49), ("bar_opacity", 101),
        ("aurora_pause_idle", -1), ("aurora_pause_idle", 241), ("aurora_palette", "neon"), ("aurora_streaks", "yes")])
    def test_an_out_of_range_value_is_refused_and_not_stored(self, configure, key, bad):
        configure()
        res = asyncio.run(server.patch_config({"web": {key: bad}}))
        assert res["saved"] is False and key in res["error"]
        assert asyncio.run(server.get_config())["web"][key] != bad


class TestLanguage:
    def test_default_and_supported(self, configure):
        configure()
        assert asyncio.run(server.get_language()) == {"language": "en", "supported": ["en", "de"]}

    def test_german(self, configure):
        configure({"language": "de"})
        assert asyncio.run(server.get_language())["language"] == "de"

    def test_an_unknown_language_falls_back_to_english(self, configure):
        configure({"language": "klingon"})
        assert asyncio.run(server.get_language())["language"] == "en"

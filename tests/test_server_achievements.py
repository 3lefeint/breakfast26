from starlette.testclient import TestClient

from breakfast.achievements import INNER_BULL, Achievement, AchievementEngine
from breakfast.stats import StatsDB, StatsTracker
from breakfast.web import server


# Stand-ins for two real achievements, so the endpoint is tested without the full list.
DEFINITIONS = (
    Achievement("bullseye", "general", "easy", {"en": "Bullseye", "de": "Bullseye"},
                {"en": "Hit the inner bull.", "de": "Das innere Bull treffen."},
                check=lambda ctx: any(d in INNER_BULL for t in ctx.turns for d in t.darts)),
    Achievement("beast_mode", "easter_egg", "hidden", {"en": "Beast Mode", "de": "Beast Mode"},
                {"en": "Hit three S6 in one turn.", "de": "Drei S6 in einer Aufnahme treffen."},
                hidden=True, label="666",
                check=lambda ctx: any(t.darts == ("S6", "S6", "S6") for t in ctx.turns)),
)


def _get(name):
    return TestClient(server.app).get(f"/api/achievements/{name}").json()


def test_without_a_stats_database_the_list_is_empty():
    server.wire(None, None)
    assert _get("ana") == {"player": "ana", "achievements": []}


def test_without_an_engine_the_list_is_empty(tmp_path):
    server.wire(None, None, stats_tracker=StatsTracker(StatsDB(str(tmp_path / "s.db"))))
    try:
        assert _get("ana")["achievements"] == []
    finally:
        server.wire(None, None)


def test_lists_the_achievements_of_a_player(tmp_path):
    db = StatsDB(str(tmp_path / "s.db"))
    AchievementEngine(db, definitions=DEFINITIONS).attach()
    server.wire(None, None, stats_tracker=StatsTracker(db))
    try:
        db.open_match("m1", "X01", 501)
        db.insert_turn("m1", "ana", 1, 1, 501, 50, False, False, [("BULL", 50, 451)])
        db.insert_turn("m1", "bo", 1, 1, 501, 20, False, False, [("S20", 20, 481)])
        db.close_match("m1")
        body = _get("ana")
        assert body["player"] == "ana"
        by_id = {a["id"]: a for a in body["achievements"]}
        assert by_id["bullseye"]["tier"] == 1
        assert by_id["beast_mode"]["names"] is None
    finally:
        server.wire(None, None)

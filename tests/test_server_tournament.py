import pytest
from starlette.testclient import TestClient

from breakfast.elimination import EliminationController
from breakfast.state import GameState
from breakfast.stats import StatsDB, StatsTracker
from breakfast.tournament import TournamentController
from breakfast.web import server
from breakfast.x01_game import X01Controller
from tests.test_target_battle import FakeMqttPub, MISS, hit, play


@pytest.fixture(autouse=True)
def no_start_delay(monkeypatch):
    monkeypatch.setattr("breakfast.x01_game.START_CALLS_DELAY_S", 0)


@pytest.fixture
def client(tmp_path):
    db = StatsDB(str(tmp_path / "s.db"))
    tracker = StatsTracker(db)
    state = GameState()

    def emit(data):
        state.update(data)
        tracker.process(data)

    x01 = X01Controller(emit, stats_db=db, on_change=server.push)
    tour = TournamentController(x01, stats_db=db, on_change=server.push, next_delay=0)
    elim = EliminationController(FakeMqttPub(), "autodarts", stats_db=db)
    server.wire(state, elim, stats_tracker=tracker, x01_ctrl=x01, tournament_ctrl=tour)
    yield TestClient(server.app), x01, tour, elim, db
    server.wire(None, None)


START = {"seats": ["ana", "bo", "cy", None], "start": 2}


def win(x01, who):
    if x01.game.phase == "bull_off":
        for k in range(len(x01.game.order)):
            play(x01.game, hit(25, 1, x=0.2 + 0.1 * k, y=0.0))
    while x01.game.snapshot()["state"] == "playing":
        play(x01.game, hit(1, 2) if x01.game.snapshot()["current_player"] == who else MISS)


def test_the_draw_gives_every_player_a_seat_and_stores_nothing(client):
    c, x01, tour, *_ = client
    seats = c.post("/api/tournament/draw", json={"players": ["a", " b ", "c", "", "d", "e"]}).json()["seats"]
    assert sorted(s for s in seats if s) == ["a", "b", "c", "d", "e"] and len(seats) == 8
    assert not tour.running


def test_a_draw_of_one_player_is_an_error(client):
    c, *_ = client
    assert "at least 2" in c.post("/api/tournament/draw", json={"players": ["a"]}).json()["error"]


def test_a_tournament_starts_and_shows_up_in_the_state(client):
    c, x01, tour, *_ = client
    assert server._build_payload()["tournament"] == {"active": False}
    assert c.post("/api/tournament/start", json=START).json() == {"ok": True}
    snap = server._build_payload()["tournament"]
    assert snap["active"] and snap["phase"] == "match" and snap["config"]["start"] == 2
    assert [m["bye"] for m in snap["rounds"][0]] == [False, True]
    assert sorted(x01.game.order) == ["ana", "bo"] and server._build_payload()["x01"]["active"]


def test_a_setup_that_cannot_be_played_comes_back_as_an_error(client):
    c, *_ = client
    assert "power of two" in c.post("/api/tournament/start", json={"seats": ["a", "b", "c"]}).json()["error"]
    assert "bye cannot face a bye" in c.post("/api/tournament/start", json={"seats": ["a", "b", None, None]}).json()["error"]
    assert "start score" in c.post("/api/tournament/start", json={**START, "start": 1}).json()["error"]


def test_the_tournament_is_played_through_the_routes(client):
    c, x01, tour, elim, db = client
    c.post("/api/tournament/start", json=START)
    win(x01, "bo")
    assert server._build_payload()["tournament"]["pending"]["winner"] == "bo"
    assert c.post("/api/tournament/next").json() == {"ok": True}
    snap = server._build_payload()["tournament"]
    assert snap["current"] == {"round": 1, "index": 0} and sorted(x01.game.order) == ["bo", "cy"]
    win(x01, "cy")
    c.post("/api/tournament/next")
    snap = server._build_payload()["tournament"]
    assert snap["phase"] == "finished" and snap["winner"] == "cy"
    assert c.post("/api/tournament/close").json() == {"ok": True}
    assert server._build_payload()["tournament"] == {"active": False}
    history = c.get("/api/tournament/history").json()
    assert [(h["status"], h["winner"]) for h in history] == [("finished", "cy")]
    assert sorted(history[0]["players"]) == ["ana", "bo", "cy"]


def test_abort_ends_it_and_frees_the_board(client):
    c, x01, tour, elim, db = client
    c.post("/api/tournament/start", json=START)
    assert c.post("/api/tournament/abort").json() == {"ok": True}
    assert not tour.running and x01.game is None
    assert c.get("/api/tournament/history").json()[0]["status"] == "aborted"
    assert c.post("/api/tournament/abort").json() == {"error": "no tournament is running"}
    assert c.post("/api/elimination/start", json={"players": ["ana", "bo"]}).json() == {"ok": True}


def test_a_running_tournament_blocks_everything_else(client):
    c, x01, tour, elim, db = client
    c.post("/api/tournament/start", json=START)
    assert "tournament is already running" in c.post("/api/tournament/start", json=START).json()["error"]
    assert "tournament is running" in c.post("/api/x01/start", json={"players": ["a", "b"]}).json()["error"]
    assert "tournament is running" in c.post("/api/x01/stop").json()["error"]
    assert "tournament is running" in c.post("/api/elimination/start", json={"players": ["a", "b"]}).json()["error"]
    assert x01.game is not None


def test_a_game_that_runs_blocks_the_tournament(client):
    c, x01, tour, elim, db = client
    c.post("/api/elimination/start", json={"players": ["ana", "bo"]})
    assert "Elimination" in c.post("/api/tournament/start", json=START).json()["error"]
    c.post("/api/elimination/stop")
    c.post("/api/x01/start", json={"players": ["a", "b"], "bull_off": False})
    assert "X01 match is running" in c.post("/api/tournament/start", json=START).json()["error"]


def test_a_finished_match_that_is_left_over_does_not_block_a_tournament(client):
    c, x01, tour, elim, db = client
    c.post("/api/x01/start", json={"players": ["a", "b"], "bull_off": False, "start": 2})
    win(x01, x01.game.snapshot()["current_player"])
    assert c.post("/api/tournament/start", json=START).json() == {"ok": True}


def test_next_and_close_without_a_tournament_say_so(client):
    c, *_ = client
    assert c.post("/api/tournament/next").json() == {"error": "nothing to go on with"}
    assert c.post("/api/tournament/close").json() == {"error": "no finished tournament"}
    assert c.get("/api/tournament/history").json() == []


def test_the_bull_off_option_reaches_the_matches(client):
    c, x01, tour, *_ = client
    c.post("/api/tournament/start", json={**START, "bull_off": False})
    assert x01.game.phase == "playing" and server._build_payload()["tournament"]["config"]["bull_off"] is False


def test_the_bull_off_is_on_by_default(client):
    c, x01, tour, *_ = client
    c.post("/api/tournament/start", json=START)
    assert x01.game.phase == "bull_off"


def test_the_max_rounds_reach_the_matches(client):
    c, x01, tour, *_ = client
    c.post("/api/tournament/start", json={**START, "max_rounds": 15})
    assert x01.game.max_rounds == 15 and server._build_payload()["tournament"]["config"]["max_rounds"] == 15


def test_max_rounds_that_make_no_sense_are_refused(client):
    c, *_ = client
    assert "max rounds" in c.post("/api/tournament/start", json={**START, "max_rounds": 0}).json()["error"]


def test_a_bot_can_play_in_a_tournament(client):
    c, x01, tour, *_ = client
    x01.bots._spawn = lambda fn: None          # no bot plays during this test
    body = {**START, "seats": ["ana", "bot 3", "cy", "bot 5"], "bots": {"bot 3": 3, "bot 5": 5}}
    assert c.post("/api/tournament/start", json=body).json() == {"ok": True}
    assert tour.t["config"]["bots"] == {"bot 3": 3, "bot 5": 5}
    assert x01.game.bot_levels == {name: lv for name, lv in {"bot 3": 3, "bot 5": 5}.items() if name in x01.game.order}
    assert x01.bots.levels == x01.game.bot_levels


def test_a_tournament_of_bots_alone_is_refused(client):
    c, x01, tour, *_ = client
    body = {**START, "seats": ["bot 1", "bot 3", None, None], "bots": {"bot 1": 1, "bot 3": 3}}
    assert c.post("/api/tournament/start", json=body).json() == {"error": "at least one player has to be human"}
    assert not tour.running

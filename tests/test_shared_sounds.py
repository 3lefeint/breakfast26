"""Scenes and achievement sounds shared in the circle: two sites over one stand-in relay, and the scene routes that guard a copy.
The relay's own rules are tested in relay/test/circle_shared.test.ts."""

import base64
import hashlib

import pytest
from starlette.testclient import TestClient

from breakfast import achievement_sounds as ach_sounds
from breakfast import config as cfg_mod
from breakfast import scene_sounds
from breakfast.audio_engine import AudioEngine
from breakfast.circle_sync import CircleSync
from breakfast.locations import LocationError
from breakfast.scenes import SceneEngine
from breakfast.shared_sounds import SharedSounds
from breakfast.stats import StatsDB
from breakfast.web import server

MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 64


def mp3(tag: str) -> bytes:
    return MP3 + tag.encode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Relay:
    """One relay for several sites: sounds by hash, scenes and achievement sounds with a seq, as the real relay keeps them."""

    def __init__(self):
        self.sounds, self.scenes, self.achievements, self.seq = {}, {}, {}, 0
        self.calls = []
        self.broken = None           # a LocationError for the routes of sharing

    def site(self, site_id, name):
        return Site(self, site_id, name)


class Site:
    def __init__(self, relay, site_id, name):
        self.relay, self.id, self.name = relay, site_id, name

    def status(self):
        return {"registered": True, "id": self.id, "name": self.name}

    def _next(self):
        self.relay.seq += 1
        return self.relay.seq

    def call(self, method, path, body=None):
        r = self.relay
        r.calls.append((self.id, method, path.split("?")[0]))
        route = path.split("?")[0]
        if route == "/circle/state":
            return {"approved": True}
        if route == "/circle/config":
            return {"approved": True, "refetch": 0, "circle_players": [], "mappings": [], "profiles": [], "site_mappings": []}
        if route == "/circle/records":
            return {"records": [], "next": 0}
        if r.broken and (route.startswith("/circle/sounds") or route.startswith("/circle/scenes") or route.startswith("/circle/achievement-sounds")):
            raise r.broken
        if route.startswith("/circle/sounds/"):
            h = route.rsplit("/", 1)[1]
            if method == "PUT":
                data = base64.b64decode(body["data"])
                assert sha(data) == h
                r.sounds[h] = data
                return {"hash": h}
            if h not in r.sounds:
                raise LocationError("unknown sound", 404)
            return {"hash": h, "data": base64.b64encode(r.sounds[h]).decode()}
        if route.startswith("/circle/scenes/") and method == "PUT":
            key = (self.id, route.rsplit("/", 1)[1])
            for s in body.get("sounds", []):
                if s["hash"] not in r.sounds:
                    raise LocationError("upload the sounds first", 422)
            r.scenes.pop(key, None)
            r.scenes[key] = {"seq": self._next(), "scene_id": key[1], "origin": {"id": self.id, "name": self.name},
                             "name": body.get("name", ""), "graph": body.get("graph", {}), "sounds": body.get("sounds", []),
                             "deleted": bool(body.get("deleted"))}
            return {"seq": r.scenes[key]["seq"]}
        if route == "/circle/scenes":
            since = int(path.split("since=")[1].split("&")[0])
            rows = sorted((v for v in r.scenes.values() if v["seq"] > since and v["origin"]["id"] != self.id), key=lambda v: v["seq"])
            return {"scenes": rows, "next": rows[-1]["seq"] if rows else since}
        if route.startswith("/circle/achievement-sounds/") and method == "PUT":
            key = (self.id, route.rsplit("/", 1)[1])
            r.achievements.pop(key, None)
            r.achievements[key] = {"seq": self._next(), "achievement": key[1], "origin": {"id": self.id, "name": self.name},
                                   "files": body.get("files", []), "deleted": bool(body.get("deleted"))}
            return {}
        if route == "/circle/achievement-sounds":
            since = int(path.split("since=")[1].split("&")[0])
            rows = sorted((v for v in r.achievements.values() if v["seq"] > since and v["origin"]["id"] != self.id), key=lambda v: v["seq"])
            return {"sounds": rows, "next": rows[-1]["seq"] if rows else since}
        raise AssertionError(route)


class Node:
    """One installation: database, sound folders, scene engine, circle sync."""

    def __init__(self, tmp_path, relay, name):
        self.dir = tmp_path / name
        base = self.dir / "sounds"
        self.achievements, self.library = base / "achievements", base / "scenes"
        self.achievements.mkdir(parents=True)
        self.library.mkdir()
        self.audio = AudioEngine([str(base), str(self.achievements)], library_dirs=[str(self.library)])
        self.db = StatsDB(str(self.dir / "stats.db"))
        self.engine = SceneEngine(self.db, self.audio)
        self.config = self.dir / "config.toml"
        self.config.write_text("")
        self.shared = SharedSounds(self.db, self.config, engine=lambda: self.engine, audio=lambda: self.audio)
        self.relay = relay.site(f"loc-{name}", name.capitalize())
        self.sync = CircleSync(self.db, self.relay, self.config, "1.9.0", shared=self.shared)

    def library_file(self, name, data):
        (self.library / name).write_bytes(data)
        self.audio.files_changed()

    def scene(self, name, files=(), shared=True):
        nodes = [{"id": "t", "type": "trigger", "event": "x01.leg_won", "x": 0, "y": 0}]
        edges = []
        for i, f in enumerate(files):
            nodes.append({"id": f"s{i}", "type": "action", "kind": "sound", "files": [{"file": f, "weight": 1}], "x": 0, "y": 0})
            edges.append({"from": "t", "to": f"s{i}"})
        return self.engine.save(None, {"name": name, "enabled": True, "graph": {"nodes": nodes, "edges": edges}, "shared": shared})

    def copies(self):
        return [s for s in self.engine.scenes() if s.get("source")]


@pytest.fixture
def two(tmp_path):
    relay = Relay()
    return relay, Node(tmp_path, relay, "alpha"), Node(tmp_path, relay, "bravo")


def sounds_of(scene):
    return [e["file"] for n in scene["graph"]["nodes"] if n.get("kind") == "sound" for e in n["files"]]


class TestScenes:
    def test_a_shared_scene_arrives_as_a_read_only_copy_with_its_sounds(self, two):
        relay, a, b = two
        a.library_file("cheer.mp3", mp3("1"))
        a.scene("Cheer", ["cheer.mp3"])
        a.scene("Private", ["cheer.mp3"], shared=False)
        a.sync.run_once()
        b.sync.run_once()
        copies = b.copies()
        assert [c["name"] for c in copies] == ["Cheer"]
        assert copies[0]["source"] == {"id": "loc-alpha", "name": "Alpha"} and copies[0]["enabled"] and not copies[0]["default"]
        assert sounds_of(copies[0]) == ["cheer.mp3"] and (b.library / "cheer.mp3").read_bytes() == mp3("1")
        assert a.copies() == []

    def test_a_scene_that_is_not_shared_stays_here(self, two):
        relay, a, b = two
        a.scene("Private", shared=False)
        a.sync.run_once()
        assert relay.scenes == {}

    def test_a_change_updates_the_copy_and_keeps_its_switch(self, two):
        relay, a, b = two
        scene_id = a.scene("Cheer")
        a.sync.run_once()
        b.sync.run_once()
        copy = b.copies()[0]
        b.engine.save(copy["id"], {"name": copy["name"], "enabled": False, "graph": copy["graph"]})
        a.engine.save(scene_id, {"name": "Cheer 2", "enabled": True, "graph": a.engine.find(scene_id)["graph"]})
        a.sync.run_once()
        b.sync.run_once()
        copies = b.copies()
        assert len(copies) == 1 and copies[0]["name"] == "Cheer 2" and copies[0]["enabled"] is False

    def test_unsharing_or_deleting_removes_the_copies(self, two):
        relay, a, b = two
        first, second = a.scene("One"), a.scene("Two")
        a.sync.run_once()
        b.sync.run_once()
        assert len(b.copies()) == 2
        a.engine.save(first, {"name": "One", "enabled": True, "graph": a.engine.find(first)["graph"], "shared": False})
        a.engine.delete(second)
        a.sync.run_once()
        b.sync.run_once()
        assert b.copies() == []

    def test_an_unchanged_scene_is_not_sent_again(self, two):
        relay, a, b = two
        a.library_file("cheer.mp3", mp3("1"))
        a.scene("Cheer", ["cheer.mp3"])
        a.sync.run_once()
        a.sync.run_once()
        puts = [c for c in relay.calls if c[0] == "loc-alpha" and c[1] == "PUT" and c[2].startswith(("/circle/scenes/", "/circle/sounds/"))]
        assert len(puts) == 2

    def test_a_file_name_that_holds_other_bytes_here_gets_a_name_with_the_hash(self, two):
        relay, a, b = two
        a.library_file("cheer.mp3", mp3("from alpha"))
        b.library_file("cheer.mp3", mp3("my own"))
        a.scene("Cheer", ["cheer.mp3"])
        a.sync.run_once()
        b.sync.run_once()
        name = f"cheer-{sha(mp3('from alpha'))[:8]}.mp3"
        assert sounds_of(b.copies()[0]) == [name]
        assert (b.library / name).read_bytes() == mp3("from alpha") and (b.library / "cheer.mp3").read_bytes() == mp3("my own")

    def test_the_same_bytes_under_the_same_name_are_used_as_they_are(self, two):
        relay, a, b = two
        a.library_file("cheer.mp3", mp3("same"))
        b.library_file("cheer.mp3", mp3("same"))
        a.scene("Cheer", ["cheer.mp3"])
        a.sync.run_once()
        b.sync.run_once()
        assert sounds_of(b.copies()[0]) == ["cheer.mp3"] and len(list(b.library.iterdir())) == 1

    def test_a_sound_that_is_too_large_or_missing_is_left_out_and_marked(self, two):
        relay, a, b = two
        a.library_file("big.mp3", MP3 + b"\x00" * (2 * 1024 * 1024))
        a.scene("Cheer", ["big.mp3", "gone.mp3"])
        a.sync.run_once()
        assert relay.sounds == {}
        b.sync.run_once()
        copy = b.copies()[0]
        assert sounds_of(copy) == ["big.mp3", "gone.mp3"]
        assert set(b.shared.problems(copy["graph"]).values()) == {"sound"}

    def test_without_a_sound_directory_no_scene_is_taken_and_the_cursor_waits(self, two):
        relay, a, b = two
        a.library_file("cheer.mp3", mp3("1"))
        a.scene("Cheer", ["cheer.mp3"])
        a.sync.run_once()
        audio = b.audio
        b.shared._audio = lambda: None                       # no [audio] dir: no engine, no library
        status = b.sync.run_once()
        assert b.copies() == [] and status["error"] is None
        assert b.sync._load().get("scenes_cursor", 0) == 0
        b.shared._audio = lambda: audio                      # the directory is set later
        b.sync.run_once()
        assert sounds_of(b.copies()[0]) == ["cheer.mp3"] and (b.library / "cheer.mp3").exists()

    def test_a_relay_without_the_routes_does_not_stop_the_round(self, two):
        relay, a, b = two
        relay.broken = LocationError("not found", 404)
        a.scene("Cheer")
        status = a.sync.run_once()
        assert status["error"] is None and status["last_sync"]

    def test_an_unreachable_relay_is_tried_again_and_loses_nothing(self, two):
        relay, a, b = two
        a.library_file("cheer.mp3", mp3("1"))
        a.scene("Cheer", ["cheer.mp3"])
        a.sync.run_once()
        relay.broken = LocationError("the relay is not reachable")
        b.sync.run_once()
        assert b.copies() == []
        relay.broken = None
        b.sync.run_once()
        assert sounds_of(b.copies()[0]) == ["cheer.mp3"]

    def test_a_sound_the_relay_lost_is_sent_again(self, two):
        relay, a, b = two
        a.library_file("cheer.mp3", mp3("1"))
        a.scene("Cheer", ["cheer.mp3"])
        a.sync.run_once()
        relay.sounds.clear()
        relay.scenes.clear()
        a.sync._update(scenes_sent={})                  # a changed scene is sent again; the relay says the sound is missing
        a.sync.run_once()
        assert relay.scenes == {}
        a.sync.run_once()                               # the sound goes first this time
        assert relay.sounds and relay.scenes

    def test_the_names_a_copy_misses_are_marked(self, two):
        relay, a, b = two
        nodes = [{"id": "t", "type": "trigger", "event": "x01.leg_won"},
                 {"id": "p", "type": "condition", "kind": "player", "names": ["anna", "nobody"]},
                 {"id": "c", "type": "action", "kind": "call", "key": "no_such_key_here"}]
        b.db.upsert_player("anna")
        problems = b.shared.problems({"nodes": nodes, "edges": []})
        assert problems == {"p": "player", "c": "call"}


class TestAchievementSounds:
    def assign(self, node, achievement, *files):
        for f in files:
            (node.achievements / f).write_bytes(mp3(f))
        node.audio.files_changed()
        ach_sounds.set_assignment(node.config, achievement, list(files))

    def test_only_a_site_that_switched_it_on_publishes(self, two):
        relay, a, b = two
        self.assign(a, "ton_up", "fanfare.mp3")
        a.sync.run_once()
        assert relay.achievements == {}
        a.sync.set_share_achievement_sounds(True)
        a.sync.run_once()
        b.sync.run_once()
        assert b.shared.achievement_files("ton_up") == ["fanfare.mp3"]
        assert b.shared.achievement_shared("ton_up")["origin"] == "Alpha"

    def test_an_own_sound_is_not_replaced_and_taking_it_back_removes_the_shared_one(self, two):
        relay, a, b = two
        self.assign(a, "ton_up", "fanfare.mp3")
        a.sync.set_share_achievement_sounds(True)
        a.sync.run_once()
        b.sync.run_once()
        assert b.shared.achievement_files("ton_up") == ["fanfare.mp3"]
        # the own assignment is a file of its own: the server prefers it (see TestRoutes); here the switch off
        a.sync.set_share_achievement_sounds(False)
        a.sync.run_once()
        b.sync.run_once()
        assert b.shared.achievement_files("ton_up") == []

    def test_the_newest_of_several_authors_plays(self, two, tmp_path):
        relay, a, b = two
        c = Node(tmp_path, relay, "charlie")
        self.assign(a, "ton_up", "a.mp3")
        self.assign(c, "ton_up", "c.mp3")
        for n in (a, c):
            n.sync.set_share_achievement_sounds(True)
        a.sync.run_once()
        c.sync.run_once()
        b.sync.run_once()
        assert b.shared.achievement_shared("ton_up")["origin"] == "Charlie"
        c.sync.set_share_achievement_sounds(False)
        c.sync.run_once()
        b.sync.run_once()
        assert b.shared.achievement_shared("ton_up")["origin"] == "Alpha"

    def test_without_a_sound_directory_the_achievement_sounds_wait(self, two):
        relay, a, b = two
        self.assign(a, "ton_up", "fanfare.mp3")
        a.sync.set_share_achievement_sounds(True)
        a.sync.run_once()
        audio = b.audio
        b.shared._audio = lambda: None
        b.sync.run_once()
        assert b.sync._load().get("achievements_cursor", 0) == 0
        b.shared._audio = lambda: audio
        b.sync.run_once()
        assert b.shared.achievement_files("ton_up") == ["fanfare.mp3"]

    def test_a_file_that_is_gone_is_not_offered(self, two):
        relay, a, b = two
        self.assign(a, "ton_up", "fanfare.mp3")
        a.sync.set_share_achievement_sounds(True)
        a.sync.run_once()
        b.sync.run_once()
        (b.achievements / "fanfare.mp3").unlink()
        b.audio.files_changed()
        assert b.shared.achievement_files("ton_up") == []


class TestStorage:
    def test_a_database_from_before_sharing_is_migrated(self, tmp_path):
        import sqlite3
        path = tmp_path / "old.db"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE scenes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,"
                     " graph TEXT NOT NULL, slug TEXT, position INTEGER NOT NULL DEFAULT 0)")
        conn.execute("INSERT INTO scenes (name, graph) VALUES ('Old', '{\"nodes\": [], \"edges\": []}')")
        conn.commit()
        conn.close()
        db = StatsDB(str(path))
        row = db.list_scenes()[0]
        assert row["name"] == "Old" and row["shared"] is False and row["source"] is None and row["share_id"] is None

    def test_a_shared_scene_gets_one_id_that_stays(self, tmp_path):
        db = StatsDB(str(tmp_path / "s.db"))
        data = {"name": "A", "enabled": True, "graph": {"nodes": [], "edges": []}}
        scene_id = db.save_scene(None, data)
        assert db.list_scenes()[0]["share_id"] is None
        db.save_scene(scene_id, {**data, "shared": True})
        share_id = db.list_scenes()[0]["share_id"]
        assert share_id and db.list_scenes()[0]["shared"]
        db.save_scene(scene_id, {**data, "shared": False})
        assert db.list_scenes()[0]["share_id"] == share_id and not db.list_scenes()[0]["shared"]
        db.save_scene(scene_id, data)               # no key: unchanged
        db.save_scene(scene_id, {**data, "shared": True})
        assert db.list_scenes()[0]["share_id"] == share_id


class TestRoutes:
    @pytest.fixture
    def client(self, two, monkeypatch):
        relay, a, b = two
        a.library_file("cheer.mp3", mp3("1"))
        a.scene("Cheer", ["cheer.mp3"])
        a.sync.run_once()
        b.sync.run_once()
        monkeypatch.setattr(server, "_scene_engine", b.engine)
        monkeypatch.setattr(server, "_shared", b.shared)
        monkeypatch.setattr(server, "_circle", b.sync)
        monkeypatch.setattr(server, "_audio_engine", b.audio)
        monkeypatch.setattr(server, "_config_path", str(b.config))
        return TestClient(server.app), b

    def test_a_copy_is_listed_with_its_author_and_a_write_changes_only_the_switch(self, client):
        c, b = client
        scenes = c.get("/api/scenes").json()["scenes"]
        copy = next(s for s in scenes if s.get("source"))
        assert copy["source"]["name"] == "Alpha" and copy["problems"] == {}
        res = c.put(f"/api/scenes/{copy['id']}", json={"name": "Renamed", "enabled": False, "graph": {"nodes": [], "edges": []}, "shared": True}).json()
        assert res["ok"]
        after = b.engine.find(copy["id"])
        assert after["name"] == "Cheer" and after["enabled"] is False and after["graph"] == copy["graph"] and not after["shared"]

    def test_edit_a_copy_makes_a_scene_of_your_own_and_leaves_the_copy(self, client):
        c, b = client
        copy = b.copies()[0]
        made = c.post(f"/api/scenes/{copy['id']}/copy").json()
        assert made["ok"]
        own = b.engine.find(made["id"])
        assert own["name"] == "Cheer (copy)" and own["source"] is None and not own["shared"] and own["graph"] == copy["graph"]
        assert len(b.copies()) == 1

    def test_the_switch_of_a_scene_is_set_through_the_body(self, client):
        c, b = client
        made = c.post("/api/scenes", json={"name": "Mine", "enabled": True, "graph": {"nodes": [], "edges": []}, "shared": True}).json()
        assert b.engine.find(made["id"])["shared"] is True
        c.put(f"/api/scenes/{made['id']}", json={"name": "Mine", "enabled": False, "graph": {"nodes": [], "edges": []}})
        assert b.engine.find(made["id"])["shared"] is True            # no key: unchanged
        c.put(f"/api/scenes/{made['id']}", json={"name": "Mine", "enabled": False, "graph": {"nodes": [], "edges": []}, "shared": False})
        assert b.engine.find(made["id"])["shared"] is False

    def test_a_default_scene_cannot_be_shared(self, client):
        c, b = client
        slug = next(s["id"] for s in b.engine.scenes() if s["default"])
        c.put(f"/api/scenes/{slug}", json={"name": "x", "enabled": True, "graph": b.engine.find(slug)["graph"], "shared": True})
        assert not any(r["shared"] for r in b.db.list_scenes() if r["slug"])

    def test_the_circle_switch_for_achievement_sounds(self, client):
        c, b = client
        assert c.post("/api/circle/share-achievement-sounds", json={"enabled": True}).json()["share_achievement_sounds"] is True
        assert c.post("/api/circle/share-achievement-sounds", json={"enabled": False}).json()["share_achievement_sounds"] is False

    def test_a_shared_achievement_sound_plays_only_without_an_own_one(self, client):
        c, b = client
        relay = b.relay.relay
        (b.achievements / "x.mp3").write_bytes(mp3("x"))
        b.audio.files_changed()
        data = mp3("shared")
        relay.sounds[sha(data)] = data
        relay.achievements[("loc-alpha", "ton_up")] = {"seq": 99, "achievement": "ton_up", "origin": {"id": "loc-alpha", "name": "Alpha"},
                                                       "files": [{"file": "shared.mp3", "hash": sha(data)}], "deleted": False}
        b.sync.run_once()
        assert server.assigned_achievement_sounds("ton_up") == ["shared.mp3"]
        ach_sounds.set_assignment(b.config, "ton_up", ["x.mp3"])
        assert server.assigned_achievement_sounds("ton_up") == ["x.mp3"]
        ach_sounds.set_assignment(b.config, "ton_up", [])
        (b.achievements / "achievement_ton_up.mp3").write_bytes(mp3("id"))
        b.audio.files_changed()
        b.audio.invalidate("achievement_ton_up")
        assert server.assigned_achievement_sounds("ton_up") == []        # a file named for the achievement is an own sound

    def test_a_shared_sound_is_listed_and_can_be_taken_over(self, client):
        c, b = client
        relay = b.relay.relay
        data = mp3("shared")
        relay.sounds[sha(data)] = data
        relay.achievements[("loc-alpha", "ton_up")] = {"seq": 99, "achievement": "ton_up", "origin": {"id": "loc-alpha", "name": "Alpha"},
                                                       "files": [{"file": "shared.mp3", "hash": sha(data)}], "deleted": False}
        b.sync.run_once()
        server._dev_unlocked = True
        try:
            row = next(a for a in c.get("/api/admin/achievement-sounds").json()["achievements"] if a["id"] == "ton_up")
            assert row["shared"] == {"origin": "Alpha", "files": ["shared.mp3"]} and row["plays_now"]["source"] == "circle"
            assert c.post("/api/admin/achievement-sounds/ton_up/adopt").json()["assigned"] == ["shared.mp3"]
            assert ach_sounds.assignments(cfg_mod.load(b.config))["ton_up"] == ["shared.mp3"]
            row = next(a for a in c.get("/api/admin/achievement-sounds").json()["achievements"] if a["id"] == "ton_up")
            assert row["assigned"] == ["shared.mp3"] and not row.get("shared") and row["plays_now"]["source"] == "assigned"
            assert "own already" in c.post("/api/admin/achievement-sounds/ton_up/adopt").json()["error"]
            assert "no shared" in c.post("/api/admin/achievement-sounds/bullseye/adopt").json()["error"]
            assert "unknown" in c.post("/api/admin/achievement-sounds/nope/adopt").json()["error"]
        finally:
            server._dev_unlocked = False

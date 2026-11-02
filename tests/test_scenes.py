import contextlib

import pytest
from starlette.testclient import TestClient

from breakfast import scene_sounds
from breakfast import scenes as sc
from breakfast import scenes_default, sound_edit
from breakfast.audio_engine import AudioEngine
from breakfast.elimination import EliminationGame
from breakfast.stats import StatsDB
from breakfast.web import server

MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 64


class FakeAudio:
    def __init__(self, files=("boom.mp3",)):
        self.files = set(files)
        self.played = []
        self.calls = []

    def play_file(self, filename, volume=1.0, channel="voice"):
        if filename not in self.files:
            return False
        self.played.append((filename, volume, channel))
        return True

    def play(self, name, **kwargs):
        self.calls.append(name)
        return True

    def batch(self):
        return contextlib.nullcontext()


def graph(*nodes, edges=()):
    return {"nodes": list(nodes), "edges": [{"from": a, "to": b} for a, b in edges]}


def trigger(event, node_id="t"):
    return {"id": node_id, "type": "trigger", "event": event}


def sound(node_id="s", file="boom.mp3", **extra):
    files = [{"file": file, "weight": 1}] if file else []
    return {"id": node_id, "type": "action", "kind": "sound", "files": files, **extra}


def condition(node_id, kind, **extra):
    return {"id": node_id, "type": "condition", "kind": kind, **extra}


def mine(engine):
    """The scenes of the user: the default scenes come with every engine."""
    return [s for s in engine.scenes() if not s["default"]]


def engine_with(scene_graph, audio=None, overlays=None, enabled=True):
    store = sc.MemoryScenes()
    store.save_scene(None, sc.clean_scene({"name": "x", "enabled": enabled, "graph": scene_graph}))
    return sc.SceneEngine(store, audio=audio, overlay=overlays.append if overlays is not None else None)


class TestCleanGraph:
    def test_unknown_nodes_and_edges_to_missing_nodes_are_dropped(self):
        cleaned = sc.clean_graph({
            "nodes": [trigger("x01.bust"), {"id": "bad id", "type": "trigger", "event": "x01.bust"},
                      {"id": "q", "type": "action", "kind": "explode"}, {"id": "t", "type": "action", "kind": "delay"}],
            "edges": [{"from": "t", "to": "t"}, {"from": "t", "to": "nope"}, {"from": "t", "to": "t"}]})
        assert [n["id"] for n in cleaned["nodes"]] == ["t"]
        assert cleaned["edges"] == []

    def test_values_are_limited_and_defaults_filled(self):
        node = sc.clean_node(sound(volume=7, channel="bogus"))
        assert node["volume"] == sc.MAX_VOLUME and node["channel"] == "ambient" and node["replace"] is False
        assert sc.clean_node(condition("c", "chance", percent=500))["percent"] == 100
        assert sc.clean_node({"id": "d", "type": "action", "kind": "delay", "seconds": 999})["seconds"] == sc.MAX_DELAY_S
        assert sc.clean_node(condition("c", "compare", op="~", value="x")) == {
            "id": "c", "x": 0, "y": 0, "type": "condition", "kind": "compare", "field": "score", "op": ">=", "value": 0}

    def test_player_names_come_as_a_list_or_a_comma_text(self):
        assert sc.clean_node(condition("c", "player", names="Anna, ben ,"))["names"] == ["Anna", "ben"]

    def test_a_scene_without_a_name_gets_one(self):
        assert sc.clean_scene({})["name"] == "Scene"


class TestEngine:
    def test_a_sound_after_a_trigger_plays_for_that_event_only(self):
        audio = FakeAudio()
        engine = engine_with(graph(trigger("x01.bust"), sound(volume=0.5, channel="voice"), edges=[("t", "s")]), audio)
        assert engine.fire("x01.leg_won", {"player": "anna"}) is False and audio.played == []
        engine.fire("x01.bust", {"player": "anna"})
        assert audio.played == [("boom.mp3", 0.5, "voice")]

    def test_a_disabled_scene_does_nothing(self):
        audio = FakeAudio()
        engine = engine_with(graph(trigger("x01.bust"), sound(), edges=[("t", "s")]), audio, enabled=False)
        engine.fire("x01.bust", {})
        assert audio.played == []

    @pytest.mark.parametrize("score,played", [(139, 0), (140, 1), (180, 1)])
    def test_a_compare_condition_lets_the_flow_pass(self, score, played):
        audio = FakeAudio()
        engine = engine_with(graph(
            trigger("x01.turn_scored"), condition("c", "compare", field="score", op=">=", value=140), sound(),
            edges=[("t", "c"), ("c", "s")]), audio)
        engine.fire("x01.turn_scored", {"player": "anna", "score": score})
        assert len(audio.played) == played

    def test_a_compare_on_a_fact_the_event_does_not_have_stops_the_flow(self):
        audio = FakeAudio()
        engine = engine_with(graph(trigger("x01.bust"), condition("c", "compare", field="score", op=">=", value=0),
                                   sound(), edges=[("t", "c"), ("c", "s")]), audio)
        engine.fire("x01.bust", {"player": "anna"})
        assert audio.played == []

    def test_a_chance_condition(self, monkeypatch):
        audio = FakeAudio()
        engine = engine_with(graph(trigger("x01.bust"), condition("c", "chance", percent=10), sound(),
                                   edges=[("t", "c"), ("c", "s")]), audio)
        monkeypatch.setattr(sc.random, "random", lambda: 0.099)
        engine.fire("x01.bust", {})
        monkeypatch.setattr(sc.random, "random", lambda: 0.1)
        engine.fire("x01.bust", {})
        assert len(audio.played) == 1

    def test_a_player_condition_ignores_case(self):
        audio = FakeAudio()
        engine = engine_with(graph(trigger("x01.bust"), condition("c", "player", names=["Anna"]), sound(),
                                   edges=[("t", "c"), ("c", "s")]), audio)
        engine.fire("x01.bust", {"player": "ben"})
        engine.fire("x01.bust", {"player": "anna"})
        assert len(audio.played) == 1

    def test_one_node_may_lead_to_several_and_the_overlay_text_has_the_facts(self):
        audio, overlays = FakeAudio(), []
        engine = engine_with(graph(
            trigger("x01.turn_scored"), sound(),
            {"id": "o", "type": "action", "kind": "overlay", "animation": "banner", "text": "{player}: {score}!"},
            edges=[("t", "s"), ("t", "o")]), audio, overlays)
        engine.fire("x01.turn_scored", {"player": "anna", "score": 180})
        assert len(audio.played) == 1
        assert overlays == [{"type": "scene_overlay", "animation": "banner", "text": "anna: 180!", "seconds": 4}]

    def test_replace_is_reported_only_for_a_sound_that_played(self):
        audio = FakeAudio()
        replacing = graph(trigger("x01.bust"), sound(replace=True), edges=[("t", "s")])
        assert engine_with(replacing, audio).fire("x01.bust", {}) is True
        assert engine_with(graph(trigger("x01.bust"), sound(), edges=[("t", "s")]), audio).fire("x01.bust", {}) is False
        missing = graph(trigger("x01.bust"), sound(file="gone.mp3", replace=True), edges=[("t", "s")])
        assert engine_with(missing, audio).fire("x01.bust", {}) is False

    def test_a_delay_runs_the_rest_on_a_timer_and_cannot_replace(self, monkeypatch):
        started = []

        class FakeTimer:
            def __init__(self, seconds, function, args):
                started.append((seconds, function, args))
                self.daemon = False

            def start(self):
                pass

        monkeypatch.setattr(sc.threading, "Timer", FakeTimer)
        audio = FakeAudio()
        engine = engine_with(graph(
            trigger("x01.bust"), {"id": "d", "type": "action", "kind": "delay", "seconds": 2}, sound(replace=True),
            edges=[("t", "d"), ("d", "s")]), audio)
        assert engine.fire("x01.bust", {}) is False and audio.played == []
        seconds, function, args = started[0]
        assert seconds == 2
        function(*args)
        assert len(audio.played) == 1

    def test_a_loop_does_not_run_forever(self):
        audio = FakeAudio()
        engine = engine_with(graph(trigger("x01.bust"), sound("a"), sound("b"),
                                   edges=[("t", "a"), ("a", "b"), ("b", "a")]), audio)
        engine.fire("x01.bust", {})
        assert len(audio.played) == 2

    def test_the_test_run_ignores_the_switch_and_traces_the_flow(self):
        audio = FakeAudio()
        engine = engine_with(graph(trigger("x01.bust"), sound(), edges=[("t", "s")]), audio, enabled=False)
        scene_id = mine(engine)[0]["id"]
        trace = []
        engine.fire("x01.bust", {}, only=scene_id, trace=trace)
        assert trace == [{"node": "s", "result": "done", "file": "boom.mp3"}] and len(audio.played) == 1

    def test_the_trace_says_why_a_step_was_skipped(self):
        class Silent(FakeAudio):
            def play(self, name, **kwargs):
                return name == "heard"

        def run(node, audio=None, ctx=None, ambient=None):
            engine = engine_with(graph(trigger("x01.bust"), node, edges=[("t", "s")]), audio or Silent())
            if ambient is not None:
                engine.ambient_volume = ambient
            trace = []
            engine.fire("x01.bust", ctx or {}, only=mine(engine)[0]["id"], trace=trace)
            return trace[0]

        call = lambda key: {"id": "s", "type": "action", "kind": "call", "key": key}
        assert run(sound(file="")) == {"node": "s", "result": "skipped", "why": "no_file"}
        assert run(sound(file="gone.mp3"))["why"] == "file_missing"
        assert run(sound(), audio=Silent(files=("boom.mp3",)))["result"] == "done"
        assert run(call(""))["why"] == "no_key"
        assert run(call("nothing"))["why"] == "no_sound"
        assert run(call("require_{remaining}"))["why"] == "missing_fact:remaining"
        assert run(call("ambient_x"), ambient=0)["why"] == "ambient_muted"
        assert run(call("heard"))["result"] == "done"
        assert run({"id": "s", "type": "action", "kind": "overlay", "text": "x"})["why"] == "no_display"

    def test_an_error_does_not_reach_the_game(self):
        class Broken:
            def list_scenes(self):
                raise RuntimeError("boom")

        assert sc.SceneEngine(Broken()).fire("x01.bust", {}) is False


def snapshot(**cur):
    return {"game_mode": "X01", "active_player_name": "anna", "current_leg": 3, "current": cur}


class TestWeightedSounds:
    @staticmethod
    def weighted(*entries, **extra):
        return {"id": "s", "type": "action", "kind": "sound", "files": [{"file": f, "weight": w} for f, w in entries], **extra}

    @staticmethod
    def fire(node, audio, times=1, trace=None):
        engine = engine_with(graph(trigger("x01.bust"), node, edges=[("t", "s")]), audio)
        for _ in range(times):
            engine.fire("x01.bust", {}, only=mine(engine)[0]["id"] if trace is not None else None, trace=trace)
        return engine

    def test_a_single_file_of_an_older_step_is_one_entry_of_weight_one(self):
        old = {"id": "s", "type": "action", "kind": "sound", "file": "boom.mp3", "volume": 1, "channel": "voice"}
        assert sc.clean_node(old)["files"] == [{"file": "boom.mp3", "weight": 1}] and "file" not in sc.clean_node(old)
        stored = {"nodes": [trigger("x01.bust"), old], "edges": [{"from": "t", "to": "s"}]}
        store = sc.MemoryScenes()
        store.save_scene(None, {"name": "old", "enabled": True, "graph": stored})
        engine = sc.SceneEngine(store, audio=FakeAudio())
        assert mine(engine)[0]["graph"]["nodes"][1]["files"] == [{"file": "boom.mp3", "weight": 1}]
        assert sc.sound_files(stored) == ["boom.mp3"]
        engine.fire("x01.bust", {})
        assert engine.audio.played == [("boom.mp3", 1, "voice")]

    def test_the_entries_are_cleaned(self):
        node = sc.clean_node(self.weighted(("a.mp3", 30), ("b.mp3", 0), ("a.mp3", 5), ("", 9), ("c.mp3", 500)))
        assert node["files"] == [{"file": "a.mp3", "weight": 35}, {"file": "b.mp3", "weight": 1}, {"file": "c.mp3", "weight": 100}]
        many = sc.clean_node(self.weighted(*[(f"f{i}.mp3", 1) for i in range(40)]))
        assert len(many["files"]) == sc.MAX_SOUND_FILES

    def test_the_pick_follows_the_weights(self):
        import random
        random.seed(7)
        audio = FakeAudio(files=("a.mp3", "b.mp3"))
        self.fire(self.weighted(("a.mp3", 75), ("b.mp3", 25)), audio, times=2000)
        a = sum(1 for p in audio.played if p[0] == "a.mp3")
        assert len(audio.played) == 2000 and 1400 < a < 1600

    def test_volume_and_channel_are_those_of_the_step(self):
        audio = FakeAudio(files=("a.mp3", "b.mp3"))
        self.fire(self.weighted(("a.mp3", 1), ("b.mp3", 1), volume=0.5, channel="voice"), audio, times=20)
        assert {(p[1], p[2]) for p in audio.played} == {(0.5, "voice")}

    def test_a_missing_file_is_left_out_and_the_others_share_its_weight(self):
        audio = FakeAudio(files=("a.mp3", "b.mp3"))
        trace = []
        self.fire(self.weighted(("gone.mp3", 90), ("a.mp3", 5), ("b.mp3", 5)), audio, times=200, trace=trace)
        assert len(audio.played) == 200 and {p[0] for p in audio.played} == {"a.mp3", "b.mp3"}
        assert all(step["result"] == "done" and step["file"] in ("a.mp3", "b.mp3") for step in trace)
        assert any(step.get("missing") == ["gone.mp3"] for step in trace)

    def test_a_step_without_any_file_in_the_library_is_skipped_and_names_them(self):
        audio = FakeAudio(files=())
        trace = []
        self.fire(self.weighted(("x.mp3", 1), ("y.mp3", 3)), audio, trace=trace)
        assert trace[0]["result"] == "skipped" and trace[0]["why"] == "file_missing"
        assert sorted(trace[0]["missing"]) == ["x.mp3", "y.mp3"] and "file" not in trace[0]

    def test_replace_counts_when_a_file_played(self):
        audio = FakeAudio(files=("a.mp3",))
        engine = engine_with(graph(trigger("x01.bust"), self.weighted(("gone.mp3", 50), ("a.mp3", 1), replace=True),
                                   edges=[("t", "s")]), audio)
        assert engine.fire("x01.bust", {}) is True
        assert self.fire(self.weighted(("gone.mp3", 1), replace=True), FakeAudio(files=())).fire("x01.bust", {}) is False

    def test_a_rename_follows_into_every_entry_and_merges_a_clash(self):
        class Lib:
            def __init__(self, folder):
                self.library_dirs = [folder]

            def files_changed(self):
                pass

        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.mp3").write_bytes(MP3)
            store = sc.MemoryScenes()
            store.save_scene(None, {"name": "x", "enabled": True, "graph": {
                "nodes": [trigger("x01.bust"), {"id": "s", "type": "action", "kind": "sound", "file": "a.mp3", "volume": 1},
                          self.weighted(("a.mp3", 3), ("other.mp3", 2), ("new.mp3", 4)) | {"id": "w"}],
                "edges": []}})
            engine = sc.SceneEngine(store)
            assert scene_sounds.rename_file(Lib(tmp), engine, "a.mp3", "new.mp3") is None
            nodes = {n["id"]: n for n in store.list_scenes()[0]["graph"]["nodes"] if n["type"] == "action"}
            assert nodes["s"]["files"] == [{"file": "new.mp3", "weight": 1}]
            assert nodes["w"]["files"] == [{"file": "new.mp3", "weight": 7}, {"file": "other.mp3", "weight": 2}]


class TestSwitch:
    @staticmethod
    def switch(field="player", mode="values", outputs=()):
        return {"id": "w", "type": "condition", "kind": "switch", "field": field, "mode": mode, "outputs": list(outputs)}

    @staticmethod
    def flow(switch, audio, targets):
        """A scene: trigger -> switch -> one sound per (output id, file) in *targets*."""
        nodes, edges = [trigger("x01.bust"), switch], [{"from": "t", "to": "w"}]
        for i, (match, name) in enumerate(targets):
            nodes.append(sound(f"s{i}", name))
            edges.append({"from": "w", "to": f"s{i}", "match": match})
        store = sc.MemoryScenes()
        store.save_scene(None, sc.clean_scene({"name": "x", "graph": {"nodes": nodes, "edges": edges}}))
        return sc.SceneEngine(store, audio=audio)

    def played(self, engine, audio, ctx):
        audio.played.clear()
        trace = []
        engine.fire("x01.bust", ctx, only=mine(engine)[0]["id"], trace=trace)
        return [p[0] for p in audio.played], trace

    def test_values_take_the_output_that_names_the_value_without_regard_to_case(self):
        audio = FakeAudio(files=("a.mp3", "b.mp3", "c.mp3"))
        outputs = [{"id": "o1", "values": ["Anna", "ben"]}, {"id": "o2", "values": ["carl"]}]
        engine = self.flow(self.switch(outputs=outputs), audio, [("o1", "a.mp3"), ("o2", "b.mp3"), ("else", "c.mp3")])
        assert self.played(engine, audio, {"player": "BEN"})[0] == ["a.mp3"]
        assert self.played(engine, audio, {"player": "carl"})[0] == ["b.mp3"]
        assert self.played(engine, audio, {"player": "tom"})[0] == ["c.mp3"]

    def test_a_value_sits_on_one_output_only(self):
        node = sc.clean_node(self.switch(outputs=[{"id": "o1", "values": "anna, Ben"}, {"id": "o2", "values": ["BEN", "carl"]}]))
        assert [o["values"] for o in node["outputs"]] == [["anna", "Ben"], ["carl"]]

    def test_a_number_is_a_value_too(self):
        audio = FakeAudio(files=("a.mp3", "c.mp3"))
        engine = self.flow(self.switch("tier", outputs=[{"id": "o1", "values": ["2"]}]), audio, [("o1", "a.mp3"), ("else", "c.mp3")])
        assert self.played(engine, audio, {"tier": 2})[0] == ["a.mp3"]
        assert self.played(engine, audio, {"tier": 2.0})[0] == ["a.mp3"]
        assert self.played(engine, audio, {"tier": 3})[0] == ["c.mp3"]

    def test_bands_end_at_their_limit_and_the_first_match_wins(self):
        audio = FakeAudio(files=("a.mp3", "b.mp3", "c.mp3", "d.mp3"))
        outputs = [{"id": "o2", "limit": 15}, {"id": "o1", "limit": 10}]
        node = sc.clean_node(self.switch("score", "bands", outputs))
        assert [o["id"] for o in node["outputs"]] == ["o1", "o2"]          # ascending, so no gap and no overlap
        engine = self.flow(node, audio, [("o1", "a.mp3"), ("o2", "b.mp3"), ("else", "c.mp3")])
        assert self.played(engine, audio, {"score": 0})[0] == ["a.mp3"]
        assert self.played(engine, audio, {"score": 10})[0] == ["a.mp3"]
        assert self.played(engine, audio, {"score": 10.5})[0] == ["b.mp3"]
        assert self.played(engine, audio, {"score": 15})[0] == ["b.mp3"]
        assert self.played(engine, audio, {"score": 16})[0] == ["c.mp3"]

    def test_a_missing_fact_takes_otherwise_and_the_trace_names_it(self):
        audio = FakeAudio(files=("a.mp3", "c.mp3"))
        engine = self.flow(self.switch("score", "bands", [{"id": "o1", "limit": 10}]), audio, [("o1", "a.mp3"), ("else", "c.mp3")])
        files, trace = self.played(engine, audio, {})
        assert files == ["c.mp3"] and trace[0] == {"node": "w", "result": "pass", "why": "missing_fact:score", "output": "else"}
        assert self.played(engine, audio, {"score": "high"})[1][0]["why"] == "not_a_number"

    def test_an_output_without_a_connection_does_nothing_and_the_trace_says_so(self):
        audio = FakeAudio(files=("c.mp3",))
        engine = self.flow(self.switch(outputs=[{"id": "o1", "values": ["anna"]}]), audio, [("else", "c.mp3")])
        files, trace = self.played(engine, audio, {"player": "anna"})
        assert files == [] and trace == [{"node": "w", "result": "stop", "why": "no_output", "output": "o1"}]

    def test_several_steps_can_hang_on_one_output(self):
        audio = FakeAudio(files=("a.mp3", "b.mp3"))
        engine = self.flow(self.switch(outputs=[{"id": "o1", "values": ["anna"]}]), audio, [("o1", "a.mp3"), ("o1", "b.mp3")])
        assert self.played(engine, audio, {"player": "anna"})[0] == ["a.mp3", "b.mp3"]

    def test_the_edges_of_a_switch_carry_a_known_output(self):
        graph = sc.clean_graph({"nodes": [trigger("x01.bust"), self.switch(outputs=[{"id": "o1", "values": ["a"]}]), sound("s1"), sound("s2"), sound("s3")],
                                "edges": [{"from": "w", "to": "s1", "match": "o1", "branch": "no"}, {"from": "w", "to": "s2", "match": "nope"},
                                          {"from": "w", "to": "s3"}, {"from": "t", "to": "w", "match": "o1"}]})
        assert graph["edges"] == [{"from": "w", "to": "s1", "match": "o1"}, {"from": "t", "to": "w"}]

    def test_the_outputs_are_limited_and_cleaned(self):
        many = [{"id": f"o{i}", "values": [f"v{i}"]} for i in range(30)]
        assert len(sc.clean_node(self.switch(outputs=many))["outputs"]) == sc.MAX_SWITCH_OUTPUTS
        bad = [{"id": "else", "values": ["x"]}, {"id": "bad id"}, {"id": "o1"}, {"id": "o1"}, "x"]
        assert sc.clean_node(self.switch(outputs=bad))["outputs"] == [{"id": "o1", "values": []}]
        node = sc.clean_node({"id": "w", "type": "condition", "kind": "switch"})
        assert (node["field"], node["mode"], node["outputs"]) == ("player", "values", [])

    def test_a_switch_survives_the_routes(self):
        store = sc.MemoryScenes()
        engine = sc.SceneEngine(store, audio=FakeAudio())
        raw = {"name": "s", "graph": {"nodes": [trigger("x01.bust"), self.switch(outputs=[{"id": "o1", "values": ["anna"]}]), sound()],
                                      "edges": [{"from": "t", "to": "w"}, {"from": "w", "to": "s", "match": "o1"}]}}
        engine.save(None, sc.clean_scene(raw))
        saved = mine(engine)[0]["graph"]
        assert saved["edges"][1] == {"from": "w", "to": "s", "match": "o1"}


class TestVoiceSlot:
    @staticmethod
    def call(node_id="c", key="line", channel="voice"):
        return {"id": node_id, "type": "action", "kind": "call", "key": key, "channel": channel}

    @staticmethod
    def engine(*scenes, audio=None, defaults=False):
        """An engine with these scenes of the user, in this order; each is a list of nodes (trigger "t" first) that
        follow each other from the trigger on, or a (nodes, edges) pair."""
        store = sc.MemoryScenes()
        for i, spec in enumerate(scenes):
            nodes, edges = spec if isinstance(spec, tuple) else (spec, None)
            edges = edges if edges is not None else [(nodes[k]["id"], nodes[k + 1]["id"]) for k in range(len(nodes) - 1)]
            store.save_scene(None, sc.clean_scene({"name": f"scene {i + 1}", "graph": graph(*nodes, edges=edges)}))
        return sc.SceneEngine(store, audio=audio or FakeAudio(files=("a.mp3", "b.mp3", "c.mp3")))

    def test_the_first_scene_that_plays_a_voice_sound_takes_the_slot(self):
        engine = self.engine([trigger("x01.bust"), sound("a", "a.mp3", channel="voice")],
                             [trigger("x01.bust"), sound("b", "b.mp3", channel="voice")])
        trace = []
        engine.fire("x01.bust", {}, trace=trace)
        assert [p[0] for p in engine.audio.played] == ["a.mp3"]
        assert [t for t in trace if t["node"] in ("a", "b")] == [
            {"node": "a", "result": "done", "file": "a.mp3"}, {"node": "b", "result": "skipped", "why": "voice_slot_taken"}]

    def test_a_scene_whose_conditions_stop_does_not_take_the_slot(self):
        engine = self.engine([trigger("x01.bust"), condition("p", "player", names=["anna"]), sound("a", "a.mp3", channel="voice")],
                             [trigger("x01.bust"), sound("b", "b.mp3", channel="voice")])
        engine.fire("x01.bust", {"player": "ben"})
        assert [p[0] for p in engine.audio.played] == ["b.mp3"]
        engine.audio.played.clear()
        engine.fire("x01.bust", {"player": "anna"})
        assert [p[0] for p in engine.audio.played] == ["a.mp3"]

    def test_a_step_that_plays_nothing_does_not_take_the_slot(self):
        engine = self.engine([trigger("x01.bust"), sound("a", "gone.mp3", channel="voice")],
                             [trigger("x01.bust"), sound("b", "b.mp3", channel="voice")])
        engine.fire("x01.bust", {})
        assert [p[0] for p in engine.audio.played] == ["b.mp3"]

    def test_ambient_sounds_and_overlays_are_never_skipped(self):
        overlays = []
        store = sc.MemoryScenes()
        for nodes in ([trigger("x01.bust"), sound("a", "a.mp3", channel="voice")],
                      [trigger("x01.bust"), sound("b", "b.mp3", channel="ambient"), self.call("k", "ambient_x"),
                       {"id": "o", "type": "action", "kind": "overlay", "animation": "flash", "text": "x", "seconds": 1}]):
            store.save_scene(None, sc.clean_scene({"name": "x", "graph": graph(*nodes, edges=[(nodes[i]["id"], nodes[i + 1]["id"]) for i in range(len(nodes) - 1)])}))
        engine = sc.SceneEngine(store, audio=FakeAudio(files=("a.mp3", "b.mp3")), overlay=overlays.append)
        engine.fire("x01.bust", {}, defaults=False)
        assert [p[0] for p in engine.audio.played] == ["a.mp3", "b.mp3"] and engine.audio.calls == ["ambient_x"] and len(overlays) == 1

    def test_calls_on_the_voice_channel_take_the_slot(self):
        engine = self.engine([trigger("x01.bust"), self.call("c", "line")], [trigger("x01.bust"), sound("b", "b.mp3", channel="voice")])
        engine.fire("x01.bust", {}, defaults=False)
        assert engine.audio.calls == ["line"] and engine.audio.played == []

    def test_a_call_that_plays_beside_the_calls_does_not(self):
        for first in (self.call("c", "line", channel="ambient"), self.call("c", "ambient_line|ambient_other")):
            engine = self.engine([trigger("x01.bust"), first], [trigger("x01.bust"), sound("b", "b.mp3", channel="voice")])
            engine.fire("x01.bust", {})
            assert [p[0] for p in engine.audio.played] == ["b.mp3"]

    def test_inside_one_scene_nothing_changes(self):
        engine = self.engine([trigger("x01.bust"), sound("a", "a.mp3", channel="voice"), sound("b", "b.mp3", channel="voice"), self.call("c")])
        engine.fire("x01.bust", {}, defaults=False)
        assert [p[0] for p in engine.audio.played] == ["a.mp3", "b.mp3"] and engine.audio.calls == ["line"]

    def test_the_standard_scenes_are_not_held_back(self):
        engine = self.engine([trigger("x01.bust"), sound("a", "a.mp3", channel="voice")])
        engine.fire("x01.bust", {})
        assert [p[0] for p in engine.audio.played] == ["a.mp3"] and engine.audio.calls      # the call of the standard scene follows

    def test_a_step_behind_a_wait_does_not_count(self):
        import time
        wait = {"id": "d", "type": "action", "kind": "delay", "seconds": 0}
        engine = self.engine([trigger("x01.bust"), wait, sound("a", "a.mp3", channel="voice")],
                             [trigger("x01.bust"), sound("b", "b.mp3", channel="voice")])
        engine.fire("x01.bust", {})
        time.sleep(0.2)
        assert sorted(p[0] for p in engine.audio.played) == ["a.mp3", "b.mp3"]

    def test_a_skipped_sound_does_not_replace_the_call(self):
        engine = self.engine([trigger("x01.bust"), sound("a", "a.mp3", channel="voice")],
                             [trigger("x01.bust"), sound("b", "b.mp3", channel="voice", replace=True)])
        assert engine.fire("x01.bust", {}) is False

    def test_a_test_run_ignores_the_slot(self):
        engine = self.engine([trigger("x01.bust"), sound("a", "a.mp3", channel="voice")],
                             [trigger("x01.bust"), sound("b", "b.mp3", channel="voice")])
        engine.fire("x01.bust", {}, only=mine(engine)[1]["id"])
        assert [p[0] for p in engine.audio.played] == ["b.mp3"]

    def test_the_order_decides(self):
        engine = self.engine([trigger("x01.bust"), sound("a", "a.mp3", channel="voice")],
                             [trigger("x01.bust"), sound("b", "b.mp3", channel="voice")])
        first, second = (s["id"] for s in mine(engine))
        engine.reorder([second, first])
        engine.fire("x01.bust", {})
        assert [p[0] for p in engine.audio.played] == ["b.mp3"] and [s["id"] for s in mine(engine)] == [second, first]


class TestSceneOrder:
    def test_scenes_keep_their_order_and_new_ones_go_to_the_end(self, tmp_path):
        db = StatsDB(str(tmp_path / "s.db"))
        ids = [db.save_scene(None, sc.clean_scene({"name": n})) for n in "abc"]
        assert [s["id"] for s in db.list_scenes()] == ids
        db.order_scenes([ids[2], ids[0]])
        assert [s["id"] for s in db.list_scenes()] == [ids[2], ids[0], ids[1]]
        new = db.save_scene(None, sc.clean_scene({"name": "d"}))
        assert [s["id"] for s in db.list_scenes()][-1] == new
        db.save_scene(ids[1], sc.clean_scene({"name": "renamed"}))              # saving does not move a scene
        assert [s["id"] for s in db.list_scenes()] == [ids[2], ids[0], ids[1], new]

    def test_scenes_made_before_the_position_get_the_order_of_their_ids(self, tmp_path):
        import sqlite3
        path = str(tmp_path / "old.db")
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE scenes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, graph TEXT NOT NULL, slug TEXT)")
        for name in ("one", "two", "three"):
            conn.execute("INSERT INTO scenes (name, graph) VALUES (?, '{\"nodes\": [], \"edges\": []}')", (name,))
        conn.commit()
        conn.close()
        db = StatsDB(path)
        assert [s["name"] for s in db.list_scenes()] == ["one", "two", "three"]
        db.save_scene(None, sc.clean_scene({"name": "four"}))
        assert [s["name"] for s in db.list_scenes()][-1] == "four"
        assert [s["name"] for s in StatsDB(path).list_scenes()][-1] == "four"       # the migration runs once

    def test_the_memory_store_orders_too(self):
        store = sc.MemoryScenes()
        ids = [store.save_scene(None, sc.clean_scene({"name": n})) for n in "ab"]
        store.order_scenes([ids[1]])
        assert [s["id"] for s in store.list_scenes()] == [ids[1], ids[0]]


class TestVoiceCheck:
    @staticmethod
    def scene(sid, *nodes, edges=None, enabled=True, name=None):
        edges = edges if edges is not None else [(nodes[i]["id"], nodes[i + 1]["id"]) for i in range(len(nodes) - 1)]
        return {"id": sid, "name": name or f"scene {sid}", "enabled": enabled, "default": False,
                "graph": sc.clean_graph(graph(*nodes, edges=edges))}

    @staticmethod
    def voice(node_id="v"):
        return sound(node_id, "a.mp3", channel="voice")

    def check(self, scenes, sid, graph_of_it=None):
        found = next(s for s in scenes if s["id"] == sid)["graph"] if graph_of_it is None else graph_of_it
        from breakfast import scene_slot
        return scene_slot.overridden_by(scenes, sid, found)

    def test_an_earlier_scene_without_a_condition_always_wins(self):
        scenes = [self.scene(1, trigger("x01.bust"), self.voice()), self.scene(2, trigger("x01.bust"), self.voice())]
        assert self.check(scenes, 2) == [{"scene": 1, "name": "scene 1", "event": "x01.bust", "level": "warning"}]
        assert self.check(scenes, 1) == []

    def test_an_earlier_scene_behind_a_condition_is_a_note(self):
        scenes = [self.scene(1, trigger("x01.bust"), condition("c", "chance", percent=50), self.voice()),
                  self.scene(2, trigger("x01.bust"), self.voice())]
        assert self.check(scenes, 2)[0]["level"] == "note"

    def test_another_moment_or_no_voice_sound_gives_nothing(self):
        scenes = [self.scene(1, trigger("x01.leg_won"), self.voice()), self.scene(2, trigger("x01.bust"), self.voice()),
                  self.scene(3, trigger("x01.bust"), sound("s", "a.mp3", channel="ambient")),
                  self.scene(4, trigger("x01.bust"), {"id": "d", "type": "action", "kind": "delay", "seconds": 1}, self.voice())]
        assert self.check(scenes, 2) == []
        assert self.check(scenes, 3) == []
        assert self.check([scenes[2], scenes[3], self.scene(5, trigger("x01.bust"), self.voice())], 5) == []      # 3 and 4 play no voice at once

    def test_a_disabled_earlier_scene_does_not_count(self):
        scenes = [self.scene(1, trigger("x01.bust"), self.voice(), enabled=False), self.scene(2, trigger("x01.bust"), self.voice())]
        assert self.check(scenes, 2) == []

    def test_a_scene_that_is_not_saved_yet_comes_last(self):
        scenes = [self.scene(1, trigger("x01.bust"), self.voice())]
        from breakfast import scene_slot
        draft = sc.clean_graph(graph(trigger("x01.bust"), self.voice(), edges=[("t", "v")]))
        assert scene_slot.overridden_by(scenes, None, draft)[0]["level"] == "warning"

    def test_other_players_do_not_compete(self):
        def only(names, sid):
            return self.scene(sid, trigger("x01.bust"), condition("p", "player", names=names), self.voice())
        assert self.check([only(["anna", "Ben"], 1), only(["carl"], 2)], 2) == []
        assert self.check([only(["anna", "Ben"], 1), only(["BEN", "carl"], 2)], 2)[0]["level"] == "note"
        no_branch = self.scene(1, trigger("x01.bust"), condition("p", "player", names=["anna"]), self.voice(),
                               edges=[("t", "p")])
        no_branch["graph"]["edges"].append({"from": "p", "to": "v", "branch": "no"})
        assert self.check([no_branch, only(["anna"], 2)], 2) == []                  # anna takes the yes side, the other scene waits for anna
        assert self.check([no_branch, only(["tom"], 2)], 2)[0]["level"] == "note"

    def test_bands_that_do_not_meet_do_not_compete(self):
        def band(op, value, sid):
            return self.scene(sid, trigger("x01.turn_scored"), condition("c", "compare", field="score", op=op, value=value), self.voice())
        assert self.check([band("<=", 10, 1), band(">=", 140, 2)], 2) == []
        assert self.check([band("<=", 10, 1), band("<", 10, 2)], 2)[0]["level"] == "note"
        assert self.check([band("<=", 10, 1), band(">", 10, 2)], 2) == []
        assert self.check([band("<=", 10, 1), band(">=", 10, 2)], 2)[0]["level"] == "note"
        assert self.check([band("==", 180, 1), band(">=", 140, 2)], 2)[0]["level"] == "note"

    def test_the_outputs_of_a_switch_do_not_compete_with_each_other(self):
        def at(output, sid, mode="values", field="player", outputs=None):
            outputs = outputs or [{"id": "o1", "values": ["anna"]}, {"id": "o2", "values": ["ben"]}]
            nodes = [trigger("x01.bust"), {"id": "w", "type": "condition", "kind": "switch", "field": field, "mode": mode, "outputs": outputs},
                     self.voice()]
            return self._switch_scene(sid, nodes, output)
        assert self.check([at("o1", 1), at("o2", 2)], 2) == []
        assert self.check([at("o1", 1), at("o1", 2)], 2)[0]["level"] == "note"
        assert self.check([at("o1", 1), at("else", 2)], 2) == []                    # anna against everybody else
        bands = [{"id": "o1", "limit": 10}, {"id": "o2", "limit": 15}]
        assert self.check([at("o1", 1, "bands", "score", bands), at("o2", 2, "bands", "score", bands)], 2) == []
        assert self.check([at("o1", 1, "bands", "score", bands), at("else", 2, "bands", "score", bands)], 2) == []
        assert self.check([at("else", 1, "bands", "score", bands), at("else", 2, "bands", "score", bands)], 2)[0]["level"] == "note"

    def _switch_scene(self, sid, nodes, output):
        edges = [{"from": "t", "to": "w"}, {"from": "w", "to": "v", "match": output}]
        return {"id": sid, "name": f"scene {sid}", "enabled": True, "default": False,
                "graph": sc.clean_graph({"nodes": nodes, "edges": edges})}

    def test_the_route_answers_for_a_draft(self, client):
        c, engine, *_ = client
        body = {"name": "first", "graph": graph(trigger("x01.bust"), self.voice(), edges=[("t", "v")])}
        first = c.post("/api/scenes", json=body).json()["id"]
        second = c.post("/api/scenes", json={**body, "name": "second"}).json()["id"]
        answer = c.post("/api/scenes/voice-check", json={"id": second, "graph": body["graph"]}).json()
        assert answer == {"overridden_by": [{"scene": first, "name": "first", "event": "x01.bust", "level": "warning"}]}
        assert c.post("/api/scenes/voice-check", json={"id": first, "graph": body["graph"]}).json() == {"overridden_by": []}
        assert c.post("/api/scenes/order", json={"ids": [second, first]}).json() == {"ok": True}
        assert [s["id"] for s in c.get("/api/scenes").json()["scenes"] if not s["default"]] == [second, first]
        assert c.post("/api/scenes/voice-check", json={"id": first, "graph": body["graph"]}).json()["overridden_by"][0]["scene"] == second


class TestX01Moments:
    def test_the_third_dart_is_a_scored_turn(self):
        moments = sc.x01_moments({"type": "dart", "dart": 3, "mode": "X01"}, snapshot(turn_score=180, remaining=321))
        assert [m[0] for m in moments] == ["x01.dart", "x01.turn_scored"]
        assert moments[1] == ("x01.turn_scored", {"player": "anna", "remaining": 321, "announce": 1, "score": 180,
                                                  "combo": "", "bracket": 150, "total": 1})

    def test_the_first_dart_and_a_finishing_dart_are_not(self):
        assert [m[0] for m in sc.x01_moments({"type": "dart", "dart": 1}, snapshot(turn_score=60, remaining=441))] == ["x01.dart"]
        assert [m[0] for m in sc.x01_moments({"type": "dart", "dart": 3}, snapshot(turn_score=60, remaining=0))] == ["x01.dart"]

    def test_a_dart_tells_what_it_hit(self):
        dart = {"type": "dart", "dart": 2, "number": 20, "multiplier": 3, "points": 60, "field": "T20"}
        (event, facts), = sc.x01_moments(dart, snapshot(remaining=200))
        assert event == "x01.dart"
        assert (facts["number"], facts["multiplier"], facts["points"], facts["dart"], facts["miss"], facts["field"]) == (
            20, 3, 60, 2, 0, "t20")
        miss = sc.x01_moments({"type": "dart", "dart": 1, "number": 0, "multiplier": 0, "miss": True}, snapshot())[0][1]
        assert miss["miss"] == 1

    def test_leg_and_match_won(self):
        leg = sc.x01_moments({"type": "won", "scope": "game"}, snapshot(turn_score=100, remaining=0))
        assert leg[0][0] == "x01.leg_won" and leg[0][1]["leg"] == 2 and leg[0][1]["score"] == 100
        assert sc.x01_moments({"type": "won", "scope": "match"}, snapshot())[0][0] == "x01.match_won"

    def test_turn_start_bust_and_match_start(self):
        assert sc.x01_moments({"type": "turn_end"}, snapshot(remaining=170))[0] == (
            "x01.turn_start", {"player": "anna", "remaining": 170, "announce": 1, "checkout": 0, "change": 0})
        assert sc.x01_moments({"type": "game_started"}, snapshot())[0][0] == "x01.leg_start"
        assert sc.x01_moments({"type": "bust"}, snapshot())[0][0] == "x01.bust"
        assert sc.x01_moments({"type": "match_started"}, snapshot())[0][0] == "x01.match_start"

    def test_other_games_and_empty_events_have_no_moments(self):
        assert sc.x01_moments(None, snapshot()) == []
        assert sc.x01_moments({"type": "bust"}, {"game_mode": "Cricket", "current": {}}) == []


class TestStore:
    def test_scenes_are_stored_in_the_database(self, tmp_path):
        db = StatsDB(str(tmp_path / "s.db"))
        data = sc.clean_scene({"name": "Ton", "graph": graph(trigger("x01.bust"))})
        scene_id = db.save_scene(None, data)
        assert db.list_scenes() == [{"id": scene_id, "slug": None, **data}]
        data["name"], data["enabled"] = "Renamed", False
        assert db.save_scene(scene_id, data) == scene_id
        assert db.list_scenes()[0]["name"] == "Renamed" and db.list_scenes()[0]["enabled"] is False
        assert db.save_scene(999, data) is None
        assert db.delete_scene(scene_id) is True and db.delete_scene(scene_id) is False
        assert db.list_scenes() == []

    def test_the_memory_store_works_the_same(self):
        store = sc.MemoryScenes()
        scene_id = store.save_scene(None, sc.clean_scene({"name": "a"}))
        assert store.list_scenes()[0]["id"] == scene_id
        assert store.save_scene(99, {}) is None
        assert store.delete_scene(scene_id) and store.list_scenes() == []


@pytest.fixture
def library(tmp_path):
    base = tmp_path / "sounds"
    base.mkdir()
    (base / "nice.mp3").write_bytes(MP3)
    sent = []
    engine = AudioEngine([str(base)], broadcast=sent.append, library_dirs=[str(base / "scenes")])
    return engine, base, sent


class TestLibrary:
    def test_an_uploaded_file_is_listed_and_played_by_name(self, library):
        engine, base, sent = library
        assert scene_sounds.save_upload(engine, "boom.mp3", MP3) is None
        assert scene_sounds.files(engine) == ["boom.mp3"]
        assert engine.play_file("boom.mp3") is True and sent[-1]["file"] == "boom.mp3"

    def test_a_library_file_is_never_the_sound_of_a_key(self, library):
        engine, base, _ = library
        scene_sounds.save_upload(engine, "freipass.mp3", MP3)
        assert engine.play("freipass") is False and engine.has_audio("freipass") is False

    @pytest.mark.parametrize("name,data,why", [
        ("../x.mp3", MP3, "the name must be"), ("x.wav", MP3, "the name must be"),
        ("x.mp3", b"", "empty"), ("x.mp3", b"not an mp3 at all", "does not look like an mp3"),
        ("x.mp3", MP3 + b"0" * scene_sounds.MAX_UPLOAD_BYTES, "larger than")])
    def test_a_bad_upload_is_refused(self, library, name, data, why):
        assert why in scene_sounds.save_upload(library[0], name, data)

    def test_a_name_exists_once_and_a_file_can_be_deleted(self, library):
        engine, *_ = library
        scene_sounds.save_upload(engine, "boom.mp3", MP3)
        assert "exists already" in scene_sounds.save_upload(engine, "boom.mp3", MP3)
        assert scene_sounds.delete_file(engine, "boom.mp3") is None
        assert "not a sound" in scene_sounds.delete_file(engine, "boom.mp3")
        assert scene_sounds.files(engine) == []

    def test_a_changed_file_gets_a_new_version_so_browsers_do_not_keep_the_old_one(self, library):
        engine, *_ = library
        seen = [engine.version]
        scene_sounds.save_upload(engine, "boom.mp3", MP3)
        seen.append(engine.version)
        scene_sounds.save_upload(engine, "boom.mp3", MP3, overwrite=True)
        seen.append(engine.version)
        scene_sounds.delete_file(engine, "boom.mp3")
        seen.append(engine.version)
        assert len(set(seen)) == 4

    def test_the_overview_says_which_scene_plays_a_file(self, library):
        engine, *_ = library
        scene_sounds.save_upload(engine, "boom.mp3", MP3)
        listed = [{"name": "Ton", "graph": graph(trigger("x01.bust"), sound(), edges=[("t", "s")])}]
        assert scene_sounds.overview(engine, listed) == [{"name": "boom.mp3", "size": len(MP3), "used_by": ["Ton"]}]



needs_ffmpeg = pytest.mark.skipif(not sound_edit.available(), reason="ffmpeg is not installed")


def tone(seconds=2.0, volume=0.1):
    """A sine wave as a wav file."""
    import subprocess
    done = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i",
                           f"sine=frequency=440:duration={seconds}", "-af", f"volume={volume}", "-f", "wav", "pipe:1"],
                          capture_output=True, check=True)
    return done.stdout


def loudness(mp3: bytes) -> float:
    import json, subprocess
    done = subprocess.run(["ffmpeg", "-nostdin", "-i", "pipe:0", "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                          input=mp3, capture_output=True)
    return float(json.loads(done.stderr.decode()[done.stderr.decode().rindex("{"):])["input_i"])


def mean_level(mp3: bytes) -> float:
    """The RMS level of the whole file in dB, quiet parts included."""
    import re, subprocess
    done = subprocess.run(["ffmpeg", "-nostdin", "-i", "pipe:0", "-af", "astats", "-f", "null", "-"], input=mp3, capture_output=True)
    return float(re.findall(r"RMS level dB: (-?[\d.]+)", done.stderr.decode())[-1])


@needs_ffmpeg
class TestSoundEdit:
    def test_the_part_between_the_marks_is_cut_and_levelled(self, library):
        engine, *_ = library
        quiet, loud = tone(volume=0.02), tone(volume=0.5)
        assert scene_sounds.save_edit(engine, "a.mp3", quiet, 0.5, 1.5, 0.1, 0.2) is None
        assert scene_sounds.save_edit(engine, "b.mp3", loud, 0.0, 1.0, 0, 0) is None
        a, b = [(scene_sounds.folder(engine) / n).read_bytes() for n in ("a.mp3", "b.mp3")]
        assert a[:3] == b"ID3" and abs(loudness(a) - loudness(b)) < 1.5
        assert abs(loudness(a) - sound_edit.TARGET_LUFS) < 2

    def test_the_trim_makes_one_sound_louder_or_quieter_than_the_level(self, library):
        engine, *_ = library
        data = tone(2.0, 0.1)
        assert scene_sounds.save_edit(engine, "flat.mp3", data, 0, 2, 0, 0) is None
        assert scene_sounds.save_edit(engine, "loud.mp3", data, 0, 2, 0, 0, trim=4) is None
        assert scene_sounds.save_edit(engine, "far.mp3", data, 0, 2, 0, 0, trim=40) is None
        read = lambda n: (scene_sounds.folder(engine) / n).read_bytes()
        assert 3 < loudness(read("loud.mp3")) - loudness(read("flat.mp3")) < 5
        assert loudness(read("far.mp3")) - loudness(read("flat.mp3")) < sound_edit.TRIM_MAX + 1     # the trim is limited

    def test_a_fade_follows_its_curve(self, library):
        engine, *_ = library
        data = tone(2.0, 0.1)
        for name, curve in (("lin.mp3", 1), ("slow.mp3", 4), ("fast.mp3", 0.25), ("wild.mp3", 99)):
            assert scene_sounds.save_edit(engine, name, data, 0, 2, 1.0, 0.5, curve_in=curve, curve_out=curve) is None
        read = lambda n: mean_level((scene_sounds.folder(engine) / n).read_bytes())
        assert read("slow.mp3") < read("lin.mp3") < read("fast.mp3")
        assert abs(read("wild.mp3") - read("slow.mp3")) < 0.2          # the curve is limited to 4

    def test_a_sharp_hit_ends_up_quieter_than_an_even_tone_of_the_same_loudness(self, library):
        import subprocess
        engine, *_ = library
        hit = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i",
                              "sine=frequency=300:duration=2,volume='if(lt(t,0.5),0.6,0.03)':eval=frame", "-f", "wav", "pipe:1"],
                             capture_output=True, check=True).stdout
        assert scene_sounds.save_edit(engine, "hit.mp3", hit, 0, 2, 0, 0) is None
        assert scene_sounds.save_edit(engine, "even.mp3", tone(2.0, 0.2), 0, 2, 0, 0) is None
        read = lambda n: (scene_sounds.folder(engine) / n).read_bytes()
        assert loudness(read("hit.mp3")) < loudness(read("even.mp3"))

    def test_a_part_shorter_than_the_window_is_set_by_its_peak(self, library):
        engine, *_ = library
        assert scene_sounds.save_edit(engine, "tick.mp3", tone(1.0, 0.05), 0, 0.2, 0, 0) is None
        assert (scene_sounds.folder(engine) / "tick.mp3").stat().st_size > 0

    def test_a_bad_selection_or_file_is_refused(self, library):
        engine, *_ = library
        data = tone()
        assert "too short" in scene_sounds.save_edit(engine, "a.mp3", data, 1.0, 1.0, 0, 0)
        assert "longer than" in scene_sounds.save_edit(engine, "a.mp3", data, 0, 500, 0, 0)
        assert "could not be read" in scene_sounds.save_edit(engine, "a.mp3", b"not audio at all", 0, 1, 0, 0)
        assert scene_sounds.files(engine) == []

    def test_an_existing_name_is_kept_unless_overwritten(self, library):
        engine, *_ = library
        data = tone()
        assert scene_sounds.save_edit(engine, "a.mp3", data, 0, 1, 0, 0) is None
        assert "exists already" in scene_sounds.save_edit(engine, "a.mp3", data, 0, 1, 0, 0)
        assert scene_sounds.save_edit(engine, "a.mp3", data, 0, 1, 0, 0, overwrite=True) is None


def scene_sounds_of(scene):
    return sc.sound_files(scene["graph"])


class TestRename:
    def test_a_rename_follows_into_the_scenes_that_play_the_file(self, client):
        c, engine, *_ = client
        c.post("/api/scenes/sounds/upload?name=boom.mp3", content=MP3)
        made = c.post("/api/scenes", json={"name": "Ton", "graph": graph(trigger("x01.bust"), sound(), edges=[("t", "s")])}).json()
        assert c.post("/api/scenes/sounds/boom.mp3/rename", json={"name": "bang.mp3"}).json() == {"ok": True, "file": "bang.mp3"}
        assert [s["name"] for s in c.get("/api/scenes").json()["sounds"]] == ["bang.mp3"]
        scene = next(s for s in c.get("/api/scenes").json()["scenes"] if s["id"] == made["id"])
        assert scene_sounds_of(scene) == ["bang.mp3"]
        assert "exists" in c.post("/api/scenes/sounds/bang.mp3/rename", json={"name": "bang.mp3"}).json()["error"]
        assert "letters" in c.post("/api/scenes/sounds/bang.mp3/rename", json={"name": "../x"}).json()["error"]

    def test_the_volume_of_a_sound_can_go_to_120_percent(self):
        g = graph(trigger("x01.bust"), sound(volume=1.5), edges=[("t", "s")])
        assert next(n for n in sc.clean_graph(g)["nodes"] if n["id"] == "s")["volume"] == 1.2

@pytest.fixture
def client(library, tmp_path):
    engine, base, sent = library
    db = StatsDB(str(tmp_path / "stats.db"))
    overlays = []
    scene_engine = sc.SceneEngine(db, audio=engine, overlay=overlays.append)
    server.wire(None, None, audio_engine=engine, scene_engine=scene_engine)
    yield TestClient(server.app), scene_engine, sent, overlays
    server.wire(None, None)


class TestRoutes:
    def test_without_the_engine_nothing_is_available(self):
        server.wire(None, None)
        assert TestClient(server.app).get("/api/scenes").json()["available"] is False
        assert "not available" in TestClient(server.app).post("/api/scenes", json={}).json()["error"]

    def test_create_read_update_and_delete(self, client):
        c, engine, *_ = client
        made = c.post("/api/scenes", json={"name": "Ton", "graph": graph(trigger("x01.bust"))}).json()
        assert made["ok"]
        body = c.get("/api/scenes").json()
        assert body["available"] and [s["name"] for s in body["scenes"] if not s["default"]] == ["Ton"]
        assert "x01.turn_scored" in body["events"] and ">=" in body["operators"]
        assert c.put(f"/api/scenes/{made['id']}", json={"name": "Neu", "enabled": False}).json()["ok"]
        assert [s["name"] for s in c.get("/api/scenes").json()["scenes"] if not s["default"]] == ["Neu"]
        assert "unknown" in c.put("/api/scenes/99", json={}).json()["error"]
        assert c.delete(f"/api/scenes/{made['id']}").json() == {"ok": True}
        assert "unknown" in c.delete(f"/api/scenes/{made['id']}").json()["error"]
        assert [s for s in c.get("/api/scenes").json()["scenes"] if not s["default"]] == []

    def test_the_fun_mode_is_a_caller_setting_and_works_at_once(self, library, tmp_path):
        from breakfast import config as cfg_mod
        engine, base, sent = library
        path = tmp_path / "config.toml"
        scene_engine = sc.SceneEngine(StatsDB(str(tmp_path / "s.db")), audio=engine)
        server.wire(None, None, audio_engine=engine, scene_engine=scene_engine, config_path=str(path))
        try:
            c = TestClient(server.app)
            assert c.get("/api/config").json()["caller"]["fun"] is False
            assert c.patch("/api/config", json={"caller": {"fun": True}}).json() == {"saved": True, "restart_required": []}
            assert scene_engine.fun is True and cfg_mod.load(str(path))["caller"]["fun"] is True
            server.wire(None, None, audio_engine=engine, scene_engine=sc.SceneEngine(None), config_path=str(path))
            assert TestClient(server.app).get("/api/config").json()["caller"]["fun"] is True
        finally:
            server.wire(None, None)

    def test_a_graph_is_cleaned_on_the_way_in(self, client):
        c, *_ = client
        c.post("/api/scenes", json={"name": "x", "graph": {"nodes": [{"id": "z", "type": "nope"}], "edges": []}})
        scene = next(s for s in c.get("/api/scenes").json()["scenes"] if not s["default"])
        assert scene["graph"] == {"nodes": [], "edges": []}

    def test_upload_list_and_delete_a_sound(self, client):
        c, *_ = client
        assert c.post("/api/scenes/sounds/upload?name=boom.mp3", content=MP3).json() == {"ok": True, "file": "boom.mp3"}
        assert [s["name"] for s in c.get("/api/scenes").json()["sounds"]] == ["boom.mp3"]
        assert c.get("/api/sound/boom.mp3").status_code == 200
        assert "exists" in c.post("/api/scenes/sounds/upload?name=boom.mp3", content=MP3).json()["error"]
        assert c.delete("/api/scenes/sounds/boom.mp3").json() == {"ok": True}
        assert "not a sound" in c.delete("/api/scenes/sounds/boom.mp3").json()["error"]

    def test_the_test_button_plays_the_scene_with_sample_values(self, client):
        c, _, sent, overlays = client
        c.post("/api/scenes/sounds/upload?name=boom.mp3", content=MP3)
        g = graph(trigger("x01.turn_scored"), condition("c", "compare", field="score", op=">=", value=140), sound(),
                  {"id": "o", "type": "action", "kind": "overlay", "text": "{score}"},
                  edges=[("t", "c"), ("c", "s"), ("c", "o")])
        scene_id = c.post("/api/scenes", json={"name": "x", "enabled": False, "graph": g}).json()["id"]
        result = c.post(f"/api/scenes/{scene_id}/test").json()
        assert result["ok"] and sent[-1]["file"] == "boom.mp3" and overlays[0]["text"] == "180"
        assert "unknown" in c.post("/api/scenes/99/test").json()["error"]

    def test_the_audio_clients_are_counted(self, client):
        c, *_ = client
        assert c.get("/api/scenes/audio-clients").json() == {"count": 0}


def throw(number, multiplier):
    return {"segment": {"number": number, "multiplier": multiplier}}


class FakeMqtt:
    def publish(self, *args, **kwargs):
        pass


class TestElimination:
    def play(self, replace):
        audio = FakeAudio(files={"boom.mp3"})
        scene_engine = engine_with(graph(trigger("elim.life_lost"), sound(replace=replace), edges=[("t", "s")]), audio)
        game = EliminationGame(["anna", "ben"], 3, FakeMqtt(), "autodarts", audio=audio)
        game.scenes = scene_engine
        game._apply_turn("anna", 50, silent=True)         # the first turn passes with anything
        audio.calls.clear()
        game.on_board_state(1, [throw(1, 1)])
        game.on_board_state(2, [throw(1, 1), throw(1, 1)])
        game.on_board_state(3, [throw(1, 1)] * 3)         # 3 is below the 50 to beat: a life is lost
        return audio

    def test_a_scene_for_a_lost_life_plays_beside_the_call(self):
        audio = self.play(replace=False)
        assert audio.played and "life_lost" in audio.calls

    def test_a_replacing_scene_leaves_out_the_call(self):
        audio = self.play(replace=True)
        assert audio.played and "life_lost" not in audio.calls and "3" not in audio.calls

    def test_no_scene_no_change(self):
        audio = FakeAudio()
        game = EliminationGame(["anna", "ben"], 3, FakeMqtt(), "autodarts", audio=audio)
        game._apply_turn("anna", 50, silent=True)
        game.on_board_state(3, [throw(1, 1)] * 3)
        assert "life_lost" in audio.calls and not audio.played

    def test_a_replayed_turn_fires_no_scene(self):
        audio = FakeAudio()
        game = EliminationGame(["anna", "ben"], 3, FakeMqtt(), "autodarts", audio=audio)
        game.scenes = engine_with(graph(trigger("elim.turn_start"), sound(), edges=[("t", "s")]), audio)
        game._apply_turn("anna", 50, silent=True)
        assert audio.played == []
        game._apply_turn("ben", 60)
        assert len(audio.played) == 1


def default_engine(audio, store=None):
    return sc.SceneEngine(store, audio=audio)


class TestDefaultScenes:
    def test_every_default_scene_is_a_valid_graph_with_a_trigger(self):
        for d in scenes_default.DEFAULTS:
            assert sc.clean_graph(d["graph"]) == d["graph"], d["slug"]
            assert any(n["type"] == "trigger" for n in d["graph"]["nodes"])

    def test_the_defaults_come_first_unedited(self):
        listed = default_engine(FakeAudio()).scenes()
        assert [s["id"] for s in listed] == [d["slug"] for d in scenes_default.DEFAULTS]
        assert all(s["default"] and not s["customized"] and s["enabled"] for s in listed)

    def test_a_default_scene_makes_the_calls_of_its_event(self):
        audio = FakeAudio()
        default_engine(audio).fire("elim.match_won", {"player": "Anna"})
        assert audio.calls == ["anna", "matchshot"]

    def test_the_words_are_the_player_the_score_and_the_next_score(self):
        audio = FakeAudio()
        engine = default_engine(audio)
        engine.fire("elim.turn_counted", {"player": "anna", "score": 41.0})
        engine.fire("elim.turn_start", {"player": "anna", "next": 51, "freipass": 0})
        assert audio.calls == ["41", "anna", "filler_target", "51"]

    def test_a_call_can_play_beside_the_voice_channel(self):
        class Channels(FakeAudio):
            def play(self, name, **kwargs):
                self.calls.append((name, kwargs.get("channel")))
                return True

        audio = Channels()
        engine = engine_with(graph(
            trigger("elim.match_won"), {"id": "c", "type": "action", "kind": "call", "key": "{player}", "channel": "ambient"},
            {"id": "d", "type": "action", "kind": "call", "key": "cheer"}, edges=[("t", "c"), ("t", "d")]), audio)
        engine.fire("elim.match_won", {"player": "anna"})
        assert audio.calls == [("anna", "ambient"), ("cheer", None), ("anna", None), ("matchshot", None)]

    def test_a_player_without_a_recording_is_called_unknown(self):
        class Strict(FakeAudio):
            def play(self, name, **kwargs):
                self.calls.append(name)
                return name != "ghost"

        audio = Strict()
        default_engine(audio).fire("elim.match_won", {"player": "ghost"})
        assert audio.calls == ["ghost", "unknown_player", "matchshot"]

    def test_an_edited_copy_replaces_the_original_and_a_reset_brings_it_back(self):
        audio = FakeAudio()
        engine = default_engine(audio)
        edited = sc.clean_scene({"name": "ignored", "graph": graph(
            trigger("elim.match_won"), {"id": "c", "type": "action", "kind": "call", "key": "applause"},
            edges=[("t", "c")])})
        assert engine.save("elimination-match-won", edited) == "elimination-match-won"
        engine.fire("elim.match_won", {"player": "anna"})
        assert audio.calls == ["applause"]
        scene = engine.find("elimination-match-won")
        assert scene["customized"] and scene["name"] == "Match won" and scene["game"] == "Elimination"
        assert engine.delete("elimination-match-won") is True
        audio.calls.clear()
        engine.fire("elim.match_won", {"player": "anna"})
        assert audio.calls == ["anna", "matchshot"]
        assert engine.delete("elimination-match-won") is False

    def test_a_default_scene_can_be_switched_off(self):
        audio = FakeAudio()
        engine = default_engine(audio)
        engine.save("elimination-match-won", sc.clean_scene({"enabled": False, "graph": engine.find("elimination-match-won")["graph"]}))
        engine.fire("elim.match_won", {"player": "anna"})
        assert audio.calls == []

    def test_an_unknown_slug_is_refused(self):
        assert default_engine(FakeAudio()).save("nope", sc.clean_scene({})) is None

    def test_a_replacing_sound_of_the_user_keeps_the_defaults_out(self):
        audio = FakeAudio()
        engine = engine_with(graph(trigger("elim.match_won"), sound(replace=True), edges=[("t", "s")]), audio)
        engine.fire("elim.match_won", {"player": "anna"})
        assert audio.played and audio.calls == []

    def test_a_sound_beside_the_call_leaves_the_defaults_running(self):
        audio = FakeAudio()
        engine = engine_with(graph(trigger("elim.match_won"), sound(), edges=[("t", "s")]), audio)
        engine.fire("elim.match_won", {"player": "anna"})
        assert audio.played and audio.calls == ["anna", "matchshot"]

    def test_a_scene_of_the_database_survives_and_the_old_table_gets_its_slug(self, tmp_path):
        import sqlite3
        path = str(tmp_path / "old.db")
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE scenes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, "
                     "enabled INTEGER NOT NULL DEFAULT 1, graph TEXT NOT NULL)")
        conn.execute("INSERT INTO scenes (name, enabled, graph) VALUES ('old', 1, '{\"nodes\": [], \"edges\": []}')")
        conn.commit()
        conn.close()
        db = StatsDB(path)
        assert db.list_scenes()[0]["slug"] is None
        engine = default_engine(FakeAudio(), db)
        engine.save("elimination-match-won", sc.clean_scene({}))
        assert [s["name"] for s in mine(engine)] == ["old"] and engine.find("elimination-match-won")["customized"]


class TestDefaultRoutes:
    def test_a_default_scene_is_edited_tested_and_reset_by_its_slug(self, client):
        c, engine, sent, overlays = client
        listed = {s["id"]: s for s in c.get("/api/scenes").json()["scenes"]}
        assert listed["elimination-match-won"]["default"] and "applause" not in c.get("/api/scenes").json()["call_keys"]
        body = {"name": "x", "enabled": True, "graph": graph(
            trigger("elim.match_won"), {"id": "o", "type": "action", "kind": "overlay", "text": "{player}"},
            edges=[("t", "o")])}
        assert c.put("/api/scenes/elimination-match-won", json=body).json() == {"ok": True, "id": "elimination-match-won"}
        again = {s["id"]: s for s in c.get("/api/scenes").json()["scenes"]}
        assert again["elimination-match-won"]["customized"] is True and not again["elimination-life-lost"]["customized"]
        assert c.post("/api/scenes/elimination-match-won/test").json()["ok"] and overlays[-1]["text"] == "test"
        assert c.delete("/api/scenes/elimination-match-won").json() == {"ok": True}
        assert "unknown" in c.delete("/api/scenes/elimination-match-won").json()["error"]
        assert "unknown" in c.put("/api/scenes/nope", json=body).json()["error"]
        assert "unknown" in c.post("/api/scenes/nope/test").json()["error"]


class RecordingAudio(FakeAudio):
    """Plays the keys of `keys` and remembers how."""

    def __init__(self, keys=(), files=("boom.mp3",)):
        super().__init__(files)
        self.keys = set(keys)
        self.heard = []

    def play(self, name, **kwargs):
        self.calls.append(name)
        if name in self.keys:
            self.heard.append((name, kwargs))
        return name in self.keys


class TestCallKeys:
    def test_a_key_takes_facts_and_falls_through_its_options(self):
        audio = RecordingAudio({"require_40", "b"})
        engine = default_engine(audio)
        assert engine._call("require_{remaining}", {"remaining": 40})
        assert engine._call("a|b", {})
        assert audio.calls == ["require_40", "a", "b"]

    def test_a_missing_fact_skips_the_key(self):
        audio = RecordingAudio({"ambient_x_", "x_"})
        engine = default_engine(audio)
        assert not engine._call("x_{player}", {"player": None})
        assert not engine._call("x_{combo}", {"combo": ""})
        assert audio.calls == []

    def test_a_plus_plays_every_part_that_has_a_sound(self):
        audio = RecordingAudio({"gameshot", "leg_2"})
        assert default_engine(audio)._call("gameshot_l{leg}_n|gameshot+leg_{leg}", {"leg": 2})
        assert audio.calls == ["gameshot_l2_n", "gameshot", "leg_2"]

    def test_ambient_keys_follow_the_ambient_volume(self):
        audio = RecordingAudio({"ambient_a"})
        engine = default_engine(audio)
        engine.ambient_volume = 0.4
        engine._call("ambient_a", {})
        assert audio.heard == [("ambient_a", {"volume": 0.4})]
        engine.ambient_volume = 0
        assert not engine._call("ambient_a", {}) and audio.calls == ["ambient_a"]


class TestX01Defaults:
    @staticmethod
    def fire(audio, event, facts, **kwargs):
        engine = default_engine(audio)
        engine.fire(event, facts, **kwargs)
        return engine

    def test_every_default_scene_starts_at_a_known_moment_of_its_game(self):
        for d in scenes_default.DEFAULTS:
            triggers = [n["event"] for n in d["graph"]["nodes"] if n["type"] == "trigger"]
            assert triggers and all(sc.EVENTS[e]["game"] == d["game"] for e in triggers), d["slug"]
            assert sc.clean_graph(d["graph"]) == d["graph"], d["slug"]

    def test_the_turn_total_and_the_ambient_ladder(self):
        audio = RecordingAudio({"140", "ambient_t20t20s5", "ambient_100more", "ambient_noscore"})
        self.fire(audio, "x01.turn_scored", {"player": "anna", "score": 140, "combo": "t20t20s20", "bracket": 120, "total": 1})
        assert audio.calls == ["140", "ambient_t20t20s20", "ambient_140", "ambient_120more"]
        audio = RecordingAudio({"0", "ambient_noscore"})
        self.fire(audio, "x01.turn_scored", {"score": 0, "combo": "", "bracket": 0, "total": 1})
        assert audio.calls == ["0", "ambient_noscore"]

    def test_the_turn_total_can_be_switched_off(self):
        audio = RecordingAudio({"140"})
        self.fire(audio, "x01.turn_scored", {"score": 140, "combo": "", "bracket": 120, "total": 0})
        assert audio.calls == []

    def test_a_sound_that_replaces_keeps_the_standard_calls_out(self):
        audio = RecordingAudio({"140"})
        engine = default_engine(audio)
        engine.save(None, sc.clean_scene({"name": "n", "graph": graph(
            trigger("x01.turn_scored"), sound(replace=True), edges=[("t", "s")])}))
        engine.fire("x01.turn_scored", {"score": 140, "combo": "", "bracket": 120, "total": 1})
        assert audio.calls == [] and audio.played == [("boom.mp3", 1, "ambient")]

    def test_without_a_caller_only_the_scenes_of_the_user_run(self):
        audio = RecordingAudio({"busted", "ambient_noscore"})
        engine = default_engine(audio)
        engine.save(None, sc.clean_scene({"name": "n", "graph": graph(
            trigger("x01.bust"), sound(), edges=[("t", "s")])}))
        sc.run_x01(engine, None, {"type": "bust", "mode": "X01"}, snapshot())
        assert audio.calls == [] and len(audio.played) == 1


def flow(*nodes, edges):
    return sc.clean_scene({"name": "n", "graph": graph(*nodes, edges=edges)})


def call(node_id, key):
    return {"id": node_id, "type": "action", "kind": "call", "key": key}


class TestBranches:
    def test_a_condition_leads_on_its_yes_or_its_no_output(self):
        audio = RecordingAudio({"hi", "lo"})
        engine = default_engine(audio)
        data = flow(trigger("x01.turn_scored"), condition("c", "compare", field="score", op=">=", value=100),
                    call("a", "hi"), call("b", "lo"), edges=[("t", "c"), ("c", "a")])
        data["graph"]["edges"] += [{"from": "c", "to": "b", "branch": "no"}]
        engine.save(None, data)
        engine.fire("x01.turn_scored", {"score": 140}, defaults=False)
        engine.fire("x01.turn_scored", {"score": 20}, defaults=False)
        assert audio.calls == ["hi", "lo"]

    def test_else_if_is_a_condition_on_the_no_output(self):
        audio = RecordingAudio({"big", "mid", "small"})
        engine = default_engine(audio)
        data = flow(trigger("x01.turn_scored"), condition("c1", "compare", field="score", op=">=", value=100),
                    condition("c2", "compare", field="score", op=">=", value=50), call("a", "big"), call("b", "mid"),
                    call("c", "small"), edges=[("t", "c1"), ("c1", "a"), ("c2", "b")])
        data["graph"]["edges"] += [{"from": "c1", "to": "c2", "branch": "no"}, {"from": "c2", "to": "c", "branch": "no"}]
        engine.save(None, data)
        for score in (140, 60, 10):
            engine.fire("x01.turn_scored", {"score": score}, defaults=False)
        assert audio.calls == ["big", "mid", "small"]

    def test_the_graph_keeps_the_branch_and_the_weight_only_when_they_matter(self):
        cleaned = sc.clean_graph({"nodes": [{"id": "a", "type": "trigger", "event": "x01.bust"},
                                            {"id": "b", "type": "condition", "kind": "pick"}],
                                  "edges": [{"from": "a", "to": "b", "branch": "yes", "weight": 1},
                                            {"from": "b", "to": "a", "branch": "no", "weight": 3}]})
        assert cleaned["edges"] == [{"from": "a", "to": "b"}, {"from": "b", "to": "a", "branch": "no", "weight": 3.0}]

    def test_a_random_pick_takes_one_next_step_by_weight(self, monkeypatch):
        audio = RecordingAudio({"a", "b"})
        engine = default_engine(audio)
        data = flow(trigger("x01.bust"), {"id": "p", "type": "condition", "kind": "pick"}, call("a", "a"), call("b", "b"),
                    edges=[("t", "p"), ("p", "a"), ("p", "b")])
        data["graph"]["edges"][2]["weight"] = 99
        engine.save(None, data)
        picks = []
        monkeypatch.setattr(sc.random, "choices", lambda items, weights: picks.append(weights) or [items[-1]])
        engine.fire("x01.bust", {}, defaults=False)
        assert audio.calls == ["b"] and picks == [[1, 99]]


class TestOnce:
    def make(self, scope="match", per_player=False):
        audio = RecordingAudio({"hi"})
        engine = default_engine(audio)
        engine.save(None, flow(trigger("x01.turn_scored"), condition("o", "once", scope=scope, per_player=per_player),
                               call("a", "hi"), edges=[("t", "o"), ("o", "a")]))
        return engine, audio

    def test_it_lets_the_first_one_through_until_the_match_starts_again(self):
        engine, audio = self.make()
        for _ in range(3):
            engine.fire("x01.turn_scored", {"player": "anna"}, defaults=False)
        assert audio.calls == ["hi"]
        engine.fire("x01.match_start", {}, defaults=False)
        engine.fire("x01.turn_scored", {"player": "anna"}, defaults=False)
        assert audio.calls == ["hi", "hi"]

    def test_a_leg_forgets_it_but_a_match_does_not(self):
        engine, audio = self.make("leg")
        engine.fire("x01.turn_scored", {}, defaults=False)
        engine.fire("x01.leg_start", {}, defaults=False)
        engine.fire("x01.turn_scored", {}, defaults=False)
        engine, audio2 = self.make("match")
        engine.fire("x01.turn_scored", {}, defaults=False)
        engine.fire("x01.leg_start", {}, defaults=False)
        engine.fire("x01.turn_scored", {}, defaults=False)
        assert audio.calls == ["hi", "hi"] and audio2.calls == ["hi"]

    def test_per_player_counts_each_player_once(self):
        engine, audio = self.make(per_player=True)
        for name in ("anna", "ben", "anna", "ben"):
            engine.fire("x01.turn_scored", {"player": name}, defaults=False)
        assert audio.calls == ["hi", "hi"]

    def test_a_test_run_does_not_use_it_up(self):
        engine, audio = self.make()
        scene = next(s for s in engine.scenes() if not s["default"])["id"]
        for _ in range(2):
            engine.fire("x01.turn_scored", {}, only=scene)
        engine.fire("x01.turn_scored", {}, defaults=False)
        assert audio.calls == ["hi", "hi", "hi"]


class TestAchievementCondition:
    def make(self, tmp_path, tier=1):
        db = StatsDB(str(tmp_path / "s.db"))
        audio = RecordingAudio({"yes", "no"})
        engine = default_engine(audio, db)
        engine.save(None, flow(trigger("x01.turn_scored"),
                               condition("c", "achievement", achievement="ton_up", tier=tier),
                               call("y", "yes"), call("n", "no"), edges=[("t", "c"), ("c", "y")]))
        data = engine.scenes()
        scene = next(x for x in data if not x["default"])
        scene["graph"]["edges"].append({"from": "c", "to": "n", "branch": "no"})
        engine.save(scene["id"], scene)
        return db, engine, audio

    def test_the_player_who_has_it_goes_on_at_yes(self, tmp_path):
        db, engine, audio = self.make(tmp_path)
        db.add_earned("anna", "ton_up", 1, None)
        engine.fire("x01.turn_scored", {"player": "anna"}, defaults=False)
        engine.fire("x01.turn_scored", {"player": "ben"}, defaults=False)
        assert audio.calls == ["yes", "no"]

    def test_a_tier_counts_from_the_chosen_one_on(self, tmp_path):
        db, engine, audio = self.make(tmp_path, tier=2)
        db.add_earned("anna", "ton_up", 1, None)
        engine.fire("x01.turn_scored", {"player": "anna"}, defaults=False)
        db.add_earned("anna", "ton_up", 2, None)
        engine.fire("x01.turn_scored", {"player": "anna"}, defaults=False)
        assert audio.calls == ["no", "yes"]

    def test_without_a_store_or_a_player_it_is_no(self, tmp_path):
        engine = default_engine(RecordingAudio({"yes"}))
        node = condition("c", "achievement", achievement="ton_up", tier=1)
        assert engine._has_achievement(node, {"player": "anna"}) is False
        db, engine, audio = self.make(tmp_path)
        assert engine._has_achievement(node, {}) is False

    def test_the_fields_are_cleaned(self):
        node = sc.clean_node(condition("c", "achievement", achievement="x" * 99, tier=500))
        assert len(node["achievement"]) == 60 and node["tier"] == 20


class TestFunMode:
    def test_the_fun_mode_is_a_fact_of_every_moment(self):
        audio = RecordingAudio({"loud", "calm"})
        engine = default_engine(audio)
        data = flow(trigger("x01.bust"), condition("c", "compare", field="fun", op="==", value=1),
                    call("a", "loud"), call("b", "calm"), edges=[("t", "c"), ("c", "a")])
        data["graph"]["edges"].append({"from": "c", "to": "b", "branch": "no"})
        engine.save(None, data)
        engine.fire("x01.bust", {}, defaults=False)
        engine.fun = True
        engine.fire("x01.bust", {}, defaults=False)
        assert audio.calls == ["calm", "loud"]


class TestAchievementTrigger:
    """The trigger `achievement.earned` fires when an achievement is announced (#134)."""

    @staticmethod
    def setup_announce(nodes, edges, audio=None, spacing=0, **kw):
        from breakfast.achievements import AchievementEngine
        store = sc.MemoryScenes()
        store.save_scene(None, sc.clean_scene({"name": "x", "graph": graph(*nodes, edges=edges)}))
        audio = audio or FakeAudio(files=("cheer.mp3", "fallback.mp3"))
        scenes = sc.SceneEngine(store, audio=audio)
        pushed = []
        ach = AchievementEngine(StatsDB(":memory:")).announce(
            pushed.append, audio, sounds=lambda a: [], scenes=scenes, spacing=spacing, **kw)
        return ach, audio, pushed, scenes

    def test_the_facts_of_an_unlock(self):
        from breakfast import achievements as a
        assert a.scene_facts(a.BY_ID["bullseye"], {"player": "ana", "tier": 0}) == {
            "player": "ana", "id": "bullseye", "tier": 1, "difficulty": 1, "secret": 0, "first": 1}
        counter = next(d for d in a.ACHIEVEMENTS if d.tiers)
        facts = a.scene_facts(counter, {"player": "ana", "tier": 2})
        assert facts["tier"] == 2 and facts["first"] == 0
        secret = next(d for d in a.ACHIEVEMENTS if d.hidden)
        assert a.scene_facts(secret, {"player": "ana", "tier": 0})["secret"] == 1 and a.scene_facts(secret, {"player": "ana", "tier": 0})["difficulty"] == 0
        ladder = {d.difficulty: a.scene_facts(d, {"player": "x", "tier": 0})["difficulty"] for d in a.ACHIEVEMENTS}
        assert {k: v for k, v in ladder.items() if v} == {"easy": 1, "medium": 2, "hard": 3, "very_hard": 4, "extreme": 5}
        assert set(ladder) == {"easy", "medium", "hard", "very_hard", "extreme", "endurance", "hidden"}

    def test_the_event_is_offered_with_its_facts(self):
        event = sc.EVENTS["achievement.earned"]
        assert event["game"] == "Achievements" and set(event["fields"]) == {"id", "tier", "difficulty", "secret", "first"}

    def test_a_scene_plays_with_the_banner_and_the_assigned_sound_stays(self):
        ach, audio, pushed, scenes = self.setup_announce([trigger("achievement.earned"), sound("s", "cheer.mp3")], [("t", "s")])
        ach.on_earned({"player": "ana", "achievement": "bullseye", "tier": 0})
        assert [p[0] for p in audio.played] == ["cheer.mp3"] and pushed and pushed[0]["id"] == "bullseye"
        assert audio.calls == ["achievement_bullseye"]            # the fallback plays as before

    def test_a_sound_that_replaces_keeps_the_assigned_sound_and_the_fallbacks_out(self):
        ach, audio, pushed, scenes = self.setup_announce(
            [trigger("achievement.earned"), sound("s", "cheer.mp3", replace=True)], [("t", "s")])
        ach.on_earned({"player": "ana", "achievement": "bullseye", "tier": 0})
        assert [p[0] for p in audio.played] == ["cheer.mp3"] and audio.calls == [] and len(pushed) == 1     # the banner is not affected

    def test_a_scene_that_plays_nothing_replaces_nothing(self):
        ach, audio, pushed, scenes = self.setup_announce(
            [trigger("achievement.earned"), sound("s", "gone.mp3", replace=True)], [("t", "s")])
        ach.on_earned({"player": "ana", "achievement": "bullseye", "tier": 0})
        assert audio.calls == ["achievement_bullseye"]

    def test_the_conditions_see_the_facts(self):
        nodes = [trigger("achievement.earned"), condition("d", "compare", field="difficulty", op=">=", value=3),
                 condition("p", "player", names=["ana"]), sound("s", "cheer.mp3", replace=True)]
        ach, audio, pushed, scenes = self.setup_announce(nodes, [("t", "d"), ("d", "p"), ("p", "s")])
        ach.on_earned({"player": "ana", "achievement": "bullseye", "tier": 0})                  # easy
        assert audio.played == []
        hard = next(d.id for d in __import__("breakfast.achievements", fromlist=["x"]).ACHIEVEMENTS if d.difficulty == "hard")
        ach.on_earned({"player": "ana", "achievement": hard, "tier": 1})
        assert [p[0] for p in audio.played] == ["cheer.mp3"] and audio.calls == ["achievement_bullseye"]   # the easy one fell back
        ach.on_earned({"player": "ben", "achievement": hard, "tier": 1})
        assert len(audio.played) == 1 and audio.calls == ["achievement_bullseye", f"achievement_{hard}"]

    def test_a_switch_can_tell_the_achievements_apart(self):
        sw = {"id": "w", "type": "condition", "kind": "switch", "field": "id", "mode": "values",
              "outputs": [{"id": "o1", "values": ["bullseye"]}]}
        store = sc.MemoryScenes()
        nodes = [trigger("achievement.earned"), sw, sound("s", "cheer.mp3", replace=True)]
        edges = [{"from": "t", "to": "w"}, {"from": "w", "to": "s", "match": "o1"}]
        store.save_scene(None, sc.clean_scene({"name": "x", "graph": {"nodes": nodes, "edges": edges}}))
        audio = FakeAudio(files=("cheer.mp3",))
        from breakfast.achievements import AchievementEngine
        ach = AchievementEngine(StatsDB(":memory:")).announce(lambda m: None, audio, scenes=sc.SceneEngine(store, audio=audio), spacing=0)
        ach.on_earned({"player": "ana", "achievement": "shanghai", "tier": 0})
        assert audio.played == []
        ach.on_earned({"player": "ana", "achievement": "bullseye", "tier": 0})
        assert [p[0] for p in audio.played] == ["cheer.mp3"]

    def test_the_unlocks_of_a_match_come_one_banner_apart(self):
        import time
        ach, audio, pushed, scenes = self.setup_announce(
            [trigger("achievement.earned"), sound("s", "cheer.mp3")], [("t", "s")], spacing=0.15)
        ach.on_earned({"player": "ana", "achievement": "bullseye", "tier": 0})
        ach.on_earned({"player": "ana", "achievement": "shanghai", "tier": 0})
        assert len(audio.played) == 1                      # the second waits for the banner of the first
        time.sleep(0.5)
        assert len(audio.played) == 2 and len(pushed) == 2

    def test_the_test_button_has_values_for_the_facts(self, client):
        c, engine, sent, _ = client
        c.post("/api/scenes/sounds/upload?name=a.mp3", content=MP3)
        sw = {"id": "w", "type": "condition", "kind": "switch", "field": "difficulty", "mode": "bands",
              "outputs": [{"id": "o1", "limit": 1}, {"id": "o2", "limit": 3}]}
        nodes = [trigger("achievement.earned"), sw, sound("s", "a.mp3")]
        made = c.post("/api/scenes", json={"name": "Hard ones", "graph": {
            "nodes": nodes, "edges": [{"from": "t", "to": "w"}, {"from": "w", "to": "s", "match": "o2"}]}}).json()
        trace = c.post(f"/api/scenes/{made['id']}/test").json()["trace"]
        assert trace[0] == {"node": "w", "result": "pass", "output": "o2"} and trace[1]["result"] == "done"

    def test_a_voice_sound_of_an_earlier_scene_takes_the_slot(self):
        engine = TestVoiceSlot.engine(
            [trigger("achievement.earned"), sound("a", "a.mp3", channel="voice")],
            [trigger("achievement.earned"), sound("b", "b.mp3", channel="voice")])
        engine.fire("achievement.earned", {"player": "ana", "id": "bullseye"}, defaults=False)
        assert [p[0] for p in engine.audio.played] == ["a.mp3"]


class TestSpeech:
    """Speech from text in the sound library (#136): the speech service is replaced by a stub."""

    @pytest.fixture
    def spoken(self, monkeypatch):
        calls = []

        async def synthesize(voice, text, rate, pitch, volume, dest, trim):
            calls.append({"voice": voice, "text": text, "rate": rate, "pitch": pitch, "volume": volume, "trim": trim})
            dest.write_bytes(MP3)

        monkeypatch.setattr("tools.generate_voicepack.synthesize", synthesize)
        return calls

    def test_the_preview_returns_audio_and_stores_nothing(self, client, spoken):
        c, engine, *_ = client
        res = c.post("/api/scenes/sounds/speech/preview", json={"text": "Well done", "pack": "ryan", "rate": 10, "pitch": -5})
        assert res.status_code == 200 and res.headers["content-type"] == "audio/mpeg" and res.content == MP3
        assert spoken == [{"voice": "en-GB-RyanNeural", "text": "Well done", "rate": "+10%", "pitch": "-5Hz", "volume": "+0%",
                           "trim": sound_edit.available()}]
        assert c.get("/api/scenes").json()["sounds"] == []

    def test_a_saved_speech_is_a_normal_file_of_the_library(self, client, spoken):
        c, engine, sent, _ = client
        body = {"text": "Nice one", "pack": "leni", "name": "nice-one.mp3"}
        assert c.post("/api/scenes/sounds/speech", json=body).json() == {"ok": True, "file": "nice-one.mp3"}
        assert [s["name"] for s in c.get("/api/scenes").json()["sounds"]] == ["nice-one.mp3"]
        assert spoken[0]["voice"] == "de-CH-LeniNeural" and spoken[0]["rate"] == "+0%"
        assert c.post("/api/scenes/sounds/nice-one.mp3/rename", json={"name": "nice.mp3"}).json()["ok"]
        assert c.delete("/api/scenes/sounds/nice.mp3").json()["ok"]

    def test_it_can_be_played_by_a_scene_and_is_picked_by_weight(self, client, spoken):
        c, engine, sent, _ = client
        c.post("/api/scenes/sounds/speech", json={"text": "One", "pack": "ryan", "name": "one.mp3"})
        c.post("/api/scenes/sounds/speech", json={"text": "Two", "pack": "ryan", "name": "two.mp3"})
        node = {"id": "s", "type": "action", "kind": "sound", "files": [{"file": "one.mp3", "weight": 1}, {"file": "two.mp3", "weight": 1}], "channel": "voice"}
        made = c.post("/api/scenes", json={"name": "Speech", "graph": graph(trigger("x01.bust"), node, edges=[("t", "s")])}).json()
        assert c.post(f"/api/scenes/{made['id']}/test").json()["trace"][0]["file"] in ("one.mp3", "two.mp3")

    @pytest.mark.parametrize("body,why", [
        ({"text": " ", "pack": "ryan", "name": "a.mp3"}, "the text is empty"),
        ({"text": "x" * 201, "pack": "ryan", "name": "a.mp3"}, "longer than 200"),
        ({"text": "x", "pack": "nobody", "name": "a.mp3"}, "unknown voice"),
        ({"text": "x", "pack": "ryan", "name": "a.mp3", "rate": 101}, "speed"),
        ({"text": "x", "pack": "ryan", "name": "a.mp3", "pitch": -51}, "pitch"),
        ({"text": "x", "pack": "ryan", "name": "../a.mp3"}, "the name must be"),
        ({"text": "x", "pack": "ryan", "name": "a.wav"}, "the name must be"),
    ])
    def test_a_request_that_cannot_be_spoken_is_refused_before_the_service_is_asked(self, client, spoken, body, why):
        c, *_ = client
        assert why in c.post("/api/scenes/sounds/speech", json=body).json()["error"]
        assert spoken == []

    def test_an_existing_name_is_kept_unless_overwritten(self, client, spoken):
        c, *_ = client
        body = {"text": "x", "pack": "ryan", "name": "a.mp3"}
        assert c.post("/api/scenes/sounds/speech", json=body).json()["ok"]
        assert "exists already" in c.post("/api/scenes/sounds/speech", json=body).json()["error"]
        assert len(spoken) == 1
        assert c.post("/api/scenes/sounds/speech", json={**body, "overwrite": True}).json()["ok"]

    def test_a_failing_service_is_reported(self, client, monkeypatch):
        c, *_ = client

        async def broken(*args, **kwargs):
            raise RuntimeError("no connection")

        monkeypatch.setattr("tools.generate_voicepack.synthesize", broken)
        answer = c.post("/api/scenes/sounds/speech", json={"text": "x", "pack": "ryan", "name": "a.mp3"}).json()
        assert "no connection" in answer["error"] and c.get("/api/scenes").json()["sounds"] == []

"""Scenes: what happens at a special moment of a game, drawn as a flow in the UI.

A scene is a graph. A trigger node names a game event (a turn scored in X01, a player eliminated, ...), condition nodes
let the flow go on or stop it (a score from 140 on, a chance of 1 in 10, one player), action nodes do something (play a
sound of the library, show an animation on the TV view, wait). Edges say what follows what, one node may lead to several.

`SceneEngine.fire()` is called by the games with an event id and the facts of the moment. It runs every enabled scene
that has a trigger for the event and returns True when one of the played sounds is marked "replace": the game then
leaves out its own call for that moment. The part of a flow after a delay runs later on a timer and cannot replace
anything any more.
"""

import contextlib
import logging
import random
import re
import threading

from . import scenes_default

log = logging.getLogger(__name__)

MAX_NODES = 60
MAX_VOLUME = 1.2      # a sound can be set 20 % louder than the library level
MAX_SOUND_FILES = 20  # files one sound step picks from
MAX_WEIGHT = 100
MAX_SWITCH_OUTPUTS = 18   # outputs of a switch, not counting "otherwise"
MAX_SWITCH_VALUES = 20
OTHERWISE = "else"        # the `match` of an edge that leaves a switch at "otherwise"
AMBIENT_VOLUME = 0.6
MATCH_STARTS = ("x01.match_start", "elim.match_start")
LEG_STARTS = ("x01.leg_start",)
MAX_NAME = 80
MAX_TEXT = 60
MAX_DELAY_S = 30
MAX_OVERLAY_S = 15
_FACT = re.compile(r"\{(\w+)\}")
_NODE_ID = re.compile(r"^[A-Za-z0-9_-]{1,24}$")

# Event id -> what the trigger offers: the label shown in the editor, the game it belongs to and the facts a condition
# can look at (name -> label). `player` is always there.
EVENTS = {
    "x01.match_start": {"label": "Match starts", "game": "X01", "fields": {"announce": "Player calls on"}},
    "x01.leg_start": {"label": "Leg starts", "game": "X01", "fields": {"announce": "Player calls on"}},
    "x01.dart": {"label": "Dart thrown", "game": "X01",
                 "fields": {"number": "Number (25 is the bull)", "multiplier": "Multiplier (0 miss, 1 single, 2 double, 3 triple)",
                            "points": "Points", "dart": "Dart of the turn", "miss": "Missed", "remaining": "Remaining"}},
    "x01.turn_start": {"label": "Turn starts", "game": "X01",
                       "fields": {"remaining": "Remaining", "checkout": "Checkout (1 call, 2 bogey number, 3 call limit reached)",
                                  "change": "Player change calls on"}},
    "x01.turn_scored": {"label": "Turn scored", "game": "X01",
                        "fields": {"score": "Turn score", "remaining": "Remaining", "total": "Turn total calls on"}},
    "x01.bust": {"label": "Bust", "game": "X01", "fields": {}},
    "x01.leg_won": {"label": "Leg won", "game": "X01",
                    "fields": {"score": "Finishing turn score", "leg": "Leg", "announce": "Player calls on"}},
    "x01.match_won": {"label": "Match won", "game": "X01",
                      "fields": {"score": "Finishing turn score", "announce": "Player calls on"}},
    "elim.match_start": {"label": "Match starts", "game": "Elimination", "fields": {}},
    "elim.dart_missed": {"label": "Missed dart", "game": "Elimination", "fields": {}},
    "elim.turn_start": {"label": "Turn starts", "game": "Elimination",
                        "fields": {"target": "Target", "lives": "Lives", "freipass": "Free pass", "next": "Score to pass"}},
    "elim.turn_counted": {"label": "Score read late", "game": "Elimination", "fields": {"score": "Turn score"}},
    "elim.passed": {"label": "Turn passed", "game": "Elimination",
                    "fields": {"score": "Turn score", "target": "Target", "margin": "Over twice the target", "preview": "Read after the 3rd dart"}},
    "elim.life_lost": {"label": "Life lost", "game": "Elimination",
                       "fields": {"score": "Turn score", "lives": "Lives left", "close": "Close", "preview": "Read after the 3rd dart", "last": "Ends the match"}},
    "elim.eliminated": {"label": "Player eliminated", "game": "Elimination",
                        "fields": {"score": "Turn score", "close": "Close", "preview": "Read after the 3rd dart", "last": "Ends the match"}},
    "elim.match_won": {"label": "Match won", "game": "Elimination", "fields": {"score": "Turn score"}},
    "achievement.earned": {"label": "Achievement earned", "game": "Achievements",
                           "fields": {"id": "Achievement", "tier": "Tier (1 for an achievement without tiers)",
                                      "difficulty": "Difficulty (1 easy to 5 extreme, 0 off the ladder)",
                                      "secret": "Secret", "first": "Earned for the first time"}},
}
OPERATORS = {
    ">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "==": lambda a, b: a == b,
    "<=": lambda a, b: a <= b, "<": lambda a, b: a < b, "!=": lambda a, b: a != b,
}
CONDITIONS = ("compare", "chance", "player", "once", "pick", "achievement", "switch")
ONCE_SCOPES = ("match", "leg")
ACTIONS = ("sound", "overlay", "delay", "call")
ANIMATIONS = ("confetti", "flash", "banner")
CHANNELS = ("voice", "ambient")


def _number(value, low, high, default):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return min(high, max(low, number))


def _text(value, limit=MAX_TEXT):
    return str(value or "").strip()[:limit]


def sound_entries(raw) -> list:
    """The files of a sound step as [{"file", "weight"}]: the list `files`, or a single `file` of a step stored before the
    list existed (weight 1). A name appears once (weights add up), an empty name is dropped."""
    items = raw.get("files") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        items = [raw.get("file")] if isinstance(raw, dict) and raw.get("file") else []
    entries = {}
    for item in items:
        name = _text(item.get("file") if isinstance(item, dict) else item, 80)
        if name:
            weight = round(_number(item.get("weight") if isinstance(item, dict) else 1, 1, MAX_WEIGHT, 1))
            entries[name] = min(MAX_WEIGHT, entries.get(name, 0) + weight)
    return [{"file": name, "weight": weight} for name, weight in list(entries.items())[:MAX_SOUND_FILES]]


def switch_outputs(raw) -> list:
    """The outputs of a switch node. Values: [{"id", "values": [...]}], a value sits on the first output that names it
    (compared without regard to case). Bands: [{"id", "limit"}] in ascending order of the limit, so a band starts where the
    one before it ends."""
    bands = isinstance(raw, dict) and raw.get("mode") == "bands"
    items = raw.get("outputs") if isinstance(raw, dict) and isinstance(raw.get("outputs"), list) else []
    outputs, ids, taken = [], {OTHERWISE}, set()
    for item in items:
        if not isinstance(item, dict) or not _NODE_ID.match(str(item.get("id", ""))) or item["id"] in ids:
            continue
        if len(outputs) >= MAX_SWITCH_OUTPUTS:
            break
        ids.add(item["id"])
        if bands:
            outputs.append({"id": item["id"], "limit": _number(item.get("limit"), -100000, 100000, 0)})
            continue
        values = item.get("values")
        values = values if isinstance(values, list) else str(values or "").split(",")
        own = []
        for value in (v.strip() for v in map(str, values)):
            if value and value.lower() not in taken and len(own) < MAX_SWITCH_VALUES:
                taken.add(value.lower())
                own.append(value[:40])
        outputs.append({"id": item["id"], "values": own})
    if bands:
        outputs.sort(key=lambda o: o["limit"])
    return outputs


def clean_node(raw: dict):
    """One node with only the fields its kind knows and sane values, None when it is not a node."""
    if not isinstance(raw, dict) or not _NODE_ID.match(str(raw.get("id", ""))):
        return None
    node = {"id": str(raw["id"]), "x": int(_number(raw.get("x"), -5000, 5000, 0)),
            "y": int(_number(raw.get("y"), -5000, 5000, 0))}
    kind = raw.get("type")
    if kind == "trigger":
        if raw.get("event") not in EVENTS:
            return None
        node.update(type="trigger", event=raw["event"])
    elif kind == "condition":
        what = raw.get("kind")
        if what not in CONDITIONS:
            return None
        node.update(type="condition", kind=what)
        if what == "compare":
            node.update(field=_text(raw.get("field"), 24) or "score",
                        op=raw.get("op") if raw.get("op") in OPERATORS else ">=",
                        value=_number(raw.get("value"), -100000, 100000, 0))
        elif what == "chance":
            node["percent"] = _number(raw.get("percent"), 0, 100, 10)
        elif what == "once":
            node.update(scope=raw.get("scope") if raw.get("scope") in ONCE_SCOPES else "match",
                        per_player=bool(raw.get("per_player")))
        elif what == "pick":
            pass
        elif what == "switch":
            mode = "bands" if raw.get("mode") == "bands" else "values"
            node.update(field=_text(raw.get("field"), 24) or "player", mode=mode, outputs=switch_outputs({**raw, "mode": mode}))
        elif what == "achievement":
            node.update(achievement=_text(raw.get("achievement"), 60), tier=int(_number(raw.get("tier"), 1, 20, 1)))
        else:
            names = raw.get("names")
            names = names if isinstance(names, list) else str(names or "").split(",")
            node["names"] = [n.strip() for n in map(str, names) if n.strip()][:20]
    elif kind == "action":
        what = raw.get("kind")
        if what not in ACTIONS:
            return None
        node.update(type="action", kind=what)
        if what == "sound":
            node.update(files=sound_entries(raw), volume=_number(raw.get("volume"), 0, MAX_VOLUME, 1),
                        replace=bool(raw.get("replace")),
                        channel=raw.get("channel") if raw.get("channel") in CHANNELS else "ambient")
        elif what == "call":
            node.update(key=_text(raw.get("key"), 160), channel="ambient" if raw.get("channel") == "ambient" else "voice")
        elif what == "overlay":
            node.update(animation=raw.get("animation") if raw.get("animation") in ANIMATIONS else "confetti",
                        text=_text(raw.get("text")), seconds=_number(raw.get("seconds"), 1, MAX_OVERLAY_S, 4))
        else:
            node["seconds"] = _number(raw.get("seconds"), 0, MAX_DELAY_S, 1)
    else:
        return None
    return node


def clean_graph(raw) -> dict:
    """A graph that is safe to store and to run: known nodes only, edges between nodes that exist."""
    raw = raw if isinstance(raw, dict) else {}
    nodes, seen = [], set()
    for item in (raw.get("nodes") if isinstance(raw.get("nodes"), list) else [])[:MAX_NODES]:
        node = clean_node(item)
        if node and node["id"] not in seen:
            seen.add(node["id"])
            nodes.append(node)
    switches = {n["id"]: {OTHERWISE, *(o["id"] for o in n["outputs"])} for n in nodes if n.get("kind") == "switch"}
    edges, pairs = [], set()
    for item in (raw.get("edges") if isinstance(raw.get("edges"), list) else [])[:MAX_NODES * 4]:
        if not isinstance(item, dict):
            continue
        a, b = item.get("from"), item.get("to")
        if a in seen and b in seen and a != b and (a, b) not in pairs:
            edge = {"from": a, "to": b}
            if a in switches:                      # an edge of a switch says which output it leaves
                if item.get("match") not in switches[a]:
                    continue
                edge["match"] = item["match"]
            elif item.get("branch") == "no":
                edge["branch"] = "no"
            pairs.add((a, b))
            weight = _number(item.get("weight"), 1, 100, 1)
            if weight != 1:
                edge["weight"] = weight
            edges.append(edge)
    return {"nodes": nodes, "edges": edges}


def clean_scene(raw: dict) -> dict:
    return {"name": _text(raw.get("name"), MAX_NAME) or "Scene", "enabled": bool(raw.get("enabled", True)),
            "graph": clean_graph(raw.get("graph"))}


def upgrade_graph(graph: dict) -> dict:
    """The graph with every sound step in the shape with a list of files (a step stored with a single `file` becomes one
    entry of weight 1). A graph that needs nothing is returned as it is."""
    nodes = graph.get("nodes", [])
    if not any(n.get("kind") == "sound" and "files" not in n for n in nodes):
        return graph
    upgraded = []
    for node in nodes:
        if node.get("kind") == "sound" and "files" not in node:
            node = {**{k: v for k, v in node.items() if k != "file"}, "files": sound_entries(node)}
        upgraded.append(node)
    return {**graph, "nodes": upgraded}


def sound_files(graph: dict) -> list:
    """The library files a graph plays."""
    return sorted({e["file"] for n in graph.get("nodes", []) if n.get("kind") == "sound" for e in sound_entries(n)})


def plays_voice(node: dict) -> bool:
    """Whether an action step plays on the voice channel: a sound with files set to "After the calls", a call set to the voice
    channel (a key that only has `ambient_` options plays beside the calls whatever the setting says)."""
    if node.get("type") != "action":
        return False
    if node.get("kind") == "sound":
        return bool(node.get("files")) and node.get("channel") == "voice"
    if node.get("kind") == "call":
        key = node.get("key") or ""
        return bool(key) and node.get("channel") != "ambient" and not all(o.strip().startswith("ambient_") for o in key.split("|"))
    return False


def x01_moments(evt: dict, snapshot: dict, caller=None) -> list:
    """The moments of the scenes in an event of the X01 stream: [(event id, facts)]. *caller*: the voice caller, whose
    settings (player calls, turn total, checkout calls) become facts of the moment."""
    if not evt or not str(evt.get("mode") or snapshot.get("game_mode") or "").upper().startswith("X01"):
        return []
    cur = snapshot.get("current") or {}
    facts = {"player": snapshot.get("active_player_name"), "remaining": cur.get("remaining"),
             "announce": 1 if getattr(caller, "call_player", True) else 0}
    handler = caller._handler_for("X01") if caller else None
    etype = evt.get("type")
    if etype == "match_started":
        return [("x01.match_start", facts)]
    if etype == "game_started":
        return [("x01.leg_start", facts)]
    if etype == "turn_end":
        extra = handler.turn_facts(snapshot, caller.audio, facts["announce"]) if handler else {"checkout": 0, "change": 0}
        return [("x01.turn_start", {**facts, **extra})]
    if etype == "bust":
        return [("x01.bust", facts)]
    if etype == "dart":
        number = evt.get("number")
        moments = [("x01.dart", {**facts, "number": number if number is not None else 0,
                                  "multiplier": evt.get("multiplier") or 0, "points": evt.get("points") or 0,
                                  "dart": evt.get("dart") or 0,
                                  "miss": 1 if evt.get("miss") or not evt.get("multiplier") else 0,
                                  "field": str(evt.get("field") or "").lower()})]
        if evt.get("dart") != 3 or cur.get("remaining") == 0:
            return moments
        score = cur.get("turn_score") or 0
        combo = "".join(str(cur.get(f"throw{i}_raw") or "").lower() for i in (1, 2, 3))
        bracket = next((t for t in (150, 120, 100, 50, 1) if score >= t), 0)
        return moments + [("x01.turn_scored", {**facts, "score": score, "combo": combo, "bracket": bracket,
                                               "total": 1 if getattr(handler, "turn_total", True) else 0})]
    if etype == "won":
        score = cur.get("turn_score") or 0
        if evt.get("scope") == "match":
            return [("x01.match_won", {**facts, "score": score})]
        return [("x01.leg_won", {**facts, "score": score, "leg": max(1, (snapshot.get("current_leg") or 2) - 1)})]
    return []


def run_x01(engine, caller, evt: dict, snapshot: dict):
    """An event of the X01 stream: the voice caller makes the calls that stay in code, then the scenes run. Without a
    caller (switched off in the settings) the standard scenes stay silent, the scenes of the user still run."""
    if caller:
        caller.on_event(evt, snapshot)
    for moment, facts in x01_moments(evt, snapshot, caller):
        batch = engine.audio.batch() if engine.audio else contextlib.nullcontext()
        with batch:                  # the calls of a moment reach the browsers in one message, in order
            engine.fire(moment, facts, defaults=caller is not None)


class MemoryScenes:
    """The scenes without a stats database: kept until the program ends."""

    def __init__(self):
        self._scenes, self._next, self._lock = {}, 1, threading.Lock()

    def list_scenes(self) -> list:
        with self._lock:
            return [dict(s, graph=dict(s["graph"])) for s in self._scenes.values()]

    def save_scene(self, scene_id, data: dict, slug=None):
        with self._lock:
            if scene_id is None:
                scene_id, self._next = self._next, self._next + 1
            elif scene_id not in self._scenes:
                return None
            self._scenes[scene_id] = {"id": scene_id, "slug": slug, **data}
            return scene_id

    def order_scenes(self, ids: list):
        with self._lock:
            first = {i: self._scenes[i] for i in ids if i in self._scenes}
            self._scenes = {**first, **{i: s for i, s in self._scenes.items() if i not in first}}

    def delete_scene(self, scene_id) -> bool:
        with self._lock:
            return self._scenes.pop(scene_id, None) is not None


class SceneEngine:
    def __init__(self, store, audio=None, overlay=None):
        """*store*: a StatsDB or MemoryScenes. *audio*: the AudioEngine. *overlay*: called with the message that the
        TV views show."""
        self.store = store or MemoryScenes()
        self.audio = audio
        self.overlay = overlay
        self.fun = False                           # the fun mode of the settings, a fact `fun` of every moment
        self._once = {"match": set(), "leg": set()}
        self.ambient_volume = AMBIENT_VOLUME       # the volume of the calls whose key starts with `ambient_`, 0 mutes them
        self._lock = threading.Lock()
        self._cache = None

    def changed(self):
        """Forget the cached scenes after one was saved or deleted."""
        with self._lock:
            self._cache = None

    def scenes(self) -> list:
        """The scenes that count: the default scenes (an edited copy in place of the original) and those of the user."""
        with self._lock:
            if self._cache is None:
                rows = self.store.list_scenes()
                edited = {r["slug"]: r for r in rows if r.get("slug") in scenes_default.BY_SLUG}
                merged = []
                for d in scenes_default.DEFAULTS:
                    row = edited.get(d["slug"])
                    merged.append({"id": d["slug"], "name": d["name"], "enabled": row["enabled"] if row else True,
                                   "graph": upgrade_graph(row["graph"] if row else d["graph"]), "default": True,
                                   "customized": bool(row), "game": d["game"]})
                merged += [{**r, "graph": upgrade_graph(r["graph"]), "default": False, "customized": False}
                           for r in rows if not r.get("slug")]
                self._cache = merged
            return self._cache

    def find(self, ref):
        """The scene with this id (a number) or slug (a default scene), None when there is none."""
        return next((s for s in self.scenes() if s["id"] == ref), None)

    def save(self, ref, data: dict):
        """Create a scene (`ref` None), replace one of the user, or store an edited copy of a default scene (`ref` its slug).
        Returns the id, None for an unknown one."""
        if isinstance(ref, str):
            if ref not in scenes_default.BY_SLUG:
                return None
            row = next((r for r in self.store.list_scenes() if r.get("slug") == ref), None)
            saved = self.store.save_scene(row["id"] if row else None, {**data, "name": scenes_default.BY_SLUG[ref]["name"]}, slug=ref)
            saved = ref if saved is not None else None
        else:
            saved = self.store.save_scene(ref, data)
        self.changed()
        return saved

    def delete(self, ref) -> bool:
        """Delete a scene of the user; for a default scene this takes the edited copy away, the original works again."""
        if isinstance(ref, str):
            row = next((r for r in self.store.list_scenes() if r.get("slug") == ref), None)
            deleted = bool(row) and self.store.delete_scene(row["id"])
        else:
            deleted = self.store.delete_scene(ref)
        self.changed()
        return deleted

    def reorder(self, ids: list):
        """Put the scenes of the user with these ids in this order. The order decides who gets the voice slot of a moment."""
        self.store.order_scenes([i for i in ids if isinstance(i, int)])
        self.changed()

    def fire(self, event: str, ctx: dict, only=None, trace=None, defaults=True) -> bool:
        """Run the scenes that start with *event*. *ctx* holds the facts of the moment (`player` and the fields the
        event lists). The scenes of the user run first; when one of them plays a sound marked "replace" the default scenes
        of the event stay out. *only*: run just this scene (a test), enabled or not. Returns True when a sound marked
        "replace" was played. *defaults*: False leaves the standard scenes out (the game's calls are switched off). The first scene
        of the user (in list order) that plays a sound or a call on the voice channel takes the voice slot of the moment: the
        voice steps of the later scenes of the user are skipped. Never raises into the game."""
        replaced = False
        try:
            ctx = {"fun": 1 if self.fun else 0, **ctx}
            if only is None:
                self._forget(event)
            everyone = self.scenes()
            slot = {"owner": None}                  # the scene of the user that plays on the voice channel at this moment
            for batch in ([s for s in everyone if not s["default"]], [s for s in everyone if s["default"]]):
                if only is None and (replaced or (batch and batch[0]["default"] and not defaults)):
                    break
                for scene in batch:
                    if only is not None and scene["id"] != only:
                        continue
                    if only is None and not scene.get("enabled"):
                        continue
                    replaced |= self._start(scene, event, ctx, trace, only is not None,
                                            None if only is not None or scene["default"] else slot)
        except Exception:
            log.exception("Scene error on %s", event)
        return replaced

    def _forget(self, event):
        """A new match (or leg) starts: what a "once" step remembered for it is forgotten."""
        with self._lock:
            if event in MATCH_STARTS:
                self._once["match"].clear()
            if event in MATCH_STARTS or event in LEG_STARTS:
                self._once["leg"].clear()

    def _start(self, scene, event, ctx, trace, test=False, slot=None) -> bool:
        graph = scene["graph"]
        follow = {}
        for edge in graph["edges"]:
            follow.setdefault(edge["from"], []).append(edge)
        run = {"nodes": {n["id"]: n for n in graph["nodes"]}, "follow": follow, "ctx": ctx, "trace": trace,
               "scene": scene["id"], "test": test, "slot": slot}
        replaced = False
        for node in graph["nodes"]:
            if node["type"] == "trigger" and node["event"] == event:
                replaced |= self._run(run, follow.get(node["id"], []), set(), True)
        return replaced

    def _run(self, run, edges, path, sync) -> bool:
        replaced = False
        for edge in edges:
            node_id = edge["to"]
            node = run["nodes"].get(node_id)
            if node is None or node_id in path:
                continue
            seen = path | {node_id}
            out = run["follow"].get(node_id, [])
            if node["type"] == "condition" and node["kind"] == "pick":
                self._note(run["trace"], node, "pick")
                if out:
                    chosen = random.choices(out, weights=[e.get("weight", 1) for e in out])[0]
                    replaced |= self._run(run, [chosen], seen, sync)
            elif node["type"] == "condition" and node["kind"] == "switch":
                chosen, why = self._switch(node, run["ctx"])
                targets = [e for e in out if e.get("match") == chosen]
                self._note(run["trace"], node, "pass" if targets else "stop", why or (None if targets else "no_output"),
                           {"output": chosen})
                replaced |= self._run(run, targets, seen, sync)
            elif node["type"] == "condition":
                ok = self._check(node, run, run["ctx"])
                self._note(run["trace"], node, "pass" if ok else "stop")
                replaced |= self._run(run, [e for e in out if (e.get("branch") == "no") != ok], seen, sync)
            elif node["kind"] == "delay":
                self._note(run["trace"], node, "wait")
                if out:
                    timer = threading.Timer(node["seconds"], self._run, (run, out, seen, False))
                    timer.daemon = True
                    timer.start()
            else:
                slot = run["slot"] if sync and plays_voice(node) else None      # a step behind a wait does not count
                if slot is not None and slot["owner"] not in (None, run["scene"]):
                    done, info = False, {}
                    self._note(run["trace"], node, "skipped", "voice_slot_taken")
                else:
                    info = {}
                    done = self._act(node, run["ctx"], info)
                    if done and slot is not None:
                        slot["owner"] = run["scene"]
                    self._note(run["trace"], node, "done" if done else "skipped",
                               None if done or run["trace"] is None else self._why(node, run["ctx"]), info)
                replaced |= bool(done and sync and node["kind"] == "sound" and node.get("replace"))
                replaced |= self._run(run, out, seen, sync)
        return replaced

    @staticmethod
    def _note(trace, node, result, why=None, info=None):
        """Add a step to the trace of a test. *info*: more the step tells (a sound step: `file` it played, `missing`)."""
        if trace is not None:
            trace.append({"node": node["id"], "result": result, **({"why": why} if why else {}), **(info or {})})

    def _why(self, node, ctx) -> str:
        """Why an action did not run, for the trace of a test: no_display, no_audio, no_file, file_missing, no_key,
        missing_fact:<names>, ambient_muted or no_sound."""
        kind = node["kind"]
        if kind == "overlay":
            return "no_display"
        if not self.audio:
            return "no_audio"
        if kind == "sound":
            return "file_missing" if node["files"] else "no_file"
        key = node.get("key") or ""
        if not key:
            return "no_key"
        missing = sorted({m for m in _FACT.findall(key) if ctx.get(m) in (None, "")})
        if missing:
            return "missing_fact:" + ",".join(missing)
        if not self.ambient_volume and all(o.strip().startswith("ambient_") for o in key.split("|")):
            return "ambient_muted"
        return "no_sound"

    @staticmethod
    def _switch(node, ctx):
        """The output a switch takes and why it is "otherwise" when the fact does not decide: (output id, None or
        `missing_fact:<name>`, `not_a_number`)."""
        field = node["field"]
        value = ctx.get(field)
        if value is None or value == "":
            return OTHERWISE, "missing_fact:" + field
        if node["mode"] == "bands":
            if not isinstance(value, (int, float)):
                return OTHERWISE, "not_a_number"
            return next((o["id"] for o in node["outputs"] if value <= o["limit"]), OTHERWISE), None
        text = str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
        text = text.strip().lower()
        return next((o["id"] for o in node["outputs"] if text in {v.lower() for v in o["values"]}), OTHERWISE), None

    def _check(self, node, run, ctx) -> bool:
        kind = node["kind"]
        if kind == "chance":
            return random.random() * 100 < node["percent"]
        if kind == "player":
            names = {n.lower() for n in node["names"]}
            return not names or str(ctx.get("player") or "").lower() in names
        if kind == "once":
            return self._once_first(node, run, ctx)
        if kind == "achievement":
            return self._has_achievement(node, ctx)
        value = ctx.get(node["field"])
        if not isinstance(value, (int, float)):
            return False
        return OPERATORS[node["op"]](value, node["value"])

    def _has_achievement(self, node, ctx) -> bool:
        """Whether the player of the moment has earned the achievement, from the tier *tier* on (an event counts as tier
        1). What is earned in the very turn of the moment is not stored yet and does not count."""
        earned = getattr(self.store, "earned_for_player", None)
        player = str(ctx.get("player") or "")
        if not earned or not player or not node.get("achievement"):
            return False
        try:
            rows = earned(player)
        except Exception:
            log.exception("Could not look up the achievements of a player")
            return False
        return any(r["achievement_id"] == node["achievement"] and (r["tier"] or 1) >= node.get("tier", 1) for r in rows)

    def _once_first(self, node, run, ctx) -> bool:
        """True the first time this step is reached in the match (or leg), False after. A test run does not use it up."""
        key = (run["scene"], node["id"], str(ctx.get("player") or "").lower() if node.get("per_player") else None)
        with self._lock:
            seen = self._once[node["scope"]]
            if key in seen:
                return False
            if not run["test"]:
                seen.add(key)
            return True

    def _act(self, node, ctx, info=None) -> bool:
        """Do an action. *info*: a dict that a sound step fills with the file it played and those it had to leave out."""
        kind = node["kind"]
        if kind == "call":
            return self._call(node["key"], ctx, node.get("channel"))
        if kind == "sound":
            return self._play_sound(node, {} if info is None else info)
        if kind == "overlay" and self.overlay:
            text = node["text"].replace("{player}", str(ctx.get("player") or ""))
            if "score" in ctx:
                text = text.replace("{score}", str(int(ctx["score"])))
            self.overlay({"type": "scene_overlay", "animation": node["animation"], "text": text,
                          "seconds": node["seconds"]})
            return True
        return False

    def _play_sound(self, node, info) -> bool:
        """Play one file of the step, picked by weight. A file that is not in the library is left out and the others
        share its weight, so the pick goes on with the rest."""
        if not self.audio:
            return False
        pool, missing = [(e["file"], e["weight"]) for e in node["files"]], []
        while pool:
            name, _ = pool.pop(random.choices(range(len(pool)), weights=[w for _, w in pool])[0])
            if self.audio.play_file(name, volume=node["volume"], channel=node["channel"]):
                info["file"] = name
                break
            missing.append(name)
        if missing:
            info["missing"] = missing
        return "file" in info

    def _call(self, key, ctx, channel=None) -> bool:
        """Play a key of the voice pack. `{player}`, `{score}` and `{next}` alone are what the moment knows. Inside a key any
        fact stands in braces (`require_{remaining}`), `a|b` tries a key after the other until one plays, `a+b` plays both. On
        the voice channel (the default) the calls wait for each other, on "ambient" one plays beside them."""
        if not self.audio or not key:
            return False
        if key == "{player}":
            name = str(ctx.get("player") or "").lower()
            return bool(name and self._play(name, channel, player=True)) or self._play("unknown_player", channel)
        if key in ("{score}", "{next}"):
            value = ctx.get("score" if key == "{score}" else "next")
            return value is not None and self._play(str(int(value)), channel)
        for option in key.split("|"):
            played = False
            for part in option.split("+"):
                played |= self._play_part(part.strip(), ctx, channel)
            if played:
                return True
        return False

    def _play_part(self, part, ctx, channel) -> bool:
        """One key with its facts filled in; False when a fact is missing."""
        missing = []

        def fill(match):
            value = ctx.get(match.group(1))
            if value is None or value == "":
                missing.append(match.group(1))
                return ""
            if match.group(1) == "player":
                return str(value).lower()
            return str(int(value)) if isinstance(value, (int, float)) else str(value)

        name = _FACT.sub(fill, part)
        return bool(name) and not missing and self._play(name, channel)

    def _play(self, name, channel, player=False) -> bool:
        """Play a key. Those that start with `ambient_` follow the ambient volume of the settings. *player*: the key is the
        name of a player, which plays an assigned name sound before the voice-pack file."""
        args = {"channel": "ambient"} if channel == "ambient" else {}
        if name.startswith("ambient_"):
            if not self.ambient_volume:
                return False
            args["volume"] = self.ambient_volume
        return self.audio.play_name(name, **args) if player else self.audio.play(name, **args)

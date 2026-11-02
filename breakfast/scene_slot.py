"""Which scenes of the user compete for the voice slot of a moment, worked out from their graphs for the editor.

At a moment the first scene of the user (in list order) that plays on the voice channel takes the slot, the voice steps of
the later ones are skipped (see `SceneEngine.fire`). The editor shows a scene when an earlier one would take the slot: a note
when it can, a warning when it always does. Two scenes that cannot both play at once because their conditions exclude each
other (other players, other bands of a score) do not compete.

A way from a trigger to a voice step is described by its conditions as constraints on a fact:
  ("in", fact, {values})            the fact is one of these values (text, lower case)
  ("out", fact, {values})           the fact is none of these
  ("range", fact, lo, lo_open, hi, hi_open, missing)   a number between the limits; *missing*: a missing fact passes too
Two ways exclude each other only when one pair of their constraints does, so a doubt is always "they compete".
"""

import math

from . import scenes

MAX_PATHS = 500


def _range_of(op, value, negate):
    """The constraint of a comparison (or of its opposite), None when it says nothing a range can hold."""
    if negate:
        op = {">=": "<", ">": "<=", "<=": ">", "<": ">=", "==": "!=", "!=": "=="}[op]
    lo, lo_open, hi, hi_open = -math.inf, True, math.inf, True
    if op == ">=":
        lo, lo_open = value, False
    elif op == ">":
        lo = value
    elif op == "<=":
        hi, hi_open = value, False
    elif op == "<":
        hi = value
    elif op == "==":
        lo, lo_open, hi, hi_open = value, False, value, False
    else:
        return None
    return lo, lo_open, hi, hi_open, negate


def _constraint(node, edge):
    """The constraint that taking *edge* out of the condition *node* puts on the moment, None for none."""
    kind = node["kind"]
    if kind == "compare":
        rng = _range_of(node["op"], node["value"], edge.get("branch") == "no")
        return ("range", node["field"], *rng) if rng else None
    if kind == "player":
        names = frozenset(n.lower() for n in node["names"])
        if not names:
            return None
        return ("out" if edge.get("branch") == "no" else "in", "player", names)
    if kind == "switch":
        outputs = node["outputs"]
        field = node["field"]
        if node["mode"] == "values":
            if edge.get("match") == scenes.OTHERWISE:
                return ("out", field, frozenset(v.lower() for o in outputs for v in o["values"]))
            hit = next((o for o in outputs if o["id"] == edge.get("match")), None)
            return ("in", field, frozenset(v.lower() for v in hit["values"])) if hit else None
        limits = [o["limit"] for o in outputs]
        if edge.get("match") == scenes.OTHERWISE:
            return ("range", field, limits[-1], True, math.inf, True, True) if limits else None
        i = next((i for i, o in enumerate(outputs) if o["id"] == edge.get("match")), None)
        if i is None:
            return None
        return ("range", field, limits[i - 1] if i else -math.inf, True, limits[i], False, False)
    return None


def voice_paths(graph: dict, event: str) -> list:
    """[(constraints, conditional)] for each way from a trigger of *event* to a voice step that runs at once (a step behind
    a wait does not count). *conditional*: a condition lies on the way."""
    nodes = {n["id"]: n for n in graph["nodes"]}
    follow = {}
    for edge in graph["edges"]:
        follow.setdefault(edge["from"], []).append(edge)
    found = []

    def walk(node_id, constraints, conditional, seen):
        node = nodes.get(node_id)
        if node is None or node_id in seen or len(found) >= MAX_PATHS:
            return
        seen = seen | {node_id}
        if node["type"] == "condition":
            conditional = True
        elif node["kind"] == "delay":
            return
        elif scenes.plays_voice(node):
            found.append((constraints, conditional))
        for edge in follow.get(node_id, []):
            extra = _constraint(node, edge) if node["type"] == "condition" else None
            walk(edge["to"], constraints + ((extra,) if extra else ()), conditional, seen)

    for trigger in graph["nodes"]:
        if trigger["type"] == "trigger" and trigger["event"] == event:
            for edge in follow.get(trigger["id"], []):
                walk(edge["to"], (), False, {trigger["id"]})
    return found


def _excludes(a, b) -> bool:
    """Whether the constraints *a* and *b* (on the same fact) cannot both hold."""
    if a[1] != b[1]:
        return False
    if a[0] == "in" and b[0] == "in":
        return not (a[2] & b[2])
    if {a[0], b[0]} == {"in", "out"}:
        inside, outside = (a, b) if a[0] == "in" else (b, a)
        return inside[2] <= outside[2]
    if a[0] == "range" and b[0] == "range":
        if a[6] and b[6]:                       # a missing fact passes both
            return False
        # the larger lower limit against the smaller upper limit; at the same value the open one counts
        low = max((a[2], a[3]), (b[2], b[3]), key=lambda x: (x[0], x[1]))
        high = min((a[4], a[5]), (b[4], b[5]), key=lambda x: (x[0], not x[1]))
        return low[0] > high[0] or (low[0] == high[0] and (low[1] or high[1]))
    return False


def exclude_each_other(a: tuple, b: tuple) -> bool:
    return any(_excludes(x, y) for x in a for y in b)


def overridden_by(scene_list: list, scene_id, graph: dict) -> list:
    """The earlier scenes of the user that take the voice slot before the scene with this graph, for the editor:
    [{"scene", "name", "event", "level"}], level `warning` when the earlier scene always takes it, else `note`.
    *scene_id*: None for a scene that is not saved yet (it comes last)."""
    earlier = []
    for scene in scene_list:
        if scene["default"]:
            continue
        if scene["id"] == scene_id:
            break
        earlier.append(scene)
    result = {}
    for event in sorted({n["event"] for n in graph["nodes"] if n["type"] == "trigger"}):
        own = voice_paths(graph, event)
        if not own:
            continue
        for other in earlier:
            if not other.get("enabled"):
                continue
            theirs = voice_paths(other["graph"], event)
            if any(not conditional for _, conditional in theirs):
                level = "warning"
            elif any(not exclude_each_other(a, b) for a, _ in own for b, _ in theirs):
                level = "note"
            else:
                continue
            if other["id"] not in result or level == "warning":
                result[other["id"]] = {"scene": other["id"], "name": other["name"], "event": event, "level": level}
    return list(result.values())

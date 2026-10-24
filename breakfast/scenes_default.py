"""The scenes that come with Breakfast: the calls a game makes by itself, drawn as flows.

A game fires an event and these scenes make the calls. A scene of this list can be edited in the Scenes tab; the edited copy is
stored under the same slug and replaces the original until it is reset. A scene of a user that plays a sound with "replace" keeps
the default scenes of that event from running.

A call is a key of the voice pack (`life_lost`). Three words stand for what the moment knows: `{player}` is the name of the
player (`unknown_player` when there is no recording of it), `{score}` the score of the turn and `{next}` the score that passes now.
Inside a key a fact stands in braces (`require_{remaining}`), `a|b` plays the first of the keys that has a sound and `a+b` plays
both. A key that starts with `ambient_` plays beside the calls, at the ambient volume of the settings.
"""

TOKENS = ("{player}", "{score}", "{next}")
GAMES = ("X01", "Elimination")
STEP_X, STEP_Y = 290, 110


def _trigger(event):
    return {"type": "trigger", "event": event}


def _call(key):
    return {"type": "action", "kind": "call", "key": key, "channel": "voice"}


def _ambient(key):
    return {"type": "action", "kind": "call", "key": key, "channel": "ambient"}


def _compare(field, op, value):
    return {"type": "condition", "kind": "compare", "field": field, "op": op, "value": value}


def _chance(percent):
    return {"type": "condition", "kind": "chance", "percent": percent}


def _seq(*specs, then=()):
    """The nodes one after the other as a tree item (node, [children]); the last one leads on to `then`."""
    item = (specs[-1], list(then))
    for spec in reversed(specs[:-1]):
        item = (spec, [item])
    return item


def _flow(root):
    """A graph from a tree of (node, [children]): the nodes in rows by depth, one column per leaf."""
    nodes, edges, columns = [], [], [0]

    def place(item, depth, parent):
        spec, children = (item, []) if isinstance(item, dict) else item
        node = {"id": f"n{len(nodes) + 1}", "y": 40 + depth * STEP_Y, **spec}
        nodes.append(node)
        if parent:
            edges.append({"from": parent, "to": node["id"]})
        xs = [place(child, depth + 1, node["id"]) for child in children]
        if xs:
            node["x"] = round(sum(xs) / len(xs))
        else:
            node["x"] = 40 + columns[0] * STEP_X
            columns[0] += 1
        return node["x"]

    place(root, 0, None)
    return {"nodes": nodes, "edges": edges}


def _comments():
    """After a lost life of a turn that was read after the third dart: `close` when it was nearly enough, `too_low` for a
    very low score."""
    return [_seq(_compare("close", "==", 1), _chance(70), _call("close")),
            _seq(_compare("close", "==", 0), _compare("score", "<", 5), _chance(50), _call("too_low"))]


def _lost(event, *calls):
    """Read after the third dart: the score, then (unless the match is over) the calls of the moment and the comments. Read
    late (fewer than three darts): the score was called already, the calls of the moment only."""
    return (_trigger(event), [
        _seq(_compare("preview", "==", 1), _call("{score}"), _compare("last", "==", 0), *(_call(c) for c in calls),
             then=_comments()),
        _seq(_compare("preview", "==", 0), _compare("last", "==", 0), *(_call(c) for c in calls))])


def _announce():
    """The call of the player's name, unless the player calls are switched off in the settings."""
    return _seq(_compare("announce", "==", 1), _call("{player}"))


def _ambient_chain(*bases):
    """The ambient sound of a moment: the one for this player first, then the general one, of each base."""
    return _ambient("|".join(f"ambient_{b}_{{player}}|ambient_{b}" for b in bases))


DEFAULTS = [
    {"slug": "x01-match-start", "name": "Match starts", "game": "X01",
     "graph": _flow((_trigger("x01.match_start"), [
         _announce(), _call("matchon|gameon"), _ambient_chain("matchon", "gameon")]))},
    {"slug": "x01-leg-start", "name": "Leg starts", "game": "X01",
     "graph": _flow((_trigger("x01.leg_start"), [_announce(), _call("gameon"), _ambient_chain("gameon")]))},
    {"slug": "x01-turn-start", "name": "Turn starts", "game": "X01",
     "graph": _flow((_trigger("x01.turn_start"), [
         _seq(_compare("checkout", "==", 2), _ambient("ambient_bogey_number_{remaining}|ambient_bogey_number")),
         _seq(_compare("checkout", "==", 1), then=[_announce(), _seq(_call("you_require"), _call("require_{remaining}"))]),
         _seq(_compare("checkout", "==", 3), _ambient("ambient_checkout_call_limit")),
         _seq(_compare("checkout", "!=", 1), then=[
             _seq(_compare("change", "==", 1), _call("{player}")), _ambient_chain("playerchange")])]))},
    {"slug": "x01-turn-scored", "name": "Turn scored", "game": "X01",
     "graph": _flow((_trigger("x01.turn_scored"), [_seq(_compare("total", "==", 1), then=[
         _call("{score}"),
         _seq(_compare("score", ">", 0), _ambient("ambient_{combo}|ambient_{score}|ambient_{bracket}more")),
         _seq(_compare("score", "==", 0), _ambient("ambient_noscore"))])]))},
    {"slug": "x01-bust", "name": "Bust", "game": "X01",
     "graph": _flow((_trigger("x01.bust"), [_seq(_call("busted")), _seq(_ambient("ambient_noscore"))]))},
    {"slug": "x01-leg-won", "name": "Leg won", "game": "X01",
     "graph": _flow((_trigger("x01.leg_won"), [
         _announce(), _call("gameshot_l{leg}_n|gameshot+leg_{leg}"), _ambient_chain("gameshot")]))},
    {"slug": "x01-match-won", "name": "Match won", "game": "X01",
     "graph": _flow((_trigger("x01.match_won"), [
         _announce(), _call("matchshot|gameshot"), _ambient_chain("matchshot", "gameshot")]))},
    {"slug": "elimination-match-start", "name": "Match starts", "game": "Elimination",
     "graph": _flow((_trigger("elim.match_start"), [_seq(_call("matchon"), _call("{player}"), _call("filler_after_name"))]))},
    {"slug": "elimination-missed-dart", "name": "Missed dart", "game": "Elimination",
     "graph": _flow((_trigger("elim.dart_missed"), [_seq(_chance(35), _call("miss"))]))},
    {"slug": "elimination-turn-passed", "name": "Turn passed", "game": "Elimination",
     "graph": _flow((_trigger("elim.passed"), [_seq(
         _compare("preview", "==", 1), _call("{score}"), _compare("margin", ">=", 0), _chance(40), _call("nice"))]))},
    {"slug": "elimination-turn-counted", "name": "Score read late", "game": "Elimination",
     "graph": _flow((_trigger("elim.turn_counted"), [_seq(_call("{score}"))]))},
    {"slug": "elimination-life-lost", "name": "Life lost", "game": "Elimination",
     "graph": _flow(_lost("elim.life_lost", "life_lost"))},
    {"slug": "elimination-eliminated", "name": "Player eliminated", "game": "Elimination",
     "graph": _flow(_lost("elim.eliminated", "{player}", "eliminated"))},
    {"slug": "elimination-match-won", "name": "Match won", "game": "Elimination",
     "graph": _flow((_trigger("elim.match_won"), [_seq(_call("{player}"), _call("matchshot"))]))},
    {"slug": "elimination-turn-start", "name": "Turn starts", "game": "Elimination",
     "graph": _flow((_trigger("elim.turn_start"), [_seq(_call("{player}"), then=[
         _seq(_compare("freipass", "==", 1), _chance(80), _call("freipass")),
         _seq(_compare("freipass", "==", 0), _call("filler_target"), _call("{next}"))])]))},
]
BY_SLUG = {d["slug"]: d for d in DEFAULTS}
CALL_KEYS = sorted({n["key"] for d in DEFAULTS for n in d["graph"]["nodes"] if n.get("kind") == "call"} - set(TOKENS))

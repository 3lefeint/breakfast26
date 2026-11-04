"""SCENES.md must say what the code does: its generated tables are current, every node field and every scene route is described,
and the example scenes survive the cleaning of the server unchanged."""

import json
import re
import subprocess
import sys
from pathlib import Path

from breakfast import scenes
from breakfast.web import server

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "SCENES.md").read_text()


def test_the_generated_tables_are_current():
    done = subprocess.run([sys.executable, str(ROOT / "tools" / "scenes_reference.py"), "--check"], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout


def documented(word: str) -> bool:
    return f"`{word}`" in DOC


def all_kinds_of_nodes():
    """One cleaned node of every kind, with every field it can hold set."""
    checks = [{"kind": "compare", "field": "score", "op": ">", "value": 1}, {"kind": "chance", "percent": 5},
              {"kind": "player", "names": ["a"]}, {"kind": "achievement", "achievement": "x", "tier": 2}]
    raw = [
        {"type": "trigger", "event": "x01.bust"},
        *({"type": "condition", "kind": k, **fields} for k, fields in {
            "compare": {"field": "score", "op": ">", "value": 1}, "chance": {"percent": 5}, "player": {"names": ["a"]},
            "once": {"scope": "leg", "per_player": True}, "pick": {}, "achievement": {"achievement": "x", "tier": 2},
            "combine": {"mode": "any", "checks": checks},
            "switch": {"field": "score", "mode": "bands", "outputs": [{"id": "o", "limit": 1}]}}.items()),
        {"type": "condition", "kind": "switch", "field": "player", "mode": "values", "outputs": [{"id": "o", "values": ["a"]}]},
        {"type": "action", "kind": "sound", "files": [{"file": "a.mp3", "weight": 2}], "volume": 1, "replace": True, "channel": "voice"},
        {"type": "action", "kind": "call", "key": "x", "channel": "ambient"},
        {"type": "action", "kind": "overlay", "animation": "flash", "text": "t", "seconds": 2},
        {"type": "action", "kind": "delay", "seconds": 2},
    ]
    nodes = [scenes.clean_node({"id": f"n{i}", **r}) for i, r in enumerate(raw)]
    assert all(nodes), "a kind of node is not cleaned any more"
    return nodes


def test_every_kind_and_field_of_a_node_is_described():
    for node in all_kinds_of_nodes():
        for key, value in node.items():
            assert documented(key), f"the field `{key}` of a {node.get('kind') or node['type']} is not in SCENES.md"
            if key in ("kind", "event") and isinstance(value, str):
                assert documented(value) or value in DOC, f"`{value}` is not in SCENES.md"
            if key == "checks":
                for check in value:
                    for name in check:
                        assert documented(name), f"the field `{name}` of a check is not in SCENES.md"
    for kind in (*scenes.CONDITIONS, *scenes.ACTIONS):
        assert documented(kind), f"the kind `{kind}` is not in SCENES.md"
    for word in ("from", "to", "branch", "match", "weight", "else", *scenes.OPERATORS, *scenes.ANIMATIONS, *scenes.CHANNELS,
                 *scenes.ONCE_SCOPES, *scenes.COMBINE_MODES, "values", "bands"):
        assert documented(word), f"`{word}` is not in SCENES.md"


def normal(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "{x}", path)


def test_every_route_of_the_scenes_is_described():
    code = {normal(r.path) for r in server.app.routes if getattr(r, "path", "").startswith("/api/scenes")}
    described = {normal(m) for m in re.findall(r"`(?:GET|POST|PUT|DELETE)` \| `(/api/scenes[^`?]*)", DOC)}
    assert code, "no scene routes found"
    assert code <= described, f"not in SCENES.md: {sorted(code - described)}"
    assert described <= code, f"in SCENES.md but not in the code: {sorted(described - code)}"


def examples():
    return [json.loads(block) for block in re.findall(r"```json scene\n(.*?)\n```", DOC, re.S)]


def test_the_examples_survive_the_cleaning():
    found = examples()
    assert len(found) >= 3
    for graph in found:
        cleaned = scenes.clean_graph(graph)
        assert [n["id"] for n in cleaned["nodes"]] == [n["id"] for n in graph["nodes"]]
        assert cleaned["edges"] == graph["edges"]
        for raw, node in zip(graph["nodes"], cleaned["nodes"]):
            for key, value in raw.items():
                assert node[key] == value, f"{raw['id']}: `{key}` is changed by the cleaning"


def test_the_swagger_ui_and_the_schema_are_served():
    from starlette.testclient import TestClient
    c = TestClient(server.app)
    page = c.get("/docs")
    assert page.status_code == 200 and "swagger" in page.text.lower()
    schema = c.get("/openapi.json").json()
    body = schema["components"]["schemas"]["SceneBody"]["properties"]["graph"]
    assert "SCENES.md" in body["description"] and body["examples"][0]["nodes"]
    cleaned = scenes.clean_graph(body["examples"][0])                               # the example of the schema is a valid graph
    assert [n["id"] for n in cleaned["nodes"]] == ["t", "c", "s"] and cleaned["edges"] == body["examples"][0]["edges"]

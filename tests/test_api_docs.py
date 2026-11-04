"""The API description (/docs, /openapi.json) has the routes in groups, and every route is in one."""

from starlette.testclient import TestClient

from breakfast.web import server


def schema():
    return TestClient(server.app).get("/openapi.json").json()


def test_every_route_is_in_a_group():
    other = sorted(path for path, ops in schema()["paths"].items() if server.api_group(path) == "Other")
    assert not other, f"no group for {other}: add its prefix to _API_GROUPS in server.py"


def test_the_groups_are_described_and_in_the_order_of_the_list():
    tags = schema()["tags"]
    names = [t["name"] for t in tags]
    assert names == [n for n, _, _ in server._API_GROUPS if n in names] and "Other" not in names
    assert all(t["description"] for t in tags)
    every = [p for _, _, prefixes in server._API_GROUPS for p in prefixes]
    assert len(every) == len(set(every)), "a prefix is in two groups"


def test_a_path_belongs_to_the_group_of_its_whole_segment():
    assert server.api_group("/api/scenes/{ref}/test") == "Scenes" and server.api_group("/api/sound/{filename}") == "Scenes"
    assert server.api_group("/api/voicepack/packs") == "Voice pack" and server.api_group("/api/voice/channels") == "Voice chat"
    assert server.api_group("/api/checkout-training/start") == "Checkout" and server.api_group("/") == "UI"
    assert server.api_group("/api/unknown") == "Other" and server.api_group("/api/scenesx") == "Other"


def test_every_operation_has_its_group_as_the_only_tag():
    for path, operations in schema()["paths"].items():
        for operation in operations.values():
            assert operation["tags"] == [server.api_group(path)]


def test_the_scenes_are_a_group_of_their_own():
    paths = [p for p, ops in schema()["paths"].items() if ops and next(iter(ops.values()))["tags"] == ["Scenes"]]
    assert "/api/scenes" in paths and all(p.startswith(("/api/scenes", "/api/sound")) for p in paths)

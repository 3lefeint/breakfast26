import pytest
from starlette.testclient import TestClient

from breakfast.web import server


class TestReadBuildInfo:
    def test_branch_and_commit_are_read(self, tmp_path):
        f = tmp_path / "build_info.txt"
        f.write_text("feature/ops-tweaks 9d3718c\n")
        assert server.read_build_info(f) == {"branch": "feature/ops-tweaks", "commit": "9d3718c"}

    def test_no_file_gives_nothing(self, tmp_path):
        assert server.read_build_info(tmp_path / "missing.txt") == {}

    @pytest.mark.parametrize("text", ["", "only-a-branch", "a b c"])
    def test_an_unusable_file_gives_nothing(self, tmp_path, text):
        f = tmp_path / "build_info.txt"
        f.write_text(text)
        assert server.read_build_info(f) == {}


class TestHealth:
    def test_the_build_is_reported_when_there_is_one(self, monkeypatch):
        monkeypatch.setattr(server, "_build_info", {"branch": "fix/x", "commit": "abc1234"})
        body = TestClient(server.app).get("/api/health").json()
        assert body["build"] == {"branch": "fix/x", "commit": "abc1234"}

    def test_the_build_is_empty_without_the_file(self, monkeypatch):
        monkeypatch.setattr(server, "_build_info", {})
        body = TestClient(server.app).get("/api/health").json()
        assert body["build"] == {}
        assert body["version"]       # the version itself stays as it was

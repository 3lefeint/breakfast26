from updater.app import _is_update_available, _parse_semver, _pick_latest_tag


class TestParseSemver:
    def test_valid(self):
        assert _parse_semver("1.2.3") == (1, 2, 3)
        assert _parse_semver("0.1.0") == (0, 1, 0)

    def test_invalid(self):
        assert _parse_semver("v1.2.3") is None  # leading 'v' not stripped here
        assert _parse_semver("1.2") is None
        assert _parse_semver("not-a-version") is None
        assert _parse_semver(None) is None
        assert _parse_semver("") is None


class TestPickLatestTag:
    def test_picks_highest_semver(self):
        tags = ["v0.1.0", "v0.10.0", "v0.2.0", "v0.9.5"]
        assert _pick_latest_tag(tags) == "v0.10.0"

    def test_ignores_non_semver_and_unprefixed_tags(self):
        tags = ["v1.0.0", "some-branch-tag", "v2.0", "1.0.0"]
        assert _pick_latest_tag(tags) == "v1.0.0"

    def test_empty_list(self):
        assert _pick_latest_tag([]) is None

    def test_no_valid_tags(self):
        assert _pick_latest_tag(["latest", "stable"]) is None

    def test_single_tag(self):
        assert _pick_latest_tag(["v0.1.0"]) == "v0.1.0"


class TestIsUpdateAvailable:
    def test_newer_latest(self):
        assert _is_update_available("0.1.0", "0.2.0") is True

    def test_same_version(self):
        assert _is_update_available("0.2.0", "0.2.0") is False

    def test_older_latest(self):
        assert _is_update_available("0.2.0", "0.1.0") is False

    def test_unparseable_current_treated_as_update_available(self):
        # Defensive: a running app that somehow reports a non-semver
        # version shouldn't block updates from ever being offered.
        assert _is_update_available("garbage", "0.1.0") is True

    def test_unparseable_latest_is_never_an_update(self):
        assert _is_update_available("0.1.0", "garbage") is False


class TestSelfRestart:
    def test_recreates_updater_from_a_detached_helper_container(self, monkeypatch):
        import subprocess
        from updater import app as updater_app

        calls = []

        def fake_run(*args, timeout=120):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, stdout="sha256:abc\n", stderr="")

        monkeypatch.setattr(updater_app, "_run", fake_run)
        monkeypatch.setattr(updater_app, "REPO_DIR", "/srv/repo")

        updater_app._self_restart()

        inspect, run = calls
        assert inspect[:2] == ("docker", "inspect")
        assert run[:4] == ("docker", "run", "-d", "--rm")
        assert "sha256:abc" in run
        assert run[-5:] == ("compose", "up", "-d", "--build", "updater")
        assert "/srv/repo:/srv/repo" in run
        assert "PWD=/srv/repo" in run

    def test_failure_is_swallowed(self, monkeypatch):
        from updater import app as updater_app

        def boom(*args, **kwargs):
            raise RuntimeError("docker unavailable")

        monkeypatch.setattr(updater_app, "_run", boom)
        updater_app._self_restart()  # must not raise


class TestDatabaseBackup:
    def test_the_copy_is_taken_and_restored(self, tmp_path, monkeypatch):
        import sqlite3
        from updater import app as updater_app

        db = tmp_path / "stats.db"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE t (v)")
        con.execute("INSERT INTO t VALUES (1)")
        con.commit()
        con.close()
        monkeypatch.setattr(updater_app, "STATS_DB", db)
        copy = updater_app._backup_db("1.5.0")
        assert copy.parent == tmp_path / "backups" and copy.name.startswith("stats-v1.5.0-")
        con = sqlite3.connect(db)
        con.execute("DELETE FROM t")
        con.commit()
        con.close()
        (tmp_path / "stats.db-wal").write_text("stale")
        updater_app._restore_db(copy)
        assert sqlite3.connect(db).execute("SELECT v FROM t").fetchall() == [(1,)]
        assert not (tmp_path / "stats.db-wal").exists()

    def test_only_the_last_three_are_kept_and_no_database_is_no_copy(self, tmp_path, monkeypatch):
        import sqlite3
        import time
        from updater import app as updater_app

        db = tmp_path / "stats.db"
        monkeypatch.setattr(updater_app, "STATS_DB", db)
        assert updater_app._backup_db("1.5.0") is None
        sqlite3.connect(db).execute("CREATE TABLE t (v)").connection.close()
        for _ in range(5):
            updater_app._backup_db("1.5.0")
            time.sleep(1.05)
        assert len(list((tmp_path / "backups").iterdir())) == 3


class TestApplyWithDatabase:
    def run_apply(self, tmp_path, monkeypatch, healthy):
        import sqlite3
        import subprocess
        from updater import app as updater_app

        db = tmp_path / "stats.db"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE t (v)")
        con.execute("INSERT INTO t VALUES (1)")
        con.commit()
        con.close()
        steps, migrated = [], []

        def fake_run(*args, **kwargs):
            steps.append(" ".join(args))
            if args[:2] == ("git", "rev-parse"):
                return subprocess.CompletedProcess(args, 0, stdout="abc\n", stderr="")
            if args[:3] == ("docker", "compose", "up") and not migrated:
                migrated.append(True)      # the new version migrates the database
                con = sqlite3.connect(db)
                con.execute("INSERT INTO t VALUES (2)")
                con.commit()
                con.close()
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        answers = iter(healthy)
        monkeypatch.setattr(updater_app, "STATS_DB", db)
        monkeypatch.setattr(updater_app, "_run", fake_run)
        monkeypatch.setattr(updater_app, "_current_version", lambda: "1.5.0")
        monkeypatch.setattr(updater_app, "_latest_tag", lambda: "v1.6.0")
        monkeypatch.setattr(updater_app, "_wait_healthy", lambda *a, **k: next(answers))
        monkeypatch.setattr(updater_app, "_self_restart", lambda: None)
        updater_app._run_apply()
        return updater_app, db, steps

    def test_a_rollback_puts_the_database_back_before_the_old_version_starts(self, tmp_path, monkeypatch):
        import sqlite3
        updater_app, db, steps = self.run_apply(tmp_path, monkeypatch, [False, True])
        assert updater_app._state["phase"] == "rolled_back" and "statistics database was restored" in updater_app._state["detail"]
        assert steps.index("docker compose stop breakfast") < len(steps) - 1
        assert steps[-1].startswith("docker compose up")
        assert sqlite3.connect(db).execute("SELECT v FROM t").fetchall() == [(1,)]

    def test_a_good_update_keeps_the_new_database_and_the_copy(self, tmp_path, monkeypatch):
        import sqlite3
        updater_app, db, steps = self.run_apply(tmp_path, monkeypatch, [True])
        assert updater_app._state["phase"] == "done"
        assert sqlite3.connect(db).execute("SELECT v FROM t").fetchall() == [(1,), (2,)]
        assert len(list((tmp_path / "backups").iterdir())) == 1

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

from breakfast import board_status


class TestResolve:
    def test_raw_status_is_forwarded_unmodified(self):
        assert board_status.resolve("Throw detected", "Takeout") == "Takeout"
        assert board_status.resolve("Throw detected", "Throw") == "Throw"
        assert board_status.resolve("Takeout started", "Takeout in progress") == "Takeout in progress"

    def test_raw_status_wins_over_event_name(self):
        assert board_status.resolve("Started", "Takeout") == "Takeout"

    def test_falls_back_to_event_map_when_no_status(self):
        assert board_status.resolve("Started", None) == "Board Started"
        assert board_status.resolve("Stopped", None) == "Board Stopped"
        assert board_status.resolve("Disconnected", None) == "Board Disconnected"

    def test_unknown_event_with_no_status_resolves_to_none(self):
        assert board_status.resolve("Something new", None) is None

    def test_empty_status_falls_back_to_event_map(self):
        assert board_status.resolve("Started", "") == "Board Started"


class TestIsIgnorable:
    def test_throw_detected_is_ignorable(self):
        assert board_status.is_ignorable("Throw detected") is True

    def test_other_events_are_not_ignorable(self):
        assert board_status.is_ignorable("Started") is False
        assert board_status.is_ignorable("Something new") is False

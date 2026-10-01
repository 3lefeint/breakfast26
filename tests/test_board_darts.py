from breakfast.board_darts import BoardDarts, _field_points


def _throw(name, x, y, number=None, multiplier=1):
    return {"segment": {"name": name, "number": number, "multiplier": multiplier}, "coords": {"x": x, "y": y}}


def _connected():
    b = BoardDarts()
    b.set_connected(True)
    return b


class TestBoardDarts:
    def test_not_connected_snapshot_is_none(self):
        assert BoardDarts().snapshot() is None

    def test_connected_without_darts_is_an_empty_list(self):
        assert _connected().snapshot() == []

    def test_numbers_darts_in_throw_order_with_field_and_points(self):
        b = _connected()
        b.update([_throw("T1", 0.16, 0.58, 1, 3), _throw("S4", 0.62, 0.43, 4, 1)])
        assert b.snapshot() == [
            {"n": 1, "field": "T1", "points": 3, "x": 0.16, "y": 0.58},
            {"n": 2, "field": "S4", "points": 4, "x": 0.62, "y": 0.43},
        ]

    def test_update_reports_change_only_when_the_darts_differ(self):
        b = _connected()
        throws = [_throw("T1", 0.16, 0.58, 1, 3)]
        assert b.update(throws) is True
        assert b.update(throws) is False
        assert b.update([]) is True

    def test_missing_coords_fall_back_to_the_field_center(self):
        b = _connected()
        b.update([{"segment": {"name": "T20", "number": 20, "multiplier": 3}}])
        assert b.snapshot() == [{"n": 1, "field": "T20", "points": 60, "x": 0.0, "y": 103 / 170}]

    def test_dart_without_coords_or_known_field_keeps_its_box_but_has_no_position(self):
        b = _connected()
        b.update([{"segment": {"name": "Outside", "number": 0, "multiplier": 0}}, _throw("S4", 0.62, 0.43, 4)])
        assert b.snapshot()[0] == {"n": 1, "field": "Outside", "points": 0, "x": None, "y": None}
        assert b.snapshot()[1]["n"] == 2

    def test_override_moves_the_dart_to_the_corrected_field(self):
        b = _connected()
        b.update([_throw("S4", 0.62, 0.43, 4), _throw("T1", 0.16, 0.58, 1, 3)])
        assert b.override(0, "t20") is True
        assert b.snapshot()[0] == {"n": 1, "field": "T20", "points": 60, "x": 0.0, "y": 103 / 170}
        assert b.snapshot()[1]["x"] == 0.16

    def test_override_survives_the_next_dart_landing(self):
        b = _connected()
        b.update([_throw("S4", 0.62, 0.43, 4)])
        b.override(0, "T20")
        b.update([_throw("S4", 0.62, 0.43, 4), _throw("T1", 0.16, 0.58, 1, 3)])
        assert b.snapshot()[0]["y"] == 103 / 170

    def test_override_is_dropped_when_the_darts_are_taken_out(self):
        b = _connected()
        b.update([_throw("S4", 0.62, 0.43, 4)])
        b.override(0, "T20")
        b.update([])
        b.update([_throw("S4", 0.62, 0.43, 4)])
        assert b.snapshot() == [{"n": 1, "field": "S4", "points": 4, "x": 0.62, "y": 0.43}]

    def test_override_ignores_unknown_field_and_missing_dart(self):
        b = _connected()
        b.update([_throw("S4", 0.62, 0.43, 4)])
        assert b.override(0, "X99") is False
        assert b.override(2, "T20") is False

    def test_disconnect_clears_everything(self):
        b = _connected()
        b.update([_throw("S4", 0.62, 0.43, 4)])
        assert b.set_connected(False) is True
        assert b.snapshot() is None
        b.set_connected(True)
        assert b.snapshot() == []


class TestFieldPoints:
    def test_fields(self):
        assert [_field_points(f) for f in ("S5", "D16", "T20", "25", "50", "0")] == [5, 32, 60, 25, 50, 0]

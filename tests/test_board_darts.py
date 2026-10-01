from breakfast.board_darts import BoardDarts


def _throw(name, x, y):
    return {"segment": {"name": name}, "coords": {"x": x, "y": y}}


def _connected():
    b = BoardDarts()
    b.set_connected(True)
    return b


class TestBoardDarts:
    def test_not_connected_snapshot_is_none(self):
        assert BoardDarts().snapshot() is None

    def test_connected_without_darts_is_an_empty_list(self):
        assert _connected().snapshot() == []

    def test_numbers_darts_in_throw_order(self):
        b = _connected()
        b.update([_throw("T1", 0.16, 0.58), _throw("S4", 0.62, 0.43)])
        assert b.snapshot() == [{"n": 1, "x": 0.16, "y": 0.58}, {"n": 2, "x": 0.62, "y": 0.43}]

    def test_update_reports_change_only_when_the_darts_differ(self):
        b = _connected()
        throws = [_throw("T1", 0.16, 0.58)]
        assert b.update(throws) is True
        assert b.update(throws) is False
        assert b.update([]) is True

    def test_missing_coords_fall_back_to_the_field_center(self):
        b = _connected()
        b.update([{"segment": {"name": "T20"}}])
        assert b.snapshot() == [{"n": 1, "x": 0.0, "y": 103 / 170}]

    def test_dart_without_coords_or_known_field_is_left_out_but_keeps_numbering(self):
        b = _connected()
        b.update([{"segment": {"name": "Outside"}}, _throw("S4", 0.62, 0.43)])
        assert b.snapshot() == [{"n": 2, "x": 0.62, "y": 0.43}]

    def test_override_moves_the_dart_to_the_corrected_field_center(self):
        b = _connected()
        b.update([_throw("S4", 0.62, 0.43), _throw("T1", 0.16, 0.58)])
        assert b.override(0, "t20") is True
        assert b.snapshot()[0] == {"n": 1, "x": 0.0, "y": 103 / 170}
        assert b.snapshot()[1]["x"] == 0.16

    def test_override_survives_the_next_dart_landing(self):
        b = _connected()
        b.update([_throw("S4", 0.62, 0.43)])
        b.override(0, "T20")
        b.update([_throw("S4", 0.62, 0.43), _throw("T1", 0.16, 0.58)])
        assert b.snapshot()[0]["y"] == 103 / 170

    def test_override_is_dropped_when_the_darts_are_taken_out(self):
        b = _connected()
        b.update([_throw("S4", 0.62, 0.43)])
        b.override(0, "T20")
        b.update([])
        b.update([_throw("S4", 0.62, 0.43)])
        assert b.snapshot() == [{"n": 1, "x": 0.62, "y": 0.43}]

    def test_override_ignores_unknown_field_and_missing_dart(self):
        b = _connected()
        b.update([_throw("S4", 0.62, 0.43)])
        assert b.override(0, "X99") is False
        assert b.override(2, "T20") is False

    def test_disconnect_clears_everything(self):
        b = _connected()
        b.update([_throw("S4", 0.62, 0.43)])
        assert b.set_connected(False) is True
        assert b.snapshot() is None
        b.set_connected(True)
        assert b.snapshot() == []

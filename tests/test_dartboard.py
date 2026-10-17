import math

from breakfast.dartboard import (
    BULL_MM, DOUBLE_IN_MM, DOUBLE_OUT_MM, OUTER_BULL_MM, SEGMENT_ORDER,
    TRIPLE_IN_MM, TRIPLE_OUT_MM, field_centers,
)


def _field_at(x, y):
    """The field a board point (unit: double ring outer edge, y up) lies in."""
    r = math.hypot(x, y) * DOUBLE_OUT_MM
    if r <= BULL_MM:
        return "50"
    if r <= OUTER_BULL_MM:
        return "25"
    if r > DOUBLE_OUT_MM:
        return "0"
    degrees = math.degrees(math.atan2(x, y)) % 360
    n = SEGMENT_ORDER[int(((degrees + 9) % 360) // 18)]
    if r <= TRIPLE_IN_MM or TRIPLE_OUT_MM < r <= DOUBLE_IN_MM:
        return f"S{n}"
    if r <= TRIPLE_OUT_MM:
        return f"T{n}"
    return f"D{n}"


class TestFieldCenters:
    def test_has_every_field(self):
        centers = field_centers()
        expected = {"0", "25", "50"} | {f"{m}{n}" for m in "SDT" for n in range(1, 21)}
        assert set(centers) == expected

    def test_every_center_lies_in_its_own_field(self):
        for field, point in field_centers().items():
            assert _field_at(point["x"], point["y"]) == field

    def test_orientation_20_on_top_1_to_its_right(self):
        centers = field_centers()
        assert centers["S20"]["x"] == 0 and centers["S20"]["y"] > 0
        assert centers["S1"]["x"] > 0 and centers["S1"]["y"] > 0
        assert centers["S6"]["x"] > 0 and abs(centers["S6"]["y"]) < 0.3
        assert centers["S3"]["y"] < 0
        assert centers["S11"]["x"] < 0

    def test_rings_are_in_order_from_the_center(self):
        centers = field_centers()
        radius = lambda f: math.hypot(centers[f]["x"], centers[f]["y"])
        assert radius("50") < radius("25") < radius("T20") < radius("S20") < radius("D20") < 1.0 < radius("0")


def test_the_segment_autodarts_stores_for_a_field():
    from breakfast.dartboard import autodarts_segment, field_centers
    centers = field_centers()
    assert autodarts_segment("t20", centers["T20"]) == {"name": "T20", "number": 20, "bed": "Triple", "multiplier": 3}
    assert autodarts_segment("D16", centers["D16"])["bed"] == "Double"
    assert autodarts_segment("50", centers["50"]) == {"name": "Bull", "number": 25, "bed": "Double", "multiplier": 2}
    assert autodarts_segment("25", centers["25"]) == {"name": "25", "number": 25, "bed": "Single", "multiplier": 1}
    assert autodarts_segment("S5", centers["S5"])["bed"] == "SingleOuter"            # the center of the field is the outer single
    assert autodarts_segment("S5", {"x": 0.0, "y": -0.3})["bed"] == "SingleInner"    # close to the bull
    assert autodarts_segment("0", {"x": 0.0, "y": 1.1}) == {"name": "M20", "number": 20, "bed": "Outside", "multiplier": 0}
    assert autodarts_segment("0", {"x": 1.1, "y": 0.0})["name"] == "M6"

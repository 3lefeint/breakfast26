import random

import pytest

from breakfast import checkout_routes as cr


def test_every_finishable_score_has_exactly_one_standard_route_and_nothing_else_has():
    finishable = {s for s in range(2, 171) if cr.finishable(s)}
    assert set(cr.STANDARD) == finishable
    assert len(finishable) == 162


def test_the_bogey_scores_are_exactly_those_no_three_darts_finish():
    assert {s for s in range(2, 171) if not cr.routes(s)} == set(cr.BOGEY)
    assert cr.routes(1) == [] and cr.routes(171) == []


@pytest.mark.parametrize("score", sorted(cr.STANDARD))
def test_a_standard_route_finishes_its_score_on_a_double_with_as_few_darts_as_possible(score):
    route = cr.STANDARD[score]
    assert sum(cr.points(f) for f in route) == score
    assert cr.is_double(route[-1])
    assert len(route) == cr.darts_to_finish(score)
    assert route in cr.routes(score)


def test_no_route_goes_below_zero_or_to_one_on_the_way():
    for score in (40, 99, 130, 170):
        for route in cr.routes(score):
            rest = score
            for field in route[:-1]:
                rest -= cr.points(field)
                assert rest >= 2


def test_the_bull_is_a_double_and_the_outer_bull_is_not():
    assert cr.is_double("50") and not cr.is_double("25") and cr.is_double("D20") and not cr.is_double("T20")
    assert cr.standard_route(50) == ["50"] and cr.standard_route(170) == ["T20", "T20", "50"]
    assert cr.standard_route(169) is None and cr.standard_route(171) is None


def test_darts_to_finish():
    assert cr.darts_to_finish(40) == 1 and cr.darts_to_finish(50) == 1
    assert cr.darts_to_finish(41) == 2 and cr.darts_to_finish(110) == 2
    assert cr.darts_to_finish(111) == 3 and cr.darts_to_finish(170) == 3
    assert cr.darts_to_finish(169) is None and cr.darts_to_finish(1) is None
    assert cr.darts_to_finish(111, darts=2) is None


def test_judging_a_first_dart():
    assert cr.judge_first_dart(81, "T19") == "standard"
    assert cr.judge_first_dart(81, "T15") == "valid"        # T15 then D18
    assert cr.judge_first_dart(81, "S20") == "valid"        # S20 then T7 then D20? 61 left: T15 D8 works
    assert cr.judge_first_dart(81, "T20") == "valid"
    assert cr.judge_first_dart(81, "S1") == "valid"
    assert cr.judge_first_dart(170, "T19") == "invalid"
    assert cr.judge_first_dart(170, "T20") == "standard"
    assert cr.judge_first_dart(169, "T20") == "invalid"


def test_valid_first_darts_of_a_double_include_the_double_itself_and_setting_it_up():
    first = cr.valid_first_darts(40)
    assert "D20" in first and "S8" in first and "S20" in first and "T20" not in first


def test_the_rest_after_darts():
    assert cr.after_darts(81, ["T19"]) == {"rest": 24, "state": "open"}
    assert cr.after_darts(40, ["D20"]) == {"rest": 0, "state": "finished"}
    assert cr.after_darts(40, ["S20", "S20"]) == {"rest": 40, "state": "bust"}     # zero without a double
    assert cr.after_darts(40, ["T20"]) == {"rest": 40, "state": "bust"}            # below zero
    assert cr.after_darts(41, ["S20", "S20"]) == {"rest": 41, "state": "bust"}   # leaves one


def test_drawing_a_score():
    rng = random.Random(1)
    for _ in range(200):
        s = cr.draw(2, 40, rng)
        assert 2 <= s <= 40 and cr.finishable(s)
    for _ in range(200):
        assert cr.draw(100, 170, rng) not in cr.BOGEY
    assert cr.draw(2, 3, rng, avoid=(2,)) == 3
    assert cr.draw(2, 2, rng, avoid=(2,)) == 2          # the only one left is allowed again
    with pytest.raises(ValueError):
        cr.draw(169, 169, rng)

import random

from breakfast.player_colors import CLOSE, PALETTE, assign_colors, distance


def test_a_color_a_player_picked_is_used_as_it_is():
    colors = assign_colors(["ana", "bo"], {"ana": "#123456"}, random.Random(1))
    assert colors["ana"] == {"color": "#123456", "ring": None}


def test_players_without_a_color_get_one_from_the_palette_and_none_twice():
    colors = assign_colors(["a", "b", "c", "d"], {}, random.Random(5))
    picked = [c["color"] for c in colors.values()]
    assert all(c in PALETTE for c in picked) and len(set(picked)) == 4
    assert all(c["ring"] is None for c in colors.values())


def test_a_palette_color_is_not_close_to_one_a_player_picked():
    for seed in range(20):
        colors = assign_colors(["ana", "bo"], {"ana": PALETTE[0]}, random.Random(seed))
        assert distance(colors["bo"]["color"], PALETTE[0]) >= CLOSE


def test_the_same_color_gives_the_later_player_a_contrasting_ring():
    colors = assign_colors(["ana", "bo"], {"ana": "#101010", "bo": "#101010"})
    assert colors["ana"]["ring"] is None
    assert colors["bo"]["ring"] == {"color": "#ffffff", "dash": False}
    light = assign_colors(["ana", "bo"], {"ana": "#f0f0a0", "bo": "#f0f0a0"})
    assert light["bo"]["ring"] == {"color": "#000000", "dash": False}


def test_colors_that_are_very_close_count_as_the_same():
    colors = assign_colors(["ana", "bo"], {"ana": "#3b82f6", "bo": "#3c83f4"})
    assert colors["bo"]["ring"] is not None


def test_colors_that_are_far_apart_need_no_ring():
    colors = assign_colors(["ana", "bo"], {"ana": "#ff0000", "bo": "#0000ff"})
    assert colors["ana"]["ring"] is None and colors["bo"]["ring"] is None


def test_rings_differ_for_a_third_and_fourth_player_of_the_same_color():
    colors = assign_colors(["a", "b", "c", "d"], {p: "#101010" for p in "abcd"})
    rings = [colors[p]["ring"] for p in "abcd"]
    assert rings[0] is None
    assert [r["color"] for r in rings[1:3]] == ["#ffffff", "#000000"]
    assert rings[3]["dash"] is True


def test_there_is_always_a_color_even_when_the_palette_is_used_up():
    players = [f"p{i}" for i in range(14)]
    colors = assign_colors(players, {}, random.Random(2))
    assert len(colors) == 14 and all(c["color"].startswith("#") and len(c["color"]) == 7 for c in colors.values())

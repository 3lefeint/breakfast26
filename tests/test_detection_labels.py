import json

from breakfast.detection import labels


def row(detected, corrected, confirmed=False, uncertain=False, margin=3.0, detected_at=None, corrected_at=None):
    r = {"t": "2026-10-16T10:00:00", "index": 0, "detected": detected, "corrected": corrected, "confirmed": confirmed,
         "detection": {"uncertain": uncertain, "margin": margin, "cams": 3, "agree": 3}}
    if detected_at:
        r["detected_at"], r["corrected_at"] = detected_at, corrected_at
    return r


class TestMistakeKind:
    def test_kinds(self):
        assert labels.mistake_kind("S20", "T20") == "ring"
        assert labels.mistake_kind("S20", "S1") == "neighbour" and labels.mistake_kind("S20", "S5") == "neighbour"
        assert labels.mistake_kind("S20", "S3") == "other"
        assert labels.mistake_kind("25", "S5") == "bull" and labels.mistake_kind("D8", "50") == "bull"
        assert labels.mistake_kind("M20", "S5") == "miss" and labels.mistake_kind("S5", "0") == "miss"


class TestSummarize:
    def test_nothing_gives_empty_numbers(self):
        s = labels.summarize([])
        assert s["looked_at"] == 0 and s["wrong_share"] is None and s["offset_mm"] is None and s["bias_mm"] is None

    def test_counts_right_and_wrong_and_the_flag(self):
        s = labels.summarize([
            row("T20", "T20", confirmed=True, uncertain=True),
            row("S5", "S5"),                                         # corrected to the same field: it was right
            row("D16", "S16", uncertain=True, margin=0.6),
            row("S1", "S18", margin=2.5),
        ])
        assert (s["looked_at"], s["right"], s["confirmed"], s["wrong"]) == (4, 2, 1, 2)
        assert s["wrong_share"] == 0.5
        assert (s["flagged_looked_at"], s["wrong_and_flagged"], s["right_but_flagged"]) == (2, 1, 1)
        assert s["mistakes"] == {"ring": 1, "neighbour": 1}
        assert {(p["detected"], p["corrected"]) for p in s["pairs"]} == {("D16", "S16"), ("S1", "S18")}

    def test_margin_buckets_count_looked_at_and_wrong(self):
        s = labels.summarize([row("D16", "S16", margin=0.6), row("T20", "T20", confirmed=True, margin=0.8),
                              row("S1", "S18", margin=2.5)])
        by = {b["from_mm"]: (b["looked_at"], b["wrong"]) for b in s["by_margin"]}
        assert by == {0.0: (2, 1), 1.0: (0, 0), 2.0: (1, 1), 4.0: (0, 0)}

    def test_distance_and_shift_of_corrected_spots(self):
        s = labels.summarize([
            row("S20", "T20", detected_at={"x": 0.0, "y": 0.50}, corrected_at={"x": 0.0, "y": 0.60}),     # 17 mm up
            row("S20", "S20", detected_at={"x": 0.1, "y": 0.50}, corrected_at={"x": 0.1, "y": 0.51}),     # 1.7 mm up
            row("S20", "S20"),                                                                            # no spots
        ])
        assert s["offset_mm"]["n"] == 2 and s["offset_mm"]["max"] == 17.0
        assert s["bias_mm"] == {"x": 0.0, "y": 9.35}


class TestRead:
    def test_a_missing_file_and_a_damaged_line_are_survived(self, tmp_path):
        assert labels.read(tmp_path / "none.jsonl") == []
        p = tmp_path / "labels.jsonl"
        p.write_text(json.dumps(row("S5", "S5", confirmed=True)) + "\n{broken\n" + json.dumps(row("S1", "S18")) + "\n")
        assert [r["detected"] for r in labels.read(p)] == ["S5", "S1"]
        assert labels.summary_of(p)["looked_at"] == 2

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


class TestDartLog:
    def test_darts_nobody_looked_at_and_darts_entered_by_hand_are_counted(self, tmp_path):
        def dart(bundle):
            return {"field": "S20", "detection": {"bundle": bundle, "uncertain": False}}
        def label(bundle, **kw):
            r = row("S20", "S20", confirmed=True); r["detection"]["bundle"] = bundle; r.update(kw); return r
        (tmp_path / "darts.jsonl").write_text("".join(json.dumps(dart(b)) + "\n" for b in ("0001-dart", "0002-dart", "0003-dart")))
        unseen = {"t": "2026-11-06T10:00:00", "index": 2, "detected": "", "corrected": "T5", "confirmed": False, "detection": None, "unseen": True}
        (tmp_path / "labels.jsonl").write_text(json.dumps(label("0002-dart")) + "\n" + json.dumps(unseen) + "\n")
        s = labels.summary_of(tmp_path / "labels.jsonl", tmp_path / "darts.jsonl")
        assert (s["darts"], s["not_looked_at"], s["unseen"]) == (3, 2, 1)
        assert (s["looked_at"], s["wrong"], s["right"]) == (1, 0, 1)         # the hand-entered dart is neither right nor wrong
        assert labels.summary_of(tmp_path / "labels.jsonl")["unseen"] == 1 and "darts" not in labels.summary_of(tmp_path / "labels.jsonl")


class TestWorkerLog:
    def _worker(self, tmp_path):
        import queue, threading
        from breakfast.detection import worker as wk
        w = object.__new__(wk.Worker)
        w.base, w.session, w.out, w.notes, w.lock = tmp_path, tmp_path / "events" / "session-1", queue.Queue(), [], threading.Lock()
        w.clips, w.seq = None, 5
        w.tracker = type("T", (), {"throws": [{"segment": {"name": "S20"}, "coords": {"x": 0.0, "y": 0.5},
                                               "detection": {"uncertain": True, "margin": 1.0, "bundle": "0001-dart"}}], "count": 1})()
        return w

    def test_a_counted_dart_is_logged_and_a_dart_beyond_the_counted_ones_is_an_unseen_label(self, tmp_path):
        w = self._worker(tmp_path)
        ev = type("E", (), {"count": 1, "throw": w.tracker.throws[0]})()
        w._log_dart(ev)
        d = [json.loads(l) for l in (tmp_path / "darts.jsonl").read_text().splitlines()]
        assert d[0]["field"] == "S20" and d[0]["session"] == "session-1" and d[0]["detection"]["bundle"] == "0001-dart"
        assert w.label(1, "T5") is True                                      # the second dart was not counted: entered by hand
        assert w.label(2, "T5") is False and w.label(1, "", confirm=True) is False
        l = [json.loads(x) for x in (tmp_path / "labels.jsonl").read_text().splitlines()]
        assert len(l) == 1 and l[0]["unseen"] is True and l[0]["corrected"] == "T5" and l[0]["detected"] == ""

    def test_a_bounce_and_a_mark_are_labels_with_their_place(self, tmp_path):
        from types import SimpleNamespace
        w = self._worker(tmp_path)
        w.clips = SimpleNamespace(last_name="clip-0007-190000", note_event=lambda *a, **k: None)
        added = []
        w.tracker.add_bouncer = lambda: added.append(1) or {"segment": {"name": "M20"}}
        assert w.bouncer() is True and added == [1]
        w.tracker.add_bouncer = lambda: None                                 # the turn is full
        assert w.bouncer() is False
        assert w.mark() is True
        l = [json.loads(x) for x in (tmp_path / "labels.jsonl").read_text().splitlines()]
        assert [r["kind"] for r in l] == ["bouncer", "mark"]
        assert l[0]["session"] == "session-1" and l[0]["clip"] == "clip-0007-190000" and l[0]["event"] == 4
        assert w.out.get_nowait()["data"]["event"] == "Dart confirmed"

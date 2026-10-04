import json

import pytest

from tools import generate_badges as gb

MODES = {"x01": {"name": "blue", "hex": "#3B82F6"}}
BADGES = [
    {"id": "one", "mode": "x01", "difficulty": "easy", "subject": "A toast"},
    {"id": "two", "mode": "x01", "difficulty": "hidden", "subject": "A dart"},
]
STYLES = {"flat": "Flat style", "pixel": "Pixel style"}
KW = dict(model="m", quality="q", size="s")


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    # A fresh timestamp for every file, so regenerated motifs never share a name.
    ticks = iter(range(10**6))
    monkeypatch.setattr(gb, "timestamp", lambda: f"20261004-{next(ticks):06d}")


@pytest.fixture(autouse=True)
def _fake_api(monkeypatch):
    # Never reach the real image API: return fixed bytes and count the calls.
    calls = []

    def fake(api_key, prompt, model, quality, size):
        calls.append(prompt)
        return b"fake png", None

    monkeypatch.setattr(gb, "request_image", fake)
    return calls


def _jobs(out, **extra):
    args = dict(selected_styles=["flat"], only=None, force=False, **KW)
    args.update(extra)
    return gb.plan_jobs(MODES, BADGES, STYLES, out, **args)


def _motifs(out, style, badge_id):
    return [p.name for p in gb.motif_files(out, style, badge_id)]


def _run(out, jobs):
    return gb.run_jobs(jobs, out, "key", max_jobs=1, **KW)


class TestPlanAndSkip:
    def test_new_motifs_are_generated_then_skipped(self, tmp_path, _fake_api):
        assert [j["action"] for j in _jobs(tmp_path)] == ["generate", "generate"]
        assert _run(tmp_path, _jobs(tmp_path)) == []
        assert len(_fake_api) == 2
        assert gb.latest_motif(tmp_path, "flat", "one").read_bytes() == b"fake png"
        assert [j["action"] for j in _jobs(tmp_path)] == ["skip", "skip"]

    def test_changed_subject_updates_only_that_motif(self, tmp_path):
        _run(tmp_path, _jobs(tmp_path))
        BADGES[1]["subject"] = "A different dart"
        try:
            assert [j["action"] for j in _jobs(tmp_path)] == ["skip", "update"]
        finally:
            BADGES[1]["subject"] = "A dart"

    def test_changed_style_text_updates_everything_of_that_style(self, tmp_path, monkeypatch):
        _run(tmp_path, _jobs(tmp_path))
        monkeypatch.setitem(STYLES, "flat", "Flat style v2")
        assert [j["action"] for j in _jobs(tmp_path)] == ["update", "update"]

    def test_force_updates_unchanged_motifs(self, tmp_path):
        _run(tmp_path, _jobs(tmp_path))
        assert [j["action"] for j in _jobs(tmp_path, force=True)] == ["update", "update"]

    def test_only_limits_the_badges(self, tmp_path):
        assert [j["id"] for j in _jobs(tmp_path, only=["two"])] == ["two"]

    def test_skipped_jobs_make_no_api_call(self, tmp_path, _fake_api):
        _run(tmp_path, _jobs(tmp_path))
        _fake_api.clear()
        _run(tmp_path, _jobs(tmp_path))
        assert _fake_api == []

    def test_failed_request_is_reported_and_not_marked_done(self, tmp_path, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("HTTP 400 nope")
        monkeypatch.setattr(gb, "request_image", boom)
        assert _run(tmp_path, _jobs(tmp_path)) == ["flat/one", "flat/two"]
        assert gb.latest_motif(tmp_path, "flat", "one") is None
        assert [j["action"] for j in _jobs(tmp_path)] == ["generate", "generate"]


class TestTimestampedFiles:
    def test_file_name_carries_a_timestamp(self, tmp_path):
        _run(tmp_path, _jobs(tmp_path, only=["one"]))
        assert _motifs(tmp_path, "flat", "one") == ["one_20261004-000000.png"]

    def test_regenerating_keeps_the_old_file_and_the_newest_counts(self, tmp_path):
        _run(tmp_path, _jobs(tmp_path, only=["one"]))
        _run(tmp_path, _jobs(tmp_path, only=["one"], force=True))
        assert _motifs(tmp_path, "flat", "one") == [
            "one_20261004-000000.png", "one_20261004-000001.png"]
        assert gb.latest_motif(tmp_path, "flat", "one").name == "one_20261004-000001.png"

    def test_moving_the_file_away_makes_it_a_new_motif_again(self, tmp_path):
        _run(tmp_path, _jobs(tmp_path, only=["one"]))
        gb.latest_motif(tmp_path, "flat", "one").unlink()
        assert [j["action"] for j in _jobs(tmp_path, only=["one"])] == ["generate"]

    def test_ids_that_start_alike_do_not_mix(self, tmp_path):
        folder = tmp_path / "flat"
        folder.mkdir()
        for name in ("big_20261004-000000.png", "big_fish_20261004-000001.png", "big.png"):
            (folder / name).write_bytes(b"x")
        assert _motifs(tmp_path, "flat", "big") == ["big.png", "big_20261004-000000.png"]
        assert _motifs(tmp_path, "flat", "big_fish") == ["big_fish_20261004-000001.png"]

    def test_plain_files_from_before_still_count_and_lose_against_stamped_ones(self, tmp_path):
        folder = tmp_path / "flat"
        folder.mkdir()
        (folder / "one.png").write_bytes(b"old")
        assert gb.latest_motif(tmp_path, "flat", "one").name == "one.png"
        (folder / "one_20261004-000000.png").write_bytes(b"new")
        assert gb.latest_motif(tmp_path, "flat", "one").name == "one_20261004-000000.png"

    def test_motif_id_drops_timestamp_and_extension(self):
        assert gb.motif_id("big_fish_20261004-120000.png") == "big_fish"
        assert gb.motif_id("big_fish.png") == "big_fish"


class TestPrompt:
    def test_prompt_has_subject_first_then_colour_style_and_requirements(self):
        prompt = gb.build_prompt("Flat style", BADGES[0], MODES["x01"])
        assert prompt.startswith("Subject, draw exactly this:\nA toast")
        assert prompt.index("blue (#3B82F6)") < prompt.index("Flat style") < prompt.index("no text")


class TestColour:
    def test_natural_colour_uses_the_mode_colour_only_as_accent(self):
        badge = dict(BADGES[0], colour="natural")
        prompt = gb.build_prompt("Flat style", badge, MODES["x01"])
        assert "natural colours" in prompt and "only as an accent" in prompt
        assert "dominant colour" not in prompt
        assert "blue (#3B82F6)" in prompt

    def test_default_is_the_dominant_mode_colour(self):
        assert "dominant colour" in gb.build_prompt("Flat style", BADGES[0], MODES["x01"])

    def test_unknown_colour_value_is_rejected(self, tmp_path):
        plan = tmp_path / "p.toml"
        plan.write_text('[modes.a]\nname="x"\nhex="#000"\n[[badge]]\nid="b"\nmode="a"\n'
                        'difficulty="easy"\nsubject="s"\ncolour="neon"\n')
        with pytest.raises(ValueError, match="colour must be"):
            gb.load_plan(plan)


class TestCheck:
    def test_reports_missing_outdated_and_orphan(self, tmp_path):
        problems = gb.check(tmp_path, BADGES, STYLES, ["flat"], modes=MODES, **KW)
        assert problems == ["missing: flat/one", "missing: flat/two"]

        _run(tmp_path, _jobs(tmp_path))
        assert gb.check(tmp_path, BADGES, STYLES, ["flat"], modes=MODES, **KW) == []

        (tmp_path / "flat" / "stray_20261004-120000.png").write_bytes(b"x")
        state = json.loads((tmp_path / "state.json").read_text())
        state["flat/one"]["hash"] = "old"
        (tmp_path / "state.json").write_text(json.dumps(state))
        assert gb.check(tmp_path, BADGES, STYLES, ["flat"], modes=MODES, **KW) == [
            "outdated: flat/one", "orphan: flat/stray_20261004-120000.png"]


class TestStylePerMode:
    MODES2 = {"x01": {"name": "blue", "hex": "#3B82F6"},
              "target_battle": {"name": "olive", "hex": "#5D5631", "style": "pixel"}}
    BADGES2 = [{"id": "one", "mode": "x01", "difficulty": "easy", "subject": "a cup"},
               {"id": "two", "mode": "target_battle", "difficulty": "easy", "subject": "a gear"}]

    def test_a_mode_style_beats_the_default(self):
        assert gb.assign_styles(self.MODES2, self.BADGES2, "flat") == {"one": "flat", "two": "pixel"}

    def test_each_badge_only_gets_the_job_of_its_style(self, tmp_path):
        assigned = gb.assign_styles(self.MODES2, self.BADGES2, "flat")
        jobs = gb.plan_jobs(self.MODES2, self.BADGES2, STYLES, tmp_path, ["flat", "pixel"], None, False,
                            assigned=assigned, **KW)
        assert [j["key"] for j in jobs] == ["flat/one", "pixel/two"]

    def test_explicit_styles_draw_every_badge(self, tmp_path):
        jobs = gb.plan_jobs(self.MODES2, self.BADGES2, STYLES, tmp_path, ["pixel"], None, False, **KW)
        assert [j["key"] for j in jobs] == ["pixel/one", "pixel/two"]

    def test_repo_plan_gives_target_battle_its_own_style(self):
        modes, badges = gb.load_plan(gb.DEFAULT_PLAN)
        styles = gb.load_styles(gb.DEFAULT_STYLES)
        assigned = gb.assign_styles(modes, badges, gb.load_default_style(gb.DEFAULT_PLAN))
        assert modes["target_battle"]["style"] == "steampunk"
        assert set(assigned.values()) <= set(styles)


class TestPlanFile:
    def test_repo_plan_is_valid_and_every_style_builds_a_prompt(self):
        modes, badges = gb.load_plan(gb.DEFAULT_PLAN)
        styles = gb.load_styles(gb.DEFAULT_STYLES)
        assert len(badges) >= 1 and "soft3d" in styles
        for badge in badges:
            for text in styles.values():
                assert badge["subject"] in gb.build_prompt(text, badge, modes[badge["mode"]])

    def test_unknown_mode_is_rejected(self, tmp_path):
        plan = tmp_path / "p.toml"
        plan.write_text('[modes.a]\nname="x"\nhex="#000"\n[[badge]]\nid="b"\nmode="zzz"\n'
                        'difficulty="easy"\nsubject="s"\n')
        with pytest.raises(ValueError, match="unknown mode"):
            gb.load_plan(plan)


class TestPreview:
    def test_preview_lists_only_existing_motifs(self, tmp_path):
        _run(tmp_path, _jobs(tmp_path, only=["one"]))
        page = gb.write_preview(tmp_path, BADGES, ["flat"]).read_text()
        assert "flat/one_20261004-000000.png" in page and "flat/two_" not in page


class TestRateLimit:
    def test_wait_is_read_from_the_api_message(self):
        msg = "Rate limit reached ... Please try again in 12s. Visit https://x"
        assert gb.parse_retry_wait(msg) == 12
        assert gb.parse_retry_wait("Please try again in 1.5s.") == 1.5
        assert gb.parse_retry_wait("Please try again in 350ms.") == 0.35
        assert gb.parse_retry_wait("no hint") == 15.0

    def test_429_is_retried_after_the_asked_pause(self, tmp_path, monkeypatch):
        sleeps = []
        monkeypatch.setattr(gb.time, "sleep", sleeps.append)
        answers = [gb.RateLimited("HTTP 429", 12), gb.RateLimited("HTTP 429", 3), (b"png", None)]

        def flaky(*a, **k):
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        monkeypatch.setattr(gb, "request_image", flaky)
        assert _run(tmp_path, _jobs(tmp_path, only=["one"])) == []
        assert sleeps == [13, 4]
        assert gb.latest_motif(tmp_path, "flat", "one").read_bytes() == b"png"

    def test_gives_up_after_the_retry_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gb.time, "sleep", lambda s: None)
        calls = []

        def always(*a, **k):
            calls.append(1)
            raise gb.RateLimited("HTTP 429", 1)

        monkeypatch.setattr(gb, "request_image", always)
        assert _run(tmp_path, _jobs(tmp_path, only=["one"])) == ["flat/one"]
        assert len(calls) == gb.RATE_LIMIT_RETRIES + 1

    def test_pacer_spaces_request_starts(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr(gb.time, "sleep", sleeps.append)
        pacer = gb.Pacer(10)
        for _ in range(3):
            pacer.wait()
        assert sleeps[0] == pytest.approx(10, abs=0.5)
        assert sleeps[1] == pytest.approx(20, abs=0.5)

    def test_zero_delay_never_sleeps(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr(gb.time, "sleep", sleeps.append)
        pacer = gb.Pacer(0)
        pacer.wait()
        pacer.wait()
        assert sleeps == []


class TestExport:
    def _generate(self, tmp_path):
        _run(tmp_path, _jobs(tmp_path))

    @staticmethod
    def _fake_magick(monkeypatch, calls):
        """ImageMagick as a double: the bounding box question gets an answer, everything else
        writes the file it was asked for."""
        monkeypatch.setattr(gb, "find_imagemagick", lambda: "magick")

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if cmd[-1] == "info:":
                return type("Done", (), {"stdout": "100x80+10+20\n"})()
            open(cmd[-1], "wb").write(b"small")

        monkeypatch.setattr(gb.subprocess, "run", fake_run)

    def test_fits_each_motif_into_the_target_folder(self, tmp_path, monkeypatch):
        self._generate(tmp_path)
        calls = []
        self._fake_magick(monkeypatch, calls)
        dest = tmp_path / "assets"
        exported, skipped, missing = gb.export_motifs(tmp_path, BADGES, "flat", dest, 128)
        assert (exported, skipped, missing) == (["one", "two"], [], [])
        assert (dest / "one.png").read_bytes() == b"small"
        final = calls[1]
        assert final[1] == str(gb.latest_motif(tmp_path, "flat", "one"))
        assert final[final.index("-crop") + 1] == "100x80+10+20"                # the motif without the margin
        assert final[final.index("-resize") + 1] == "102x102"                   # 80 % of 128
        assert final[final.index("-extent") + 1] == "128x128"
        assert final[-1] == str(dest / "one.png")                                # no timestamp in the name

    def test_faint_pixels_do_not_count_as_part_of_the_motif(self, tmp_path, monkeypatch):
        self._generate(tmp_path)
        calls = []
        self._fake_magick(monkeypatch, calls)
        gb.export_motifs(tmp_path, BADGES, "flat", tmp_path / "assets", 128, only=["one"])
        question = calls[0]
        assert "-alpha" in question and "extract" in question and "-threshold" in question

    def test_exports_the_newest_file_of_an_id(self, tmp_path, monkeypatch):
        self._generate(tmp_path)
        _run(tmp_path, _jobs(tmp_path, only=["one"], force=True))
        calls = []
        self._fake_magick(monkeypatch, calls)
        gb.export_motifs(tmp_path, BADGES, "flat", tmp_path / "assets", 128, only=["one"])
        assert calls[0][1].endswith("one_20261004-000002.png")

    def test_up_to_date_exports_are_skipped_and_missing_ones_reported(self, tmp_path, monkeypatch):
        self._generate(tmp_path)
        self._fake_magick(monkeypatch, [])
        dest = tmp_path / "assets"
        gb.export_motifs(tmp_path, BADGES, "flat", dest, 128)
        gb.latest_motif(tmp_path, "flat", "two").unlink()
        assert gb.export_motifs(tmp_path, BADGES, "flat", dest, 128) == ([], ["one"], ["two"])

    def test_force_exports_everything_again(self, tmp_path, monkeypatch):
        self._generate(tmp_path)
        self._fake_magick(monkeypatch, [])
        dest = tmp_path / "assets"
        gb.export_motifs(tmp_path, BADGES, "flat", dest, 128)
        assert gb.export_motifs(tmp_path, BADGES, "flat", dest, 128, force=True) == (["one", "two"], [], [])

    @pytest.mark.skipif(not gb.find_imagemagick(), reason="ImageMagick is not installed")
    def test_with_the_real_tool_a_small_motif_is_scaled_up_and_centered(self, tmp_path):
        import subprocess
        tool = gb.find_imagemagick()
        src, target = tmp_path / "src.png", tmp_path / "out.png"
        # A 200 x 100 canvas with a 40 x 20 motif off to the left and a faint shadow below it.
        subprocess.run([tool, "-size", "200x100", "xc:none", "-fill", "red", "-draw", "rectangle 10,10 49,29",
                        "-fill", "rgba(0,0,0,0.03)", "-draw", "rectangle 10,60 90,90", str(src)], check=True)
        gb.fit_motif(tool, src, target, 100)
        info = subprocess.run([tool, str(target), "-format", "%w %h %@", "info:"], capture_output=True,
                              text=True, check=True).stdout.split()
        assert info[:2] == ["100", "100"]
        box = info[2]                                    # the visible part, e.g. 80x40+10+30
        width, rest = box.split("x")
        height, x, y = rest.replace("+", " ").split()
        assert int(width) in (79, 80, 81) and int(height) in (39, 40, 41)     # 80 % of 100 wide, shadow ignored
        assert abs(int(x) - 10) <= 1 and abs(int(y) - 30) <= 1                 # centered


    @pytest.mark.skipif(not gb.find_imagemagick(), reason="ImageMagick is not installed")
    def test_without_fit_the_picture_keeps_its_margin_and_position(self, tmp_path):
        import subprocess
        tool = gb.find_imagemagick()
        src, target = tmp_path / "src.png", tmp_path / "out.png"
        subprocess.run([tool, "-size", "200x200", "xc:none", "-fill", "red", "-draw", "rectangle 20,20 59,59", str(src)],
                       check=True)
        gb.fit_motif(tool, src, target, 100, fit=False)
        info = subprocess.run([tool, str(target), "-format", "%w %h %@", "info:"], capture_output=True,
                              text=True, check=True).stdout.split()
        assert info[:2] == ["100", "100"]
        width, rest = info[2].split("x")
        height, x, y = rest.replace("+", " ").split()
        assert 19 <= int(width) <= 23 and abs(int(x) - 10) <= 2 and abs(int(y) - 10) <= 2

    def test_without_imagemagick_it_fails_clearly(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gb, "find_imagemagick", lambda: None)
        with pytest.raises(RuntimeError, match="ImageMagick"):
            gb.export_motifs(tmp_path, BADGES, "flat", tmp_path / "assets", 128)


class TestCosts:
    COSTS = {"gpt-image-2.5-flare": {"medium": 0.014}}

    def test_a_run_is_priced_from_the_measured_cost_per_image(self):
        assert gb.estimate_cost(self.COSTS, "gpt-image-2.5-flare", "medium", "1024x1024", 5) == \
            "estimated cost: about $0.070 for 5 images ($0.014 each)"
        assert "1 image " in gb.estimate_cost(self.COSTS, "gpt-image-2.5-flare", "medium", "1024x1024", 1)

    def test_nothing_to_generate_has_no_cost(self):
        assert gb.estimate_cost(self.COSTS, "gpt-image-2.5-flare", "medium", "1024x1024", 0) is None

    def test_an_unmeasured_model_or_quality_is_reported_as_unknown(self):
        assert "unknown" in gb.estimate_cost(self.COSTS, "gpt-image-2.5-flare", "high", "1024x1024", 2)
        assert "unknown" in gb.estimate_cost(self.COSTS, "other-model", "medium", "1024x1024", 2)

    def test_another_size_is_reported_as_unknown(self):
        assert "size 1536x1024" in gb.estimate_cost(self.COSTS, "gpt-image-2.5-flare", "medium", "1536x1024", 2)

    def test_the_table_in_the_repo_has_the_default_model_at_the_default_quality(self):
        costs = gb.load_costs()
        assert costs[gb.MODEL][gb.QUALITY] > 0

    def test_a_missing_table_means_no_known_costs(self, tmp_path):
        assert gb.load_costs(tmp_path / "none.toml") == {}


class TestMeasuredCosts:
    PRICES = {"m": {"text_input": 5.0, "image_input": 8.0, "image_output": 30.0}}
    USAGE = {"input_tokens": 100, "output_tokens": 400,
             "input_tokens_details": {"text_tokens": 100, "image_tokens": 0}}

    def test_what_an_image_cost_follows_from_the_tokens_and_the_price_per_million(self):
        assert gb.usage_cost(self.PRICES, "m", self.USAGE) == pytest.approx((100 * 5 + 400 * 30) / 1e6)
        both = {"input_tokens_details": {"text_tokens": 10, "image_tokens": 20}, "output_tokens": 0}
        assert gb.usage_cost(self.PRICES, "m", both) == pytest.approx((10 * 5 + 20 * 8) / 1e6)

    def test_without_details_all_input_counts_as_text(self):
        assert gb.usage_cost(self.PRICES, "m", {"input_tokens": 100, "output_tokens": 0}) == pytest.approx(0.0005)

    def test_an_unknown_model_or_no_usage_gives_no_cost(self):
        assert gb.usage_cost(self.PRICES, "other", self.USAGE) is None
        assert gb.usage_cost(self.PRICES, "m", None) is None

    def test_the_prices_in_the_repo_cover_the_default_model(self):
        assert set(gb.load_prices()[gb.MODEL]) == {"text_input", "image_input", "image_output"}

    def _run(self, tmp_path, monkeypatch, usage, log=True):
        monkeypatch.setattr(gb, "request_image", lambda *a, **k: (b"png", usage))
        costs = []
        jobs = gb.plan_jobs(MODES, BADGES, STYLES, tmp_path, ["flat"], None, False, **KW)
        failed = gb.run_jobs(jobs, tmp_path, "key", max_jobs=1, model="m", quality="q", size="s",
                             prices=self.PRICES, cost_log=tmp_path / "log.jsonl" if log else None, costs=costs)
        return failed, costs

    def test_every_image_is_logged_with_its_tokens_and_cost(self, tmp_path, monkeypatch, capsys):
        failed, costs = self._run(tmp_path, monkeypatch, self.USAGE)
        assert failed == [] and len(costs) == 2
        lines = [json.loads(l) for l in (tmp_path / "log.jsonl").read_text().splitlines()]
        assert [l["key"] for l in lines] == ["flat/one", "flat/two"]
        assert lines[0]["usage"] == self.USAGE and lines[0]["cost"] == pytest.approx(0.01250, abs=1e-5)
        assert (lines[0]["model"], lines[0]["quality"], lines[0]["size"]) == ("m", "q", "s")
        state = json.loads((tmp_path / "state.json").read_text())
        assert state["flat/one"]["cost"] == pytest.approx(0.0125, abs=1e-5)
        assert "($0.0125, " in capsys.readouterr().out

    def test_an_answer_without_usage_has_no_cost_but_its_time_is_still_logged(self, tmp_path, monkeypatch):
        failed, costs = self._run(tmp_path, monkeypatch, None)
        assert failed == [] and costs == []
        lines = [json.loads(l) for l in (tmp_path / "log.jsonl").read_text().splitlines()]
        assert [l["cost"] for l in lines] == [None, None] and all("seconds" in l for l in lines)
        assert gb.latest_motif(tmp_path, "flat", "one") is not None
        assert gb.measured_costs(tmp_path / "log.jsonl") == {}          # no cost, so nothing to average

    def test_without_prices_or_a_log_file_nothing_is_written(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gb, "request_image", lambda *a, **k: (b"png", self.USAGE))
        jobs = gb.plan_jobs(MODES, BADGES, STYLES, tmp_path, ["flat"], None, False, **KW)
        gb.run_jobs(jobs, tmp_path, "key", max_jobs=1, **KW)
        assert not list(tmp_path.glob("*.jsonl"))
        assert "cost" not in json.loads((tmp_path / "state.json").read_text())["flat/one"]

    def test_the_average_of_the_log_prices_the_next_run(self, tmp_path):
        log = tmp_path / "log.jsonl"
        for cost in (0.010, 0.020):
            gb.log_cost(log, {"model": "m", "quality": "q", "size": "s", "cost": cost})
        gb.log_cost(log, {"model": "m", "quality": "other", "size": "s", "cost": 0.5})
        measured = gb.measured_costs(log)
        assert measured[("m", "q", "s")] == (pytest.approx(0.015), 2)
        text = gb.estimate_cost({"m": {"q": 0.5}}, "m", "q", "s", 4, measured)
        assert text == "estimated cost: about $0.060 for 4 images ($0.015 each, average of 2 made)"

    def test_the_table_is_the_fallback_when_the_log_has_nothing(self, tmp_path):
        assert gb.measured_costs(tmp_path / "none.jsonl") == {}
        text = gb.estimate_cost({"m": {"medium": 0.014}}, "m", "medium", "1024x1024", 2, {})
        assert text == "estimated cost: about $0.028 for 2 images ($0.014 each)"

    def test_a_broken_line_in_the_log_is_skipped(self, tmp_path):
        log = tmp_path / "log.jsonl"
        log.write_text('not json\n{"model": "m"}\n')
        gb.log_cost(log, {"model": "m", "quality": "q", "size": "s", "cost": 0.01})
        assert gb.measured_costs(log) == {("m", "q", "s"): (pytest.approx(0.01), 1)}

    def test_a_measured_cost_also_serves_another_size(self):
        text = gb.estimate_cost({}, "m", "q", "1536x1024", 2, {("m", "q", "1536x1024"): (0.02, 3)})
        assert "about $0.040" in text and "average of 3 made" in text


class TestTiming:
    def _run(self, tmp_path, monkeypatch, request):
        monkeypatch.setattr(gb, "request_image", request)
        monkeypatch.setattr(gb.time, "sleep", lambda s: None)
        jobs = gb.plan_jobs(MODES, BADGES, STYLES, tmp_path, ["flat"], ["one"], False, **KW)
        gb.run_jobs(jobs, tmp_path, "key", max_jobs=1, cost_log=tmp_path / "log.jsonl", **KW)
        return [json.loads(l) for l in (tmp_path / "log.jsonl").read_text().splitlines()]

    def test_the_time_of_a_request_is_logged(self, tmp_path, monkeypatch):
        clock = iter([100.0, 100.0, 117.5])                          # called, started, finished
        monkeypatch.setattr(gb.time, "monotonic", lambda: next(clock))
        entry = self._run(tmp_path, monkeypatch, lambda *a, **k: (b"png", None))[0]
        assert entry["seconds"] == 17.5 and entry["retries"] == 0 and entry["waited"] == 0.0

    def test_rate_limit_answers_are_counted_and_their_wait_is_not_part_of_the_request(self, tmp_path, monkeypatch):
        answers = [gb.RateLimited("HTTP 429", 5), (b"png", None)]

        def flaky(*a, **k):
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        clock = iter([0.0, 1.0, 20.0, 30.0])      # called, first start (rate limited), second start, finished
        monkeypatch.setattr(gb.time, "monotonic", lambda: next(clock))
        entry = self._run(tmp_path, monkeypatch, flaky)[0]
        assert entry["retries"] == 1 and entry["waited"] == 20.0 and entry["seconds"] == 10.0

    def test_the_time_is_part_of_the_state_and_the_output(self, tmp_path, monkeypatch, capsys):
        self._run(tmp_path, monkeypatch, lambda *a, **k: (b"png", None))
        assert "seconds" in json.loads((tmp_path / "state.json").read_text())["flat/one"]
        assert " s)" in capsys.readouterr().out

    def test_the_average_time_per_image_comes_from_the_log(self, tmp_path):
        log = tmp_path / "log.jsonl"
        for seconds in (20.0, 30.0):
            gb.log_cost(log, {"model": "m", "quality": "q", "size": "s", "cost": None, "seconds": seconds})
        assert gb.measured_times(log) == {("m", "q", "s"): (25.0, 2)}
        assert gb.measured_times(tmp_path / "none.jsonl") == {}


class TestPacing:
    def test_five_per_minute_is_one_start_every_thirteen_seconds(self):
        delay, jobs = gb.pacing(5)
        assert delay == pytest.approx(12.96) and jobs == 4          # 5 per minute x 30 s assumed = 2.5, +1

    def test_twenty_per_minute_needs_more_requests_at_once(self):
        delay, jobs = gb.pacing(20, avg_seconds=25)
        assert delay == pytest.approx(3.24) and jobs == 10            # 20 x 25 s / 60 = 8.3, rounded up, +1

    def test_the_requests_in_flight_never_pass_the_limit(self):
        assert gb.pacing(1000, avg_seconds=60)[1] == gb.MAX_JOBS

    def test_delay_and_jobs_override_the_worked_out_values(self):
        assert gb.pacing(5, delay=0, jobs=2) == (0, 2)
        assert gb.pacing(20, delay=2.5) == (2.5, 11)

    def test_a_rate_of_zero_is_refused(self):
        with pytest.raises(ValueError):
            gb.pacing(0)

    def test_the_time_of_a_run_follows_the_slower_of_spacing_and_requests_in_flight(self):
        assert gb.estimate_time(0, 13, 4, 25) is None
        spaced = gb.estimate_time(10, 13, 4, 25)                      # 9 x 13 + 25 = 142 s
        assert "2.4 min" in spaced and "13.0 s" in spaced and "25 s per image measured" in spaced
        limited = gb.estimate_time(8, 1, 2, None)                     # 4 rounds x 30 s assumed = 120 s beats 7 + 30
        assert "2.0 min" in limited and "assumed" in limited
        assert gb.estimate_time(1, 13, 4, None).startswith("estimated time: about 30 s")

    def test_main_prints_the_pacing_in_a_dry_run(self, tmp_path, capsys):
        plan = tmp_path / "p.toml"
        plan.write_text('[defaults]\nstyle="flat"\n[modes.a]\nname="x"\nhex="#000"\n'
                        '[[badge]]\nid="b"\nmode="a"\ndifficulty="easy"\nsubject="s"\n')
        styles = tmp_path / "styles"
        styles.mkdir()
        (styles / "flat.txt").write_text("Flat")
        code = gb.main(["--plan", str(plan), "--styles-dir", str(styles), "--out", str(tmp_path / "out"),
                        "--dry-run", "--per-minute", "20"])
        out = capsys.readouterr().out
        assert code == 0 and "one request every 3.2 s" in out and "estimated time" in out

import logging

import main


def _make_record(level, msg="hello"):
    return logging.LogRecord(
        name="test", level=level, pathname=__file__, lineno=1,
        msg=msg, args=(), exc_info=None,
    )


class TestColorFormatter:
    def test_debug_is_blue(self):
        fmt = main._ColorFormatter("[%(levelname)s] %(message)s")
        out = fmt.format(_make_record(logging.DEBUG))
        assert "\033[34mDEBUG\033[0m" in out

    def test_info_is_green(self):
        fmt = main._ColorFormatter("[%(levelname)s] %(message)s")
        out = fmt.format(_make_record(logging.INFO))
        assert "\033[32mINFO\033[0m" in out

    def test_warning_is_yellow(self):
        fmt = main._ColorFormatter("[%(levelname)s] %(message)s")
        out = fmt.format(_make_record(logging.WARNING))
        assert "\033[33mWARNING\033[0m" in out

    def test_error_is_orange(self):
        fmt = main._ColorFormatter("[%(levelname)s] %(message)s")
        out = fmt.format(_make_record(logging.ERROR))
        assert "\033[38;5;208mERROR\033[0m" in out

    def test_critical_is_red(self):
        fmt = main._ColorFormatter("[%(levelname)s] %(message)s")
        out = fmt.format(_make_record(logging.CRITICAL))
        assert "\033[31mCRITICAL\033[0m" in out

    def test_only_levelname_is_colorized_not_the_whole_line(self):
        fmt = main._ColorFormatter("[%(levelname)s] %(message)s")
        out = fmt.format(_make_record(logging.ERROR, msg="a plain message"))
        assert "a plain message" in out
        assert "\033[" not in out.split("] ", 1)[1]

    def test_levelname_is_restored_after_formatting(self):
        # A record's levelname must not stay mutated after format() returns
        # — it's shared across every handler attached to the logger (e.g. a
        # plain file handler), so a permanent change here would leak ANSI
        # codes into the file log too.
        fmt = main._ColorFormatter("[%(levelname)s] %(message)s")
        record = _make_record(logging.ERROR)
        fmt.format(record)
        assert record.levelname == "ERROR"

    def test_second_plain_formatter_on_same_record_stays_plain(self):
        color_fmt = main._ColorFormatter("[%(levelname)s] %(message)s")
        plain_fmt = logging.Formatter("[%(levelname)s] %(message)s")
        record = _make_record(logging.ERROR)
        color_fmt.format(record)
        out = plain_fmt.format(record)
        assert "\033[" not in out


class TestSetupLogging:
    def teardown_method(self):
        logging.getLogger().handlers.clear()

    def test_stderr_handler_uses_color_formatter_by_default(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        main._setup_logging("INFO")
        root = logging.getLogger()
        assert any(isinstance(h.formatter, main._ColorFormatter) for h in root.handlers)

    def test_no_color_env_disables_color_formatter(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        main._setup_logging("INFO")
        root = logging.getLogger()
        assert not any(isinstance(h.formatter, main._ColorFormatter) for h in root.handlers)

    def test_file_handler_is_always_plain(self, monkeypatch, tmp_path):
        monkeypatch.delenv("NO_COLOR", raising=False)
        log_file = tmp_path / "test.log"
        main._setup_logging("INFO", log_file=str(log_file))
        root = logging.getLogger()
        file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) == 1
        assert not isinstance(file_handlers[0].formatter, main._ColorFormatter)

    def test_repeated_calls_dont_accumulate_handlers(self):
        main._setup_logging("INFO")
        main._setup_logging("INFO")
        root = logging.getLogger()
        assert len(root.handlers) == 1

    def test_sets_root_level(self):
        main._setup_logging("DEBUG")
        assert logging.getLogger().level == logging.DEBUG

import logging

import main


def test_log_startup_banner_logs_ascii_art_and_version(caplog):
    with caplog.at_level(logging.INFO, logger="main"):
        main._log_startup_banner()

    messages = [r.message for r in caplog.records]
    assert any("____" in m for m in messages), "figlet-style ASCII banner should be logged"
    assert any(main.__version__ in m and main.__release_date__ in m for m in messages), \
        "version + release date should be logged"


def test_banner_is_plain_ascii():
    # Deliberate: unicode box-drawing chars can render inconsistently across
    # terminals/log viewers/encodings — the banner must stay plain ASCII.
    assert main._BANNER.isascii()

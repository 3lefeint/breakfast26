import logging

from breakfast.source_direct import _Reconnect


def test_only_the_first_failure_of_an_outage_is_logged_above_debug(caplog):
    reconnect = _Reconnect("Board stream")
    with caplog.at_level(logging.DEBUG, logger="breakfast.source_direct"):
        for _ in range(5):
            reconnect.failed("ConnectionRefusedError: refused")
    levels = [r.levelno for r in caplog.records]
    assert levels == [logging.WARNING] + [logging.DEBUG] * 4


def test_the_delay_doubles_up_to_a_minute_and_starts_again_when_the_connection_is_back():
    reconnect = _Reconnect("Board stream")
    assert [reconnect.next_delay() for _ in range(7)] == [3, 6, 12, 24, 48, 60, 60]
    reconnect.opened()
    assert reconnect.next_delay() == 3


def test_a_restored_connection_is_logged_once_and_a_new_outage_is_logged_again(caplog):
    reconnect = _Reconnect("Board stream")
    with caplog.at_level(logging.INFO, logger="breakfast.source_direct"):
        reconnect.failed("refused")
        reconnect.opened()
        reconnect.opened()                    # an open without an outage says nothing
        reconnect.failed("refused again")
    assert [r.levelno for r in caplog.records] == [logging.WARNING, logging.INFO, logging.WARNING]
    assert "restored" in caplog.records[1].getMessage()

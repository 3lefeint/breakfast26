"""Joke of the day for the About page: fetched from icanhazdadjoke.com, cached in
memory per day, with built-in jokes when the request fails."""

import logging
import time
from datetime import datetime, timezone

import requests

log = logging.getLogger(__name__)

_URL = "https://icanhazdadjoke.com/"
_TIMEOUT_S = 3
_RETRY_AFTER_S = 600   # after a failed request, use the built-in joke this long

FALLBACK_JOKES = (
    "Why did the dartboard get a promotion? It was always on target.",
    "I told my friend I'd hit a double 20. He said, \"Sure, and I'll hit the lottery.\" We're both still waiting.",
    "Why don't darts players ever get lost? They always know where the bull is.",
    "My darts teammate is like a bad checkout: he keeps leaving me on one.",
    "What do you call a dart that misses the board? A very expensive wall decoration.",
)

_cache = {"day": None, "joke": None}
_failed_at = None


def _fetch() -> str:
    res = requests.get(_URL, headers={"Accept": "application/json", "User-Agent": "breakfast"},
                       timeout=_TIMEOUT_S)
    res.raise_for_status()
    joke = (res.json().get("joke") or "").strip()
    if not joke:
        raise ValueError("empty joke")
    return joke


def joke_of_the_day(now=None, fetch=None) -> dict:
    """{joke, source}; source is "icanhazdadjoke" or "builtin"."""
    global _failed_at
    fetch = fetch or _fetch
    now = now or datetime.now(timezone.utc)
    day = now.date()
    if _cache["day"] == day:
        return {"joke": _cache["joke"], "source": "icanhazdadjoke"}
    if _failed_at is None or time.monotonic() - _failed_at >= _RETRY_AFTER_S:
        try:
            joke = fetch()
        except Exception as e:
            _failed_at = time.monotonic()
            log.warning("Joke of the day not fetched, using a built-in one: %s", e)
        else:
            _failed_at = None
            _cache.update(day=day, joke=joke)
            return {"joke": joke, "source": "icanhazdadjoke"}
    return {"joke": FALLBACK_JOKES[day.toordinal() % len(FALLBACK_JOKES)], "source": "builtin"}


def reset() -> None:
    """Forget the cache and a recent failure (tests)."""
    global _failed_at
    _cache.update(day=None, joke=None)
    _failed_at = None

"""Timeout-guarded RSS fetch.

``feedparser.parse(url_string)`` performs its own network fetch internally with
no configurable timeout - a single hung feed can hang an entire collector run
indefinitely. This module always fetches bytes ourselves first (a real,
per-request timeout), then hands those bytes to ``feedparser.parse``, which
never touches the network when given bytes. Every caller must catch per-feed
failures individually so one feed's timeout/error never aborts the others -
see ``fetch_feed`` for that isolation.
"""

from __future__ import annotations

from urllib.error import URLError
from urllib.request import Request, urlopen

import feedparser


class FeedFetchError(Exception):
    """A single feed's fetch failed; the caller should skip it and continue."""


def fetch_bytes(url: str, *, timeout: float, user_agent: str) -> bytes:
    request = Request(url, headers={"User-Agent": user_agent})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except (URLError, OSError, ValueError) as exc:
        raise FeedFetchError(f"{url}: {exc}") from exc


def fetch_feed(url: str, *, timeout: float, user_agent: str):
    """Return a parsed feed, or raise ``FeedFetchError`` - never lets a network
    exception or hang from one feed propagate past this call."""
    data = fetch_bytes(url, timeout=timeout, user_agent=user_agent)
    return feedparser.parse(data)

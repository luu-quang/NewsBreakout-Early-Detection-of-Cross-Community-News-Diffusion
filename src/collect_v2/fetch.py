"""Timeout-guarded RSS fetch.

``feedparser.parse(url_string)`` performs its own network fetch internally with
no configurable timeout - a single hung feed can hang an entire collector run
indefinitely. This module always fetches bytes ourselves first (a real,
per-request timeout), then hands those bytes to ``feedparser.parse``, which
never touches the network when given bytes. Every caller must catch per-feed
failures individually so one feed's timeout/error never aborts the others -
see ``fetch_feed`` for that isolation.

Some publishers' CDNs gzip-compress the response even without an explicit
``Accept-Encoding`` request header (found the hard way: several Phase 5 feeds
silently produced zero candidates for hours - ``feedparser.parse(bytes)``
fails to parse raw gzip bytes as XML, and reports it as an unhelpful
"not well-formed (invalid token)" bozo exception rather than a fetch error).
``fetch_bytes`` always decompresses based on ``Content-Encoding``, matching
what ``feedparser.parse(url_string)``'s own internal fetcher - and every
browser and ``requests`` call - already does automatically.
"""

from __future__ import annotations

import gzip
import zlib
from urllib.error import URLError
from urllib.request import Request, urlopen

import feedparser


class FeedFetchError(Exception):
    """A single feed's fetch failed; the caller should skip it and continue."""


def _decode_content_encoding(data: bytes, content_encoding: str, url: str) -> bytes:
    encoding = content_encoding.lower().strip()
    if encoding in ("", "identity"):
        return data
    if encoding == "gzip":
        try:
            return gzip.decompress(data)
        except OSError as exc:
            raise FeedFetchError(f"{url}: failed to gzip-decompress response: {exc}") from exc
    if encoding == "deflate":
        try:
            return zlib.decompress(data)
        except zlib.error:
            # Some servers send raw deflate (no zlib header) despite the RFC.
            try:
                return zlib.decompress(data, -zlib.MAX_WBITS)
            except zlib.error as exc:
                raise FeedFetchError(f"{url}: failed to deflate-decompress response: {exc}") from exc
    raise FeedFetchError(f"{url}: unsupported Content-Encoding {content_encoding!r}")


def fetch_bytes(url: str, *, timeout: float, user_agent: str) -> bytes:
    request = Request(url, headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read()
            content_encoding = response.headers.get("Content-Encoding", "")
    except (URLError, OSError, ValueError) as exc:
        raise FeedFetchError(f"{url}: {exc}") from exc
    return _decode_content_encoding(data, content_encoding, url)


def fetch_feed(url: str, *, timeout: float, user_agent: str):
    """Return a parsed feed, or raise ``FeedFetchError`` - never lets a network
    exception or hang from one feed propagate past this call."""
    data = fetch_bytes(url, timeout=timeout, user_agent=user_agent)
    return feedparser.parse(data)

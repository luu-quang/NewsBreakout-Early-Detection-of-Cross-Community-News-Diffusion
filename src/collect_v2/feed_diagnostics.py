"""Per-feed monitoring: what happened to each individual feed on one
continuous-mode run, machine-readable end to end.

Built the hard way: the gzip bug (see ``fetch.py``) ran silently for 6+ hours
because the only visibility into a run was 2 aggregate numbers
(``entries_seen``, ``new_payloads``) - a feed silently returning zero entries
every run was indistinguishable from a feed with genuinely nothing new to
report. Every ``collect_vn.py``/``collect_intl.py`` continuous run now prints
one JSON line per feed's outcome; ``runner.py`` reads it back from the
child's captured stdout and folds it into the heartbeat record as
``per_feed``, so the failure mode that took 6 hours to notice manually would
now show up in the very next heartbeat.
"""

from __future__ import annotations

import json

PER_FEED_LINE_PREFIX = "PER_FEED_JSON:"


def make_result(
    feed_id: str,
    feed_url: str,
    *,
    http_status: int | None,
    content_encoding: str | None,
    n_entries: int,
    n_new: int,
    error: str | None,
) -> dict:
    return {
        "feed_id": feed_id,
        "feed_url": feed_url,
        "http_status": http_status,
        "content_encoding": content_encoding,
        "n_entries": n_entries,
        "n_new": n_new,
        "error": error,
    }


def print_per_feed_results(results: list[dict]) -> None:
    """Emits the one machine-readable line callers grep for. Kept on its own
    line with a fixed prefix (rather than assumed to be the literal last line
    of stdout) so it survives extra prints before/after it."""
    print(PER_FEED_LINE_PREFIX + json.dumps(results, ensure_ascii=False, separators=(",", ":")))


def parse_per_feed_results(stdout: str) -> list[dict] | None:
    """Reads ``print_per_feed_results``'s line back out of a child process's
    captured stdout. ``None`` if the line is missing (e.g. the child crashed
    before reaching it) - never raises on malformed input, since a monitoring
    helper failing must never mask the underlying child failure it's trying
    to help diagnose."""
    for line in reversed(stdout.splitlines()):
        if line.startswith(PER_FEED_LINE_PREFIX):
            try:
                return json.loads(line[len(PER_FEED_LINE_PREFIX):])
            except json.JSONDecodeError:
                return None
    return None

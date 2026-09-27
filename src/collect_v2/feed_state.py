"""Per-feed first-observed tracking, for excluding RSS backlog from later
timing analysis (e.g. Vietnamnet's ~30-day feed depth means its first-ever
poll retroactively picks up a month of history that never "arrived" in real
time).

Deliberately NOT ``collection_mode``: that field already has a different,
frozen meaning in the shared contract (GDELT ``historical_backfill`` vs
``prospective``), and this module never touches the candidate table, the
audit table, or ``build_master.py`` at all. It is a separate, analysis-facing
artifact - a single small state file, written once per feed at its first
successful poll and never overwritten, plus ``is_pre_start()`` for whoever
does that analysis to call against it.

A feed with zero entries on every one of its early polls (unusual for a real
news feed) never gets recorded, since there is nothing here to distinguish
"never successfully polled" from "polled but genuinely empty" - accepted as a
rare edge case rather than plumbing an extra signal through for it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from . import paths


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def record_first_seen_batch(
    branch: str, collector_host: str, feed_locators: dict[str, str | None], observed_at: str
) -> None:
    """``feed_locators``: {feed_locator: publisher_id_hint} for feeds that
    returned at least one entry this run. Idempotent and never overwrites: a
    feed already present keeps its original ``feed_started_at`` forever. One
    read-modify-write for the whole batch, not one file rewrite per feed."""
    if not feed_locators:
        return
    path = paths.feed_state_path()
    state = _load(path)
    host_state = state.setdefault(branch, {}).setdefault(collector_host, {})
    changed = False
    for feed_locator, hint in feed_locators.items():
        if feed_locator not in host_state:
            host_state[feed_locator] = {"feed_started_at": observed_at, "publisher_id_hint": hint}
            changed = True
    if changed:
        _atomic_write_json(path, state)


def load_state() -> dict:
    return _load(paths.feed_state_path())


def get_feed_started_at(state: dict, branch: str, collector_host: str, feed_locator: str) -> str | None:
    return state.get(branch, {}).get(collector_host, {}).get(feed_locator, {}).get("feed_started_at")


def is_pre_start(
    published_at: object, branch: str, collector_host: str, feed_locator: str, state: dict
) -> bool | None:
    """True if ``published_at`` predates this feed's recorded first-seen time
    (likely RSS backlog picked up on an early poll, not something caught
    arriving in real time). None if this cannot be determined - no start
    recorded yet for this feed, or ``published_at`` is missing/unparseable -
    callers must treat None as "unknown", never silently as "not pre-start".

    ``pd.isna()`` (not just ``not published_at``) is required to catch a
    missing value stored as a real ``float('nan')`` (as a parquet column of
    otherwise-string timestamps stores its nulls) - found the hard way: NaN
    is truthy in plain Python (``not float('nan')`` is ``False``), so it
    used to fall through this guard entirely, and ``pd.Timestamp(nan) <
    pd.Timestamp(started_at)`` silently evaluates to ``False`` (NaT
    comparisons never raise) instead of raising - meaning a row with
    genuinely unknown ``published_at`` was silently mislabeled
    ``is_pre_start=False`` instead of ``None``."""
    started_at = get_feed_started_at(state, branch, collector_host, feed_locator)
    if started_at is None or pd.isna(published_at) or not published_at:
        return None
    try:
        return bool(pd.Timestamp(published_at) < pd.Timestamp(started_at))
    except (TypeError, ValueError):
        return None

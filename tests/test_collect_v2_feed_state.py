"""Tests for per-feed first-observed tracking (feed_state.py) and its wiring
into collect_vn.py / collect_intl.py's collect_continuous(). The wiring tests
mock the network fetch entirely - no real feeds are hit.
"""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pytest

from src.collect_v2 import feed_diagnostics, feed_state, paths

REPO_ROOT = Path(__file__).resolve().parents[1]
COLLECT_VN_PATH = REPO_ROOT / "team_work/phases/phase1_collection_cleaning/vietnamese_team/code/collect_vn.py"
COLLECT_INTL_PATH = REPO_ROOT / "team_work/phases/phase1_collection_cleaning/international_team/code/collect_intl.py"


def _load_module(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _isolated_v2_root(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(paths, "V2_ROOT", tmp_path / "v2")
    yield


# --- feed_state module itself --------------------------------------------------------------


def test_record_first_seen_writes_new_feed():
    feed_state.record_first_seen_batch("domestic", "host-a", {"https://a/rss": "a"}, "2026-09-26T00:00:00Z")
    state = feed_state.load_state()
    assert feed_state.get_feed_started_at(state, "domestic", "host-a", "https://a/rss") == "2026-09-26T00:00:00Z"


def test_record_first_seen_never_overwrites():
    feed_state.record_first_seen_batch("domestic", "host-a", {"https://a/rss": "a"}, "2026-09-26T00:00:00Z")
    feed_state.record_first_seen_batch("domestic", "host-a", {"https://a/rss": "a"}, "2026-09-26T01:00:00Z")
    state = feed_state.load_state()
    assert feed_state.get_feed_started_at(state, "domestic", "host-a", "https://a/rss") == "2026-09-26T00:00:00Z"


def test_adding_a_new_feed_only_creates_a_start_for_that_feed():
    feed_state.record_first_seen_batch("domestic", "host-a", {"https://a/rss": "a"}, "2026-09-26T00:00:00Z")
    # Phase 5: a second feed is added later, at a different first-poll time.
    feed_state.record_first_seen_batch(
        "domestic", "host-a", {"https://a/rss": "a", "https://b/rss": "b"}, "2026-10-01T00:00:00Z"
    )
    state = feed_state.load_state()
    assert feed_state.get_feed_started_at(state, "domestic", "host-a", "https://a/rss") == "2026-09-26T00:00:00Z"
    assert feed_state.get_feed_started_at(state, "domestic", "host-a", "https://b/rss") == "2026-10-01T00:00:00Z"


def test_branches_and_hosts_are_kept_separate():
    feed_state.record_first_seen_batch("domestic", "host-a", {"https://x/rss": "x"}, "t0")
    feed_state.record_first_seen_batch("international", "host-a", {"https://x/rss": "x"}, "t1")
    feed_state.record_first_seen_batch("domestic", "host-b", {"https://x/rss": "x"}, "t2")
    state = feed_state.load_state()
    assert feed_state.get_feed_started_at(state, "domestic", "host-a", "https://x/rss") == "t0"
    assert feed_state.get_feed_started_at(state, "international", "host-a", "https://x/rss") == "t1"
    assert feed_state.get_feed_started_at(state, "domestic", "host-b", "https://x/rss") == "t2"


def test_empty_batch_is_a_noop_does_not_create_file():
    feed_state.record_first_seen_batch("domestic", "host-a", {}, "t0")
    assert not paths.feed_state_path().exists()


def test_state_file_is_atomic_write(tmp_path: Path):
    feed_state.record_first_seen_batch("domestic", "host-a", {"https://a/rss": "a"}, "t0")
    assert list(paths.feed_state_path().parent.glob("*.tmp-*")) == []


def test_get_feed_started_at_unknown_feed_returns_none():
    state = feed_state.load_state()
    assert feed_state.get_feed_started_at(state, "domestic", "host-a", "https://never-seen/rss") is None


# --- is_pre_start -----------------------------------------------------------------------


def test_is_pre_start_true_for_backlog_article():
    feed_state.record_first_seen_batch("domestic", "host-a", {"https://a/rss": "a"}, "2026-09-26T00:00:00Z")
    state = feed_state.load_state()
    assert feed_state.is_pre_start("2026-08-01T00:00:00Z", "domestic", "host-a", "https://a/rss", state) is True


def test_is_pre_start_false_for_fresh_article():
    feed_state.record_first_seen_batch("domestic", "host-a", {"https://a/rss": "a"}, "2026-09-26T00:00:00Z")
    state = feed_state.load_state()
    assert feed_state.is_pre_start("2026-09-27T00:00:00Z", "domestic", "host-a", "https://a/rss", state) is False


def test_is_pre_start_none_when_no_start_recorded():
    state = feed_state.load_state()
    assert feed_state.is_pre_start("2026-08-01T00:00:00Z", "domestic", "host-a", "https://never-seen/rss", state) is None


def test_is_pre_start_none_when_published_at_missing_or_unparseable():
    feed_state.record_first_seen_batch("domestic", "host-a", {"https://a/rss": "a"}, "2026-09-26T00:00:00Z")
    state = feed_state.load_state()
    assert feed_state.is_pre_start(None, "domestic", "host-a", "https://a/rss", state) is None
    assert feed_state.is_pre_start("", "domestic", "host-a", "https://a/rss", state) is None
    assert feed_state.is_pre_start("not a date", "domestic", "host-a", "https://a/rss", state) is None


# --- wiring into collect_continuous(), network fully mocked ------------------------------


def _diag(feed_id: str, feed_url: str, n_entries: int) -> dict:
    return feed_diagnostics.make_result(
        feed_id, feed_url, http_status=200, content_encoding="identity", n_entries=n_entries, n_new=0, error=None
    )


def test_collect_vn_continuous_records_feed_start_once_across_two_runs(monkeypatch):
    collect_vn = _load_module("collect_vn_feedstate_check", COLLECT_VN_PATH)
    entry = {"link": "https://vnexpress.net/a.html", "title": "T"}
    monkeypatch.setattr(
        collect_vn, "_fetch_feed_with_diagnostics",
        lambda publisher_id, feed_url, timeout: ([entry], _diag(publisher_id, feed_url, 1)),
    )

    collect_vn.collect_continuous("host-a", fetch_timeout=5.0, run_id="r1")
    state1 = feed_state.load_state()
    started_after_run1 = feed_state.get_feed_started_at(
        state1, "domestic", "host-a", collect_vn.RSS_FEEDS["vnexpress"]
    )
    assert started_after_run1 is not None

    collect_vn.collect_continuous("host-a", fetch_timeout=5.0, run_id="r2")
    state2 = feed_state.load_state()
    started_after_run2 = feed_state.get_feed_started_at(
        state2, "domestic", "host-a", collect_vn.RSS_FEEDS["vnexpress"]
    )
    assert started_after_run2 == started_after_run1  # unchanged across the second run


def test_collect_vn_continuous_only_new_feed_gets_a_new_start(monkeypatch):
    collect_vn = _load_module("collect_vn_feedstate_check2", COLLECT_VN_PATH)
    entry = {"link": "https://x/a.html", "title": "T"}

    # Run 1: only vnexpress returns anything (simulates the other feeds being down/empty).
    def fetch_only_vnexpress(publisher_id, feed_url, timeout):
        entries = [entry] if publisher_id == "vnexpress" else []
        return entries, _diag(publisher_id, feed_url, len(entries))

    monkeypatch.setattr(collect_vn, "_fetch_feed_with_diagnostics", fetch_only_vnexpress)
    collect_vn.collect_continuous("host-a", fetch_timeout=5.0, run_id="r1")
    state1 = feed_state.load_state()
    vnexpress_url = collect_vn.RSS_FEEDS["vnexpress"]
    tuoitre_url = collect_vn.RSS_FEEDS["tuoitre"]
    assert feed_state.get_feed_started_at(state1, "domestic", "host-a", vnexpress_url) is not None
    assert feed_state.get_feed_started_at(state1, "domestic", "host-a", tuoitre_url) is None

    # Run 2 ("Phase 5"-style): tuoitre now returns something too.
    monkeypatch.setattr(
        collect_vn, "_fetch_feed_with_diagnostics",
        lambda publisher_id, feed_url, timeout: ([entry], _diag(publisher_id, feed_url, 1)),
    )
    collect_vn.collect_continuous("host-a", fetch_timeout=5.0, run_id="r2")
    state2 = feed_state.load_state()
    assert feed_state.get_feed_started_at(state2, "domestic", "host-a", vnexpress_url) == feed_state.get_feed_started_at(
        state1, "domestic", "host-a", vnexpress_url
    )  # untouched
    assert feed_state.get_feed_started_at(state2, "domestic", "host-a", tuoitre_url) is not None  # newly recorded


def test_collect_intl_continuous_records_feed_start(monkeypatch):
    collect_intl = _load_module("collect_intl_feedstate_check", COLLECT_INTL_PATH)
    entry = {"link": "https://www.bbc.com/news/x", "title": "Vietnam story"}
    monkeypatch.setattr(
        collect_intl, "_fetch_feed_with_diagnostics",
        lambda domain, feed_url, timeout: ([entry], _diag(domain, feed_url, 1)),
    )

    collect_intl.collect_continuous("host-a", fetch_timeout=5.0, run_id="r1")
    state = feed_state.load_state()
    started = feed_state.get_feed_started_at(state, "international", "host-a", collect_intl.RSS_FEEDS["bbc.com"])
    assert started is not None

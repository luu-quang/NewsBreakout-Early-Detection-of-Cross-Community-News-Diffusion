"""Unit tests for the v2 continuous-collector core: hashing, JSONL storage,
seen-index (incl. rebuild-from-JSONL equivalence and crash-safety ordering),
cross-platform lock, and timeout-guarded fetch.
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.collect_v2 import continuous_write, fetch, hashing, jsonl_store, lock, paths, seen_index


# --- hashing -----------------------------------------------------------------------------


def test_content_hash_stable_regardless_of_key_order():
    assert hashing.content_hash({"a": 1, "b": 2}) == hashing.content_hash({"b": 2, "a": 1})


def test_content_hash_changes_when_content_changes():
    assert hashing.content_hash({"title": "A"}) != hashing.content_hash({"title": "B"})


def test_entry_key_prefers_url_falls_back_to_hash():
    assert hashing.entry_key("https://x/1", "deadbeef") == "https://x/1"
    assert hashing.entry_key("", "deadbeef") == "nourl:deadbeef"
    assert hashing.entry_key(None, "deadbeef") == "nourl:deadbeef"


# --- jsonl_store ---------------------------------------------------------------------------


def test_append_and_iter_roundtrip(tmp_path: Path):
    p = tmp_path / "records.jsonl"
    jsonl_store.append_line(p, {"a": 1})
    jsonl_store.append_line(p, {"a": 2})
    assert list(jsonl_store.iter_jsonl(p)) == [{"a": 1}, {"a": 2}]


def test_iter_jsonl_missing_file_yields_nothing(tmp_path: Path):
    assert list(jsonl_store.iter_jsonl(tmp_path / "missing.jsonl")) == []


def test_iter_jsonl_skips_malformed_trailing_line(tmp_path: Path):
    p = tmp_path / "records.jsonl"
    jsonl_store.append_line(p, {"a": 1})
    with p.open("a") as fh:
        fh.write('{"a": 2, unterminated\n')  # simulates a crash mid-write
    assert list(jsonl_store.iter_jsonl(p)) == [{"a": 1}]


def test_iter_jsonl_reads_gzip(tmp_path: Path):
    import gzip

    p = tmp_path / "records.jsonl.gz"
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"a": 1}) + "\n")
    assert list(jsonl_store.iter_jsonl(p)) == [{"a": 1}]


def test_rotate_old_files_leaves_recent_days_alone(tmp_path: Path):
    today = date(2026, 9, 26)
    for offset in range(4):
        day = today - timedelta(days=offset)
        (tmp_path / f"payloads-{day.isoformat()}.jsonl").write_text('{"a":1}\n')

    rotated = jsonl_store.rotate_old_files(tmp_path, prefix="payloads", keep_days=2, today=today)

    assert len(rotated) == 1  # only the 3-days-ago file
    remaining_plain = sorted(p.name for p in tmp_path.glob("payloads-*.jsonl"))
    assert remaining_plain == [
        "payloads-2026-09-24.jsonl",
        "payloads-2026-09-25.jsonl",
        "payloads-2026-09-26.jsonl",
    ]
    assert (tmp_path / "payloads-2026-09-23.jsonl.gz").exists()


def test_rotate_old_files_is_idempotent(tmp_path: Path):
    today = date(2026, 9, 26)
    (tmp_path / "payloads-2026-09-01.jsonl").write_text('{"a":1}\n')
    first = jsonl_store.rotate_old_files(tmp_path, prefix="payloads", keep_days=2, today=today)
    second = jsonl_store.rotate_old_files(tmp_path, prefix="payloads", keep_days=2, today=today)
    assert len(first) == 1
    assert second == []


def test_atomic_write_parquet_produces_readable_file(tmp_path: Path):
    import pandas as pd

    df = pd.DataFrame({"a": [1, 2, 3]})
    out = tmp_path / "out.parquet"
    paths.atomic_write_parquet(df, out)
    assert list(tmp_path.glob("*.tmp-*")) == []  # no leftover temp file
    pd.testing.assert_frame_equal(pd.read_parquet(out), df)


# --- seen_index --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_v2_root(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(paths, "V2_ROOT", tmp_path / "v2")
    yield


def test_seen_index_new_then_not_new():
    conn = seen_index.connect(paths.seen_index_path("domestic", "host-a"))
    assert seen_index.is_new(conn, "https://x/1", "hash1") is True
    seen_index.record_seen(conn, "https://x/1", "hash1", "2026-09-26T00:00:00Z", "ref1")
    assert seen_index.is_new(conn, "https://x/1", "hash1") is False
    assert seen_index.get_payload_ref(conn, "https://x/1", "hash1") == "ref1"
    conn.close()


def test_seen_index_edit_produces_new_pair_same_url():
    conn = seen_index.connect(paths.seen_index_path("domestic", "host-a"))
    seen_index.record_seen(conn, "https://x/1", "hash-original", "t0", "ref-original")
    # Same URL, edited content -> different hash -> still "new" (history preserved).
    assert seen_index.is_new(conn, "https://x/1", "hash-edited") is True
    conn.close()


def test_write_continuous_batch_dedupes_payload_across_polls(tmp_path):
    candidate = continuous_write.RawCandidate(
        url="https://x/1", payload={"title": "same"}, source_system="rss", source_locator="https://feed"
    )
    refs1 = continuous_write.write_continuous_batch(
        "domestic", "host-a", [candidate], observed_at="2026-09-26T00:00:00Z", run_id="run1"
    )
    refs2 = continuous_write.write_continuous_batch(
        "domestic", "host-a", [candidate], observed_at="2026-09-26T00:10:00Z", run_id="run2"
    )
    assert refs1 == refs2  # same content -> same payload_ref, no new payload written

    payloads = list(jsonl_store.iter_jsonl(paths.payloads_path("domestic", "host-a")))
    sightings = list(jsonl_store.iter_jsonl(paths.sightings_path("domestic", "host-a")))
    assert len(payloads) == 1  # written once, not once per poll
    assert len(sightings) == 2  # every poll still recorded a sighting
    assert [s["is_new"] for s in sightings] == [True, False]


def test_write_continuous_batch_edit_preserves_history():
    v1 = continuous_write.RawCandidate(
        url="https://x/1", payload={"title": "original"}, source_system="rss", source_locator="https://feed"
    )
    v2 = continuous_write.RawCandidate(
        url="https://x/1", payload={"title": "edited"}, source_system="rss", source_locator="https://feed"
    )
    continuous_write.write_continuous_batch("domestic", "host-a", [v1], observed_at="t0", run_id="r1")
    continuous_write.write_continuous_batch("domestic", "host-a", [v2], observed_at="t1", run_id="r2")
    payloads = list(jsonl_store.iter_jsonl(paths.payloads_path("domestic", "host-a")))
    assert len(payloads) == 2  # both versions archived, not collapsed


def test_write_continuous_batch_crash_before_index_update_is_harmless():
    """Simulates a crash between the JSONL writes and the index update: the next
    run must not lose data, and may only produce a harmless duplicate payload."""
    candidate = continuous_write.RawCandidate(
        url="https://x/1", payload={"title": "same"}, source_system="rss", source_locator="https://feed"
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated crash")

    # Save/restore by hand rather than monkeypatch.undo(): the shared fixture
    # instance also holds the autouse V2_ROOT patch, and undo() reverts everything
    # applied through it, not just the most recent setattr.
    original_record_seen = seen_index.record_seen
    seen_index.record_seen = _boom
    try:
        with pytest.raises(RuntimeError):
            continuous_write.write_continuous_batch(
                "domestic", "host-a", [candidate], observed_at="t0", run_id="r1"
            )
    finally:
        seen_index.record_seen = original_record_seen

    # Next run has no memory of the crashed attempt (index was never updated).
    continuous_write.write_continuous_batch("domestic", "host-a", [candidate], observed_at="t1", run_id="r2")
    payloads = list(jsonl_store.iter_jsonl(paths.payloads_path("domestic", "host-a")))
    assert len(payloads) == 2  # duplicate, not data loss - exactly the tolerated outcome
    assert payloads[0]["content_hash"] == payloads[1]["content_hash"]


def test_rebuild_from_jsonl_matches_incremental_index():
    candidates = [
        continuous_write.RawCandidate(url=f"https://x/{i}", payload={"title": f"t{i}"}, source_system="rss", source_locator="f")
        for i in range(3)
    ]
    continuous_write.write_continuous_batch("domestic", "host-a", candidates, observed_at="t0", run_id="r1")
    # Re-poll: first two unchanged (sighting only), third edited (new pair).
    edited = continuous_write.RawCandidate(url="https://x/2", payload={"title": "t2-edited"}, source_system="rss", source_locator="f")
    continuous_write.write_continuous_batch("domestic", "host-a", candidates[:2] + [edited], observed_at="t1", run_id="r2")

    incremental_db = paths.seen_index_path("domestic", "host-a")
    incremental_rows = _dump_seen_table(incremental_db)

    seen_index.rebuild_from_jsonl("domestic", "host-a")
    rebuilt_rows = _dump_seen_table(incremental_db)

    assert incremental_rows == rebuilt_rows


def _dump_seen_table(db_path: Path) -> set[tuple]:
    import sqlite3

    conn = sqlite3.connect(db_path)
    rows = set(conn.execute("SELECT entry_key, content_hash, first_seen_at, last_seen_at, payload_ref FROM seen").fetchall())
    conn.close()
    return rows


def test_rebuild_after_gzip_rotation_reproduces_same_payload_ref():
    """A ref recorded before rotation must still resolve after the file is
    gzipped - rebuild must not mint a .gz-suffixed ref for old records."""
    candidate = continuous_write.RawCandidate(url="https://x/1", payload={"title": "a"}, source_system="rss", source_locator="f")
    refs_before = continuous_write.write_continuous_batch("domestic", "host-a", [candidate], observed_at="t0", run_id="r1")

    directory = paths.branch_host_dir("domestic", "host-a")
    tomorrow = date.today() + timedelta(days=1)  # "today"'s file is never rotated; pretend it's the next day
    jsonl_store.rotate_old_files(directory, prefix="payloads", keep_days=0, today=tomorrow)
    jsonl_store.rotate_old_files(directory, prefix="sightings", keep_days=0, today=tomorrow)
    assert list(directory.glob("payloads-*.jsonl.gz"))  # confirm rotation actually happened

    seen_index.rebuild_from_jsonl("domestic", "host-a")
    conn = seen_index.connect(paths.seen_index_path("domestic", "host-a"))
    rebuilt_ref = seen_index.get_payload_ref(conn, "https://x/1", hashing.content_hash({"title": "a"}))
    conn.close()

    assert rebuilt_ref == refs_before[0]
    assert not rebuilt_ref.endswith(".gz")


def test_rebuild_from_jsonl_is_a_pure_function_of_jsonl_content():
    """Same JSONL archive, rebuilt twice, must give byte-identical results -
    the requirement the leader asked for: deterministic candidate construction."""
    candidates = [
        continuous_write.RawCandidate(url="https://x/1", payload={"title": "a"}, source_system="rss", source_locator="f")
    ]
    continuous_write.write_continuous_batch("domestic", "host-a", candidates, observed_at="t0", run_id="r1")
    db_path = paths.seen_index_path("domestic", "host-a")

    seen_index.rebuild_from_jsonl("domestic", "host-a")
    first = _dump_seen_table(db_path)
    seen_index.rebuild_from_jsonl("domestic", "host-a")
    second = _dump_seen_table(db_path)
    assert first == second


# --- lock ----------------------------------------------------------------------------------


def test_lock_blocks_concurrent_acquire(tmp_path: Path):
    lock_path = tmp_path / "run.lock"
    with lock.run_lock(lock_path, timeout=0.2):
        with pytest.raises(lock.RunAlreadyInProgress):
            with lock.run_lock(lock_path, timeout=0.2):
                pass  # pragma: no cover - must not be reached


def test_lock_released_after_context_exits(tmp_path: Path):
    lock_path = tmp_path / "run.lock"
    with lock.run_lock(lock_path, timeout=0.2):
        pass
    with lock.run_lock(lock_path, timeout=0.2):
        pass  # must not raise: first lock was released


# --- fetch -----------------------------------------------------------------------------------


def test_fetch_bytes_timeout_raises_feed_fetch_error():
    with pytest.raises(fetch.FeedFetchError):
        # Port 1 is reserved/unassigned - connection should fail fast, not hang.
        fetch.fetch_bytes("http://127.0.0.1:1/", timeout=1.0, user_agent="test")


def test_fetch_bytes_unresolvable_host_raises_feed_fetch_error():
    with pytest.raises(fetch.FeedFetchError):
        fetch.fetch_bytes("http://this-host-does-not-exist.invalid/", timeout=1.0, user_agent="test")

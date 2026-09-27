"""Tests for scripts/show_feed_health.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from src.collect_v2 import feed_diagnostics, jsonl_store
from src.collect_v2 import paths as v2_paths

spec = importlib.util.spec_from_file_location("show_feed_health", REPO_ROOT / "scripts/show_feed_health.py")
show_feed_health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(show_feed_health)


@pytest.fixture(autouse=True)
def _isolated_v2_root(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(v2_paths, "V2_ROOT", tmp_path / "v2")
    yield


def _record(run_at: str, feed_id: str, n_entries: int, n_new: int, error: str | None = None) -> dict:
    return {
        "run_id": run_at, "run_at": run_at,
        "children": {
            "domestic": {
                "per_feed": [
                    feed_diagnostics.make_result(
                        feed_id, "url-x", http_status=200, content_encoding="identity",
                        n_entries=n_entries, n_new=n_new, error=error,
                    )
                ]
            }
        },
    }


def test_load_last_n_runs_returns_tail_in_order():
    path = v2_paths.heartbeat_path("host-a")
    for i in range(10):
        jsonl_store.append_line(path, _record(f"2026-09-27T0{i}:00:00Z", "x", n_entries=1, n_new=1))

    records = show_feed_health.load_last_n_runs("host-a", 3)
    assert [r["run_at"] for r in records] == ["2026-09-27T07:00:00Z", "2026-09-27T08:00:00Z", "2026-09-27T09:00:00Z"]


def test_load_last_n_runs_empty_when_no_history():
    assert show_feed_health.load_last_n_runs("never-seen-host", 6) == []


def test_format_table_includes_feed_row_and_error():
    records = [_record("2026-09-27T10:00:00Z", "vietnamplus", n_entries=0, n_new=0, error="bozo: bad xml")]
    table = show_feed_health.format_table(records)
    assert "vietnamplus" in table
    assert "bozo: bad xml" in table
    assert "2026-09-27T10:00:00Z" in table


def test_format_table_includes_feed_issues_line_when_present():
    record = _record("2026-09-27T10:00:00Z", "x", n_entries=0, n_new=0, error="fetch failed: timeout")
    record["feed_issues"] = ["x: fetch failed: timeout"]
    table = show_feed_health.format_table([record])
    assert "feed_issues" in table
    assert "drives /fail" in table


def test_format_table_includes_stale_feed_issues_line_separately():
    record = _record("2026-09-27T10:00:00Z", "x", n_entries=5, n_new=0)
    record["stale_feed_issues"] = ["x: no new payload in 8.0h (threshold 6.0h)"]
    table = show_feed_health.format_table([record])
    assert "stale_feed_issues" in table
    assert "does not fail the check" in table
    assert "no new payload in 8.0h" in table
    assert "no new payload in 8.0h" in table

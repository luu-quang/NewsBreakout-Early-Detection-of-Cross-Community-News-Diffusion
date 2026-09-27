"""Tests for scripts/build_snapshot.py.

``test_end_to_end_collect_branch_matches_real_contract`` is the important
one - it runs the real ``clean_vn.clean()`` through ``collect_branch()``
against a tiny real JSONL archive (via ``continuous_write``), not mocks,
proving the orchestration wiring (raw candidates -> clean -> is_pre_start
join) behaves as designed end to end.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from src.collect_v2 import continuous_write, feed_state
from src.collect_v2 import paths as v2_paths

spec = importlib.util.spec_from_file_location("build_snapshot", REPO_ROOT / "scripts/build_snapshot.py")
build_snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_snapshot)


@pytest.fixture(autouse=True)
def _isolated_v2_root(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(v2_paths, "V2_ROOT", tmp_path / "v2")
    yield


def _vn_entry(link: str, title: str, published: str) -> dict:
    return {"link": link, "title": title, "summary": f"Tóm tắt {title}", "published": published, "category": "Thời sự"}


# --- filter_window -----------------------------------------------------------------------


def test_filter_window_since_is_inclusive_until_is_exclusive():
    df = pd.DataFrame(
        {
            "first_seen_at": [
                "2026-09-25T00:00:00Z",
                "2026-09-26T00:00:00Z",
                "2026-09-27T00:00:00Z",
            ]
        }
    )
    out = build_snapshot.filter_window(df, since="2026-09-26", until="2026-09-27")
    assert out["first_seen_at"].tolist() == ["2026-09-26T00:00:00Z"]


def test_filter_window_no_bounds_returns_everything():
    df = pd.DataFrame({"first_seen_at": ["2026-09-25T00:00:00Z", "2026-09-26T00:00:00Z"]})
    out = build_snapshot.filter_window(df, since=None, until=None)
    assert len(out) == 2


# --- attach_is_pre_start -------------------------------------------------------------------


def test_attach_is_pre_start_true_false_and_unknown():
    df = pd.DataFrame(
        {
            "raw_payload_ref": ["ref-backlog", "ref-live", "ref-unmapped"],
            "published_at": ["2026-09-01T00:00:00Z", "2026-09-27T00:00:00Z", "2026-09-27T00:00:00Z"],
            "branch": ["domestic", "domestic", "domestic"],
        }
    )
    ref_locator = {"ref-backlog": "https://vietnamnet.vn/rss/thoi-su.rss", "ref-live": "https://vietnamnet.vn/rss/thoi-su.rss"}
    ref_host = {"ref-backlog": "host-a", "ref-live": "host-a"}
    state = {"domestic": {"host-a": {"https://vietnamnet.vn/rss/thoi-su.rss": {"feed_started_at": "2026-09-10T00:00:00Z"}}}}

    out = build_snapshot.attach_is_pre_start(df, ref_locator, ref_host, state)
    assert out.set_index("raw_payload_ref")["is_pre_start"].to_dict() == {
        "ref-backlog": True,
        "ref-live": False,
        "ref-unmapped": None,
    }


def test_attach_is_pre_start_on_empty_frame():
    df = pd.DataFrame(columns=["raw_payload_ref", "published_at", "branch"])
    out = build_snapshot.attach_is_pre_start(df, {}, {}, {})
    assert list(out.columns) == ["raw_payload_ref", "published_at", "branch", "is_pre_start"]
    assert len(out) == 0


# --- feed_manifest_rows -------------------------------------------------------------------


def test_feed_manifest_rows_flattens_and_sorts():
    state = {
        "international": {"host-b": {"https://feeds.bbci.co.uk/x.xml": {"feed_started_at": "t2", "publisher_id_hint": "bbc.com"}}},
        "domestic": {"host-a": {"https://vnexpress.net/rss/tin-moi-nhat.rss": {"feed_started_at": "t1", "publisher_id_hint": "vnexpress"}}},
    }
    rows = build_snapshot.feed_manifest_rows(state)
    assert [r["branch"] for r in rows] == ["domestic", "international"]
    assert rows[0]["feed_locator"] == "https://vnexpress.net/rss/tin-moi-nhat.rss"
    assert rows[0]["feed_started_at"] == "t1"


# --- build_manifest -----------------------------------------------------------------------


def test_build_manifest_sha256_and_counts(tmp_path: Path):
    df = pd.DataFrame(
        {
            "branch": ["domestic", "domestic", "international"],
            "publisher_id": ["vnexpress", "vnexpress", "bbc"],
            "first_seen_at": ["2026-09-26T00:00:00Z", "2026-09-27T00:00:00Z", "2026-09-27T01:00:00Z"],
            "published_at": ["2026-09-26T00:00:00Z", None, "2026-09-27T01:00:00Z"],
            "is_pre_start": [True, False, None],
        }
    )
    output_path = tmp_path / "articles_master_v2_2026-09-27.parquet"
    df.to_parquet(output_path, index=False)

    manifest = build_snapshot.build_manifest(output_path, df, since="2026-09-26", until=None, feed_rows=[])

    assert manifest["sha256"] == hashlib.sha256(output_path.read_bytes()).hexdigest()
    assert manifest["row_count"] == 3
    assert manifest["rows_by_branch"] == {"domestic": 2, "international": 1}
    assert manifest["rows_by_publisher"] == {"vnexpress": 2, "bbc": 1}
    assert manifest["is_pre_start_counts"] == {"True": 1, "False": 1, "unknown": 1}
    assert manifest["date_range"]["first_seen_at_min"] == "2026-09-26T00:00:00+00:00"


# --- end-to-end: real clean_vn.clean() through collect_branch() ---------------------------


def test_end_to_end_collect_branch_matches_real_contract(tmp_path: Path):
    live = continuous_write.RawCandidate(
        url="https://vnexpress.net/live.html",
        payload=_vn_entry("https://vnexpress.net/live.html", "Việt Nam tin mới", "Sun, 27 Sep 2026 10:00:00 +0700"),
        source_system="rss",
        source_locator="https://vnexpress.net/rss/tin-moi-nhat.rss",
        publisher_id_hint="vnexpress",
    )
    backlog = continuous_write.RawCandidate(
        url="https://vnexpress.net/old.html",
        payload=_vn_entry("https://vnexpress.net/old.html", "Việt Nam tin cũ", "Tue, 01 Sep 2026 10:00:00 +0700"),
        source_system="rss",
        source_locator="https://vnexpress.net/rss/tin-moi-nhat.rss",
        publisher_id_hint="vnexpress",
    )
    continuous_write.write_continuous_batch(
        "domestic", "host-a", [live, backlog], observed_at="2026-09-27T03:00:00Z", run_id="r1"
    )
    feed_state.record_first_seen_batch(
        "domestic", "host-a", {"https://vnexpress.net/rss/tin-moi-nhat.rss": "vnexpress"}, "2026-09-10T00:00:00Z"
    )

    clean_vn = build_snapshot._load_module("clean_vn_test", build_snapshot.CLEAN_VN_PATH)
    relevant, audit, ref_locator, ref_host = build_snapshot.collect_branch("domestic", clean_vn, since=None, until=None)

    assert len(relevant) == 2
    assert set(ref_host.values()) == {"host-a"}
    assert set(ref_locator.values()) == {"https://vnexpress.net/rss/tin-moi-nhat.rss"}

    state = feed_state.load_state()
    tagged = build_snapshot.attach_is_pre_start(relevant, ref_locator, ref_host, state)
    by_url = tagged.set_index("url")["is_pre_start"].to_dict()
    assert by_url["https://vnexpress.net/live.html"] is False
    assert by_url["https://vnexpress.net/old.html"] is True

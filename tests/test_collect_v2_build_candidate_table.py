"""Tests for the offline v2 -> v1-compatible candidate-table builder.

The most important test here (``test_domestic_and_international_survive_the_real_contract``)
is not a unit test of this module's internals - it runs the REAL, unmodified
``clean_vn.clean()`` / ``clean_intl.clean()`` and the REAL
``build_master.validate_phase1_frame()`` against tables this builder produced,
proving the v2 collector needs no contract change anywhere downstream.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.collect_v2 import build_candidate_table as bct
from src.collect_v2 import continuous_write, paths
from src.integration.build_master import AUDIT_SCHEMA, SHARED_SCHEMA, ContractError, validate_phase1_frame

CLEAN_VN = bct._load_module("clean_vn_v1", bct.COLLECT_VN_PATH.parent / "clean_vn.py")
CLEAN_INTL = bct._load_module("clean_intl_v1", bct.COLLECT_INTL_PATH.parent / "clean_intl.py")


@pytest.fixture(autouse=True)
def _isolated_v2_root(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(paths, "V2_ROOT", tmp_path / "v2")
    yield


def _vn_entry(link: str, title: str, published: str = "Fri, 26 Sep 2026 10:00:00 +0700") -> dict:
    return {"link": link, "title": title, "summary": f"Tóm tắt cho {title}", "published": published, "category": "Thời sự"}


def _intl_entry(link: str, title: str, published: str = "Fri, 26 Sep 2026 03:00:00 GMT") -> dict:
    return {"link": link, "title": title, "summary": f"Summary for {title}", "published": published}


# --- aggregation correctness --------------------------------------------------------------


def test_domestic_basic_shape_matches_v1_raw_columns():
    candidate = continuous_write.RawCandidate(
        url="https://vnexpress.net/a.html",
        payload=_vn_entry("https://vnexpress.net/a.html", "Tiêu đề A"),
        source_system="rss",
        source_locator="https://vnexpress.net/rss/tin-moi-nhat.rss",
        publisher_id_hint="vnexpress",
    )
    continuous_write.write_continuous_batch("domestic", "host-a", [candidate], observed_at="2026-09-26T00:00:00Z", run_id="r1")

    df = bct.build("domestic", "host-a")
    collect_vn = bct._load_module("collect_vn_check", bct.COLLECT_VN_PATH)
    assert list(df.columns) == collect_vn.RAW_COLUMNS
    assert len(df) == 1
    row = df.iloc[0]
    assert row["url"] == "https://vnexpress.net/a.html"
    assert row["publisher_id_hint"] == "vnexpress"
    assert row["collection_mode"] == "prospective"
    assert "#raw_record_id=" in row["raw_payload_ref"]


def test_international_basic_shape_matches_v1_raw_columns():
    candidate = continuous_write.RawCandidate(
        url="https://www.bbc.com/news/x",
        payload=_intl_entry("https://www.bbc.com/news/x", "Vietnam story"),
        source_system="rss",
        source_locator="https://feeds.bbci.co.uk/news/world/asia/rss.xml",
        publisher_id_hint="bbc.com",
    )
    continuous_write.write_continuous_batch("international", "host-a", [candidate], observed_at="2026-09-26T00:00:00Z", run_id="r1")

    df = bct.build("international", "host-a")
    collect_intl = bct._load_module("collect_intl_check", bct.COLLECT_INTL_PATH)
    assert list(df.columns) == collect_intl.RAW_COLUMNS
    assert len(df) == 1
    row = df.iloc[0]
    assert row["title"] == "Vietnam story"
    assert row["publisher_domain"] == "bbc.com"
    assert row["branch"] == "international"
    assert row["description"] == "Summary for Vietnam story"


def test_first_and_last_seen_aggregate_across_polls_including_an_edit():
    v1 = continuous_write.RawCandidate(
        url="https://vnexpress.net/a.html", payload=_vn_entry("https://vnexpress.net/a.html", "Bản đầu"),
        source_system="rss", source_locator="feed", publisher_id_hint="vnexpress",
    )
    v2 = continuous_write.RawCandidate(
        url="https://vnexpress.net/a.html", payload=_vn_entry("https://vnexpress.net/a.html", "Bản sửa"),
        source_system="rss", source_locator="feed", publisher_id_hint="vnexpress",
    )
    continuous_write.write_continuous_batch("domestic", "host-a", [v1], observed_at="2026-09-26T00:00:00Z", run_id="r1")
    continuous_write.write_continuous_batch("domestic", "host-a", [v1], observed_at="2026-09-26T00:10:00Z", run_id="r2")  # unchanged re-poll
    continuous_write.write_continuous_batch("domestic", "host-a", [v2], observed_at="2026-09-26T00:20:00Z", run_id="r3")  # edited

    df = bct.build("domestic", "host-a")
    assert len(df) == 1  # still one candidate row per URL
    row = df.iloc[0]
    assert row["first_seen_at"] == "2026-09-26T00:00:00Z"
    assert row["last_seen_at"] == "2026-09-26T00:20:00Z"
    # keep=first content, matching v1's own merge_with_history() convention
    assert "Bản đầu" in row["entry_json"]
    assert "Bản sửa" not in row["entry_json"]


def test_build_is_a_pure_function_of_the_archive():
    candidate = continuous_write.RawCandidate(
        url="https://vnexpress.net/a.html", payload=_vn_entry("https://vnexpress.net/a.html", "T"),
        source_system="rss", source_locator="feed", publisher_id_hint="vnexpress",
    )
    continuous_write.write_continuous_batch("domestic", "host-a", [candidate], observed_at="2026-09-26T00:00:00Z", run_id="r1")
    first = bct.build("domestic", "host-a")
    second = bct.build("domestic", "host-a")
    pd.testing.assert_frame_equal(first, second)


def test_unknown_branch_rejected():
    with pytest.raises(ValueError):
        bct.build("bogus", "host-a")


# --- the real contract, end to end -------------------------------------------------------


def test_domestic_and_international_survive_the_real_contract():
    """Build both branches' candidate tables from the v2 archive, run them
    through the REAL clean_vn.clean()/clean_intl.clean(), and check the result
    against the REAL build_master.validate_phase1_frame() - the property the
    leader asked for: no contract change anywhere downstream."""
    vn_candidates = [
        continuous_write.RawCandidate(
            url=f"https://vnexpress.net/{i}.html",
            payload=_vn_entry(f"https://vnexpress.net/{i}.html", f"Bài viết số {i} về Hà Nội"),
            source_system="rss", source_locator="https://vnexpress.net/rss/tin-moi-nhat.rss",
            publisher_id_hint="vnexpress",
        )
        for i in range(5)
    ]
    intl_candidates = [
        continuous_write.RawCandidate(
            url=f"https://www.bbc.com/news/{i}",
            payload=_intl_entry(f"https://www.bbc.com/news/{i}", f"Vietnam story {i}"),
            source_system="rss", source_locator="https://feeds.bbci.co.uk/news/world/asia/rss.xml",
            publisher_id_hint="bbc.com",
        )
        for i in range(5)
    ]
    continuous_write.write_continuous_batch("domestic", "host-a", vn_candidates, observed_at="2026-09-26T00:00:00Z", run_id="r1")
    continuous_write.write_continuous_batch(
        "international", "host-a", intl_candidates, observed_at="2026-09-26T00:00:00Z", run_id="r1"
    )

    vn_raw = bct.build("domestic", "host-a")
    intl_raw = bct.build("international", "host-a")

    vn_audit = CLEAN_VN.clean(vn_raw)
    intl_audit = CLEAN_INTL.clean(intl_raw)

    # Real contract validation, audit-mode (both True/False relevance allowed).
    validate_phase1_frame(vn_audit, label="vn audit", expected_schema=AUDIT_SCHEMA, expected_branch="domestic", audit=True)
    validate_phase1_frame(
        intl_audit, label="intl audit", expected_schema=AUDIT_SCHEMA, expected_branch="international", audit=True
    )

    # Real contract validation, relevant-only mode (matches what clean_vn.py/clean_intl.py
    # actually feed to build_master.py).
    vn_relevant = vn_audit[
        vn_audit["rejection_reason"].isna() & vn_audit["vietnam_relevance"].eq(True)
    ].sort_values("first_seen_at").drop_duplicates(subset=["canonical_url"], keep="first")[SHARED_SCHEMA]
    intl_relevant = intl_audit[
        intl_audit["rejection_reason"].isna() & intl_audit["vietnam_relevance"].eq(True)
    ].sort_values("first_seen_at").drop_duplicates(subset=["canonical_url"], keep="first")[SHARED_SCHEMA]

    assert len(vn_relevant) == 5  # Hanoi-mentioning titles should all pass VN's relevance heuristic
    assert len(intl_relevant) == 5  # "Vietnam" in every title should pass INTL's relevance heuristic

    validate_phase1_frame(vn_relevant, label="vn relevant", expected_schema=SHARED_SCHEMA, expected_branch="domestic", audit=False)
    validate_phase1_frame(
        intl_relevant, label="intl relevant", expected_schema=SHARED_SCHEMA, expected_branch="international", audit=False
    )


def test_broken_entry_gets_a_distinct_candidate_row_not_dropped():
    """An entry with no usable URL must still get its own candidate row (via the
    nourl: fallback key) so the cleaner can record a rejection_reason, matching
    v1's own stated design intent - never silently dropping broken input."""
    broken = continuous_write.RawCandidate(
        url="", payload={"title": "No link here"}, source_system="rss", source_locator="feed", publisher_id_hint="vnexpress"
    )
    continuous_write.write_continuous_batch("domestic", "host-a", [broken], observed_at="2026-09-26T00:00:00Z", run_id="r1")

    df = bct.build("domestic", "host-a")
    assert len(df) == 1
    audit = CLEAN_VN.clean(df)
    assert audit.iloc[0]["rejection_reason"] is not None
    assert "invalid_url" in audit.iloc[0]["rejection_reason"]

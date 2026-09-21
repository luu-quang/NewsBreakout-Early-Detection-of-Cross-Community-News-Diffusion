"""Automated contract and regression tests for Phase 2B Deduplication & Syndication Detection."""

import json
from pathlib import Path
import pandas as pd
import pytest

from src.deduplication.detector import DeduplicationDetector
from src.deduplication.pipeline import (
    FROZEN_SCHEMA,
    compute_sha256,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MASTER_INPUT = REPOSITORY_ROOT / "data/processed/master/articles_master.parquet"
DEDUP_OUTPUT = REPOSITORY_ROOT / "data/processed/master/articles_dedup.parquet"
QC_CSV = (
    REPOSITORY_ROOT
    / "team_work/phases/phase2_processing/phase2b_dedup_syndication/sample_output/dedup_pairs_qc_independent.csv"
)
FAMILY_CSV = (
    REPOSITORY_ROOT
    / "team_work/phases/phase2_processing/phase2b_dedup_syndication/sample_output/dedup_family_summary_independent.csv"
)
MANIFEST_JSON = (
    REPOSITORY_ROOT
    / "team_work/phases/phase2_processing/phase2b_dedup_syndication/sample_output/dedup_manifest_independent.json"
)

EXPECTED_MASTER_SHA256 = "b021a43395a46af3ca36586b1042b061c644e90a92178a9b9d5779c11ea156f3"


def test_master_input_hash():
    """Verify input master dataset matches frozen snapshot SHA-256."""
    assert MASTER_INPUT.is_file(), f"Master input missing: {MASTER_INPUT}"
    actual_hash = compute_sha256(MASTER_INPUT)
    assert actual_hash == EXPECTED_MASTER_SHA256, f"Master hash mismatch: {actual_hash}"


def test_output_schema_and_order():
    """Verify dedup output conforms to exact 20-column frozen schema and row count."""
    assert DEDUP_OUTPUT.is_file(), f"Dedup output missing: {DEDUP_OUTPUT}"
    df_dedup = pd.read_parquet(DEDUP_OUTPUT)
    assert list(df_dedup.columns) == FROZEN_SCHEMA
    assert len(df_dedup) == 1223


def test_non_family_columns_immutability():
    """Verify all 19 non-family columns are 100% untouched bitwise copies of input."""
    df_master = pd.read_parquet(MASTER_INPUT)
    df_dedup = pd.read_parquet(DEDUP_OUTPUT)

    non_family_cols = [c for c in FROZEN_SCHEMA if c != "duplicate_family_id"]
    pd.testing.assert_frame_equal(df_master[non_family_cols], df_dedup[non_family_cols])


def test_family_id_constraints():
    """Verify family ID semantics: singletons are null, assigned families have >= 2 articles."""
    df_dedup = pd.read_parquet(DEDUP_OUTPUT)

    assigned = df_dedup[df_dedup["duplicate_family_id"].notna()]
    assert len(assigned) > 0, "No duplicate families were assigned!"

    # Every family must have at least 2 members
    family_counts = assigned["duplicate_family_id"].value_counts()
    assert (family_counts >= 2).all(), f"Families with < 2 members: {family_counts[family_counts < 2]}"

    # Family IDs must follow naming convention
    for fam_id in family_counts.index:
        assert fam_id.startswith("fam_exact_") or fam_id.startswith("fam_synd_"), f"Invalid ID format: {fam_id}"


def test_determinism():
    """Verify running the detector twice produces bit-for-bit identical duplicate families."""
    df_master = pd.read_parquet(MASTER_INPUT)
    detector = DeduplicationDetector()

    out1, _, _, metrics1 = detector.detect_and_cluster(df_master)
    out2, _, _, metrics2 = detector.detect_and_cluster(df_master)

    pd.testing.assert_series_equal(out1["duplicate_family_id"], out2["duplicate_family_id"])
    assert metrics1 == metrics2


def test_qc_artifacts():
    """Verify QC CSV and JSON manifest files exist, have correct schema, and cover required strata."""
    assert QC_CSV.is_file()
    assert FAMILY_CSV.is_file()
    assert MANIFEST_JSON.is_file()

    qc_df = pd.read_csv(QC_CSV)
    expected_qc_cols = [
        "pair_id",
        "left_article_id",
        "right_article_id",
        "left_publisher",
        "right_publisher",
        "left_url",
        "right_url",
        "left_title",
        "right_title",
        "left_description",
        "right_description",
        "similarity_evidence",
        "predicted_relation",
        "manual_relation",
        "duplicate_family_id",
        "review_notes",
    ]
    assert list(qc_df.columns) == expected_qc_cols
    assert len(qc_df) >= 30

    relations = set(qc_df["predicted_relation"].unique())
    assert "EXACT_DUPLICATE" in relations
    assert "SYNDICATED_COPY" in relations
    assert "SAME_EVENT_INDEPENDENT" in relations
    assert "UNRELATED" in relations

    # Verify manifest
    with open(MANIFEST_JSON, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["input_sha256"] == EXPECTED_MASTER_SHA256
    assert manifest["input_rows"] == 1223
    assert manifest["output_rows"] == 1223
    assert manifest["metrics"]["total_families"] == 3

"""Automated contract and regression tests for Phase 2C Event Clustering."""

import json
from pathlib import Path

import pandas as pd
import pytest

from src.event_clustering.pipeline import (
    FROZEN_SCHEMA_INPUT,
    FROZEN_SCHEMA_OUTPUT,
    compute_sha256,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEDUP_INPUT = REPOSITORY_ROOT / "data/processed/master/articles_dedup.parquet"
CLUSTERED_OUTPUT = REPOSITORY_ROOT / "data/processed/master/articles_clustered.parquet"
QC_CSV = (
    REPOSITORY_ROOT
    / "team_work/phases/phase2_processing/phase2c_event_clustering/sample_output/event_clusters_qc.csv"
)
SUMMARY_CSV = (
    REPOSITORY_ROOT
    / "team_work/phases/phase2_processing/phase2c_event_clustering/sample_output/event_cluster_summary.csv"
)
MANIFEST_JSON = (
    REPOSITORY_ROOT
    / "team_work/phases/phase2_processing/phase2c_event_clustering/sample_output/event_clustering_manifest.json"
)

EXPECTED_DEDUP_SHA256 = "9c51b0fc3630a3aa07d5dc7cf5e812d96a6054bcf57fcef85cdbff9f98cf9f36"


def test_dedup_input_hash():
    """Verify input dedup dataset matches frozen snapshot SHA-256."""
    assert DEDUP_INPUT.is_file(), f"Dedup input missing: {DEDUP_INPUT}"
    actual_hash = compute_sha256(DEDUP_INPUT)
    assert actual_hash == EXPECTED_DEDUP_SHA256, f"Dedup hash mismatch: {actual_hash}"


def test_output_schema_and_order():
    """Verify clustered output conforms to exact 21-column schema and row count."""
    assert CLUSTERED_OUTPUT.is_file(), f"Clustered output missing: {CLUSTERED_OUTPUT}"
    df = pd.read_parquet(CLUSTERED_OUTPUT)
    assert list(df.columns) == FROZEN_SCHEMA_OUTPUT
    assert len(df) == 1223


def test_non_cluster_columns_immutability():
    """Verify all 20 non-event-cluster columns are bitwise copies of input."""
    df_dedup = pd.read_parquet(DEDUP_INPUT)
    df_clustered = pd.read_parquet(CLUSTERED_OUTPUT)

    non_cluster_cols = [c for c in FROZEN_SCHEMA_OUTPUT if c != "event_cluster_id"]
    pd.testing.assert_frame_equal(
        df_dedup[non_cluster_cols].reset_index(drop=True),
        df_clustered[non_cluster_cols].reset_index(drop=True),
    )


def test_event_cluster_id_constraints():
    """Verify event cluster ID semantics: singletons null, clusters have >= 2 members."""
    df = pd.read_parquet(CLUSTERED_OUTPUT)

    assigned = df[df["event_cluster_id"].notna()]
    assert len(assigned) > 0, "No event clusters were assigned!"

    # Every cluster must have at least 2 members
    cluster_counts = assigned["event_cluster_id"].value_counts()
    assert (cluster_counts >= 2).all(), (
        f"Clusters with < 2 members: {cluster_counts[cluster_counts < 2]}"
    )

    # Cluster IDs must follow naming convention
    for cluster_id in cluster_counts.index:
        assert cluster_id.startswith("evt_"), f"Invalid ID format: {cluster_id}"


def test_duplicate_family_same_event():
    """Verify all members of the same duplicate_family_id share the same event_cluster_id."""
    df = pd.read_parquet(CLUSTERED_OUTPUT)

    family_groups = df[df["duplicate_family_id"].notna()].groupby("duplicate_family_id")
    for fam_id, group in family_groups:
        event_ids = group["event_cluster_id"].dropna().unique()
        assert len(event_ids) <= 1, (
            f"Family {fam_id} spans multiple event clusters: {event_ids}"
        )


def test_qc_artifacts_exist():
    """Verify QC artifacts (CSV, JSON) exist and have expected structure."""
    assert QC_CSV.is_file(), f"QC CSV missing: {QC_CSV}"
    assert SUMMARY_CSV.is_file(), f"Summary CSV missing: {SUMMARY_CSV}"
    assert MANIFEST_JSON.is_file(), f"Manifest JSON missing: {MANIFEST_JSON}"

    # Verify summary CSV
    summary_df = pd.read_csv(SUMMARY_CSV)
    assert "event_cluster_id" in summary_df.columns
    assert "cluster_size" in summary_df.columns
    assert len(summary_df) > 0

    # Verify manifest JSON
    with open(MANIFEST_JSON, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["input_sha256"] == EXPECTED_DEDUP_SHA256
    assert manifest["input_rows"] == 1223
    assert manifest["output_rows"] == 1223
    assert manifest["total_event_clusters"] > 0
    assert manifest["cross_publisher_clusters"] > 0

"""Tests for Phase 2C event clustering.

Two groups:
* synthetic unit tests (no model, no data files) for the clustering logic, and
* artifact tests on the regenerated outputs, skipped when the local parquet is absent.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.event_clustering.clusterer import (
    build_summaries,
    cluster_units,
    collapse_families,
    event_time,
    propagate,
    summarize_metrics,
)
from src.event_clustering.embedder import build_texts, clean_text
from src.event_clustering.pipeline import (
    DEFAULT_DISTANCE_THRESHOLD,
    DEFAULT_LINKAGE,
    DEFAULT_WINDOW_DAYS,
    EXPECTED_DEDUP_SHA256,
    FROZEN_SCHEMA_INPUT,
    FROZEN_SCHEMA_OUTPUT,
    ContractError,
    compute_sha256,
    run_event_clustering_pipeline,
)
from src.event_clustering.qc import (
    STRATUM_INTER_NEAR,
    select_qc_pairs,
)
from src.event_clustering.clusterer import cosine_distance_matrix, time_gap_matrix

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEDUP_INPUT = REPOSITORY_ROOT / "data/processed/master/articles_dedup.parquet"
CLUSTERED_OUTPUT = REPOSITORY_ROOT / "data/processed/master/articles_clustered.parquet"
SAMPLE_DIR = (
    REPOSITORY_ROOT / "team_work/phases/phase2_processing/phase2c_event_clustering/sample_output"
)
QC_CSV = SAMPLE_DIR / "event_clusters_qc.csv"
SUMMARY_CSV = SAMPLE_DIR / "event_cluster_summary.csv"
SWEEP_CSV = SAMPLE_DIR / "threshold_sweep.csv"
MANIFEST_JSON = SAMPLE_DIR / "event_clustering_manifest.json"


# ── synthetic helpers ────────────────────────────────────────────────────────


def make_df(rows):
    """rows: dicts with article_id, published_at (day offset or None), optional publisher/family/first_seen."""
    base = pd.Timestamp("2026-09-01T00:00:00Z")
    records = []
    for r in rows:
        published = None if r.get("day") is None else (base + pd.Timedelta(days=r["day"])).isoformat()
        records.append(
            {
                "article_id": r["id"],
                "title": r.get("title", f"title {r['id']}"),
                "url": f"https://{r.get('pub', 'a.vn')}/{r['id']}",
                "canonical_url": f"https://{r.get('pub', 'a.vn')}/{r['id']}",
                "publisher_domain": r.get("pub", "a.vn"),
                "publisher_id": r.get("pub", "a.vn"),
                "publisher_group_id": "g",
                "source_system": "rss",
                "first_seen_at": (base + pd.Timedelta(days=30)).isoformat(),
                "published_at": published,
                "timestamp_confidence": "publisher_reported",
                "language": "vi",
                "publisher_country": "VN",
                "description": r.get("desc", f"desc {r['id']}"),
                "category": None,
                "vietnam_relevance": "high",
                "duplicate_family_id": r.get("fam"),
                "branch": "domestic",
                "collection_mode": "rss",
                "raw_payload_ref": None,
            }
        )
    return pd.DataFrame(records, columns=FROZEN_SCHEMA_INPUT)


def unit_vecs(angles_deg):
    """2-D unit vectors; cosine distance between two is 1 - cos(angle difference)."""
    a = np.deg2rad(np.asarray(angles_deg, dtype="float64"))
    return np.column_stack([np.cos(a), np.sin(a)])


def run_pipeline_on(df, emb, threshold=0.3, window=5.0, linkage="complete"):
    times, _ = event_time(df)
    units = collapse_families(df, emb, times)
    labels = cluster_units(units.embeddings, units.times, threshold, window, linkage)
    out = df.copy()
    out["event_cluster_id"] = propagate(df, units, labels, times)
    return out, times, units


# ── text cleaning ────────────────────────────────────────────────────────────


def test_clean_text_unescapes_html_before_embedding():
    assert clean_text("Biển người &apos;đi bão&apos; &amp; hát") == "Biển người 'đi bão' & hát"
    assert clean_text(None) == ""
    assert clean_text(float("nan")) == ""


def test_build_texts_uses_cleaned_title_and_description():
    df = make_df([{"id": "a", "title": "A &quot;b&quot;", "desc": "  mô   tả "}, {"id": "b", "title": "T", "desc": ""}])
    df.loc[1, "description"] = None
    assert build_texts(df) == ['A "b". mô tả', "T"]


# ── event time ───────────────────────────────────────────────────────────────


def test_published_at_is_primary_and_first_seen_is_fallback():
    df = make_df([{"id": "a", "day": 1}, {"id": "b", "day": None}])
    times, source = event_time(df)
    assert source.tolist() == ["published_at", "first_seen_at"]
    # published_at (day 1) is used for a, NOT its first_seen_at (day 30)
    assert times[1] - times[0] == pytest.approx(29.0)


# ── family collapse / propagation ────────────────────────────────────────────


def test_family_members_share_event_even_if_embeddings_disagree():
    df = make_df(
        [
            {"id": "a", "day": 0, "fam": "dupfam_x"},
            {"id": "b", "day": 0, "fam": "dupfam_x"},
            {"id": "c", "day": 0},
        ]
    )
    emb = unit_vecs([0, 90, 180])  # a and b are orthogonal, c is opposite a
    out, _, units = run_pipeline_on(df, emb, threshold=0.05)
    assert len(units.members) == 2  # family collapsed into one unit
    assert out.loc[0, "event_cluster_id"] == out.loc[1, "event_cluster_id"]
    assert out.loc[2, "event_cluster_id"] != out.loc[0, "event_cluster_id"]


def test_every_article_gets_an_event_id_and_singletons_are_own_events():
    df = make_df([{"id": f"a{i}", "day": 0} for i in range(4)])
    emb = unit_vecs([0, 1, 90, 180])
    out, _, _ = run_pipeline_on(df, emb, threshold=0.05)
    assert out["event_cluster_id"].notna().all()
    assert out["event_cluster_id"].nunique() == 3  # a0+a1 merged, a2, a3 singleton events
    assert out["event_cluster_id"].str.startswith("evt_").all()


def test_event_id_is_stable_when_cluster_gains_a_member():
    emb2 = unit_vecs([0, 0])
    df2 = make_df([{"id": "a", "day": 0}, {"id": "b", "day": 1}])
    out2, _, _ = run_pipeline_on(df2, emb2)
    df3 = make_df([{"id": "a", "day": 0}, {"id": "b", "day": 1}, {"id": "c", "day": 2}])
    out3, _, _ = run_pipeline_on(df3, unit_vecs([0, 0, 0]))
    assert out3["event_cluster_id"].nunique() == 1
    assert out3.loc[0, "event_cluster_id"] == out2.loc[0, "event_cluster_id"]


# ── time gate ────────────────────────────────────────────────────────────────


def test_time_gate_is_hard_with_complete_linkage():
    # Identical text at t=0, 4, 8: a-b and b-c are within 5 days, a-c is not.
    df = make_df([{"id": "a", "day": 0}, {"id": "b", "day": 4}, {"id": "c", "day": 8}])
    out, times, _ = run_pipeline_on(df, unit_vecs([0, 0, 0]), window=5.0, linkage="complete")
    for _, group in out.groupby("event_cluster_id"):
        t = times[group.index]
        assert t.max() - t.min() <= 5.0
    assert out["event_cluster_id"].nunique() >= 2


def test_articles_far_apart_never_merge_and_unknown_time_never_merges():
    df = make_df([{"id": "a", "day": 0}, {"id": "b", "day": 30}])
    out, _, _ = run_pipeline_on(df, unit_vecs([0, 0]), window=10.0)
    assert out["event_cluster_id"].nunique() == 2

    df = make_df([{"id": "a", "day": 0}, {"id": "b", "day": 0}])
    df["published_at"] = None
    df["first_seen_at"] = None
    out, _, _ = run_pipeline_on(df, unit_vecs([0, 0]))
    assert out["event_cluster_id"].nunique() == 2


# ── summaries ────────────────────────────────────────────────────────────────


def test_summaries_are_computed_from_final_frame_and_reconcile():
    df = make_df(
        [
            {"id": "a", "day": 0, "pub": "x.vn", "fam": "dupfam_1"},
            {"id": "b", "day": 1, "pub": "y.vn", "fam": "dupfam_1"},
            {"id": "c", "day": 1, "pub": "z.vn"},
            {"id": "d", "day": 2, "pub": "z.vn"},
        ]
    )
    emb = unit_vecs([0, 4, 2, 180])
    out, times, _ = run_pipeline_on(df, emb, threshold=0.05)
    summary = build_summaries(out, emb, times)

    assert summary["cluster_size"].sum() == len(df)
    top = summary.iloc[0]
    assert top["cluster_size"] == 3  # family(a,b) + c
    assert top["n_publishers"] == 3
    assert top["n_duplicate_families"] == 1
    assert top["n_units"] == 2
    metrics = summarize_metrics(summary, len(df))
    assert metrics["total_events"] == 2
    assert metrics["singleton_events"] == 1
    assert metrics["cross_publisher_events"] == 1


# ── QC sampling ──────────────────────────────────────────────────────────────


def _qc_fixture():
    angles = [0, 4, 30, 34, 60, 64, 120, 125, 200]
    df = make_df(
        [{"id": f"a{i}", "day": 0.1 * i, "pub": "x.vn" if i % 2 else "y.vn"} for i in range(len(angles))]
    )
    emb = unit_vecs(angles)
    out, times, _ = run_pipeline_on(df, emb, threshold=0.02, window=5.0)
    return out, emb, times


def test_inter_cluster_near_is_selected_by_embedding_distance():
    out, emb, times = _qc_fixture()
    qc = select_qc_pairs(out, emb, times, window_days=5.0, per_stratum=3)
    near = qc[qc["stratum"] == STRATUM_INTER_NEAR]
    assert len(near) == 3
    assert (near["left_event_cluster_id"] != near["right_event_cluster_id"]).all()
    assert near["cosine_distance"].is_monotonic_increasing

    # Brute force: the closest cross-event pair in the window must be the first pick.
    dist = cosine_distance_matrix(emb)
    gap = time_gap_matrix(times)
    ev = out["event_cluster_id"].to_numpy()
    best = min(
        dist[i, j]
        for i in range(len(out))
        for j in range(i + 1, len(out))
        if ev[i] != ev[j] and gap[i, j] <= 5.0
    )
    assert near["cosine_distance"].iloc[0] == pytest.approx(best, abs=1e-4)


def test_qc_sampling_is_deterministic_and_excludes_intra_family_pairs():
    out, emb, times = _qc_fixture()
    out.loc[[0, 1], "duplicate_family_id"] = "dupfam_z"
    first = select_qc_pairs(out, emb, times, window_days=5.0)
    second = select_qc_pairs(out, emb, times, window_days=5.0)
    pd.testing.assert_frame_equal(first, second)
    pairs = set(zip(first["left_article_id"], first["right_article_id"]))
    assert ("a0", "a1") not in pairs


# ── pipeline (injected embeddings, no model) ─────────────────────────────────


def test_pipeline_rejects_input_that_is_not_the_frozen_artifact(tmp_path):
    df = make_df([{"id": "a", "day": 0}, {"id": "b", "day": 0}])
    path = tmp_path / "articles_dedup.parquet"
    df.to_parquet(path, index=False)
    with pytest.raises(ContractError):
        run_event_clustering_pipeline(
            input_path=path,
            output_path=tmp_path / "out.parquet",
            sample_output_dir=tmp_path / "s",
            embeddings=unit_vecs([0, 0]),
            run_threshold_sweep=False,
        )


def test_pipeline_end_to_end_on_synthetic_input(tmp_path):
    df = make_df(
        [
            {"id": "a", "day": 0, "fam": "dupfam_1", "pub": "x.vn"},
            {"id": "b", "day": 0, "fam": "dupfam_1", "pub": "y.vn"},
            {"id": "c", "day": 1, "pub": "z.vn"},
            {"id": "d", "day": 2, "pub": "z.vn"},
        ]
    )
    path = tmp_path / "articles_dedup.parquet"
    df.to_parquet(path, index=False)
    manifest = run_event_clustering_pipeline(
        input_path=path,
        output_path=tmp_path / "out.parquet",
        sample_output_dir=tmp_path / "s",
        embeddings=unit_vecs([0, 0, 3, 180]),
        expected_input_sha256=None,
        run_threshold_sweep=True,
    )
    out = pd.read_parquet(tmp_path / "out.parquet")
    assert list(out.columns) == FROZEN_SCHEMA_OUTPUT
    assert out["event_cluster_id"].notna().all()
    assert out.loc[0, "event_cluster_id"] == out.loc[1, "event_cluster_id"]
    pd.testing.assert_frame_equal(out[FROZEN_SCHEMA_INPUT], df)
    assert manifest["metrics"]["total_events"] == out["event_cluster_id"].nunique()
    assert manifest["clustering_units"]["n_units"] == 3
    assert (tmp_path / "s" / "threshold_sweep.csv").is_file()
    assert not Path(manifest["input_path"]).is_absolute()


# ── artifact tests on the regenerated outputs ────────────────────────────────

needs_outputs = pytest.mark.skipif(
    not (DEDUP_INPUT.is_file() and CLUSTERED_OUTPUT.is_file()),
    reason="local Phase 2B/2C parquet files not present",
)


@pytest.mark.skipif(not DEDUP_INPUT.is_file(), reason="dedup parquet not present")
def test_dedup_input_is_the_frozen_phase2b_artifact():
    assert compute_sha256(DEDUP_INPUT) == EXPECTED_DEDUP_SHA256


@needs_outputs
def test_output_schema_rows_and_immutability():
    dedup = pd.read_parquet(DEDUP_INPUT)
    clustered = pd.read_parquet(CLUSTERED_OUTPUT)
    assert list(clustered.columns) == FROZEN_SCHEMA_OUTPUT
    assert len(clustered) == len(dedup)
    pd.testing.assert_frame_equal(
        dedup[FROZEN_SCHEMA_INPUT].reset_index(drop=True),
        clustered[FROZEN_SCHEMA_INPUT].reset_index(drop=True),
    )


@needs_outputs
def test_every_article_has_an_event_and_families_stay_together():
    df = pd.read_parquet(CLUSTERED_OUTPUT)
    assert df["event_cluster_id"].notna().all()
    assert df["event_cluster_id"].str.startswith("evt_").all()
    fam = df[df["duplicate_family_id"].notna()].groupby("duplicate_family_id")["event_cluster_id"].nunique()
    assert (fam == 1).all()


@needs_outputs
def test_manifest_summary_and_qc_reconcile_with_parquet():
    df = pd.read_parquet(CLUSTERED_OUTPUT)
    manifest = json.loads(MANIFEST_JSON.read_text(encoding="utf-8"))
    summary = pd.read_csv(SUMMARY_CSV)
    qc = pd.read_csv(QC_CSV)

    assert manifest["input_sha256"] == EXPECTED_DEDUP_SHA256
    assert manifest["output_sha256"] == compute_sha256(CLUSTERED_OUTPUT)
    assert manifest["parameters"]["distance_threshold"] == DEFAULT_DISTANCE_THRESHOLD
    assert manifest["parameters"]["window_days"] == DEFAULT_WINDOW_DAYS
    assert manifest["parameters"]["linkage"] == DEFAULT_LINKAGE

    sizes = df["event_cluster_id"].value_counts()
    m = manifest["metrics"]
    assert m["total_events"] == len(sizes)
    assert m["singleton_events"] == int((sizes == 1).sum())
    assert m["multi_article_events"] == int((sizes >= 2).sum()) == len(summary)
    assert int(summary["cluster_size"].sum()) + m["singleton_events"] == len(df)
    assert set(summary["event_cluster_id"]) == set(sizes[sizes >= 2].index)
    assert (summary["cluster_size"].to_numpy() == sizes[summary["event_cluster_id"]].to_numpy()).all()

    near = qc[qc["stratum"] == STRATUM_INTER_NEAR]
    assert len(near) > 0
    assert (near["left_event_cluster_id"] != near["right_event_cluster_id"]).all()
    assert SWEEP_CSV.is_file()

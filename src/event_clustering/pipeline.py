"""Phase 2C pipeline orchestrator — reads dedup output, embeds, clusters, writes results."""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd

# Ensure repository root is importable
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.event_clustering.clusterer import EventClusterer
from src.event_clustering.embedder import ArticleEmbedder

logger = logging.getLogger(__name__)

# Frozen schema: the 20 columns from articles_dedup.parquet + event_cluster_id
FROZEN_SCHEMA_INPUT = [
    "article_id",
    "title",
    "url",
    "canonical_url",
    "publisher_domain",
    "publisher_id",
    "publisher_group_id",
    "source_system",
    "first_seen_at",
    "published_at",
    "timestamp_confidence",
    "language",
    "publisher_country",
    "description",
    "category",
    "vietnam_relevance",
    "duplicate_family_id",
    "branch",
    "collection_mode",
    "raw_payload_ref",
]

FROZEN_SCHEMA_OUTPUT = FROZEN_SCHEMA_INPUT + ["event_cluster_id"]


def compute_sha256(filepath: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _json_serializer(obj: Any) -> Any:
    """Custom JSON serializer for numpy/pathlib types."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def run_event_clustering_pipeline(
    input_path: Path | None = None,
    output_path: Path | None = None,
    sample_output_dir: Path | None = None,
    distance_threshold: float = 0.35,
    max_event_days: float = 10.0,
    model_name: str = "paraphrase-multilingual-MiniLM-L12-v2",
    batch_size: int = 64,
) -> Dict[str, Any]:
    """Run the full Phase 2C event clustering pipeline.

    Args:
        input_path: Path to articles_dedup.parquet (Phase 2B output).
        output_path: Path to write articles_clustered.parquet.
        sample_output_dir: Directory for QC artifacts (CSV, JSON).
        distance_threshold: Cosine distance threshold for clustering.
        max_event_days: Max temporal span for articles in same event.
        model_name: sentence-transformers model name.
        batch_size: Embedding batch size.

    Returns:
        Dict with pipeline metrics.
    """
    if input_path is None:
        input_path = REPOSITORY_ROOT / "data/processed/master/articles_dedup.parquet"
    if output_path is None:
        output_path = REPOSITORY_ROOT / "data/processed/master/articles_clustered.parquet"
    if sample_output_dir is None:
        sample_output_dir = (
            REPOSITORY_ROOT
            / "team_work/phases/phase2_processing/phase2c_event_clustering/sample_output"
        )

    input_path = Path(input_path)
    output_path = Path(output_path)
    sample_output_dir = Path(sample_output_dir)
    sample_output_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Load and validate input ──────────────────────────────────
    logger.info("Loading input from %s …", input_path)
    assert input_path.is_file(), f"Input file not found: {input_path}"
    input_sha256 = compute_sha256(input_path)

    df = pd.read_parquet(input_path)
    assert list(df.columns) == FROZEN_SCHEMA_INPUT, (
        f"Input schema mismatch. Expected {FROZEN_SCHEMA_INPUT}, got {list(df.columns)}"
    )
    n_rows = len(df)
    logger.info("Loaded %d articles (SHA-256: %s)", n_rows, input_sha256[:16])

    # ── Step 2: Embed articles ───────────────────────────────────────────
    t0 = time.time()
    embedder = ArticleEmbedder(model_name=model_name)
    embeddings = embedder.embed(df, batch_size=batch_size)
    embed_time = time.time() - t0
    logger.info("Embedding took %.1fs", embed_time)

    # ── Step 3: Cluster ──────────────────────────────────────────────────
    t0 = time.time()
    clusterer = EventClusterer(
        distance_threshold=distance_threshold,
        max_event_days=max_event_days,
    )
    labels = clusterer.cluster(embeddings, df)
    output_df, cluster_summaries, metrics = clusterer.assign_event_ids(df, labels)
    cluster_time = time.time() - t0
    logger.info("Clustering took %.1fs", cluster_time)

    # ── Step 4: Validate output schema ───────────────────────────────────
    assert list(output_df.columns) == FROZEN_SCHEMA_OUTPUT, (
        f"Output schema mismatch. Expected {FROZEN_SCHEMA_OUTPUT}, got {list(output_df.columns)}"
    )
    assert len(output_df) == n_rows, "Row count changed during clustering!"

    # Validate immutability of non-cluster columns
    non_cluster_cols = [c for c in FROZEN_SCHEMA_OUTPUT if c != "event_cluster_id"]
    pd.testing.assert_frame_equal(
        df[non_cluster_cols].reset_index(drop=True),
        output_df[non_cluster_cols].reset_index(drop=True),
    )

    # Validate duplicate family constraint
    family_groups = output_df[output_df["duplicate_family_id"].notna()].groupby("duplicate_family_id")
    for fam_id, group in family_groups:
        event_ids = group["event_cluster_id"].dropna().unique()
        assert len(event_ids) <= 1, (
            f"Family {fam_id} has members in multiple event clusters: {event_ids}"
        )

    # ── Step 5: Write output ─────────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_df.to_parquet(output_path, index=False, engine="pyarrow")
    output_sha256 = compute_sha256(output_path)
    logger.info("Wrote %d rows to %s", len(output_df), output_path)

    # ── Step 6: Write QC artifacts ───────────────────────────────────────
    # Cluster summary CSV
    summary_csv = sample_output_dir / "event_cluster_summary.csv"
    if cluster_summaries:
        pd.DataFrame(cluster_summaries).to_csv(summary_csv, index=False, encoding="utf-8-sig")
        logger.info("Wrote cluster summary to %s", summary_csv)

    # QC sample CSV — stratified sample of article pairs for manual review
    qc_pairs = _generate_qc_pairs(output_df, cluster_summaries, n_per_stratum=10)
    qc_csv = sample_output_dir / "event_clusters_qc.csv"
    qc_pairs.to_csv(qc_csv, index=False, encoding="utf-8-sig")
    logger.info("Wrote QC pairs (%d rows) to %s", len(qc_pairs), qc_csv)

    # Manifest JSON
    metrics["input_path"] = str(input_path)
    metrics["input_sha256"] = input_sha256
    metrics["output_path"] = str(output_path)
    metrics["output_sha256"] = output_sha256
    metrics["input_rows"] = n_rows
    metrics["output_rows"] = len(output_df)
    metrics["model_name"] = model_name
    metrics["embedding_dim"] = int(embedder.embedding_dim)
    metrics["embed_time_seconds"] = round(embed_time, 2)
    metrics["cluster_time_seconds"] = round(cluster_time, 2)
    metrics["timestamp"] = datetime.now(timezone.utc).isoformat()

    manifest_json = sample_output_dir / "event_clustering_manifest.json"
    with open(manifest_json, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False, default=_json_serializer)
    logger.info("Wrote manifest to %s", manifest_json)

    return metrics


def _generate_qc_pairs(
    df: pd.DataFrame,
    cluster_summaries: list,
    n_per_stratum: int = 10,
) -> pd.DataFrame:
    """Generate a stratified QC sample of article pairs for manual review.

    Strata:
    1. INTRA_CLUSTER_SAME_PUB: same event, same publisher
    2. INTRA_CLUSTER_CROSS_PUB: same event, different publishers (most interesting)
    3. INTER_CLUSTER_NEAR: different events but semantically close (hard negatives)
    """
    import random
    random.seed(42)

    pairs = []
    clustered = df[df["event_cluster_id"].notna()]

    # Stratum 1 & 2: intra-cluster pairs
    for evt_id in clustered["event_cluster_id"].unique():
        members = clustered[clustered["event_cluster_id"] == evt_id]
        if len(members) < 2:
            continue
        indices = members.index.tolist()
        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                a, b = df.loc[indices[i]], df.loc[indices[j]]
                same_pub = a["publisher_domain"] == b["publisher_domain"]
                stratum = "INTRA_CLUSTER_SAME_PUB" if same_pub else "INTRA_CLUSTER_CROSS_PUB"
                pairs.append({
                    "left_article_id": a["article_id"],
                    "right_article_id": b["article_id"],
                    "left_publisher": a["publisher_domain"],
                    "right_publisher": b["publisher_domain"],
                    "left_title": a["title"],
                    "right_title": b["title"],
                    "left_description": str(a["description"] or ""),
                    "right_description": str(b["description"] or ""),
                    "event_cluster_id": evt_id,
                    "stratum": stratum,
                    "manual_label": "",
                    "review_notes": "",
                })

    # Stratum 3: inter-cluster near pairs (sample from different clusters)
    cluster_ids = clustered["event_cluster_id"].unique().tolist()
    if len(cluster_ids) >= 2:
        for _ in range(n_per_stratum):
            c1, c2 = random.sample(cluster_ids, 2)
            m1 = clustered[clustered["event_cluster_id"] == c1]
            m2 = clustered[clustered["event_cluster_id"] == c2]
            a = m1.sample(1, random_state=random.randint(0, 9999)).iloc[0]
            b = m2.sample(1, random_state=random.randint(0, 9999)).iloc[0]
            pairs.append({
                "left_article_id": a["article_id"],
                "right_article_id": b["article_id"],
                "left_publisher": a["publisher_domain"],
                "right_publisher": b["publisher_domain"],
                "left_title": a["title"],
                "right_title": b["title"],
                "left_description": str(a["description"] or ""),
                "right_description": str(b["description"] or ""),
                "event_cluster_id": f"{c1} vs {c2}",
                "stratum": "INTER_CLUSTER_NEAR",
                "manual_label": "",
                "review_notes": "",
            })

    return pd.DataFrame(pairs)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    metrics = run_event_clustering_pipeline()
    print("\n=== Phase 2C Event Clustering Complete ===")
    print(json.dumps(metrics, indent=2, default=_json_serializer))

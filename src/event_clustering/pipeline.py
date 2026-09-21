"""Phase 2C pipeline: frozen dedup artifact → event clusters (every article gets an event id)."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

# Ensure repository root is importable when run as a script
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.event_clustering.clusterer import (  # noqa: E402
    build_summaries,
    cluster_units,
    collapse_families,
    event_time,
    propagate,
    summarize_metrics,
)
from src.event_clustering.embedder import DEFAULT_MODEL_NAME, ArticleEmbedder  # noqa: E402
from src.event_clustering.qc import select_qc_pairs  # noqa: E402
from src.event_clustering.sweep import run_sweep  # noqa: E402

logger = logging.getLogger(__name__)

# Frozen schema: the 20 columns of articles_dedup.parquet + event_cluster_id
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

# The ONLY authoritative Phase 2C input: Phase 2B frozen on main at commit 3442f01.
EXPECTED_DEDUP_SHA256 = "4d1b967a99a103c0e4ede002786e84f52cbe5c61bb011d878189cd7d4bc6244f"

DEFAULT_INPUT = REPOSITORY_ROOT / "data/processed/master/articles_dedup.parquet"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "data/processed/master/articles_clustered.parquet"
DEFAULT_SAMPLE_DIR = (
    REPOSITORY_ROOT / "team_work/phases/phase2_processing/phase2c_event_clustering/sample_output"
)
DEFAULT_CACHE_DIR = REPOSITORY_ROOT / "data/interim"

# Selected from the sweep (see phase2c README / threshold_sweep.csv).
DEFAULT_DISTANCE_THRESHOLD = 0.30
DEFAULT_WINDOW_DAYS = 5.0
DEFAULT_LINKAGE = "complete"


class ContractError(ValueError):
    """Raised when data violates the Phase 2 frozen contract."""


def compute_sha256(filepath: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _json_default(obj: Any) -> Any:
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, Path):
        return obj.as_posix()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _relative(path: Path) -> str:
    """Repo-relative POSIX path (keeps tracked manifests free of machine-specific paths)."""
    try:
        return Path(path).resolve().relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError:
        return Path(path).name


def _git_revision() -> Optional[str]:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def validate_input(df: pd.DataFrame) -> None:
    if list(df.columns) != FROZEN_SCHEMA_INPUT:
        raise ContractError(
            f"Input schema mismatch. Expected {FROZEN_SCHEMA_INPUT}, got {list(df.columns)}"
        )
    if df["article_id"].duplicated().any():
        raise ContractError("article_id must be unique in the input")


def validate_output(df: pd.DataFrame, output_df: pd.DataFrame) -> None:
    """Contract checks on the final propagated frame."""
    if list(output_df.columns) != FROZEN_SCHEMA_OUTPUT:
        raise ContractError(f"Output schema mismatch: {list(output_df.columns)}")
    if len(output_df) != len(df):
        raise ContractError("Row count changed during clustering")
    if output_df["event_cluster_id"].isna().any():
        raise ContractError("Every article must have an event_cluster_id (singleton events included)")

    pd.testing.assert_frame_equal(
        df.reset_index(drop=True),
        output_df[FROZEN_SCHEMA_INPUT].reset_index(drop=True),
        check_exact=True,
    )

    families = output_df[output_df["duplicate_family_id"].notna()]
    spread = families.groupby("duplicate_family_id")["event_cluster_id"].nunique()
    if (spread > 1).any():
        raise ContractError(f"Duplicate families split across events: {spread[spread > 1].index.tolist()}")


def run_event_clustering_pipeline(
    input_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    sample_output_dir: Optional[Path] = None,
    distance_threshold: float = DEFAULT_DISTANCE_THRESHOLD,
    window_days: float = DEFAULT_WINDOW_DAYS,
    linkage: str = DEFAULT_LINKAGE,
    model_name: str = DEFAULT_MODEL_NAME,
    batch_size: int = 64,
    cache_dir: Optional[Path] = DEFAULT_CACHE_DIR,
    run_threshold_sweep: bool = True,
    expected_input_sha256: Optional[str] = EXPECTED_DEDUP_SHA256,
    embeddings: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Run the full Phase 2C pipeline and return the run manifest.

    Steps: load + verify frozen input → embed (HTML-unescaped title+description) → collapse duplicate
    families into units → cluster units (published_at time gate) → propagate event ids to every article →
    recompute summaries from the final frame → QC pairs → optional parameter sweep.

    ``embeddings`` may be injected (row-aligned with the input) to skip the model, e.g. in tests.
    """
    input_path = Path(input_path or DEFAULT_INPUT)
    output_path = Path(output_path or DEFAULT_OUTPUT)
    sample_output_dir = Path(sample_output_dir or DEFAULT_SAMPLE_DIR)
    sample_output_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Load and verify the frozen Phase 2B artifact ─────────────────────
    if not input_path.is_file():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    input_sha256 = compute_sha256(input_path)
    if expected_input_sha256 is not None and input_sha256 != expected_input_sha256:
        raise ContractError(
            f"{input_path.name} SHA-256 {input_sha256} != frozen Phase 2B artifact {expected_input_sha256}. "
            "Phase 2C must use the dedup parquet published on main (3442f01)."
        )
    df = pd.read_parquet(input_path).reset_index(drop=True)
    validate_input(df)
    n_rows = len(df)
    logger.info("Loaded %d articles (SHA-256 %s…)", n_rows, input_sha256[:16])

    # ── 2. Event time and embeddings ────────────────────────────────────────
    times, time_source = event_time(df)

    t0 = time.time()
    embedder = ArticleEmbedder(model_name=model_name)
    if embeddings is None:
        embeddings = embedder.embed(df, batch_size=batch_size, cache_dir=cache_dir)
    embeddings = np.asarray(embeddings)
    if len(embeddings) != n_rows:
        raise ContractError("Embedding count does not match row count")
    embed_time = time.time() - t0

    # ── 3. Collapse duplicate families, cluster units, propagate ────────────
    t0 = time.time()
    units = collapse_families(df, embeddings, times)
    unit_labels = cluster_units(units.embeddings, units.times, distance_threshold, window_days, linkage)
    output_df = df.copy()
    output_df["event_cluster_id"] = propagate(df, units, unit_labels, times)
    cluster_time = time.time() - t0

    # ── 4. Validate final frame, then summarise FROM it ─────────────────────
    validate_output(df, output_df)
    summary = build_summaries(output_df, embeddings, times)
    metrics = summarize_metrics(summary, n_rows)
    if int(summary["cluster_size"].sum()) != n_rows:
        raise ContractError("Event summary does not reconcile with the propagated frame")

    # ── 5. Write outputs ────────────────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_df.to_parquet(output_path, index=False, engine="pyarrow")
    output_sha256 = compute_sha256(output_path)
    logger.info("Wrote %d rows to %s", n_rows, output_path)

    multi = summary[summary["cluster_size"] >= 2]
    multi.to_csv(sample_output_dir / "event_cluster_summary.csv", index=False, encoding="utf-8-sig")

    qc = select_qc_pairs(output_df, embeddings, times, window_days=window_days)
    qc.to_csv(sample_output_dir / "event_clusters_qc.csv", index=False, encoding="utf-8-sig")
    metrics["qc_pairs_by_stratum"] = {k: int(v) for k, v in qc["stratum"].value_counts().sort_index().items()}

    sweep_rows = 0
    if run_threshold_sweep:
        sweep = run_sweep(df, embeddings, times, units)
        sweep.to_csv(sample_output_dir / "threshold_sweep.csv", index=False)
        sweep_rows = len(sweep)

    # ── 6. Manifest ─────────────────────────────────────────────────────────
    manifest: Dict[str, Any] = {
        "stage": "Phase 2C - Event Clustering",
        "input_path": _relative(input_path),
        "input_sha256": input_sha256,
        "input_rows": n_rows,
        "output_path": _relative(output_path),
        "output_sha256": output_sha256,
        "output_rows": len(output_df),
        "parameters": {
            "model_name": model_name,
            "embedding_dim": int(embeddings.shape[1]),
            "text_cleaning": "html.unescape + NFC + whitespace collapse (embedding input only)",
            "distance_metric": "cosine",
            "linkage": linkage,
            "distance_threshold": distance_threshold,
            "window_days": window_days,
            "event_time": "published_at, fallback first_seen_at",
            "singleton_events": "assigned (event_cluster_id never null)",
        },
        "time_source_counts": {str(k): int(v) for k, v in time_source.value_counts().items()},
        "clustering_units": {
            "n_units": len(units.members),
            "n_duplicate_families_collapsed": int(df["duplicate_family_id"].nunique()),
            "articles_in_duplicate_families": int(df["duplicate_family_id"].notna().sum()),
        },
        "metrics": metrics,
        "sweep_settings_evaluated": sweep_rows,
        "embed_time_seconds": round(embed_time, 2),
        "cluster_time_seconds": round(cluster_time, 2),
        "code_base_revision": _git_revision(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(sample_output_dir / "event_clustering_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False, default=_json_default)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Phase 2C event clustering.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-output-dir", type=Path, default=DEFAULT_SAMPLE_DIR)
    parser.add_argument("--threshold", type=float, default=DEFAULT_DISTANCE_THRESHOLD)
    parser.add_argument("--window-days", type=float, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--linkage", choices=["average", "complete"], default=DEFAULT_LINKAGE)
    parser.add_argument("--skip-sweep", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    manifest = run_event_clustering_pipeline(
        input_path=args.input,
        output_path=args.output,
        sample_output_dir=args.sample_output_dir,
        distance_threshold=args.threshold,
        window_days=args.window_days,
        linkage=args.linkage,
        run_threshold_sweep=not args.skip_sweep,
    )
    print("\n=== Phase 2C Event Clustering Complete ===")
    print(json.dumps(manifest, indent=2, ensure_ascii=False, default=_json_default))


if __name__ == "__main__":
    main()

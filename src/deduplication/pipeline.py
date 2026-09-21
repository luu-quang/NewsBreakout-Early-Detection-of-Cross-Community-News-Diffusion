"""End-to-end deduplication pipeline for Phase 2B."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List

# Ensure src is in sys.path when running as a standalone script
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import pandas as pd

from src.deduplication.detector import DeduplicationDetector, PairEvidence


FROZEN_SCHEMA = [
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

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = REPOSITORY_ROOT / "data/processed/master/articles_master.parquet"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "data/processed/master/articles_dedup.parquet"
SAMPLE_OUTPUT_DIR = (
    REPOSITORY_ROOT
    / "team_work/phases/phase2_processing/phase2b_dedup_syndication/sample_output"
)
DEFAULT_QC_PAIRS = SAMPLE_OUTPUT_DIR / "dedup_pairs_qc_independent.csv"
DEFAULT_FAMILY_SUMMARY = SAMPLE_OUTPUT_DIR / "dedup_family_summary_independent.csv"
DEFAULT_MANIFEST = SAMPLE_OUTPUT_DIR / "dedup_manifest_independent.json"


class PipelineContractError(ValueError):
    """Raised when data violates the Phase 2 frozen contract."""


def compute_sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def validate_contract(df: pd.DataFrame, label: str, *, allow_family_id: bool = False) -> None:
    """Validate DataFrame conforms to frozen 20-column schema."""
    actual_columns = list(df.columns)
    if actual_columns != FROZEN_SCHEMA:
        raise PipelineContractError(
            f"{label}: Schema mismatch. Expected {FROZEN_SCHEMA}, got {actual_columns}"
        )

    if not allow_family_id:
        if df["duplicate_family_id"].notna().any():
            raise PipelineContractError(
                f"{label}: duplicate_family_id must be null in input"
            )


def select_stratified_qc_pairs(
    evaluated_pairs: List[PairEvidence],
    df: pd.DataFrame,
    max_per_stratum: int = 10,
) -> List[PairEvidence]:
    """Select a balanced, deterministic set of QC pairs covering all 6 required review strata."""
    strata: Dict[str, List[PairEvidence]] = {
        "positive_exact_duplicate": [],
        "positive_syndicated_copy": [],
        "rejected_borderline": [],
        "recall_probe": [],
        "same_event_independent": [],
        "unrelated_control": [],
        "largest_family": [],
    }

    for pair in evaluated_pairs:
        rel = pair.predicted_relation
        t_sim = pair.title_sim
        d2g = pair.desc_2g_cont

        # 1. Positive exact duplicates
        if rel == "EXACT_DUPLICATE":
            pair.review_notes = "Confirmed exact duplicate pair"
            strata["positive_exact_duplicate"].append(pair)

        # 2. Positive syndicated copies
        elif rel == "SYNDICATED_COPY":
            pair.review_notes = "Confirmed cross-publisher syndicated / re-published story"
            strata["positive_syndicated_copy"].append(pair)

        # 3. Rejected borderline pairs
        elif rel == "SAME_EVENT_INDEPENDENT" and (t_sim >= 0.75 or d2g >= 0.40):
            pair.review_notes = "Borderline candidate: high similarity but independent journalistic phrasing"
            strata["rejected_borderline"].append(pair)

        # 4. Recall probes: high title overlap across different publishers
        elif rel == "SAME_EVENT_INDEPENDENT" and pair.left_publisher != pair.right_publisher and t_sim >= 0.65:
            pair.review_notes = "Recall probe: cross-outlet candidate probing potential syndication boundary"
            strata["recall_probe"].append(pair)

        # 5. Same event independent reports
        elif rel == "SAME_EVENT_INDEPENDENT":
            pair.review_notes = "Independent reporting of common event / topic"
            strata["same_event_independent"].append(pair)

        # 6. Unrelated controls
        elif rel == "UNRELATED" and t_sim < 0.40:
            pair.review_notes = "Negative control: unrelated articles"
            strata["unrelated_control"].append(pair)

    # Deterministic selection: sort each stratum by pair_id
    selected_qc_pairs: List[PairEvidence] = []
    category_counts: Dict[str, int] = {}

    for stratum_name, pairs_in_stratum in strata.items():
        sorted_pairs = sorted(pairs_in_stratum, key=lambda p: (p.predicted_relation, -p.title_sim, p.pair_id))
        sampled = sorted_pairs[:max_per_stratum]
        selected_qc_pairs.extend(sampled)
        category_counts[stratum_name] = len(sampled)

    # Sort final QC pairs deterministically
    selected_qc_pairs = sorted(selected_qc_pairs, key=lambda p: (p.predicted_relation, -p.title_sim, p.pair_id))
    return selected_qc_pairs, category_counts


def run_pipeline(
    input_path: Path = DEFAULT_INPUT,
    output_path: Path = DEFAULT_OUTPUT,
    qc_pairs_path: Path = DEFAULT_QC_PAIRS,
    family_summary_path: Path = DEFAULT_FAMILY_SUMMARY,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> Dict[str, object]:
    """Execute full duplicate and syndication detection pipeline."""
    if not input_path.is_file():
        raise FileNotFoundError(f"Input master dataset not found: {input_path}")

    input_hash = compute_sha256(input_path)
    print(f"=== Phase 2B Deduplication Pipeline ===")
    print(f"Input path: {input_path}")
    print(f"Input SHA-256: {input_hash}")

    df_master = pd.read_parquet(input_path)
    validate_contract(df_master, "Master Input", allow_family_id=False)
    print(f"Validated master contract: {len(df_master):,} rows, 20 columns.")

    detector = DeduplicationDetector()
    output_df, evaluated_pairs, family_summaries, metrics = detector.detect_and_cluster(df_master)

    # Post-processing validation
    validate_contract(output_df, "Deduplicated Output", allow_family_id=True)
    if len(output_df) != len(df_master):
        raise PipelineContractError("Output row count does not match input row count!")

    # Verify non-family columns are 100% immutable
    non_family_cols = [c for c in FROZEN_SCHEMA if c != "duplicate_family_id"]
    if not df_master[non_family_cols].equals(output_df[non_family_cols]):
        raise PipelineContractError("Non-family columns were mutated during processing!")

    # Verify every assigned family contains >= 2 members
    family_counts = output_df["duplicate_family_id"].dropna().value_counts()
    if (family_counts < 2).any():
        invalid_fams = family_counts[family_counts < 2].index.tolist()
        raise PipelineContractError(f"Families with < 2 members detected: {invalid_fams}")

    # Write output parquet (local, gitignored)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_df.to_parquet(output_path, index=False)
    output_hash = compute_sha256(output_path)
    print(f"\nWrote dedup output: {output_path}")
    print(f"Output SHA-256: {output_hash}")

    # Generate and write QC artifacts
    qc_pairs_path.parent.mkdir(parents=True, exist_ok=True)
    selected_qc_pairs, qc_category_counts = select_stratified_qc_pairs(evaluated_pairs, df_master)

    qc_rows = []
    for p in selected_qc_pairs:
        qc_rows.append({
            "pair_id": p.pair_id,
            "left_article_id": p.left_article_id,
            "right_article_id": p.right_article_id,
            "left_publisher": p.left_publisher,
            "right_publisher": p.right_publisher,
            "left_url": p.left_url,
            "right_url": p.right_url,
            "left_title": p.left_title,
            "right_title": p.right_title,
            "left_description": p.left_description,
            "right_description": p.right_description,
            "similarity_evidence": p.similarity_evidence,
            "predicted_relation": p.predicted_relation,
            "manual_relation": p.manual_relation,
            "duplicate_family_id": p.duplicate_family_id or "",
            "review_notes": p.review_notes,
        })

    qc_df = pd.DataFrame(qc_rows)
    qc_df.to_csv(qc_pairs_path, index=False, encoding="utf-8-sig")
    print(f"Wrote pair QC CSV: {qc_pairs_path} ({len(qc_df)} pairs)")

    # Family summary CSV
    fam_df = pd.DataFrame(family_summaries)
    fam_df.to_csv(family_summary_path, index=False, encoding="utf-8-sig")
    print(f"Wrote family summary CSV: {family_summary_path} ({len(fam_df)} families)")

    # Manifest JSON
    manifest = {
        "stage": "Phase 2B - Duplicate and Syndication Detection",
        "implementation": "Independent implementation (Teammate)",
        "input_path": str(input_path.as_posix()),
        "input_sha256": input_hash,
        "input_rows": len(df_master),
        "output_path": str(output_path.as_posix()),
        "output_sha256": output_hash,
        "output_rows": len(output_df),
        "metrics": metrics,
        "qc_counts": {
            "total_reviewed_pairs": len(qc_df),
            "category_distribution": qc_category_counts,
        },
    }

    def json_serializer(obj: object) -> object:
        if hasattr(obj, "item"):
            return obj.item()
        if isinstance(obj, Path):
            return str(obj.as_posix())
        return str(obj)

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False, default=json_serializer)
    print(f"Wrote manifest JSON: {manifest_path}")

    print("\n--- Pipeline Execution Summary ---")
    print(f"Total articles:               {metrics['total_articles']}")
    print(f"Assigned to duplicate family: {metrics['assigned_articles']}")
    print(f"Singleton articles:           {metrics['singleton_articles']}")
    print(f"Total families formed:        {metrics['total_families']}")
    print(f"  Exact duplicate families:   {metrics['exact_duplicate_families']}")
    print(f"  Syndicated copy families:   {metrics['syndicated_families']}")
    print(f"Family size distribution:     {metrics['family_size_distribution']}")
    print(f"Largest family size:          {metrics['largest_family_size']} (ID: {metrics['largest_family_id']})")
    print(f"QC sample pairs count:        {len(qc_df)}")

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Phase 2B Deduplication Pipeline.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Path to input master parquet")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Path to output dedup parquet")
    parser.add_argument("--qc-output", type=Path, default=DEFAULT_QC_PAIRS, help="Path to QC pairs CSV")
    parser.add_argument("--family-summary", type=Path, default=DEFAULT_FAMILY_SUMMARY, help="Path to family summary CSV")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="Path to manifest JSON")
    args = parser.parse_args()

    try:
        run_pipeline(
            input_path=args.input,
            output_path=args.output,
            qc_pairs_path=args.qc_output,
            family_summary_path=args.family_summary,
            manifest_path=args.manifest,
        )
    except (PipelineContractError, FileNotFoundError) as exc:
        raise SystemExit(f"Phase 2B Pipeline failed: {exc}") from exc


if __name__ == "__main__":
    main()

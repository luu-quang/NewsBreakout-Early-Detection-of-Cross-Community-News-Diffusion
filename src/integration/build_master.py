"""Build Phase 2 master article and audit datasets from frozen Phase 1 outputs."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import pandas as pd


SHARED_SCHEMA = [
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
AUDIT_SCHEMA = SHARED_SCHEMA + ["source_seen_at", "rejection_reason"]

ALLOWED_BRANCHES = {"domestic", "international"}
ALLOWED_COLLECTION_MODES = {"prospective", "historical_backfill"}
ALLOWED_TIMESTAMP_CONFIDENCE = {
    "publisher_reported",
    "publisher_reported_timezone_inferred",
    "unavailable",
}

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VN_ARTICLES = REPOSITORY_ROOT / "data/processed/vietnamese/vietnamese_clean.parquet"
DEFAULT_INTL_ARTICLES = REPOSITORY_ROOT / "data/processed/international/international_clean.parquet"
DEFAULT_VN_AUDIT = REPOSITORY_ROOT / "data/processed/vietnamese/vietnamese_clean_audit.parquet"
DEFAULT_INTL_AUDIT = REPOSITORY_ROOT / "data/processed/international/international_clean_audit.parquet"
DEFAULT_MASTER_ARTICLES = REPOSITORY_ROOT / "data/processed/master/articles_master.parquet"
DEFAULT_MASTER_AUDIT = REPOSITORY_ROOT / "data/processed/master/articles_audit.parquet"


class ContractError(ValueError):
    """Raised when a Phase 1 input violates the frozen shared contract."""


def _nonblank(series: pd.Series) -> pd.Series:
    return series.notna() & series.astype(str).str.strip().ne("")


def _format_examples(indices: Iterable[object]) -> str:
    return ", ".join(str(index) for index in list(indices)[:5])


def _validate_schema(df: pd.DataFrame, expected: list[str], label: str) -> None:
    actual = list(df.columns)
    if actual == expected:
        return
    missing = [column for column in expected if column not in actual]
    unexpected = [column for column in actual if column not in expected]
    raise ContractError(
        f"{label}: incompatible schema. Expected columns in this exact order: {expected}. "
        f"Actual: {actual}. Missing: {missing or 'none'}. "
        f"Unexpected: {unexpected or 'none'}."
    )


def _validate_allowed_values(
    df: pd.DataFrame,
    column: str,
    allowed: set[str],
    label: str,
) -> None:
    invalid = df[column].isna() | ~df[column].isin(allowed)
    if invalid.any():
        values = df.loc[invalid, column].drop_duplicates().tolist()[:5]
        raise ContractError(
            f"{label}: {column} contains values outside {sorted(allowed)}: {values}"
        )


def _validate_utc_timestamps(
    df: pd.DataFrame,
    column: str,
    label: str,
    *,
    nullable: bool,
) -> None:
    present = df[column].notna()
    if not nullable and not present.all():
        raise ContractError(
            f"{label}: {column} is required but is null at rows "
            f"{_format_examples(df.index[~present])}."
        )

    failures: list[object] = []
    for index, value in df.loc[present, column].items():
        try:
            timestamp = pd.Timestamp(value)
        except (TypeError, ValueError):
            failures.append(index)
            continue
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            failures.append(index)
            continue
        if timestamp.utcoffset().total_seconds() != 0:
            failures.append(index)

    if failures:
        raise ContractError(
            f"{label}: {column} must contain explicit UTC timestamps; invalid rows: "
            f"{_format_examples(failures)}."
        )


def _validate_required_identifiers(
    df: pd.DataFrame,
    label: str,
    *,
    audit: bool,
) -> None:
    if audit:
        valid_row = df["rejection_reason"].isna() | df["rejection_reason"].astype(str).str.strip().eq("")
    else:
        valid_row = pd.Series(True, index=df.index)

    required_masks = {
        "article_id": valid_row,
        "canonical_url": valid_row,
        "raw_payload_ref": pd.Series(True, index=df.index),
    }
    for column, required in required_masks.items():
        missing = required & ~_nonblank(df[column])
        if missing.any():
            raise ContractError(
                f"{label}: {column} is missing where required at rows "
                f"{_format_examples(df.index[missing])}."
            )


def validate_phase1_frame(
    df: pd.DataFrame,
    *,
    label: str,
    expected_schema: list[str],
    expected_branch: str | None,
    audit: bool,
) -> None:
    _validate_schema(df, expected_schema, label)
    _validate_allowed_values(df, "branch", ALLOWED_BRANCHES, label)
    _validate_allowed_values(df, "collection_mode", ALLOWED_COLLECTION_MODES, label)
    _validate_allowed_values(
        df,
        "timestamp_confidence",
        ALLOWED_TIMESTAMP_CONFIDENCE,
        label,
    )

    if expected_branch is not None:
        wrong_branch = df["branch"].ne(expected_branch)
        if wrong_branch.any():
            values = df.loc[wrong_branch, "branch"].drop_duplicates().tolist()
            raise ContractError(
                f"{label}: expected branch={expected_branch!r}, found {values}."
            )

    if not pd.api.types.is_bool_dtype(df["vietnam_relevance"].dtype):
        raise ContractError(f"{label}: vietnam_relevance must use a boolean dtype.")
    invalid_relevance = df["vietnam_relevance"].isna() | ~df[
        "vietnam_relevance"
    ].isin([True, False])
    if invalid_relevance.any():
        raise ContractError(f"{label}: vietnam_relevance must contain only non-null booleans.")
    if not audit and not df["vietnam_relevance"].eq(True).all():
        false_count = int(df["vietnam_relevance"].ne(True).sum())
        raise ContractError(
            f"{label}: relevant-only input contains {false_count} row(s) where "
            "vietnam_relevance is not True."
        )

    _validate_utc_timestamps(df, "first_seen_at", label, nullable=False)
    _validate_utc_timestamps(df, "published_at", label, nullable=True)
    _validate_required_identifiers(df, label, audit=audit)

    if df["duplicate_family_id"].notna().any():
        raise ContractError(
            f"{label}: duplicate_family_id must remain null before deduplication."
        )


def _read_phase1(
    path: Path,
    *,
    label: str,
    expected_schema: list[str],
    expected_branch: str,
    audit: bool,
) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"{label}: Phase 1 input not found: {path}")
    frame = pd.read_parquet(path)
    validate_phase1_frame(
        frame,
        label=label,
        expected_schema=expected_schema,
        expected_branch=expected_branch,
        audit=audit,
    )
    return frame


def _duplicate_counts(df: pd.DataFrame, column: str) -> tuple[int, int]:
    values = df.loc[_nonblank(df[column]), column]
    duplicate_values = int(values[values.duplicated(keep=False)].nunique())
    excess_rows = int(values.duplicated(keep="first").sum())
    return duplicate_values, excess_rows


def _print_summary(label: str, df: pd.DataFrame) -> None:
    print(f"\n{label}: {len(df):,} rows")
    for column in ("branch", "collection_mode", "source_system", "vietnam_relevance"):
        counts = df.groupby(column, dropna=False).size()
        rendered = ", ".join(f"{value}={count:,}" for value, count in counts.items())
        print(f"  {column}: {rendered}")
    for column in ("article_id", "canonical_url"):
        duplicate_values, excess_rows = _duplicate_counts(df, column)
        print(
            f"  duplicate {column}: {duplicate_values:,} value(s), "
            f"{excess_rows:,} row(s) beyond first"
        )


def build_master(
    vn_articles_path: Path,
    intl_articles_path: Path,
    vn_audit_path: Path,
    intl_audit_path: Path,
    master_articles_path: Path,
    master_audit_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    vn_articles = _read_phase1(
        vn_articles_path,
        label="Vietnamese relevant-only",
        expected_schema=SHARED_SCHEMA,
        expected_branch="domestic",
        audit=False,
    )
    intl_articles = _read_phase1(
        intl_articles_path,
        label="International relevant-only",
        expected_schema=SHARED_SCHEMA,
        expected_branch="international",
        audit=False,
    )
    vn_audit = _read_phase1(
        vn_audit_path,
        label="Vietnamese audit",
        expected_schema=AUDIT_SCHEMA,
        expected_branch="domestic",
        audit=True,
    )
    intl_audit = _read_phase1(
        intl_audit_path,
        label="International audit",
        expected_schema=AUDIT_SCHEMA,
        expected_branch="international",
        audit=True,
    )

    articles_master = pd.concat([vn_articles, intl_articles], ignore_index=True)
    articles_audit = pd.concat([vn_audit, intl_audit], ignore_index=True)

    # Revalidate the combined outputs before writing. Column selection is
    # intentionally absent so an incompatible input cannot be silently fixed.
    validate_phase1_frame(
        articles_master,
        label="Master articles",
        expected_schema=SHARED_SCHEMA,
        expected_branch=None,
        audit=False,
    )
    validate_phase1_frame(
        articles_audit,
        label="Master audit",
        expected_schema=AUDIT_SCHEMA,
        expected_branch=None,
        audit=True,
    )

    master_articles_path.parent.mkdir(parents=True, exist_ok=True)
    master_audit_path.parent.mkdir(parents=True, exist_ok=True)
    articles_master.to_parquet(master_articles_path, index=False)
    articles_audit.to_parquet(master_audit_path, index=False)

    _print_summary("Master articles", articles_master)
    _print_summary("Master audit", articles_audit)
    print(f"\nWrote: {master_articles_path}")
    print(f"Wrote: {master_audit_path}")
    return articles_master, articles_audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Combine frozen Phase 1 outputs into Phase 2 master datasets."
    )
    parser.add_argument("--vn-articles", type=Path, default=DEFAULT_VN_ARTICLES)
    parser.add_argument("--intl-articles", type=Path, default=DEFAULT_INTL_ARTICLES)
    parser.add_argument("--vn-audit", type=Path, default=DEFAULT_VN_AUDIT)
    parser.add_argument("--intl-audit", type=Path, default=DEFAULT_INTL_AUDIT)
    parser.add_argument("--master-articles", type=Path, default=DEFAULT_MASTER_ARTICLES)
    parser.add_argument("--master-audit", type=Path, default=DEFAULT_MASTER_AUDIT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        build_master(
            args.vn_articles,
            args.intl_articles,
            args.vn_audit,
            args.intl_audit,
            args.master_articles,
            args.master_audit,
        )
    except (ContractError, FileNotFoundError) as exc:
        raise SystemExit(f"Master integration failed: {exc}") from exc


if __name__ == "__main__":
    main()

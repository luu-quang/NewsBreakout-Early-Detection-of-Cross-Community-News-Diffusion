"""Basic cleaning for collected international articles.

Reads the raw table produced by ``collect_intl.py``, applies Phase 1's
"basic cleaning only" rules (standardize columns, normalize timestamps and
publisher domains, drop obviously broken rows), and writes three things:

- an audit/QC table with EVERY row that survived basic cleaning, both
  vietnam_relevance=True and False, to
  ``data/processed/international/international_clean_audit.parquet`` - so the
  relevance filter's false positives/negatives stay inspectable instead of
  silently vanishing.
- the final relevant-only table (audit table filtered to vietnam_relevance=True,
  and optionally to first_seen_at >= --pilot-start) to
  ``data/processed/international/international_clean.parquet``
- a small review sample (20-100 rows) drawn from the final table, to
  ``sample_output/sample_intl.csv``

Raw data is never modified or deleted; this script only reads it.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

RAW_INPUT_PATH = Path("data/raw/international/international_raw.parquet")
AUDIT_OUTPUT_PATH = Path("data/processed/international/international_clean_audit.parquet")
CLEAN_OUTPUT_PATH = Path("data/processed/international/international_clean.parquet")
SAMPLE_OUTPUT_PATH = Path(__file__).resolve().parents[1] / "sample_output" / "sample_intl.csv"

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


def normalize_domain(url_or_domain: str) -> str:
    hostname = url_or_domain
    if "://" in url_or_domain:
        hostname = urlparse(url_or_domain).hostname or ""
    hostname = hostname.lower().strip()
    return hostname[4:] if hostname.startswith("www.") else hostname


def is_vietnam_relevant(title: str, description: str | None) -> bool:
    """Require "Vietnam" in the title or description itself.

    GDELT's DOC search matches full article text, which also picks up
    sidebar/related-story boilerplate — a bare keyword hit from the collector
    is not enough to call an article Vietnam-relevant.
    """
    text = f"{title} {description or ''}".lower()
    return "vietnam" in text or "việt nam" in text


def clean(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Basic cleaning + recomputed vietnam_relevance.

    Returns the audit/QC table: EVERY row that survives basic cleaning, with
    both vietnam_relevance=True and False rows present. Callers that want only
    the relevant rows must filter this themselves - this function used to drop
    False rows internally, which meant the relevance heuristic's mistakes were
    invisible to reviewers.
    """
    if raw_df.empty:
        return pd.DataFrame(columns=SHARED_SCHEMA)

    df = raw_df.copy()

    # remove obviously broken records
    df = df.dropna(subset=["title", "url"])
    df = df[(df["title"].str.strip() != "") & (df["url"].str.strip() != "")]

    # normalize publisher/domain names
    df["publisher_domain"] = df["publisher_domain"].fillna("").map(normalize_domain)
    df = df[df["publisher_domain"] != ""]

    # normalize timestamps to UTC ISO 8601
    for col in ("first_seen_at", "published_at"):
        df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")

    df = df.dropna(subset=["first_seen_at"])

    # dedupe by URL, keeping the earliest observation
    df = df.sort_values("first_seen_at").drop_duplicates(subset=["url"], keep="first")

    # recompute vietnam_relevance from title/description, not just "the query matched somewhere";
    # both True and False rows are kept here - see module docstring
    df["vietnam_relevance"] = df.apply(
        lambda r: is_vietnam_relevant(r["title"], r.get("description")), axis=1
    )

    for col in SHARED_SCHEMA:
        if col not in df.columns:
            df[col] = None

    # sort most-recent-published first; a single collection run shares one first_seen_at,
    # so sorting by that alone (as an earlier version of this script did) does not
    # surface recent articles - it leaves rows in whatever order groupby happened to produce.
    df = df.sort_values("published_at", ascending=False)

    df["first_seen_at"] = df["first_seen_at"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    df["published_at"] = df["published_at"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    return df[SHARED_SCHEMA].reset_index(drop=True)


def filter_pilot_window(df: pd.DataFrame, pilot_start: str | None) -> pd.DataFrame:
    """Drop rows first observed before T_start (the official 48h pilot start).

    Per the main README's pilot rules, warm-up/seed collection run before both
    branches' collectors are confirmed healthy should not silently count as
    official pilot data. Rows excluded here are NOT deleted anywhere else -
    they remain in the raw archive and the audit table for QC.
    """
    if not pilot_start:
        return df
    cutoff = pd.Timestamp(pilot_start)
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    first_seen = pd.to_datetime(df["first_seen_at"], utc=True)
    return df[first_seen >= cutoff].reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean collected international articles.")
    parser.add_argument("--input", default=str(RAW_INPUT_PATH))
    parser.add_argument("--audit-output", default=str(AUDIT_OUTPUT_PATH))
    parser.add_argument("--output", default=str(CLEAN_OUTPUT_PATH))
    parser.add_argument("--sample-output", default=str(SAMPLE_OUTPUT_PATH))
    parser.add_argument("--sample-size", type=int, default=50)
    parser.add_argument(
        "--pilot-start",
        default=None,
        help=(
            "ISO8601 UTC timestamp for T_start of the official 48h pilot. When set, "
            "the final clean table/sample exclude rows with first_seen_at earlier "
            "than this (warm-up/seed data) - they stay in the raw archive and the "
            "audit table, just excluded from the official pilot deliverable."
        ),
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"No raw data found at {input_path}. Run collect_intl.py first.")

    raw_df = pd.read_parquet(input_path)
    audit_df = clean(raw_df)

    audit_path = Path(args.audit_output)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_df.to_parquet(audit_path, index=False)

    relevant_df = audit_df[audit_df["vietnam_relevance"]].reset_index(drop=True)
    final_df = filter_pilot_window(relevant_df, args.pilot_start)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    final_df.to_parquet(output_path, index=False)

    sample_path = Path(args.sample_output)
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    sample_size = max(1, min(args.sample_size, 100))
    final_df.head(sample_size).to_csv(sample_path, index=False)

    n_relevant = int(audit_df["vietnam_relevance"].sum())
    n_not_relevant = len(audit_df) - n_relevant
    print(f"Raw rows        : {len(raw_df):,}")
    print(f"Audited rows    : {len(audit_df):,} (relevant: {n_relevant:,}, not relevant: {n_not_relevant:,})")
    print(f"Audit output    : {audit_path}")
    if args.pilot_start:
        excluded = len(relevant_df) - len(final_df)
        print(f"Pilot T_start   : {args.pilot_start} ({excluded:,} relevant rows excluded as pre-pilot warm-up)")
    print(f"Final rows      : {len(final_df):,}")
    print(f"Clean output    : {output_path}")
    print(f"Sample output   : {sample_path} ({min(sample_size, len(final_df))} rows)")


if __name__ == "__main__":
    main()

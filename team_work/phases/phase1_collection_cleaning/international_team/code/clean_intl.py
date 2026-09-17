"""Basic cleaning for collected international articles.

Reads the raw table produced by ``collect_intl.py``, applies Phase 1's
"basic cleaning only" rules (standardize columns, normalize timestamps and
publisher domains, drop obviously broken rows), and writes:

- a full cleaned table to ``data/processed/international/international_clean.parquet``
- a small review sample (20-100 rows) to ``sample_output/sample_intl.csv``

Raw data is never modified or deleted; this script only reads it.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

RAW_INPUT_PATH = Path("data/raw/international/international_raw.parquet")
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

    # recompute vietnam_relevance from title/description, not just "the query matched somewhere"
    df["vietnam_relevance"] = df.apply(
        lambda r: is_vietnam_relevant(r["title"], r.get("description")), axis=1
    )
    df = df[df["vietnam_relevance"]]

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean collected international articles.")
    parser.add_argument("--input", default=str(RAW_INPUT_PATH))
    parser.add_argument("--output", default=str(CLEAN_OUTPUT_PATH))
    parser.add_argument("--sample-output", default=str(SAMPLE_OUTPUT_PATH))
    parser.add_argument("--sample-size", type=int, default=50)
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"No raw data found at {input_path}. Run collect_intl.py first.")

    raw_df = pd.read_parquet(input_path)
    clean_df = clean(raw_df)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    clean_df.to_parquet(output_path, index=False)

    sample_path = Path(args.sample_output)
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    sample_size = max(1, min(args.sample_size, 100))
    clean_df.head(sample_size).to_csv(sample_path, index=False)

    print(f"Raw rows      : {len(raw_df):,}")
    print(f"Cleaned rows  : {len(clean_df):,}")
    print(f"Clean output  : {output_path}")
    print(f"Sample output : {sample_path} ({min(sample_size, len(clean_df))} rows)")


if __name__ == "__main__":
    main()

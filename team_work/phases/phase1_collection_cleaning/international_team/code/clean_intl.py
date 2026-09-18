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
import hashlib
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

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

# source_seen_at (e.g. GDELT's seendate) is QC-only metadata, deliberately excluded
# from SHARED_SCHEMA (the official cross-team table) - see collect_intl.py.
AUDIT_SCHEMA = SHARED_SCHEMA + ["source_seen_at"]

# Tracking params that don't change article identity; dropped during canonicalization.
_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "fbclid", "gclid", "oc"}

# Positive-signal terms for is_vietnam_relevant(). Beyond the literal "Vietnam" /
# "Việt Nam" match, this adds major Vietnamese cities that international coverage
# sometimes names without ever saying "Vietnam" (e.g. "Hanoi launches new metro
# line"). Deliberately small and inspectable, not a gazetteer - see known issues in
# the branch README for why this needs re-checking with real audit-table samples.
_VIETNAM_KEYWORDS = [
    "vietnam", "vietnamese", "việt nam",
    "hanoi", "ha noi", "hà nội",
    "ho chi minh city", "ho chi minh", "hcmc", "saigon", "sài gòn", "sai gon",
    "da nang", "đà nẵng",
]


def normalize_domain(url_or_domain: str) -> str:
    hostname = url_or_domain
    if "://" in url_or_domain:
        hostname = urlparse(url_or_domain).hostname or ""
    hostname = hostname.lower().strip()
    return hostname[4:] if hostname.startswith("www.") else hostname


def canonicalize_url(url: str) -> str:
    """Strip tracking params/fragment and normalize scheme+host+path so that URL
    variants of the same article (e.g. with/without ?utm_source=rss_feed) collapse
    to one canonical form. Adapted from the Vietnamese team's clean_vn.py for
    cross-branch consistency."""
    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        clean_query = {k: v for k, v in query.items() if k not in _TRACKING_PARAMS}
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        elif netloc.startswith("m."):
            netloc = netloc[2:]
        path = parsed.path.rstrip("/")
        return urlunparse((parsed.scheme.lower() or "https", netloc, path, parsed.params, urlencode(clean_query, doseq=True), ""))
    except Exception:
        return url


def article_id_from_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def is_vietnam_relevant(title: str, description: str | None) -> bool:
    """Rule-based Vietnam relevance: literal "Vietnam"/"Việt Nam" plus a small set
    of major Vietnamese place names that international coverage can use without
    ever saying "Vietnam" itself.

    GDELT's DOC search matches full article text, which also picks up
    sidebar/related-story boilerplate — a bare keyword hit from the collector
    is not enough to call an article Vietnam-relevant, which is why this is
    recomputed here from title/description only rather than trusted from collection.
    """
    text = f"{title} {description or ''}".lower()
    return any(keyword in text for keyword in _VIETNAM_KEYWORDS)


def clean(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Basic cleaning + URL canonicalization + recomputed vietnam_relevance.

    Returns the audit/QC table (AUDIT_SCHEMA columns): EVERY row that survives
    basic cleaning, with both vietnam_relevance=True and False rows present.
    Callers that want only the relevant rows must filter this themselves - this
    function used to drop False rows internally, which meant the relevance
    heuristic's mistakes were invisible to reviewers.
    """
    if raw_df.empty:
        return pd.DataFrame(columns=AUDIT_SCHEMA)

    df = raw_df.copy()
    if "source_seen_at" not in df.columns:
        df["source_seen_at"] = None

    # remove obviously broken records
    df = df.dropna(subset=["title", "url"])
    df = df[(df["title"].str.strip() != "") & (df["url"].str.strip() != "")]

    # normalize publisher/domain names
    df["publisher_domain"] = df["publisher_domain"].fillna("").map(normalize_domain)
    df = df[df["publisher_domain"] != ""]

    # canonicalize URLs (strip tracking params/fragment) and rederive article_id from
    # the canonical form, so tracking-param variants of the same article collapse to
    # one row instead of silently becoming two different article_ids
    df["canonical_url"] = df["url"].map(canonicalize_url)
    df["article_id"] = df["canonical_url"].map(article_id_from_url)

    # normalize timestamps to UTC ISO 8601
    for col in ("first_seen_at", "published_at", "source_seen_at"):
        df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")

    df = df.dropna(subset=["first_seen_at"])

    # dedupe by canonical URL, keeping the earliest observation
    df = df.sort_values("first_seen_at").drop_duplicates(subset=["canonical_url"], keep="first")

    # recompute vietnam_relevance from title/description, not just "the query matched somewhere";
    # both True and False rows are kept here - see module docstring
    df["vietnam_relevance"] = df.apply(
        lambda r: is_vietnam_relevant(r["title"], r.get("description")), axis=1
    )

    for col in AUDIT_SCHEMA:
        if col not in df.columns:
            df[col] = None

    # sort most-recent first for review. published_at is null for gdelt_doc rows
    # (see collect_intl.py), so falling back to published_at alone (as an earlier
    # version of this script did) leaves those rows in arbitrary order. Fall back
    # to source_seen_at (GDELT's crawl time - still a decent recency proxy), then
    # first_seen_at (our own poll time - identical within one run, but better than
    # nothing) so every row has *some* meaningful sort key.
    review_sort_time = df["published_at"].fillna(df["source_seen_at"]).fillna(df["first_seen_at"])
    df = df.assign(_review_sort_time=review_sort_time).sort_values("_review_sort_time", ascending=False)

    for col in ("first_seen_at", "published_at", "source_seen_at"):
        df[col] = df[col].dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    return df[AUDIT_SCHEMA].reset_index(drop=True)


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
    # source_seen_at is QC-only metadata (see AUDIT_SCHEMA) - excluded from the
    # official cross-team table.
    final_df = final_df[SHARED_SCHEMA]

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

"""Collect Vietnam-related articles from international publishers.

Two collection methods, both writing rows in the shared NewsBreakout schema:

1. GDELT DOC 2.0 API (``source_system = gdelt_doc``) — searches GDELT's full-text
   index restricted to a fixed set of international publisher domains, requiring
   the keyword "Vietnam". This is a live/prospective search, not the unfiltered
   Global Article List feed.
2. Direct publisher RSS (``source_system = rss``) — pulls each publisher's own
   feed and keeps only entries whose title/summary mention Vietnam.

Raw (unfiltered-by-cleaning) rows are appended to
``data/raw/international/international_raw.parquet``, deduplicated by URL while
tracking ``first_seen_at`` / ``last_seen_at`` across runs. Run ``clean_intl.py``
afterwards to produce the cleaned table and review sample.
"""

from __future__ import annotations

import argparse
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import feedparser
import pandas as pd
import requests

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
RAW_OUTPUT_PATH = Path("data/raw/international/international_raw.parquet")

# publisher_domain -> static metadata used regardless of which collection method found the article
PUBLISHERS = {
    "reuters.com": {"publisher_id": "reuters", "publisher_group_id": "thomson_reuters", "publisher_country": "GB"},
    "bbc.com": {"publisher_id": "bbc", "publisher_group_id": "bbc", "publisher_country": "GB"},
    "bbc.co.uk": {"publisher_id": "bbc", "publisher_group_id": "bbc", "publisher_country": "GB"},
    "apnews.com": {"publisher_id": "ap", "publisher_group_id": "ap", "publisher_country": "US"},
    "scmp.com": {"publisher_id": "scmp", "publisher_group_id": "scmp", "publisher_country": "HK"},
    "straitstimes.com": {"publisher_id": "straits_times", "publisher_group_id": "sph_media", "publisher_country": "SG"},
    "channelnewsasia.com": {"publisher_id": "cna", "publisher_group_id": "mediacorp", "publisher_country": "SG"},
    "asia.nikkei.com": {"publisher_id": "nikkei_asia", "publisher_group_id": "nikkei", "publisher_country": "JP"},
}

# publisher_domain -> RSS feed URL, for publishers with a usable open feed
RSS_FEEDS = {
    "bbc.com": "https://feeds.bbci.co.uk/news/world/asia/rss.xml",
    "channelnewsasia.com": "https://www.channelnewsasia.com/rssfeeds/8395986",
}

COLUMNS = [
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


def domain_from_url(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lower()
    return hostname[4:] if hostname.startswith("www.") else hostname


def article_id_from_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def base_row(url: str, title: str, source_system: str) -> dict:
    domain = domain_from_url(url)
    meta = PUBLISHERS.get(domain, {})
    return {
        "article_id": article_id_from_url(url),
        "title": title.strip(),
        "url": url,
        "canonical_url": url,
        "publisher_domain": domain,
        "publisher_id": meta.get("publisher_id", domain.split(".")[0] if domain else None),
        "publisher_group_id": meta.get("publisher_group_id"),
        "source_system": source_system,
        "published_at": None,
        "language": None,
        "publisher_country": meta.get("publisher_country"),
        "description": None,
        "category": None,
        "vietnam_relevance": True,
        "duplicate_family_id": None,
        "branch": "international",
        "collection_mode": "prospective",
        "raw_payload_ref": None,
    }


def fetch_gdelt_doc(max_retries: int = 3) -> pd.DataFrame:
    """Search GDELT DOC 2.0 for Vietnam coverage restricted to PUBLISHERS' domains.

    GDELT asks for at most one request every 5 seconds; a 429 here means the
    caller's IP is currently throttled (common on shared/sandboxed networks) —
    back off and give up gracefully rather than failing the whole collection run.
    """
    domain_clause = " OR ".join(f"domain:{d}" for d in PUBLISHERS)
    params = {
        "query": f"({domain_clause}) Vietnam",
        "mode": "artlist",
        "maxrecords": 250,
        "format": "json",
        "sort": "datedesc",
    }

    for attempt in range(max_retries):
        response = requests.get(GDELT_DOC_URL, params=params, timeout=30)
        if response.status_code == 429:
            wait = 5 * (2**attempt)
            print(f"[gdelt_doc] rate-limited (429), retrying in {wait}s...")
            time.sleep(wait)
            continue
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:
            print("[gdelt_doc] non-JSON response, skipping this source for now")
            return pd.DataFrame(columns=COLUMNS)
        break
    else:
        print("[gdelt_doc] still rate-limited after retries, skipping this source for now")
        return pd.DataFrame(columns=COLUMNS)

    observed_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for article in payload.get("articles", []):
        url = str(article.get("url", "")).strip()
        title = str(article.get("title", "")).strip()
        if not url or not title:
            continue

        row = base_row(url, title, source_system="gdelt_doc")
        row["first_seen_at"] = observed_at
        row["timestamp_confidence"] = "gdelt_seen_time"  # seendate is when GDELT observed it, not confirmed publish time
        seendate = article.get("seendate")
        if seendate:
            try:
                row["published_at"] = datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").replace(
                    tzinfo=timezone.utc
                ).isoformat()
            except ValueError:
                pass
        language = article.get("language")
        if language:
            row["language"] = language.strip().lower()
        if not row["publisher_country"]:
            row["publisher_country"] = article.get("sourcecountry")
        rows.append(row)

    return pd.DataFrame(rows, columns=COLUMNS)


def fetch_publisher_rss() -> pd.DataFrame:
    """Pull each publisher's own RSS feed, keeping only Vietnam-relevant entries."""
    observed_at = datetime.now(timezone.utc).isoformat()
    rows = []

    for domain, feed_url in RSS_FEEDS.items():
        feed = feedparser.parse(feed_url)
        if getattr(feed, "bozo", False) and not feed.entries:
            print(f"[rss] could not parse feed for {domain}: {feed.bozo_exception}")
            continue

        for entry in feed.entries:
            url = str(entry.get("link", "")).strip()
            title = str(entry.get("title", "")).strip()
            summary = str(entry.get("summary", ""))
            if not url or not title:
                continue
            if "vietnam" not in (title + " " + summary).lower():
                continue

            row = base_row(url, title, source_system="rss")
            row["first_seen_at"] = observed_at
            row["description"] = summary.strip() or None

            published_struct = entry.get("published_parsed")
            if published_struct:
                row["published_at"] = datetime(*published_struct[:6], tzinfo=timezone.utc).isoformat()
                row["timestamp_confidence"] = "publisher_reported"
            else:
                row["timestamp_confidence"] = "first_seen_only"
            rows.append(row)

    return pd.DataFrame(rows, columns=COLUMNS)


def merge_with_history(new_df: pd.DataFrame, output_path: Path) -> pd.DataFrame:
    if output_path.exists():
        old_df = pd.read_parquet(output_path)
    else:
        old_df = pd.DataFrame(columns=COLUMNS)

    combined = pd.concat([old_df, new_df], ignore_index=True)
    if combined.empty:
        return pd.DataFrame(columns=COLUMNS + ["last_seen_at"])

    combined["first_seen_at"] = pd.to_datetime(combined["first_seen_at"], utc=True)
    combined["last_seen_at"] = combined["first_seen_at"]

    other_cols = [c for c in COLUMNS if c not in ("article_id", "url", "first_seen_at")]
    agg = {col: "last" for col in other_cols}
    agg["article_id"] = "first"
    agg["first_seen_at"] = "min"
    agg["last_seen_at"] = "max"

    combined = combined.sort_values("first_seen_at").groupby("url", as_index=False).agg(agg)
    return combined[COLUMNS + ["last_seen_at"]].sort_values("first_seen_at").reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Vietnam-related international articles.")
    parser.add_argument("--output", default=str(RAW_OUTPUT_PATH))
    parser.add_argument("--skip-gdelt", action="store_true", help="skip the GDELT DOC API call")
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    frames = []
    if not args.skip_gdelt:
        frames.append(fetch_gdelt_doc())
    frames.append(fetch_publisher_rss())

    new_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS)
    new_df = new_df.drop_duplicates(subset=["url"]).reset_index(drop=True)

    merged_df = merge_with_history(new_df, output_path)
    merged_df.to_parquet(output_path, index=False)

    print(f"Fetched this snapshot : {len(new_df):,} unique URLs")
    print(f"Stored total          : {len(merged_df):,} unique URLs")
    print(f"Output                : {output_path}")

    if not new_df.empty:
        print("\nSample:")
        print(new_df[["title", "publisher_domain", "source_system"]].head(5).to_string(index=False))


if __name__ == "__main__":
    main()

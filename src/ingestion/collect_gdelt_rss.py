from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import feedparser
import pandas as pd
import yaml


COLUMNS = [
    "article_id",
    "title",
    "url",
    "publisher_domain",
    "source",
    "first_seen_at",
    "last_seen_at",
]


def load_config(path: str | Path = "config/config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def domain_from_url(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lower()
    return hostname[4:] if hostname.startswith("www.") else hostname


def article_id_from_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def fetch_gdelt_rss(feed_url: str) -> pd.DataFrame:
    observed_at = datetime.now(timezone.utc).isoformat()
    feed = feedparser.parse(feed_url)

    if getattr(feed, "bozo", False) and not feed.entries:
        raise RuntimeError(f"Could not parse GDELT RSS feed: {feed.bozo_exception}")

    rows = []
    for entry in feed.entries:
        url = str(entry.get("link", "")).strip()
        title = str(entry.get("title", "")).strip()

        if not url:
            continue

        rows.append(
            {
                "article_id": article_id_from_url(url),
                "title": title,
                "url": url,
                "publisher_domain": domain_from_url(url),
                "source": "gdelt_rss",
                "first_seen_at": observed_at,
                "last_seen_at": observed_at,
            }
        )

    df = pd.DataFrame(rows, columns=COLUMNS)
    if not df.empty:
        df = df.drop_duplicates(subset=["url"]).reset_index(drop=True)
    return df


def merge_with_history(new_df: pd.DataFrame, output_path: str | Path) -> pd.DataFrame:
    output_path = Path(output_path)

    if output_path.exists():
        old_df = pd.read_parquet(output_path)
    else:
        old_df = pd.DataFrame(columns=COLUMNS)

    combined = pd.concat([old_df, new_df], ignore_index=True)

    if combined.empty:
        return pd.DataFrame(columns=COLUMNS)

    combined["first_seen_at"] = pd.to_datetime(combined["first_seen_at"], utc=True)
    combined["last_seen_at"] = pd.to_datetime(combined["last_seen_at"], utc=True)

    combined = (
        combined.sort_values("first_seen_at")
        .groupby("url", as_index=False)
        .agg(
            article_id=("article_id", "first"),
            title=("title", "last"),
            publisher_domain=("publisher_domain", "last"),
            source=("source", "last"),
            first_seen_at=("first_seen_at", "min"),
            last_seen_at=("last_seen_at", "max"),
        )
    )

    return combined[COLUMNS].sort_values("first_seen_at").reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect one GDELT RSS snapshot.")
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    feed_url = config["ingestion"]["gdelt_rss_url"]
    output_path = Path(config["ingestion"]["output_path"])
    output_path.parent.mkdir(parents=True, exist_ok=True)

    new_df = fetch_gdelt_rss(feed_url)
    merged_df = merge_with_history(new_df, output_path)
    merged_df.to_parquet(output_path, index=False)

    print(f"Fetched this snapshot : {len(new_df):,} unique URLs")
    print(f"Stored total          : {len(merged_df):,} unique URLs")
    print(f"Output                : {output_path}")

    if not new_df.empty:
        print("\nSample:")
        print(
            new_df[
                ["title", "publisher_domain", "first_seen_at"]
            ].head(5).to_string(index=False)
        )


if __name__ == "__main__":
    main()

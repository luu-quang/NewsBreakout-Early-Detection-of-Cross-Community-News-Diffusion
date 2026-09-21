"""Collect Vietnamese publisher RSS without applying relevance filtering.

Every fetched entry is first appended to an exact JSONL payload archive. A
separate Parquet candidate table keeps operational metadata and a stable
``raw_payload_ref`` of the form ``path#raw_record_id=<id>``. Repeated runs retain
the earliest collector observation for a URL and update ``last_seen_at``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import pandas as pd

RSS_FEEDS = {
    "vnexpress": "https://vnexpress.net/rss/tin-moi-nhat.rss",
    "tuoitre": "https://tuoitre.vn/rss/tin-moi-nhat.rss",
    "thanhnien": "https://thanhnien.vn/rss/home.rss",
    "dantri": "https://dantri.com.vn/rss/home.rss",
    "vietnamnet": "https://vietnamnet.vn/rss/thoi-su.rss",
}

USER_AGENT = "NewsBreakout/1.0 (+https://github.com/luu-quang/NewsBreakout)"
RAW_COLUMNS = [
    "url",
    "publisher_id_hint",
    "feed_url",
    "source_system",
    "first_seen_at",
    "last_seen_at",
    "collection_mode",
    "raw_payload_ref",
    "entry_json",
]


def _json_safe(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _archive_label(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _raw_record(publisher_id: str, feed_url: str, observed_at: str, entry: dict) -> dict:
    safe_entry = _json_safe(entry)
    identity = json.dumps(
        {
            "publisher_id": publisher_id,
            "feed_url": feed_url,
            "observed_at": observed_at,
            "payload": safe_entry,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "raw_record_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        "publisher_id": publisher_id,
        "feed_url": feed_url,
        "source_system": "rss",
        "observed_at": observed_at,
        "payload": safe_entry,
    }


def append_raw_records(records: list[dict], archive_path: Path) -> None:
    """Append exact source records before any cleaning or relevance decision."""
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with archive_path.open("a", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def merge_with_history(new_df: pd.DataFrame, output_path: Path) -> pd.DataFrame:
    if output_path.exists():
        old_df = pd.read_parquet(output_path)
    else:
        old_df = pd.DataFrame(columns=RAW_COLUMNS)

    combined = pd.concat([old_df, new_df], ignore_index=True)
    if combined.empty:
        return pd.DataFrame(columns=RAW_COLUMNS)

    combined["first_seen_at"] = pd.to_datetime(combined["first_seen_at"], utc=True)
    combined["last_seen_at"] = pd.to_datetime(combined["last_seen_at"], utc=True)
    combined = combined.sort_values("first_seen_at")
    # Broken entries still need distinct candidate rows so the cleaner can record
    # rejection reasons. Exact payload identity is their stable fallback key.
    combined["_candidate_key"] = combined["url"].where(
        combined["url"].fillna("").str.strip().ne(""), combined["raw_payload_ref"]
    )
    first_rows = combined.drop_duplicates(subset=["_candidate_key"], keep="first").set_index("_candidate_key")
    first_rows["last_seen_at"] = combined.groupby("_candidate_key")["last_seen_at"].max()
    merged = first_rows.reset_index(drop=True)[RAW_COLUMNS]
    return merged.sort_values("first_seen_at").reset_index(drop=True)


def collect(collection_mode: str, archive_path: Path) -> pd.DataFrame:
    observed_at = datetime.now(timezone.utc).isoformat()
    raw_records: list[dict] = []

    for publisher_id, feed_url in RSS_FEEDS.items():
        print(f"[rss] fetching {publisher_id}: {feed_url}")
        feed = feedparser.parse(feed_url, agent=USER_AGENT)
        if getattr(feed, "bozo", False) and not feed.entries:
            print(f"[rss] parse failed for {publisher_id}: {feed.bozo_exception}")
            continue
        for entry in feed.entries:
            raw_records.append(_raw_record(publisher_id, feed_url, observed_at, dict(entry)))

    # This happens before URL validation or relevance filtering by design.
    append_raw_records(raw_records, archive_path)
    archive_label = _archive_label(archive_path)

    rows = []
    for record in raw_records:
        entry = record["payload"]
        url = str(entry.get("link", "")).strip()
        rows.append(
            {
                "url": url,
                "publisher_id_hint": record["publisher_id"],
                "feed_url": record["feed_url"],
                "source_system": "rss",
                "first_seen_at": observed_at,
                "last_seen_at": observed_at,
                "collection_mode": collection_mode,
                "raw_payload_ref": f"{archive_label}#raw_record_id={record['raw_record_id']}",
                "entry_json": json.dumps(entry, ensure_ascii=False, separators=(",", ":")),
            }
        )
    return pd.DataFrame(rows, columns=RAW_COLUMNS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Vietnamese publisher RSS entries.")
    parser.add_argument(
        "--collection-mode",
        choices=("prospective", "historical_backfill"),
        default="prospective",
    )
    parser.add_argument("--output", default=None, help="Normalized raw candidate Parquet path.")
    parser.add_argument("--payload-archive", default=None, help="Exact append-only JSONL archive path.")
    args = parser.parse_args()

    suffix = "historical" if args.collection_mode == "historical_backfill" else "raw"
    output_path = Path(args.output or f"data/raw/vietnamese/vietnamese_{suffix}.parquet")
    archive_path = Path(
        args.payload_archive or f"data/raw/vietnamese/vietnamese_{suffix}_payloads.jsonl"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    new_df = collect(args.collection_mode, archive_path)
    new_df["_candidate_key"] = new_df["url"].where(
        new_df["url"].fillna("").str.strip().ne(""), new_df["raw_payload_ref"]
    )
    new_df = new_df.drop_duplicates(subset=["_candidate_key"], keep="first").drop(columns="_candidate_key").reset_index(drop=True)
    merged_df = merge_with_history(new_df, output_path)
    merged_df.to_parquet(output_path, index=False)

    print(f"Fetched this snapshot : {len(new_df):,} unique URLs")
    print(f"Stored total          : {len(merged_df):,} unique URLs")
    print(f"Raw payload archive   : {archive_path}")
    print(f"Candidate table       : {output_path}")


if __name__ == "__main__":
    main()

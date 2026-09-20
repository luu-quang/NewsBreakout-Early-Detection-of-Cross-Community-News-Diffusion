"""Collect direct international RSS plus supplementary GDELT candidates.

Exact source records are appended to JSONL before basic validation. The
normalized raw candidate table preserves collector observation history and
points back to one exact archive record through ``raw_payload_ref``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import dateutil.parser
import feedparser
import pandas as pd
from dateutil.tz import gettz

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_TIMESPAN = "1w"
USER_AGENT = "NewsBreakout/1.0 (+https://github.com/luu-quang/NewsBreakout)"

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

RSS_FEEDS = {
    "bbc.com": "https://feeds.bbci.co.uk/news/world/asia/rss.xml",
    "channelnewsasia.com": "https://www.channelnewsasia.com/rssfeeds/8395986",
    "scmp.com": "https://www.scmp.com/rss/91/feed",
    "asia.nikkei.com": "https://asia.nikkei.com/rss/feed/nar",
    "straitstimes.com": "https://www.straitstimes.com/news/asia/rss.xml",
}

PUBLISHER_TIMEZONES = {
    "bbc.com": "Europe/London",
    "channelnewsasia.com": "Asia/Singapore",
    "scmp.com": "Asia/Hong_Kong",
    "asia.nikkei.com": "Asia/Tokyo",
    "straitstimes.com": "Asia/Singapore",
}

SHARED_SCHEMA = [
    "article_id", "title", "url", "canonical_url", "publisher_domain",
    "publisher_id", "publisher_group_id", "source_system", "first_seen_at",
    "published_at", "timestamp_confidence", "language", "publisher_country",
    "description", "category", "vietnam_relevance", "duplicate_family_id",
    "branch", "collection_mode", "raw_payload_ref",
]
RAW_COLUMNS = SHARED_SCHEMA + ["source_seen_at", "last_seen_at"]


def domain_from_url(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lower()
    return hostname[4:] if hostname.startswith("www.") else hostname


def article_id_from_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _json_safe(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _archive_label(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def make_raw_record(source_system: str, source_locator: str, observed_at: str, payload: object) -> dict:
    safe_payload = _json_safe(payload)
    identity = json.dumps(
        {"source_system": source_system, "source_locator": source_locator, "observed_at": observed_at, "payload": safe_payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "raw_record_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        "source_system": source_system,
        "source_locator": source_locator,
        "observed_at": observed_at,
        "payload": safe_payload,
    }


def append_raw_records(records: list[dict], archive_path: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with archive_path.open("a", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def raw_ref(archive_path: Path, record_id: str) -> str:
    return f"{_archive_label(archive_path)}#raw_record_id={record_id}"


def parse_publisher_time(value: object, domain: str) -> tuple[str | None, str]:
    if value is None or not str(value).strip():
        return None, "unavailable"
    try:
        parsed = dateutil.parser.parse(str(value))
        if parsed.tzinfo is None:
            timezone_name = PUBLISHER_TIMEZONES.get(domain)
            if not timezone_name:
                return None, "unavailable"
            source_tz = gettz(timezone_name)
            if source_tz is None:
                return None, "unavailable"
            parsed = parsed.replace(tzinfo=source_tz)
            confidence = "publisher_reported_timezone_inferred"
        else:
            confidence = "publisher_reported"
        return parsed.astimezone(timezone.utc).isoformat(), confidence
    except (TypeError, ValueError, OverflowError):
        return None, "unavailable"


def base_row(url: str, title: str, source_system: str, collection_mode: str, observed_at: str, payload_ref: str) -> dict:
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
        "first_seen_at": observed_at,
        "published_at": None,
        "timestamp_confidence": "unavailable",
        "language": None,
        "publisher_country": meta.get("publisher_country"),
        "description": None,
        "category": None,
        "vietnam_relevance": None,
        "duplicate_family_id": None,
        "branch": "international",
        "collection_mode": collection_mode,
        "raw_payload_ref": payload_ref,
        "source_seen_at": None,
        "last_seen_at": observed_at,
    }


def fetch_gdelt_doc(archive_path: Path, timespan: str = GDELT_TIMESPAN, collection_mode: str = "prospective", max_retries: int = 3) -> pd.DataFrame:
    domain_clause = " OR ".join(f"domain:{domain}" for domain in PUBLISHERS)
    params = {"query": f"({domain_clause}) Vietnam", "mode": "artlist", "maxrecords": 250, "format": "json", "sort": "datedesc", "timespan": timespan}

    request_url = f"{GDELT_DOC_URL}?{urlencode(params)}"
    for attempt in range(max_retries):
        try:
            request = Request(request_url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code != 429:
                raise
            wait = 5 * (2**attempt)
            print(f"[gdelt_doc] rate-limited; retrying in {wait}s")
            time.sleep(wait)
            continue
        except (UnicodeDecodeError, json.JSONDecodeError):
            print("[gdelt_doc] non-JSON response; source skipped")
            return pd.DataFrame(columns=RAW_COLUMNS)
        break
    else:
        print("[gdelt_doc] retry limit reached; source skipped")
        return pd.DataFrame(columns=RAW_COLUMNS)

    observed_at = datetime.now(timezone.utc).isoformat()
    records = [make_raw_record("gdelt_doc", request_url, observed_at, article) for article in payload.get("articles", [])]
    append_raw_records(records, archive_path)

    rows = []
    for record in records:
        article = record["payload"]
        url = str(article.get("url", "")).strip()
        title = str(article.get("title", "")).strip()
        row = base_row(url, title, "gdelt_doc", collection_mode, observed_at, raw_ref(archive_path, record["raw_record_id"]))
        # GDELT seendate is source observation metadata, never publication time.
        seendate = article.get("seendate")
        if seendate:
            try:
                row["source_seen_at"] = datetime.strptime(str(seendate), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                pass
        language = article.get("language")
        row["language"] = str(language).strip().lower() if language else None
        if not row["publisher_country"]:
            row["publisher_country"] = article.get("sourcecountry")
        rows.append(row)
    return pd.DataFrame(rows, columns=RAW_COLUMNS)


def fetch_publisher_rss(archive_path: Path) -> pd.DataFrame:
    """Fetch every current feed entry; relevance is never filtered here."""
    observed_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for domain, feed_url in RSS_FEEDS.items():
        feed = feedparser.parse(feed_url, agent=USER_AGENT)
        if getattr(feed, "bozo", False) and not feed.entries:
            print(f"[rss] parse failed for {domain}: {feed.bozo_exception}")
            continue

        records = [make_raw_record("rss", feed_url, observed_at, dict(entry)) for entry in feed.entries]
        append_raw_records(records, archive_path)
        for record in records:
            entry = record["payload"]
            url = str(entry.get("link", "")).strip()
            title = str(entry.get("title", "")).strip()
            row = base_row(url, title, "rss", "prospective", observed_at, raw_ref(archive_path, record["raw_record_id"]))
            row["description"] = str(entry.get("summary") or entry.get("description") or "").strip() or None
            row["category"] = str(entry.get("category") or "").strip() or None
            row["published_at"], row["timestamp_confidence"] = parse_publisher_time(
                entry.get("published") or entry.get("pubDate") or entry.get("updated"), domain
            )
            rows.append(row)
    return pd.DataFrame(rows, columns=RAW_COLUMNS)


def merge_with_history(new_df: pd.DataFrame, output_path: Path) -> pd.DataFrame:
    old_df = pd.read_parquet(output_path) if output_path.exists() else pd.DataFrame(columns=RAW_COLUMNS)
    combined = pd.concat([old_df, new_df], ignore_index=True)
    if combined.empty:
        return pd.DataFrame(columns=RAW_COLUMNS)
    combined["first_seen_at"] = pd.to_datetime(combined["first_seen_at"], utc=True)
    combined["last_seen_at"] = pd.to_datetime(combined["last_seen_at"], utc=True)
    combined = combined.sort_values("first_seen_at")
    combined["_candidate_key"] = combined["url"].where(
        combined["url"].fillna("").str.strip().ne(""), combined["raw_payload_ref"]
    )
    first_rows = combined.drop_duplicates(subset=["_candidate_key"], keep="first").set_index("_candidate_key")
    first_rows["last_seen_at"] = combined.groupby("_candidate_key")["last_seen_at"].max()
    return first_rows.reset_index(drop=True)[RAW_COLUMNS].sort_values("first_seen_at").reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect international Phase 1 candidates.")
    parser.add_argument("--output", default=None)
    parser.add_argument("--payload-archive", default=None)
    parser.add_argument("--skip-gdelt", action="store_true")
    parser.add_argument("--historical-days", type=int, default=None)
    args = parser.parse_args()

    historical = args.historical_days is not None
    suffix = "historical" if historical else "raw"
    output_path = Path(args.output or f"data/raw/international/international_{suffix}.parquet")
    archive_path = Path(args.payload_archive or f"data/raw/international/international_{suffix}_payloads.jsonl")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    frames = []
    if historical:
        frames.append(fetch_gdelt_doc(archive_path, timespan=f"{args.historical_days}d", collection_mode="historical_backfill"))
    else:
        if not args.skip_gdelt:
            frames.append(fetch_gdelt_doc(archive_path))
        frames.append(fetch_publisher_rss(archive_path))

    new_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=RAW_COLUMNS)
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

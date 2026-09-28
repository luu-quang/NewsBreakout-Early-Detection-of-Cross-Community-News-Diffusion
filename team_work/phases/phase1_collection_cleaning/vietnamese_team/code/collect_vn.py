"""Collect Vietnamese publisher RSS without applying relevance filtering.

Every fetched entry is first appended to an exact JSONL payload archive. A
separate Parquet candidate table keeps operational metadata and a stable
``raw_payload_ref`` of the form ``path#raw_record_id=<id>``. Repeated runs retain
the earliest collector observation for a URL and update ``last_seen_at``.

Default invocation (no ``--continuous``) is byte-for-byte the same v1 behavior,
except two universal safety fixes that change no output content: each feed
fetch now has a real timeout (``feedparser.parse(url)`` has none of its own -
one hung feed used to hang the whole run), and the candidate Parquet is now
written atomically (temp file + ``os.replace``, so a crash mid-write cannot
corrupt it). ``--continuous`` switches to the v2 layout for safe unattended
polling every few minutes - see ``src/collect_v2/`` and
``docs/HANDOFF_2026-09-26.md``; it does not write the candidate Parquet at all
(build it offline with ``src/collect_v2/build_candidate_table.py``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))
from src.collect_v2 import continuous_write, feed_diagnostics, feed_state, fetch, lock  # noqa: E402
from src.collect_v2 import paths as v2_paths  # noqa: E402

DEFAULT_FETCH_TIMEOUT = 15.0

RSS_FEEDS = {
    "vnexpress": "https://vnexpress.net/rss/tin-moi-nhat.rss",
    # Temporary exception to the "no category feeds" rule (2026-09-28): the
    # tin-moi-nhat.rss endpoint above gets stuck on a severely stale CDN
    # cache when polled from the VM's network path (confirmed 20h+ stale at
    # times, immune to cache-busting - not a bug in this collector, verified
    # from both the VM and elsewhere with identical code/headers - see
    # docs/HANDOFF_2026-09-28.md). thoi-su.rss is reliably fresh from the same
    # VM and is kept alongside (not replacing) tin-moi-nhat above so neither
    # the v1/v2 comparison feed set nor vnexpress's own primary feed_id
    # changes - remove this once tin-moi-nhat.rss's CDN cache is confirmed
    # healthy again for a sustained period.
    "vnexpress_thoisu": "https://vnexpress.net/rss/thoi-su.rss",
    "tuoitre": "https://tuoitre.vn/rss/tin-moi-nhat.rss",
    "thanhnien": "https://thanhnien.vn/rss/home.rss",
    "dantri": "https://dantri.com.vn/rss/home.rss",
    "vietnamnet": "https://vietnamnet.vn/rss/thoi-su.rss",
    "vietnamplus": "https://www.vietnamplus.vn/rss/trangchu.rss",
    "baotintuc": "https://baotintuc.vn/rss/trang-chu.rss",
    "tienphong": "https://tienphong.vn/rss/home.rss",
    "sggp": "https://sggp.org.vn/rss/home.rss",
    "nhandan": "https://nhandan.vn/rss/home.rss",
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


def _fetch_feed_entries(publisher_id: str, feed_url: str, fetch_timeout: float) -> list[dict]:
    """Fetch one feed in isolation: a timeout or any other fetch error here is
    logged and skipped, never raised, so one bad feed cannot abort the run."""
    print(f"[rss] fetching {publisher_id}: {feed_url}")
    try:
        feed = fetch.fetch_feed(feed_url, timeout=fetch_timeout, user_agent=USER_AGENT)
    except fetch.FeedFetchError as exc:
        print(f"[rss] fetch failed for {publisher_id}: {exc}")
        return []
    if getattr(feed, "bozo", False) and not feed.entries:
        print(f"[rss] parse failed for {publisher_id}: {feed.bozo_exception}")
        return []
    return [dict(entry) for entry in feed.entries]


def collect(collection_mode: str, archive_path: Path, fetch_timeout: float = DEFAULT_FETCH_TIMEOUT) -> pd.DataFrame:
    observed_at = datetime.now(timezone.utc).isoformat()
    raw_records: list[dict] = []

    for publisher_id, feed_url in RSS_FEEDS.items():
        for entry in _fetch_feed_entries(publisher_id, feed_url, fetch_timeout):
            raw_records.append(_raw_record(publisher_id, feed_url, observed_at, entry))

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


def _fetch_feed_with_diagnostics(publisher_id: str, feed_url: str, fetch_timeout: float) -> tuple[list[dict], dict]:
    """Like ``_fetch_feed_entries``, but also returns a machine-readable
    per-feed result (``feed_diagnostics.make_result``) - used only by
    ``collect_continuous()``; ``collect()`` (v1) keeps using the plain
    ``_fetch_feed_entries`` above unchanged."""
    print(f"[rss] fetching {publisher_id}: {feed_url}")
    try:
        result = fetch.fetch_bytes_with_meta(feed_url, timeout=fetch_timeout, user_agent=USER_AGENT)
    except fetch.FeedFetchError as exc:
        print(f"[rss] fetch failed for {publisher_id}: {exc}")
        return [], feed_diagnostics.make_result(
            publisher_id, feed_url, http_status=exc.http_status, content_encoding=None,
            n_entries=0, n_new=0, error=str(exc),
        )
    feed = feedparser.parse(result.data)
    if getattr(feed, "bozo", False) and not feed.entries:
        print(f"[rss] parse failed for {publisher_id}: {feed.bozo_exception}")
        return [], feed_diagnostics.make_result(
            publisher_id, feed_url, http_status=result.http_status, content_encoding=result.content_encoding,
            n_entries=0, n_new=0, error=str(feed.bozo_exception),
        )
    entries = [dict(entry) for entry in feed.entries]
    return entries, feed_diagnostics.make_result(
        publisher_id, feed_url, http_status=result.http_status, content_encoding=result.content_encoding,
        n_entries=len(entries), n_new=0, error=None,
    )


def collect_continuous(collector_host: str, fetch_timeout: float, run_id: str) -> tuple[int, int]:
    """Fetch every feed once and write it under the v2 continuous layout.

    Returns (new_payloads, entries_seen). Writes no candidate Parquet - build
    it offline from the JSONL archive with
    ``src/collect_v2/build_candidate_table.py``. Also prints one machine-
    readable per-feed diagnostics line (see ``feed_diagnostics.py``) that
    ``runner.py`` reads back to catch a feed silently going quiet.
    """
    observed_at = datetime.now(timezone.utc).isoformat()
    feeds_with_entries: dict[str, str | None] = {}
    per_feed_results: list[dict] = []
    total_entries = 0
    total_new = 0
    for publisher_id, feed_url in RSS_FEEDS.items():
        entries, result = _fetch_feed_with_diagnostics(publisher_id, feed_url, fetch_timeout)
        if entries:
            feeds_with_entries[feed_url] = publisher_id
        candidates = [
            continuous_write.RawCandidate(
                url=str(entry.get("link", "")).strip(),
                payload=entry,
                source_system="rss",
                source_locator=feed_url,
                publisher_id_hint=publisher_id,
            )
            for entry in entries
        ]
        _refs, new_count = continuous_write.write_continuous_batch(
            "domestic", collector_host, candidates, observed_at=observed_at, run_id=run_id
        )
        result["n_new"] = new_count
        per_feed_results.append(result)
        total_entries += len(candidates)
        total_new += new_count
    feed_state.record_first_seen_batch("domestic", collector_host, feeds_with_entries, observed_at)
    feed_diagnostics.print_per_feed_results(per_feed_results)
    return total_new, total_entries


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Vietnamese publisher RSS entries.")
    parser.add_argument(
        "--collection-mode",
        choices=("prospective", "historical_backfill"),
        default="prospective",
    )
    parser.add_argument("--output", default=None, help="Normalized raw candidate Parquet path.")
    parser.add_argument("--payload-archive", default=None, help="Exact append-only JSONL archive path.")
    parser.add_argument(
        "--continuous",
        action="store_true",
        help=(
            "Write to the v2 append-only JSONL layout (data/raw/v2/domestic/<host>/...) "
            "instead of the v1 candidate Parquet. Disjoint from the flags above."
        ),
    )
    parser.add_argument("--collector-host", default=None, help="Defaults to $COLLECTOR_HOST or the machine hostname.")
    parser.add_argument("--fetch-timeout", type=float, default=DEFAULT_FETCH_TIMEOUT, help="Per-feed HTTP timeout, seconds.")
    parser.add_argument("--run-lock", default=None, help="Continuous mode only: override the run-lock path.")
    args = parser.parse_args()

    if args.continuous:
        if args.collection_mode == "historical_backfill":
            raise SystemExit("--continuous does not support --collection-mode historical_backfill.")
        collector_host = args.collector_host or v2_paths.default_collector_host()
        lock_path = Path(args.run_lock) if args.run_lock else v2_paths.branch_host_dir("domestic", collector_host) / "run.lock"
        run_id = uuid.uuid4().hex
        with lock.run_lock(lock_path):
            new_count, seen_count = collect_continuous(collector_host, args.fetch_timeout, run_id)
        print(f"[continuous] run_id={run_id} collector_host={collector_host}")
        print(f"Entries seen this run : {seen_count:,}")
        print(f"New payloads archived : {new_count:,}")
        return

    suffix = "historical" if args.collection_mode == "historical_backfill" else "raw"
    output_path = Path(args.output or f"data/raw/vietnamese/vietnamese_{suffix}.parquet")
    archive_path = Path(
        args.payload_archive or f"data/raw/vietnamese/vietnamese_{suffix}_payloads.jsonl"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    new_df = collect(args.collection_mode, archive_path, fetch_timeout=args.fetch_timeout)
    new_df["_candidate_key"] = new_df["url"].where(
        new_df["url"].fillna("").str.strip().ne(""), new_df["raw_payload_ref"]
    )
    new_df = new_df.drop_duplicates(subset=["_candidate_key"], keep="first").drop(columns="_candidate_key").reset_index(drop=True)
    merged_df = merge_with_history(new_df, output_path)
    v2_paths.atomic_write_parquet(merged_df, output_path)

    print(f"Fetched this snapshot : {len(new_df):,} unique URLs")
    print(f"Stored total          : {len(merged_df):,} unique URLs")
    print(f"Raw payload archive   : {archive_path}")
    print(f"Candidate table       : {output_path}")


if __name__ == "__main__":
    main()

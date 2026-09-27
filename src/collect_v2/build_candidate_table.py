"""Offline candidate-table builder: v2 JSONL archive -> v1-compatible candidate Parquet.

Reads the append-only payloads/sightings JSONL archive for one (branch,
collector_host) and produces a Parquet with EXACTLY the same columns as the
corresponding v1 collector's own candidate table (``RAW_COLUMNS`` in
``collect_vn.py`` for ``domestic``, ``collect_intl.py`` for ``international``),
so ``clean_vn.py`` / ``clean_intl.py`` consume it completely unmodified - no
contract change, no code change in either cleaner.

Field-construction logic (``base_row``, ``parse_publisher_time``,
``domain_from_url``, the ``PUBLISHERS``/``PUBLISHER_TIMEZONES`` tables) is
reused directly from the live collectors by loading them as modules from their
own file paths, rather than duplicated here - so this builder can never drift
from what the live collector would have produced for the same entry.

Deterministic: a pure function of the JSONL archive's content (see
``tests/test_collect_v2_build_candidate_table.py``, including a round-trip
through the REAL ``clean_vn.clean()`` / ``clean_intl.clean()`` and
``build_master.validate_phase1_frame()`` to prove the contract holds).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import types
from pathlib import Path

import pandas as pd

from . import jsonl_store, paths

COLLECT_VN_PATH = (
    paths.REPOSITORY_ROOT
    / "team_work/phases/phase1_collection_cleaning/vietnamese_team/code/collect_vn.py"
)
COLLECT_INTL_PATH = (
    paths.REPOSITORY_ROOT
    / "team_work/phases/phase1_collection_cleaning/international_team/code/collect_intl.py"
)


def _load_module(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _day_files(directory: Path, prefix: str) -> list[Path]:
    files = list(directory.glob(f"{prefix}-*.jsonl")) + list(directory.glob(f"{prefix}-*.jsonl.gz"))
    return sorted(files, key=lambda p: p.name.replace(".gz", ""))


def _aggregate_timing(directory: Path) -> dict[str, dict[str, str]]:
    """{entry_key: {first_seen_at, last_seen_at}}, min/max observed_at over every
    sighting - regardless of content_hash, matching URL-level (not per-content)
    first/last-seen semantics, same as v1's own merge_with_history()."""
    timing: dict[str, dict[str, str]] = {}
    for file_path in _day_files(directory, "sightings"):
        for record in jsonl_store.iter_jsonl(file_path):
            key = record["entry_key"]
            t = record["observed_at"]
            slot = timing.setdefault(key, {"first_seen_at": t, "last_seen_at": t})
            if t < slot["first_seen_at"]:
                slot["first_seen_at"] = t
            if t > slot["last_seen_at"]:
                slot["last_seen_at"] = t
    return timing


def _earliest_payload_per_key(directory: Path) -> dict[str, dict]:
    """{entry_key: {"record": payload record, "ref": raw_payload_ref}} - one
    representative per URL, the earliest-observed version, matching v1's own
    keep="first" (sorted by observed_at) convention in merge_with_history()."""
    chosen: dict[str, dict] = {}
    for file_path in _day_files(directory, "payloads"):
        label = paths.archive_label(file_path)
        for record in jsonl_store.iter_jsonl(file_path):
            key = record["entry_key"]
            ref = f"{label}#raw_record_id={record['raw_record_id']}"
            existing = chosen.get(key)
            if existing is None or record["observed_at"] < existing["record"]["observed_at"]:
                chosen[key] = {"record": record, "ref": ref}
    return chosen


def build_domestic(branch_dir: Path, collect_vn: types.ModuleType) -> pd.DataFrame:
    timing = _aggregate_timing(branch_dir)
    chosen = _earliest_payload_per_key(branch_dir)
    rows = []
    for key, item in chosen.items():
        record = item["record"]
        entry = record["payload"]
        url = str(entry.get("link", "")).strip()
        t = timing.get(key, {"first_seen_at": record["observed_at"], "last_seen_at": record["observed_at"]})
        rows.append(
            {
                "url": url,
                "publisher_id_hint": record.get("publisher_id_hint"),
                "feed_url": record.get("source_locator"),
                "source_system": record.get("source_system", "rss"),
                "first_seen_at": t["first_seen_at"],
                "last_seen_at": t["last_seen_at"],
                "collection_mode": "prospective",
                "raw_payload_ref": item["ref"],
                "entry_json": json.dumps(entry, ensure_ascii=False, separators=(",", ":")),
            }
        )
    return pd.DataFrame(rows, columns=collect_vn.RAW_COLUMNS)


def build_international(branch_dir: Path, collect_intl: types.ModuleType) -> pd.DataFrame:
    timing = _aggregate_timing(branch_dir)
    chosen = _earliest_payload_per_key(branch_dir)
    rows = []
    for key, item in chosen.items():
        record = item["record"]
        entry = record["payload"]
        url = str(entry.get("link", "")).strip()
        title = str(entry.get("title", "")).strip()
        t = timing.get(key, {"first_seen_at": record["observed_at"], "last_seen_at": record["observed_at"]})
        source_system = record.get("source_system", "rss")

        row = collect_intl.base_row(
            url, title, source_system, "prospective", t["first_seen_at"], item["ref"]
        )
        row["last_seen_at"] = t["last_seen_at"]
        row["description"] = str(entry.get("summary") or entry.get("description") or "").strip() or None
        row["category"] = str(entry.get("category") or "").strip() or None
        row["published_at"], row["timestamp_confidence"] = collect_intl.parse_publisher_time(
            entry.get("published") or entry.get("pubDate") or entry.get("updated"),
            collect_intl.domain_from_url(url),
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=collect_intl.RAW_COLUMNS)


def ref_feed_locators(branch_dir: Path) -> dict[str, str | None]:
    """``{raw_payload_ref: feed_locator}`` for every candidate row that
    ``build_domestic``/``build_international`` would produce for this
    directory - the feed URL each ref was fetched from, for callers that need
    it after ``clean_vn.py``/``clean_intl.py`` have already dropped
    ``feed_url`` from their output (e.g. ``feed_state.is_pre_start()``)."""
    chosen = _earliest_payload_per_key(branch_dir)
    return {item["ref"]: item["record"].get("source_locator") for item in chosen.values()}


def build(branch: str, collector_host: str) -> pd.DataFrame:
    branch_dir = paths.branch_host_dir(branch, collector_host)
    if branch == "domestic":
        collect_vn = _load_module("collect_vn_v1", COLLECT_VN_PATH)
        return build_domestic(branch_dir, collect_vn)
    if branch == "international":
        collect_intl = _load_module("collect_intl_v1", COLLECT_INTL_PATH)
        return build_international(branch_dir, collect_intl)
    raise ValueError(f"branch must be one of {sorted(paths.ALLOWED_BRANCHES)}, got {branch!r}")


_DEFAULT_OUTPUT = {
    "domestic": paths.REPOSITORY_ROOT / "data/raw/vietnamese/vietnamese_raw.parquet",
    "international": paths.REPOSITORY_ROOT / "data/raw/international/international_raw.parquet",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a v1-compatible candidate Parquet from the v2 JSONL archive."
    )
    parser.add_argument("--branch", choices=sorted(paths.ALLOWED_BRANCHES), required=True)
    parser.add_argument("--collector-host", required=True)
    parser.add_argument("--output", default=None, help="Defaults to the same path collect_vn.py/collect_intl.py would use.")
    args = parser.parse_args()

    df = build(args.branch, args.collector_host)
    output_path = Path(args.output) if args.output else _DEFAULT_OUTPUT[args.branch]
    paths.atomic_write_parquet(df, output_path)
    print(f"Branch                : {args.branch}")
    print(f"Collector host        : {args.collector_host}")
    print(f"Candidate rows        : {len(df):,}")
    print(f"Candidate table       : {output_path}")


if __name__ == "__main__":
    main()

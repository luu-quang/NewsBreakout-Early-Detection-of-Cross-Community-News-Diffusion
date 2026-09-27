"""Single command: v2 JSONL archive (``data/raw/v2/``) -> a dated master
snapshot, for teammates without VM/SSH access.

Chains ``build_candidate_table`` -> ``clean_vn``/``clean_intl`` ->
``build_master`` (all three unmodified - this script only orchestrates them
and never changes their contract), then attaches an ``is_pre_start`` column
(see ``src/collect_v2/feed_state.py``) and writes a manifest for
reproducibility. Run after ``scripts/pull_snapshot.py`` has populated
``data/raw/v2/`` from a backup - see ``docs/DATA_ACCESS.md``.

Output never touches the frozen Phase 2A contract file
(``data/processed/master/articles_master.parquet``) - it writes to
``data/processed/v2/articles_master_v2_<date>.parquet`` instead.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import tempfile
import types
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.collect_v2 import build_candidate_table, feed_state  # noqa: E402
from src.collect_v2 import paths as v2_paths  # noqa: E402
from src.integration import build_master  # noqa: E402

CLEAN_VN_PATH = (
    REPO_ROOT / "team_work/phases/phase1_collection_cleaning/vietnamese_team/code/clean_vn.py"
)
CLEAN_INTL_PATH = (
    REPO_ROOT / "team_work/phases/phase1_collection_cleaning/international_team/code/clean_intl.py"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data/processed/v2"


def _load_module(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _parse_bound(value: str | None) -> pd.Timestamp | None:
    if value is None:
        return None
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def filter_window(df: pd.DataFrame, since: str | None, until: str | None) -> pd.DataFrame:
    """Filters on ``first_seen_at`` - the collection window (always present,
    unlike ``published_at`` which can be ``unavailable``) - not on
    ``published_at``, which is the field being measured, not the selector."""
    start, end = _parse_bound(since), _parse_bound(until)
    if start is None and end is None:
        return df.reset_index(drop=True)
    seen = pd.to_datetime(df["first_seen_at"], utc=True, errors="coerce")
    mask = pd.Series(True, index=df.index)
    if start is not None:
        mask &= seen.ge(start)
    if end is not None:
        mask &= seen.lt(end)
    return df[mask].reset_index(drop=True)


def _relevant_and_audit(raw_df: pd.DataFrame, clean_module: types.ModuleType) -> tuple[pd.DataFrame, pd.DataFrame]:
    audit_df = clean_module.clean(raw_df)
    relevant = (
        audit_df[audit_df["rejection_reason"].isna() & audit_df["vietnam_relevance"].eq(True)]
        .sort_values("first_seen_at")
        .drop_duplicates(subset=["canonical_url"], keep="first")[clean_module.SHARED_SCHEMA]
        .reset_index(drop=True)
    )
    return relevant, audit_df


def collect_branch(
    branch: str, clean_module: types.ModuleType, since: str | None, until: str | None
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str | None], dict[str, str]]:
    """Returns (relevant, audit, ref->feed_locator, ref->collector_host) for
    every host this branch has ever been collected from."""
    relevant_parts: list[pd.DataFrame] = []
    audit_parts: list[pd.DataFrame] = []
    ref_locator: dict[str, str | None] = {}
    ref_host: dict[str, str] = {}
    for host in v2_paths.discover_hosts(branch):
        branch_dir = v2_paths.branch_host_dir(branch, host)
        raw_df = build_candidate_table.build(branch, host)
        if raw_df.empty:
            continue
        raw_df = filter_window(raw_df, since, until)
        if raw_df.empty:
            continue
        locators = build_candidate_table.ref_feed_locators(branch_dir)
        for ref in raw_df["raw_payload_ref"]:
            ref_locator[ref] = locators.get(ref)
            ref_host[ref] = host
        relevant, audit = _relevant_and_audit(raw_df, clean_module)
        relevant_parts.append(relevant)
        audit_parts.append(audit)
    relevant_df = (
        pd.concat(relevant_parts, ignore_index=True) if relevant_parts else pd.DataFrame(columns=clean_module.SHARED_SCHEMA)
    )
    audit_df = pd.concat(audit_parts, ignore_index=True) if audit_parts else pd.DataFrame(columns=clean_module.AUDIT_SCHEMA)
    return relevant_df, audit_df, ref_locator, ref_host


def attach_is_pre_start(
    df: pd.DataFrame,
    ref_locator: dict[str, str | None],
    ref_host: dict[str, str],
    state: dict,
) -> pd.DataFrame:
    def _compute(row: pd.Series) -> bool | None:
        locator = ref_locator.get(row["raw_payload_ref"])
        host = ref_host.get(row["raw_payload_ref"])
        if locator is None or host is None:
            return None
        return feed_state.is_pre_start(row["published_at"], row["branch"], host, locator, state)

    df = df.copy()
    df["is_pre_start"] = df.apply(_compute, axis=1) if len(df) else pd.Series(dtype=object)
    return df


def feed_manifest_rows(state: dict) -> list[dict]:
    rows = []
    for branch, hosts in state.items():
        for host, feeds in hosts.items():
            for locator, info in feeds.items():
                rows.append(
                    {
                        "branch": branch,
                        "collector_host": host,
                        "feed_locator": locator,
                        "publisher_id_hint": info.get("publisher_id_hint"),
                        "feed_started_at": info.get("feed_started_at"),
                    }
                )
    return sorted(rows, key=lambda r: (r["branch"], r["collector_host"], r["feed_locator"]))


def _iso_or_none(value: pd.Timestamp) -> str | None:
    return None if pd.isna(value) else value.isoformat()


def build_manifest(
    output_path: Path,
    df: pd.DataFrame,
    since: str | None,
    until: str | None,
    feed_rows: list[dict],
) -> dict:
    first_seen = pd.to_datetime(df["first_seen_at"], utc=True, errors="coerce")
    published = pd.to_datetime(df["published_at"], utc=True, errors="coerce")
    pre_start_counts = df["is_pre_start"].map(lambda v: "unknown" if v is None else str(v)).value_counts().to_dict()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since": since,
        "until": until,
        "output_file": output_path.name,
        "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "row_count": len(df),
        "rows_by_branch": df.groupby("branch").size().to_dict() if len(df) else {},
        "rows_by_publisher": df.groupby("publisher_id").size().sort_values(ascending=False).to_dict() if len(df) else {},
        "date_range": {
            "first_seen_at_min": _iso_or_none(first_seen.min()) if len(df) else None,
            "first_seen_at_max": _iso_or_none(first_seen.max()) if len(df) else None,
            "published_at_min": _iso_or_none(published.min()) if len(df) else None,
            "published_at_max": _iso_or_none(published.max()) if len(df) else None,
        },
        "is_pre_start_counts": pre_start_counts,
        "feeds": feed_rows,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a dated master snapshot + manifest from data/raw/v2/."
    )
    parser.add_argument("--since", default=None, help="ISO date/datetime; filters on first_seen_at (inclusive).")
    parser.add_argument("--until", default=None, help="ISO date/datetime; filters on first_seen_at (exclusive).")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--date-tag", default=None, help="Defaults to today's UTC date.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    clean_vn = _load_module("clean_vn_v2snapshot", CLEAN_VN_PATH)
    clean_intl = _load_module("clean_intl_v2snapshot", CLEAN_INTL_PATH)

    vn_relevant, vn_audit, vn_locator, vn_host = collect_branch("domestic", clean_vn, args.since, args.until)
    intl_relevant, intl_audit, intl_locator, intl_host = collect_branch(
        "international", clean_intl, args.since, args.until
    )

    if vn_relevant.empty and intl_relevant.empty:
        raise SystemExit(
            "No candidate rows found in data/raw/v2/ for the given window - "
            "is it populated? See scripts/pull_snapshot.py / docs/DATA_ACCESS.md."
        )

    date_tag = args.date_tag or date.today().isoformat()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    master_path = output_dir / f"articles_master_v2_{date_tag}.parquet"
    audit_path = output_dir / f"articles_audit_v2_{date_tag}.parquet"
    manifest_path = output_dir / f"articles_master_v2_{date_tag}.manifest.json"

    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        vn_relevant.to_parquet(tmp / "vn_articles.parquet", index=False)
        intl_relevant.to_parquet(tmp / "intl_articles.parquet", index=False)
        vn_audit.to_parquet(tmp / "vn_audit.parquet", index=False)
        intl_audit.to_parquet(tmp / "intl_audit.parquet", index=False)
        articles_master, articles_audit = build_master.build_master(
            tmp / "vn_articles.parquet",
            tmp / "intl_articles.parquet",
            tmp / "vn_audit.parquet",
            tmp / "intl_audit.parquet",
            master_path,
            audit_path,
        )

    state = feed_state.load_state()
    ref_locator = {**vn_locator, **intl_locator}
    ref_host = {**vn_host, **intl_host}
    articles_master = attach_is_pre_start(articles_master, ref_locator, ref_host, state)
    articles_audit = attach_is_pre_start(articles_audit, ref_locator, ref_host, state)
    v2_paths.atomic_write_parquet(articles_master, master_path)
    v2_paths.atomic_write_parquet(articles_audit, audit_path)

    feed_rows = feed_manifest_rows(state)
    manifest = build_manifest(master_path, articles_master, args.since, args.until, feed_rows)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")

    print(f"Master rows          : {len(articles_master):,} -> {master_path}")
    print(f"Audit rows           : {len(articles_audit):,} -> {audit_path}")
    print(f"Manifest             : {manifest_path}")
    print(f"sha256               : {manifest['sha256']}")
    print(f"Date range (first_seen_at): {manifest['date_range']['first_seen_at_min']} .. {manifest['date_range']['first_seen_at_max']}")
    print("Rows by branch        :", manifest["rows_by_branch"])
    print("Rows by publisher     :", manifest["rows_by_publisher"])
    print("is_pre_start counts   :", manifest["is_pre_start_counts"])


if __name__ == "__main__":
    main()

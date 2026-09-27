"""Print the per-feed table of the last N collector runs, for spot-checking
collector health without touching the raw archive. Reads only the heartbeat
JSONL (see ``src/collect_v2/runner.py`` / ``feed_diagnostics.py`` for what
``per_feed`` means and how ``feed_issues`` are classified).

Usage::

    python3 scripts/show_feed_health.py                      # last 6 runs, this host
    python3 scripts/show_feed_health.py --last 20
    python3 scripts/show_feed_health.py --collector-host newsbreakoutcollector
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.collect_v2 import jsonl_store, paths  # noqa: E402


def load_last_n_runs(collector_host: str, n: int) -> list[dict]:
    """The current + previous month's heartbeat file (a run near the 1st of
    the month may need both), sorted oldest-to-newest, tail-truncated to the
    last ``n`` runs."""
    today = date.today()
    prev_month_day = today.replace(day=1) - timedelta(days=1)
    months = {today.strftime("%Y-%m"), prev_month_day.strftime("%Y-%m")}
    records: list[dict] = []
    for year_month in months:
        path = paths.heartbeat_path(collector_host, year_month)
        if path.exists():
            records.extend(jsonl_store.iter_jsonl(path))
    records.sort(key=lambda r: r["run_at"])
    return records[-n:] if n > 0 else records


def format_table(records: list[dict]) -> str:
    columns = ["run_at", "branch", "feed_id", "http_status", "content_encoding", "n_entries", "n_new", "error"]
    widths = {"run_at": 26, "branch": 14, "feed_id": 16, "http_status": 6, "content_encoding": 10, "n_entries": 9, "n_new": 6}
    header = "  ".join(col.ljust(widths.get(col, 0)) for col in columns[:-1]) + "  error"
    lines = [header, "-" * len(header)]
    for record in records:
        run_at = record.get("run_at", "")
        for branch, child in record.get("children", {}).items():
            for result in child.get("per_feed", []):
                row = [
                    str(run_at).ljust(widths["run_at"]),
                    str(branch).ljust(widths["branch"]),
                    str(result.get("feed_id", "")).ljust(widths["feed_id"]),
                    str(result.get("http_status", "")).ljust(widths["http_status"]),
                    str(result.get("content_encoding", "")).ljust(widths["content_encoding"]),
                    str(result.get("n_entries", "")).rjust(widths["n_entries"]),
                    str(result.get("n_new", "")).rjust(widths["n_new"]),
                ]
                lines.append("  ".join(row) + "  " + (result.get("error") or ""))
        issues = record.get("feed_issues") or []
        if issues:
            lines.append(f"  -> feed_issues (real problem, drives /fail): {'; '.join(issues)}")
        stale = record.get("stale_feed_issues") or []
        if stale:
            lines.append(f"  -> stale_feed_issues (informational only, does not fail the check): {'; '.join(stale)}")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Print the per-feed table of the last N collector runs.")
    parser.add_argument("--collector-host", default=None)
    parser.add_argument("--last", type=int, default=6)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    collector_host = args.collector_host or paths.default_collector_host()
    records = load_last_n_runs(collector_host, args.last)
    if not records:
        print(f"No heartbeat history found for collector_host={collector_host!r}.")
        return
    print(format_table(records))


if __name__ == "__main__":
    main()

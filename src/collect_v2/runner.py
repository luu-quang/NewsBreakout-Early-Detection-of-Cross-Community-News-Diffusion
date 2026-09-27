"""Continuous-collector runner: invokes both collectors as isolated
subprocesses, writes one heartbeat record per run, and pings healthchecks.io.

Per-feed isolation lives inside each collector (see ``fetch.py``); this runner
adds one more layer: a whole collector (domestic or international) hanging,
crashing, or failing to acquire its own run-lock must never prevent the OTHER
collector from running, and must never go unnoticed - see the heartbeat and
healthchecks.io reporting below.

Per-feed detail: each child prints one machine-readable line (see
``feed_diagnostics.py``) with its own result for every feed - this runner
reads it back from the child's captured stdout and stores it as
``per_feed`` on that child's heartbeat entry. Found the hard way (see
``fetch.py``'s gzip fix) that "the collector ran successfully" and "every
feed actually produced data" are different questions - a run can report
``ok: true`` while several feeds silently returned nothing for hours. Two
independent checks turn specific feed problems into a healthchecks.io
failure, each naming the feed(s) involved:

1. ``classify_feed_issues`` - this run's own per-feed results: a fetch
   error, a parse error (bozo) with zero entries, or an established feed
   (has a recorded ``feed_started_at``) that returned zero entries this run
   with no explicit error at all (a legitimate-looking but suspicious empty
   response).
2. ``stale_feed_issues`` - reads back recent heartbeat history (never the
   raw archive - per-feed ``n_new`` in past heartbeats is enough) to catch a
   feed that has gone quiet more gradually: zero new payloads for
   ``FEED_STALE_HOURS_OVERRIDE.get(feed_id, DEFAULT_STALE_HOURS)`` hours.
   The default (6h) needs real per-feed tuning as the team observes actual
   posting cadence (some outlets post sparsely overnight) - see
   ``docs/HANDOFF_2026-09-27.md``.

healthchecks.io: reads ``HEALTHCHECKS_PING_URL`` from the environment (never
committed - set it on the VM at deploy time). A fully successful run (both
children ok AND no feed issues) issues a GET to that URL; anything else issues
a POST to ``<url>/fail`` with a short text summary, naming the failing
child(ren) and/or feed(s). Unset -> skipped with a note, not an error (so
local/manual runs don't require it).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from . import feed_diagnostics, feed_state, jsonl_store, paths

COLLECT_VN = (
    paths.REPOSITORY_ROOT
    / "team_work/phases/phase1_collection_cleaning/vietnamese_team/code/collect_vn.py"
)
COLLECT_INTL = (
    paths.REPOSITORY_ROOT
    / "team_work/phases/phase1_collection_cleaning/international_team/code/collect_intl.py"
)

DEFAULT_CHILD_TIMEOUT = 180.0
DEFAULT_FETCH_TIMEOUT = 15.0

DEFAULT_STALE_HOURS = 6.0
# Per-feed overrides for outlets known to post sparsely at certain hours -
# fill in as the team observes real posting cadence (see module docstring).
FEED_STALE_HOURS_OVERRIDE: dict[str, float] = {}


def _parse_counts(stdout: str) -> tuple[int | None, int | None]:
    new_count = seen_count = None
    for line in stdout.splitlines():
        if line.startswith("New payloads archived :"):
            new_count = int(line.split(":", 1)[1].strip().replace(",", ""))
        elif line.startswith("Entries seen this run :"):
            seen_count = int(line.split(":", 1)[1].strip().replace(",", ""))
    return new_count, seen_count


def run_child(script: Path, collector_host: str, fetch_timeout: float, child_timeout: float) -> dict:
    """Run one collector script with ``--continuous``, never raising: any
    failure (non-zero exit, timeout, or failure to even start the process) is
    captured in the returned dict so the caller can record the other child's
    result regardless. ``per_feed`` is parsed best-effort from whatever stdout
    the child produced, even on a non-zero exit - a crash partway through
    still leaves earlier feeds' results readable."""
    started = time.monotonic()
    cmd = [
        sys.executable, str(script), "--continuous",
        "--collector-host", collector_host,
        "--fetch-timeout", str(fetch_timeout),
    ]
    try:
        result = subprocess.run(cmd, cwd=paths.REPOSITORY_ROOT, capture_output=True, text=True, timeout=child_timeout)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return {
            "ok": False, "duration_seconds": round(time.monotonic() - started, 3),
            "error": f"timed out after {child_timeout}s", "per_feed": feed_diagnostics.parse_per_feed_results(stdout) or [],
        }
    except OSError as exc:
        return {"ok": False, "duration_seconds": round(time.monotonic() - started, 3), "error": f"failed to start: {exc}", "per_feed": []}

    duration = round(time.monotonic() - started, 3)
    per_feed = feed_diagnostics.parse_per_feed_results(result.stdout) or []
    if result.returncode != 0:
        return {
            "ok": False, "duration_seconds": duration,
            "error": f"exit code {result.returncode}: {result.stderr.strip()[-2000:]}", "per_feed": per_feed,
        }
    new_count, seen_count = _parse_counts(result.stdout)
    return {
        "ok": True, "duration_seconds": duration, "new_payloads": new_count, "entries_seen": seen_count,
        "error": None, "per_feed": per_feed,
    }


def classify_feed_issues(per_feed: list[dict], branch: str, collector_host: str, state: dict) -> list[str]:
    """Per-feed problems visible from this single run alone: an explicit
    fetch/parse error, or an established feed (already has a recorded
    ``feed_started_at``) that came back with zero entries and no error at
    all - a legitimate-looking but suspicious empty response. A brand-new
    feed with no ``feed_started_at`` yet returning zero entries is not
    flagged here - it may just not have bootstrapped yet."""
    issues = []
    for result in per_feed:
        feed_id = result["feed_id"]
        if result.get("error"):
            issues.append(f"{feed_id}: {result['error']}")
            continue
        if result.get("n_entries", 0) == 0:
            started_at = feed_state.get_feed_started_at(state, branch, collector_host, result["feed_url"])
            if started_at is not None:
                issues.append(f"{feed_id}: 0 entries this run (established feed since {started_at})")
    return issues


def _recent_heartbeat_records(collector_host: str, now: datetime, lookback_hours: float):
    """Heartbeat records from the last ``lookback_hours``, newest first -
    reads only the heartbeat JSONL (never the raw payload/sightings archive),
    transparently spanning a month boundary if the window crosses one."""
    cutoff = now - timedelta(hours=lookback_hours)
    months = {now.strftime("%Y-%m"), cutoff.strftime("%Y-%m")}
    records = []
    for year_month in months:
        path = paths.heartbeat_path(collector_host, year_month)
        if path.exists():
            records.extend(jsonl_store.iter_jsonl(path))
    records.sort(key=lambda r: r["run_at"], reverse=True)
    for record in records:
        if datetime.fromisoformat(record["run_at"]) < cutoff:
            break
        yield record


def hours_since_last_new(collector_host: str, feed_id: str, now: datetime, max_lookback_hours: float) -> float | None:
    """Hours since ``feed_id`` last had ``n_new > 0`` in the heartbeat
    history, scanning back at most ``max_lookback_hours``.

    If heartbeat history exists in the window but this feed never had
    ``n_new > 0`` in it, returns ``max_lookback_hours`` itself (a lower
    bound - "at least this stale") rather than ``None``, so a feed that has
    been stale for LONGER than the scan window still gets flagged instead of
    silently falling out of view the longer it stays broken. ``None`` only
    when there is no heartbeat history at all in the window (can't confirm
    anything - the feed or the collector itself is too new)."""
    any_heartbeat = False
    for record in _recent_heartbeat_records(collector_host, now, max_lookback_hours):
        any_heartbeat = True
        for child in record.get("children", {}).values():
            for result in child.get("per_feed", []):
                if result["feed_id"] == feed_id and result.get("n_new", 0) > 0:
                    run_at = datetime.fromisoformat(record["run_at"])
                    return (now - run_at).total_seconds() / 3600.0
    return max_lookback_hours if any_heartbeat else None


def stale_feed_issues(feed_ids: set[str], collector_host: str, now: datetime) -> list[str]:
    issues = []
    for feed_id in sorted(feed_ids):
        threshold = FEED_STALE_HOURS_OVERRIDE.get(feed_id, DEFAULT_STALE_HOURS)
        hours = hours_since_last_new(collector_host, feed_id, now, max_lookback_hours=max(threshold * 4, 24.0))
        if hours is not None and hours >= threshold:
            issues.append(f"{feed_id}: no new payload in {hours:.1f}h (threshold {threshold:.1f}h)")
    return issues


def ping_healthchecks(ok: bool, summary: str) -> None:
    base_url = os.environ.get("HEALTHCHECKS_PING_URL")
    if not base_url:
        print("[runner] HEALTHCHECKS_PING_URL not set, skipping ping")
        return
    url = base_url if ok else base_url.rstrip("/") + "/fail"
    try:
        data = None if ok else summary.encode("utf-8")
        request = Request(url, data=data, method="GET" if ok else "POST")
        with urlopen(request, timeout=10) as response:
            response.read()
    except Exception as exc:  # best-effort: a monitoring ping must never crash the runner
        print(f"[runner] healthchecks ping failed: {exc}")


def run_once(collector_host: str, fetch_timeout: float, child_timeout: float) -> dict:
    run_id = uuid.uuid4().hex
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()

    domestic = run_child(COLLECT_VN, collector_host, fetch_timeout, child_timeout)
    international = run_child(COLLECT_INTL, collector_host, fetch_timeout, child_timeout)

    for branch in ("domestic", "international"):
        directory = paths.branch_host_dir(branch, collector_host)
        jsonl_store.rotate_old_files(directory, prefix="payloads", keep_days=2)
        jsonl_store.rotate_old_files(directory, prefix="sightings", keep_days=2)

    record = {
        "run_id": run_id,
        "run_at": started_at,
        "collector_host": collector_host,
        "duration_seconds": round(time.monotonic() - started, 3),
        "children": {"domestic": domestic, "international": international},
        "overall_ok": bool(domestic["ok"] and international["ok"]),
    }

    state = feed_state.load_state()
    feed_issues: list[str] = []
    all_feed_ids: set[str] = set()
    for branch, child in record["children"].items():
        per_feed = child.get("per_feed") or []
        feed_issues += classify_feed_issues(per_feed, branch, collector_host, state)
        all_feed_ids |= {result["feed_id"] for result in per_feed}
    now = datetime.now(timezone.utc)
    feed_issues += stale_feed_issues(all_feed_ids, collector_host, now)
    record["feed_issues"] = feed_issues
    record["ping_ok"] = record["overall_ok"] and not feed_issues

    jsonl_store.append_line(paths.heartbeat_path(collector_host), record)

    if record["ping_ok"]:
        ping_healthchecks(True, "ok")
    else:
        failures = "; ".join(f"{branch}: {r['error']}" for branch, r in record["children"].items() if not r["ok"])
        if feed_issues:
            feed_summary = "feed issues: " + "; ".join(feed_issues)
            failures = f"{failures}; {feed_summary}" if failures else feed_summary
        ping_healthchecks(False, failures)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description="Run both v2 continuous collectors once and record a heartbeat.")
    parser.add_argument("--collector-host", default=None)
    parser.add_argument("--fetch-timeout", type=float, default=DEFAULT_FETCH_TIMEOUT)
    parser.add_argument("--child-timeout", type=float, default=DEFAULT_CHILD_TIMEOUT)
    args = parser.parse_args()

    collector_host = args.collector_host or paths.default_collector_host()
    record = run_once(collector_host, args.fetch_timeout, args.child_timeout)
    print(json.dumps(record, indent=2))
    if not record["ping_ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

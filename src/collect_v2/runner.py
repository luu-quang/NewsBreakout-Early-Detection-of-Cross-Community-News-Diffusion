"""Continuous-collector runner: invokes both collectors as isolated
subprocesses, writes one heartbeat record per run, and pings healthchecks.io.

Per-feed isolation lives inside each collector (see ``fetch.py``); this runner
adds one more layer: a whole collector (domestic or international) hanging,
crashing, or failing to acquire its own run-lock must never prevent the OTHER
collector from running, and must never go unnoticed - see the heartbeat and
healthchecks.io reporting below. Per-feed detail (which feed failed and why)
stays in each collector's own stdout/stderr, captured by systemd's journal in
deployment (see Phase 2) - the heartbeat records per-COLLECTOR outcomes only.

healthchecks.io: reads ``HEALTHCHECKS_PING_URL`` from the environment (never
committed - set it on the VM at deploy time). A fully successful run issues a
GET to that URL; any child failure issues a POST to ``<url>/fail`` with a short
text summary. Unset -> skipped with a note, not an error (so local/manual runs
don't require it).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from . import jsonl_store, paths

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
    result regardless."""
    started = time.monotonic()
    cmd = [
        sys.executable, str(script), "--continuous",
        "--collector-host", collector_host,
        "--fetch-timeout", str(fetch_timeout),
    ]
    try:
        result = subprocess.run(cmd, cwd=paths.REPOSITORY_ROOT, capture_output=True, text=True, timeout=child_timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "duration_seconds": round(time.monotonic() - started, 3), "error": f"timed out after {child_timeout}s"}
    except OSError as exc:
        return {"ok": False, "duration_seconds": round(time.monotonic() - started, 3), "error": f"failed to start: {exc}"}

    duration = round(time.monotonic() - started, 3)
    if result.returncode != 0:
        return {"ok": False, "duration_seconds": duration, "error": f"exit code {result.returncode}: {result.stderr.strip()[-2000:]}"}
    new_count, seen_count = _parse_counts(result.stdout)
    return {"ok": True, "duration_seconds": duration, "new_payloads": new_count, "entries_seen": seen_count, "error": None}


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
    jsonl_store.append_line(paths.heartbeat_path(collector_host), record)

    if record["overall_ok"]:
        ping_healthchecks(True, "ok")
    else:
        failures = "; ".join(f"{branch}: {r['error']}" for branch, r in record["children"].items() if not r["ok"])
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
    if not record["overall_ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

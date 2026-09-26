"""Path layout and atomic-write helper for the v2 continuous collector.

Layout (approved 2026-09-26, single-VM scope - see docs/HANDOFF_2026-09-26.md):

    data/raw/v2/<branch>/<collector_host>/payloads-YYYY-MM-DD.jsonl[.gz]
    data/raw/v2/<branch>/<collector_host>/sightings-YYYY-MM-DD.jsonl[.gz]
    data/raw/v2/<branch>/<collector_host>/seen_index.sqlite3
    data/raw/v2/heartbeat/<collector_host>-YYYY-MM.jsonl

``<branch>`` uses the frozen contract's own enum values (``domestic`` /
``international`` - see ``ALLOWED_BRANCHES`` in ``src/integration/build_master.py``
and the ``branch`` column in ``clean_vn.py`` / ``clean_intl.py``), not the
``vietnamese`` naming used only for v1's folder/file conventions. Nothing here
reads or writes any v1 path (``data/raw/vietnamese/...``,
``data/raw/international/international_raw.parquet``, etc.).
"""

from __future__ import annotations

import os
import socket
from datetime import date
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
V2_ROOT = REPOSITORY_ROOT / "data" / "raw" / "v2"

ALLOWED_BRANCHES = {"domestic", "international"}


def default_collector_host() -> str:
    """Explicit ``COLLECTOR_HOST`` env var wins; otherwise the platform hostname
    (``socket.gethostname()`` works identically on Linux and Windows)."""
    return os.environ.get("COLLECTOR_HOST") or socket.gethostname()


def _require_branch(branch: str) -> str:
    if branch not in ALLOWED_BRANCHES:
        raise ValueError(f"branch must be one of {sorted(ALLOWED_BRANCHES)}, got {branch!r}")
    return branch


def branch_host_dir(branch: str, collector_host: str) -> Path:
    return V2_ROOT / _require_branch(branch) / collector_host


def payloads_path(branch: str, collector_host: str, day: date | None = None) -> Path:
    day = day or date.today()
    return branch_host_dir(branch, collector_host) / f"payloads-{day.isoformat()}.jsonl"


def sightings_path(branch: str, collector_host: str, day: date | None = None) -> Path:
    day = day or date.today()
    return branch_host_dir(branch, collector_host) / f"sightings-{day.isoformat()}.jsonl"


def seen_index_path(branch: str, collector_host: str) -> Path:
    return branch_host_dir(branch, collector_host) / "seen_index.sqlite3"


def heartbeat_path(collector_host: str, year_month: str | None = None) -> Path:
    year_month = year_month or date.today().strftime("%Y-%m")
    return V2_ROOT / "heartbeat" / f"{collector_host}-{year_month}.jsonl"


def feed_state_path() -> Path:
    """Per-feed first-observed tracking (see ``feed_state.py``). One file for
    every branch/host - small, and there is exactly one of it by design."""
    return V2_ROOT / "state" / "feeds.json"


def archive_label(path: Path) -> str:
    """Repo-relative POSIX path when possible, matching v1's own convention
    (see ``_archive_label`` in ``collect_vn.py`` / ``collect_intl.py``) - but
    resolved against the fixed repository root rather than the process's
    current working directory, so ``raw_payload_ref`` stays correct
    regardless of where the collector/systemd unit is invoked from.

    A record's ``raw_payload_ref`` is always constructed while its archive file
    is still the live, plain ``.jsonl`` (rotation never touches today's file -
    see ``jsonl_store.rotate_old_files``), so a ``.gz`` suffix is stripped here
    too: reading a rotated file later must reproduce the exact same label the
    write path used, or ``rebuild_from_jsonl`` would silently mint different
    refs than the ones already recorded in old sightings.
    """
    if path.suffix == ".gz":
        path = path.with_suffix("")
    try:
        return path.resolve().relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def atomic_write_parquet(df, path: Path) -> None:
    """Write a DataFrame to ``path`` via a same-directory temp file + ``os.replace``.

    ``os.replace`` is atomic on both POSIX and Windows, so a crash or kill
    mid-write can never leave a half-written file at ``path`` - readers either
    see the previous complete file or the new complete file, never a corrupt one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    df.to_parquet(tmp_path, index=False)
    os.replace(tmp_path, path)

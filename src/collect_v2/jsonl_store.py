"""Append-only JSONL storage: the source of truth for the v2 continuous collector.

Every write is a single ``open(..., "a") -> write -> flush -> fsync -> close``
sequence, so a crash can at worst leave one incomplete trailing line, never a
corrupted earlier line and never a partially-applied multi-line write.
``iter_jsonl`` defends against exactly that: a malformed line (mid-write crash,
or a manually truncated file) is skipped with a warning instead of raising,
so one bad line cannot break a rebuild or a candidate-table build.
"""

from __future__ import annotations

import gzip
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator


def append_line(path: Path, record: dict) -> None:
    """Append one record as a single JSON line, fsynced before returning.

    Never appends to a ``.gz`` file - rotation only touches files once they are
    no longer the active (today's) file, so a live collector never writes into
    a rotated file by construction (see ``rotate_old_files``).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def iter_jsonl(path: Path) -> Iterator[dict]:
    """Yield records from a plain or gzip-compressed JSONL file.

    Missing files yield nothing (a branch/host that never ran yet is not an
    error). Malformed lines are skipped with a warning to stderr rather than
    raising, since the only way such a line exists is a crash mid-write.
    """
    if not path.exists():
        return
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                print(f"[jsonl_store] skipping malformed line {line_number} in {path}", file=sys.stderr)


def existing_variants(path: Path) -> Path | None:
    """Return whichever of ``path`` or ``path`` + ``.gz`` exists, if any."""
    if path.exists():
        return path
    gz = path.with_suffix(path.suffix + ".gz")
    if gz.exists():
        return gz
    return None


def rotate_old_files(directory: Path, *, prefix: str, keep_days: int = 2, today: date | None = None) -> list[Path]:
    """Gzip day-rotated ``{prefix}-YYYY-MM-DD.jsonl`` files older than ``keep_days``.

    Never touches today's file or the ``keep_days`` most recent days (a slow
    clock, a late-arriving write, or a run spanning midnight should never rotate
    a file still being appended to). Idempotent: already-gzipped or missing
    files are skipped silently. Returns the paths that were rotated.
    """
    if not directory.exists():
        return []
    today = today or date.today()
    cutoff = today - timedelta(days=keep_days)
    rotated = []
    for candidate in sorted(directory.glob(f"{prefix}-*.jsonl")):
        stem = candidate.stem[len(prefix) + 1 :]
        try:
            file_date = date.fromisoformat(stem)
        except ValueError:
            continue
        if file_date >= cutoff:
            continue
        gz_path = candidate.with_suffix(candidate.suffix + ".gz")
        with candidate.open("rb") as src, gzip.open(gz_path, "wb") as dst:
            dst.writelines(src)
        candidate.unlink()
        rotated.append(gz_path)
    return rotated

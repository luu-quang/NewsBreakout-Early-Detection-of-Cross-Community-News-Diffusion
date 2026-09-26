"""SQLite seen-index: a rebuildable runtime cache, never a source of truth.

The index answers one question fast, without re-reading potentially large
JSONL history on every poll: "have we already archived the full payload for
this (entry_key, content_hash) pair?" JSONL (payloads + sightings) is the only
source of truth; ``rebuild_from_jsonl`` reconstructs the index from scratch and
must produce the same answer as incremental updates would have.

Write-ordering contract (enforced by callers, e.g. ``collect_continuous.py``):
JSONL append + fsync happens BEFORE ``record_seen`` is called. If the process
crashes in between, the index still says "not seen" on the next run, so the
(harmless, deterministic-build-deduped) payload gets written again - it is
never possible for the index to say "seen" while the payload was not actually
written.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import jsonl_store, paths

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    entry_key TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    payload_ref TEXT NOT NULL,
    PRIMARY KEY (entry_key, content_hash)
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute(_SCHEMA)
    return conn


def is_new(conn: sqlite3.Connection, entry_key: str, content_hash: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM seen WHERE entry_key = ? AND content_hash = ?",
        (entry_key, content_hash),
    ).fetchone()
    return row is None


def get_payload_ref(conn: sqlite3.Connection, entry_key: str, content_hash: str) -> str | None:
    row = conn.execute(
        "SELECT payload_ref FROM seen WHERE entry_key = ? AND content_hash = ?",
        (entry_key, content_hash),
    ).fetchone()
    return row[0] if row else None


def record_seen(
    conn: sqlite3.Connection,
    entry_key: str,
    content_hash: str,
    observed_at: str,
    payload_ref: str,
) -> None:
    """Idempotent: safe to call again for an already-known pair (advances
    ``last_seen_at`` only)."""
    conn.execute(
        """
        INSERT INTO seen (entry_key, content_hash, first_seen_at, last_seen_at, payload_ref)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (entry_key, content_hash) DO UPDATE SET last_seen_at = excluded.last_seen_at
        """,
        (entry_key, content_hash, observed_at, observed_at, payload_ref),
    )


def rebuild_from_jsonl(branch: str, collector_host: str) -> Path:
    """Recreate the seen-index for (branch, host) purely from its JSONL archive.

    Replays every payload record (day files in chronological order, ``.jsonl``
    and rotated ``.jsonl.gz`` both included) exactly as the live collector would
    have on first sight of each (entry_key, content_hash); then replays sightings
    to advance ``last_seen_at``. Returns the rebuilt database path.
    """
    db_path = paths.seen_index_path(branch, collector_host)
    if db_path.exists():
        db_path.unlink()
    for suffix in ("-wal", "-shm"):
        sidecar = db_path.with_name(db_path.name + suffix)
        if sidecar.exists():
            sidecar.unlink()

    conn = connect(db_path)
    directory = paths.branch_host_dir(branch, collector_host)

    payload_files = list(directory.glob("payloads-*.jsonl")) + list(directory.glob("payloads-*.jsonl.gz"))
    for file_path in sorted(payload_files, key=lambda p: p.name.replace(".gz", "")):
        # Payload records don't carry payload_ref directly; it's derived from
        # this file's own path + the record's raw_record_id, exactly as
        # continuous_write.write_continuous_batch() constructs it at write time.
        archive_label = paths.archive_label(file_path)
        for record in jsonl_store.iter_jsonl(file_path):
            payload_ref = f"{archive_label}#raw_record_id={record['raw_record_id']}"
            conn.execute(
                """
                INSERT INTO seen (entry_key, content_hash, first_seen_at, last_seen_at, payload_ref)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (entry_key, content_hash) DO NOTHING
                """,
                (
                    record["entry_key"],
                    record["content_hash"],
                    record["observed_at"],
                    record["observed_at"],
                    payload_ref,
                ),
            )

    sighting_files = list(directory.glob("sightings-*.jsonl")) + list(directory.glob("sightings-*.jsonl.gz"))
    for file_path in sorted(sighting_files, key=lambda p: p.name.replace(".gz", "")):
        for record in jsonl_store.iter_jsonl(file_path):
            conn.execute(
                """
                UPDATE seen SET last_seen_at = ?
                WHERE entry_key = ? AND content_hash = ? AND last_seen_at < ?
                """,
                (record["observed_at"], record["entry_key"], record["content_hash"], record["observed_at"]),
            )
    conn.commit()
    conn.close()
    return db_path

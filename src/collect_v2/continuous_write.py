"""Write one poll's fetched entries under the v2 continuous-mode contract.

Per entry: append a full payload record ONLY the first time this exact content
has ever been seen (by ``(entry_key, content_hash)``); always append a small
sightings record; only then update the seen-index. See ``seen_index.py`` for
why that order matters and what a mid-write crash can and cannot corrupt.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import hashing, jsonl_store, paths, seen_index


@dataclass
class RawCandidate:
    url: str
    payload: dict
    source_system: str
    source_locator: str
    publisher_id_hint: str | None = None


def write_continuous_batch(
    branch: str,
    collector_host: str,
    candidates: list[RawCandidate],
    *,
    observed_at: str,
    run_id: str,
) -> tuple[list[str], int]:
    """Write ``candidates``; return (``raw_payload_ref`` per candidate, in order,
    count of candidates that were genuinely new this call).

    The new-count is NOT ``len(set(refs))`` - two different candidates in the
    same batch can share a ref (duplicate content within one poll), which is a
    different thing from "this content had never been archived before".
    """
    payloads_file = paths.payloads_path(branch, collector_host)
    sightings_file = paths.sightings_path(branch, collector_host)
    conn = seen_index.connect(paths.seen_index_path(branch, collector_host))
    refs: list[str] = []
    new_count = 0
    try:
        for candidate in candidates:
            h = hashing.content_hash(candidate.payload)
            key = hashing.entry_key(candidate.url, h)
            new = seen_index.is_new(conn, key, h)

            if new:
                new_count += 1
                record_id = hashing.record_id(key, h)
                ref = f"{paths.archive_label(payloads_file)}#raw_record_id={record_id}"
                jsonl_store.append_line(
                    payloads_file,
                    {
                        "raw_record_id": record_id,
                        "entry_key": key,
                        "content_hash": h,
                        "source_system": candidate.source_system,
                        "source_locator": candidate.source_locator,
                        "publisher_id_hint": candidate.publisher_id_hint,
                        "observed_at": observed_at,
                        "payload": candidate.payload,
                    },
                )
            else:
                ref = seen_index.get_payload_ref(conn, key, h)

            jsonl_store.append_line(
                sightings_file,
                {
                    "observed_at": observed_at,
                    "run_id": run_id,
                    "branch": branch,
                    "collector_host": collector_host,
                    "entry_key": key,
                    "content_hash": h,
                    "is_new": new,
                    "payload_ref": ref,
                },
            )

            # Ordering contract: both JSONL appends above are flushed+fsynced
            # (see jsonl_store.append_line) before the index is touched at all.
            seen_index.record_seen(conn, key, h, observed_at, ref)
            refs.append(ref)
    finally:
        conn.close()
    return refs, new_count

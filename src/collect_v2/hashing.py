"""Content-identity helpers for the v2 continuous collector.

Deliberately separate from ``raw_record_id`` in the v1 collectors
(``collect_vn.py`` / ``collect_intl.py``), which hashes
``{source, locator, observed_at, payload}`` together - that makes every poll's
record unique by design (archival identity), not by content. Here we need the
opposite: a hash of the entry's own content only, so that re-polling the same
unedited entry maps to the same key and a genuinely edited entry maps to a new
one, deliberately preserving edit history rather than collapsing it.
"""

from __future__ import annotations

import hashlib
import json


def content_hash(payload: object) -> str:
    """SHA-256 of the entry's own content, independent of when it was observed."""
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def entry_key(url: object, fallback_hash: str) -> str:
    """Stable identity for an entry across polls.

    Mirrors the v1 collectors' own fallback rule (``_candidate_key``): prefer
    the URL; entries without a usable URL fall back to a hash-based key so
    they still get a stable identity instead of colliding on an empty string.
    """
    text = str(url or "").strip()
    return text if text else f"nourl:{fallback_hash}"


def record_id(entry_key_value: str, content_hash_value: str) -> str:
    """Unique id for one archived JSONL line.

    Deliberately NOT the same as ``content_hash`` alone: two different URLs can
    carry byte-identical content (true syndication - the exact case this
    project studies), which would otherwise archive as two distinct lines that
    share one id, making ``raw_payload_ref`` ambiguous about which line it
    names. Combining with ``entry_key`` keeps every archived line uniquely
    addressable while ``content_hash`` alone still drives the seen-index dedup
    decision (same URL, same content -> genuinely not new).
    """
    return hashlib.sha256(f"{entry_key_value}|{content_hash_value}".encode("utf-8")).hexdigest()

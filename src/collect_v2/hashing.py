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

"""Clean international RSS/GDELT candidates under the Phase 1 contract."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import pandas as pd

SHARED_SCHEMA = [
    "article_id", "title", "url", "canonical_url", "publisher_domain",
    "publisher_id", "publisher_group_id", "source_system", "first_seen_at",
    "published_at", "timestamp_confidence", "language", "publisher_country",
    "description", "category", "vietnam_relevance", "duplicate_family_id",
    "branch", "collection_mode", "raw_payload_ref",
]
AUDIT_SCHEMA = SHARED_SCHEMA + ["source_seen_at", "rejection_reason"]
CONFIDENCE_VALUES = {
    "publisher_reported",
    "publisher_reported_timezone_inferred",
    "unavailable",
}
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "fbclid", "gclid", "oc",
}

PUBLISHERS = {
    "reuters.com": ("reuters", "thomson_reuters", "GB"),
    "bbc.com": ("bbc", "bbc", "GB"),
    "bbc.co.uk": ("bbc", "bbc", "GB"),
    "apnews.com": ("ap", "ap", "US"),
    "scmp.com": ("scmp", "scmp", "HK"),
    "straitstimes.com": ("straits_times", "sph_media", "SG"),
    "channelnewsasia.com": ("cna", "mediacorp", "SG"),
    "asia.nikkei.com": ("nikkei_asia", "nikkei", "JP"),
}

VIETNAM_TERMS = (
    "vietnam", "vietnamese", "việt nam", "hanoi", "ha noi", "hà nội",
    "ho chi minh city", "ho chi minh", "hcmc", "saigon", "sài gòn", "sai gon",
    "da nang", "đà nẵng", "hai phong", "hải phòng", "can tho", "cần thơ",
    "nha trang", "mekong delta", "mekong delta",
)


def normalize_domain(url_or_domain: object) -> str:
    text = str(url_or_domain or "").strip()
    hostname = urlparse(text).hostname or "" if "://" in text else text
    hostname = hostname.lower().strip()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    elif hostname.startswith("m."):
        hostname = hostname[2:]
    return hostname


def canonicalize_url(url: str) -> str:
    try:
        parsed = urlparse(url.strip())
        if not parsed.hostname:
            return ""
        query = parse_qs(parsed.query, keep_blank_values=True)
        clean_query = {k: v for k, v in query.items() if k.lower() not in TRACKING_PARAMS}
        host = normalize_domain(parsed.hostname)
        return urlunparse((parsed.scheme.lower() or "https", host, parsed.path.rstrip("/"), "", urlencode(clean_query, doseq=True), ""))
    except Exception:
        return ""


def article_id_from_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def is_vietnam_relevant(title: object, description: object) -> bool:
    text = f"{title or ''} {description or ''}".lower()
    return any(term in text for term in VIETNAM_TERMS)


def _exact_ref(value: object) -> bool:
    return isinstance(value, str) and "#raw_record_id=" in value and bool(value.rsplit("=", 1)[-1])


def _timestamp_text(value: object) -> str | None:
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    return None if pd.isna(parsed) else parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def clean(raw_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for _, raw in raw_df.iterrows():
        reasons: list[str] = []
        url = str(raw.get("url") or "").strip()
        title = str(raw.get("title") or "").strip()
        canonical = canonicalize_url(url)
        if not title:
            reasons.append("missing_title")
        if not canonical:
            reasons.append("invalid_url")

        domain = normalize_domain(canonical or raw.get("publisher_domain"))
        publisher_id, group_id, country = PUBLISHERS.get(
            domain,
            (raw.get("publisher_id"), raw.get("publisher_group_id"), raw.get("publisher_country")),
        )
        source_system = str(raw.get("source_system") or "").strip()
        if source_system not in {"rss", "gdelt_doc"}:
            reasons.append("invalid_source_system")

        first_seen = _timestamp_text(raw.get("first_seen_at"))
        if first_seen is None:
            reasons.append("missing_first_seen_at")

        # GDELT seendate never becomes a publisher timestamp or confidence value.
        if source_system == "gdelt_doc":
            published_at = None
            confidence = "unavailable"
        else:
            published_at = _timestamp_text(raw.get("published_at"))
            raw_confidence = str(raw.get("timestamp_confidence") or "")
            if published_at is None:
                confidence = "unavailable"
            elif raw_confidence in {"publisher_reported", "publisher_reported_timezone_inferred"}:
                confidence = raw_confidence
            else:
                confidence = "publisher_reported"

        raw_ref = raw.get("raw_payload_ref")
        if not _exact_ref(raw_ref):
            reasons.append("non_exact_raw_payload_ref")
        mode = raw.get("collection_mode")
        if mode not in {"prospective", "historical_backfill"}:
            reasons.append("invalid_collection_mode")

        description = raw.get("description")
        rows.append(
            {
                "article_id": article_id_from_url(canonical) if canonical else None,
                "title": title or None,
                "url": url or None,
                "canonical_url": canonical or None,
                "publisher_domain": domain or None,
                "publisher_id": publisher_id,
                "publisher_group_id": group_id,
                "source_system": source_system or None,
                "first_seen_at": first_seen,
                "published_at": published_at,
                "timestamp_confidence": confidence,
                "language": raw.get("language"),
                "publisher_country": country,
                "description": description,
                "category": raw.get("category"),
                "vietnam_relevance": bool(is_vietnam_relevant(title, description)),
                "duplicate_family_id": None,
                "branch": "international",
                "collection_mode": mode,
                "raw_payload_ref": raw_ref,
                "source_seen_at": _timestamp_text(raw.get("source_seen_at")),
                "rejection_reason": ";".join(reasons) or None,
            }
        )
    return pd.DataFrame(rows, columns=AUDIT_SCHEMA)


def filter_pilot_window(df: pd.DataFrame, pilot_start: str | None) -> pd.DataFrame:
    if not pilot_start:
        return df.reset_index(drop=True)
    start = pd.Timestamp(pilot_start)
    start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
    end = start + pd.Timedelta(hours=48)
    first_seen = pd.to_datetime(df["first_seen_at"], utc=True, errors="coerce")
    mask = (
        df["collection_mode"].eq("prospective")
        & first_seen.ge(start)
        & first_seen.lt(end)
    )
    return df[mask].reset_index(drop=True)


def review_sample(audit_df: pd.DataFrame, size: int) -> pd.DataFrame:
    valid = audit_df[audit_df["rejection_reason"].isna()]
    if valid.empty:
        return valid.head(0)
    per_class = max(1, size // 2)
    parts = [valid[valid["vietnam_relevance"].eq(value)].head(per_class) for value in (True, False)]
    sample = pd.concat(parts).drop_duplicates(subset=["raw_payload_ref"])
    if len(sample) < size:
        sample = pd.concat([sample, valid]).drop_duplicates(subset=["raw_payload_ref"])
    return sample.head(size)


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean international Phase 1 candidates.")
    parser.add_argument("--collection-mode", choices=("prospective", "historical_backfill"), default="prospective")
    parser.add_argument("--input", default=None)
    parser.add_argument("--audit-output", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--sample-output", default=None)
    parser.add_argument("--sample-size", type=int, default=50)
    parser.add_argument("--pilot-start", default=None, help="Shared pilot T_start in ISO 8601 form.")
    args = parser.parse_args()

    historical = args.collection_mode == "historical_backfill"
    raw_suffix = "historical" if historical else "raw"
    clean_suffix = "historical" if historical else "clean"
    input_path = Path(args.input or f"data/raw/international/international_{raw_suffix}.parquet")
    audit_path = Path(args.audit_output or f"data/processed/international/international_{clean_suffix}_audit.parquet")
    output_path = Path(args.output or f"data/processed/international/international_{clean_suffix}.parquet")
    sample_path = Path(args.sample_output or f"team_work/phases/phase1_collection_cleaning/international_team/sample_output/sample_intl_{clean_suffix}.csv")
    if not input_path.exists():
        raise SystemExit(f"No raw candidates found at {input_path}. Run collect_intl.py first.")

    audit_df = clean(pd.read_parquet(input_path))
    for path in (audit_path, output_path, sample_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    audit_df.to_parquet(audit_path, index=False)

    relevant = audit_df[
        audit_df["rejection_reason"].isna() & audit_df["vietnam_relevance"].eq(True)
    ].sort_values("first_seen_at").drop_duplicates(subset=["canonical_url"], keep="first")
    final_df = filter_pilot_window(relevant, args.pilot_start)[SHARED_SCHEMA]
    final_df.to_parquet(output_path, index=False)
    review_sample(audit_df, max(1, min(args.sample_size, 100))).to_csv(sample_path, index=False)

    counts = audit_df["vietnam_relevance"].value_counts().to_dict()
    print(f"Audited rows : {len(audit_df):,} (True={counts.get(True, 0):,}, False={counts.get(False, 0):,})")
    print(f"Final rows   : {len(final_df):,}")
    print(f"Audit output : {audit_path}")
    print(f"Final output : {output_path}")
    print(f"Review sample: {sample_path}")


if __name__ == "__main__":
    main()

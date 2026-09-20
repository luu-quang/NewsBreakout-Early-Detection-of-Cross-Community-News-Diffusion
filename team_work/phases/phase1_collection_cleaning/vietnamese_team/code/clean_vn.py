"""Clean Vietnamese RSS candidates under the frozen Phase 1 contract."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from datetime import timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import dateutil.parser
import pandas as pd
from dateutil.tz import gettz

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

PUBLISHERS = {
    "vnexpress.net": ("vnexpress", None),
    "tuoitre.vn": ("tuoitre", None),
    "thanhnien.vn": ("thanhnien", None),
    "dantri.com.vn": ("dantri", None),
    "vietnamnet.vn": ("vietnamnet", None),
}
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "fbclid", "gclid", "gidzl", "oc",
}

# Deliberately excludes the unsafe bare substring "vn". These patterns are
# conservative signals that an article concerns Vietnam, not ground truth.
STRONG_VIETNAM_PATTERNS = [
    r"\bviệt\s*nam\b", r"\bvietnam(?:ese)?\b",
    r"\bhà\s*nội\b", r"\b(?:tp\.?\s*hcm|tphcm|hồ\s*chí\s*minh|sài\s*gòn)\b",
    r"\bđà\s*nẵng\b", r"\bhải\s*phòng\b", r"\bcần\s*thơ\b", r"\bnha\s*trang\b",
    r"\b(?:an\s*giang|bắc\s*giang|bắc\s*kạn|bạc\s*liêu|bắc\s*ninh|bến\s*tre)\b",
    r"\b(?:bình\s*định|bình\s*dương|bình\s*phước|bình\s*thuận|cà\s*mau|cao\s*bằng)\b",
    r"\b(?:đắk\s*lắk|đắk\s*nông|điện\s*biên|đồng\s*nai|đồng\s*tháp|gia\s*lai)\b",
    r"\b(?:hà\s*giang|hà\s*nam|hà\s*tĩnh|hải\s*dương|hậu\s*giang|hòa\s*bình|hưng\s*yên)\b",
    r"\b(?:khánh\s*hòa|kiên\s*giang|kon\s*tum|lai\s*châu|lâm\s*đồng|lạng\s*sơn|lào\s*cai)\b",
    r"\b(?:long\s*an|nam\s*định|nghệ\s*an|ninh\s*bình|ninh\s*thuận|phú\s*thọ|phú\s*yên)\b",
    r"\b(?:quảng\s*bình|quảng\s*nam|quảng\s*ngãi|quảng\s*ninh|quảng\s*trị)\b",
    r"\b(?:sóc\s*trăng|sơn\s*la|tây\s*ninh|thái\s*bình|thái\s*nguyên|thanh\s*hóa)\b",
    r"\b(?:thừa\s*thiên\s*huế|huế|tiền\s*giang|trà\s*vinh|tuyên\s*quang)\b",
    r"\b(?:vĩnh\s*long|vĩnh\s*phúc|yên\s*bái)\b",
    r"\b(?:ubnd|hđnd)\b", r"\bquốc\s*hội\s*việt\s*nam\b",
    r"\b(?:tuyển|u23)\s*việt\s*nam\b", r"\bv[.-]?league\b",
]
STRONG_VIETNAM_RE = re.compile("|".join(STRONG_VIETNAM_PATTERNS), re.IGNORECASE)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def clean_text(value: object) -> str:
    if value is None:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(str(value))
        parser.close()
        return " ".join(parser.parts)
    except Exception:
        return html.unescape(re.sub(r"<[^>]+>", " ", str(value))).strip()


def canonicalize_url(url: str) -> str:
    try:
        parsed = urlparse(url.strip())
        if not parsed.hostname:
            return ""
        query = parse_qs(parsed.query, keep_blank_values=True)
        clean_query = {k: v for k, v in query.items() if k.lower() not in TRACKING_PARAMS}
        host = parsed.hostname.lower()
        if host.startswith("www."):
            host = host[4:]
        elif host.startswith("m."):
            host = host[2:]
        return urlunparse((parsed.scheme.lower() or "https", host, parsed.path.rstrip("/"), "", urlencode(clean_query, doseq=True), ""))
    except Exception:
        return ""


def article_id(canonical_url: str) -> str:
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:16]


def parse_publisher_time(value: object) -> tuple[str | None, str]:
    if value is None or not str(value).strip():
        return None, "unavailable"
    try:
        parsed = dateutil.parser.parse(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=gettz("Asia/Ho_Chi_Minh"))
            confidence = "publisher_reported_timezone_inferred"
        else:
            confidence = "publisher_reported"
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), confidence
    except (TypeError, ValueError, OverflowError):
        return None, "unavailable"


def is_vietnam_relevant(title: str, description: str) -> bool:
    return bool(STRONG_VIETNAM_RE.search(f"{title} {description}"))


def _publisher_metadata(canonical_url: str, hint: object) -> tuple[str, str | None, str | None]:
    domain = (urlparse(canonical_url).hostname or "").lower()
    publisher_id, group_id = PUBLISHERS.get(domain, (str(hint).strip() or None, None))
    return domain, publisher_id, group_id


def _exact_ref(value: object) -> bool:
    return isinstance(value, str) and "#raw_record_id=" in value and bool(value.rsplit("=", 1)[-1])


def clean(raw_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for _, raw in raw_df.iterrows():
        reasons: list[str] = []
        try:
            entry = json.loads(raw.get("entry_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            entry = {}
            reasons.append("invalid_entry_json")

        url = str(raw.get("url") or entry.get("link") or "").strip()
        canonical = canonicalize_url(url)
        title = clean_text(entry.get("title"))
        description = clean_text(entry.get("summary") or entry.get("description"))
        if not title:
            reasons.append("missing_title")
        if not canonical:
            reasons.append("invalid_url")
        raw_ref = raw.get("raw_payload_ref")
        if not _exact_ref(raw_ref):
            reasons.append("non_exact_raw_payload_ref")

        first_seen = pd.to_datetime(raw.get("first_seen_at"), utc=True, errors="coerce")
        if pd.isna(first_seen):
            reasons.append("missing_first_seen_at")
            first_seen_text = None
        else:
            first_seen_text = first_seen.strftime("%Y-%m-%dT%H:%M:%SZ")

        published_at, confidence = parse_publisher_time(
            entry.get("published") or entry.get("pubDate") or entry.get("updated")
        )
        domain, publisher_id, group_id = _publisher_metadata(canonical, raw.get("publisher_id_hint"))
        relevant = is_vietnam_relevant(title, description) if title else False
        mode = raw.get("collection_mode")
        if mode not in {"prospective", "historical_backfill"}:
            reasons.append("invalid_collection_mode")

        rows.append(
            {
                "article_id": article_id(canonical) if canonical else None,
                "title": title or None,
                "url": url or None,
                "canonical_url": canonical or None,
                "publisher_domain": domain or None,
                "publisher_id": publisher_id,
                "publisher_group_id": group_id,
                "source_system": "rss",
                "first_seen_at": first_seen_text,
                "published_at": published_at,
                "timestamp_confidence": confidence,
                "language": "vi",
                "publisher_country": "VN",
                "description": description or None,
                "category": clean_text(entry.get("category")) or None,
                "vietnam_relevance": bool(relevant),
                "duplicate_family_id": None,
                "branch": "domestic",
                "collection_mode": mode,
                "raw_payload_ref": raw_ref,
                "source_seen_at": None,
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
    parser = argparse.ArgumentParser(description="Clean Vietnamese Phase 1 candidates.")
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
    input_path = Path(args.input or f"data/raw/vietnamese/vietnamese_{raw_suffix}.parquet")
    audit_path = Path(args.audit_output or f"data/processed/vietnamese/vietnamese_{clean_suffix}_audit.parquet")
    output_path = Path(args.output or f"data/processed/vietnamese/vietnamese_{clean_suffix}.parquet")
    sample_path = Path(args.sample_output or f"team_work/phases/phase1_collection_cleaning/vietnamese_team/sample_output/sample_vn_{clean_suffix}.csv")
    if not input_path.exists():
        raise SystemExit(f"No raw candidates found at {input_path}. Run collect_vn.py first.")

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

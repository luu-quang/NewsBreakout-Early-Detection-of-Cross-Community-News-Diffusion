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
AUDIT_SAMPLE_RANDOM_SEED = 20260920

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

# Deliberately excludes the unsafe bare substring "vn". Explicit national and
# institutional signals can establish relevance on their own.
NATIONAL_CONTEXT_PATTERNS = [
    r"\bviệt\s*nam\b", r"\bvietnam(?:ese)?\b",
    r"\b(?:ubnd|hđnd)\b", r"\bquốc\s*hội\s*việt\s*nam\b",
    r"\b(?:tuyển|u23)\s*việt\s*nam\b", r"\bv[.-]?league\b",
    r"\b(?:kỳ\s*)?thi\s+tốt\s+nghiệp\s+thpt\b",
]
NATIONAL_CONTEXT_RE = re.compile("|".join(NATIONAL_CONTEXT_PATTERNS), re.IGNORECASE)
TIMEZONE_ONLY_RE = re.compile(
    r"\b(?:theo\s+)?(?:múi\s+)?giờ\s+việt\s+nam\b",
    re.IGNORECASE,
)
MINISTRY_PATTERN = (
    r"\bbộ\s+(?:y\s+tế|giáo\s*dục(?:\s+và\s+đào\s+tạo)?|gd(?:&|-)?đt|công\s+an|"
    r"tài\s+chính|xây\s+dựng|nội\s+vụ|ngoại\s+giao|công\s+thương|tư\s+pháp|quốc\s+phòng|"
    r"khoa\s+học\s+và\s+công\s+nghệ|nông\s+nghiệp\s+và\s+môi\s+trường|"
    r"văn\s+hóa,?\s*thể\s+thao\s+và\s+du\s+lịch)\b"
)
MINISTRY_RE = re.compile(MINISTRY_PATTERN, re.IGNORECASE)
FOREIGN_MINISTRY_RE = re.compile(
    MINISTRY_PATTERN
    + r"\s+(?:của\s+)?(?:nhật\s+bản|mỹ|hoa\s+kỳ|trung\s+quốc|hàn\s+quốc|triều\s+tiên|nga|"
    r"ukraine|israel|palestine|gaza|pháp|đức|anh|thái\s+lan|indonesia|philippines|"
    r"singapore|campuchia|lào)\b",
    re.IGNORECASE,
)
VIETNAM_SPECIFIC_PUBLIC_BODY_RE = re.compile(
    r"\b(?:cục\s+)?csgt\b|\bcảnh\s+sát\s+giao\s+thông\b|\b(?:tand|vksnd)\b|"
    r"\b(?:ubnd|hđnd)\b",
    re.IGNORECASE,
)
GENERIC_NATIONAL_OFFICE_RE = re.compile(
    r"\b(?:chính\s+phủ|tổng\s+bí\s+thư|chủ\s+tịch\s+nước|"
    r"phó\s+thủ\s+tướng|thủ\s+tướng|bộ\s+trưởng)\b",
    re.IGNORECASE,
)
FOREIGN_OFFICIAL_RE = re.compile(
    r"\b(?:chính\s+phủ|tổng\s+bí\s+thư|chủ\s+tịch\s+nước|"
    r"phó\s+thủ\s+tướng|thủ\s+tướng|bộ\s+trưởng)\s+(?:của\s+)?"
    r"(?:nhật\s+bản|mỹ|hoa\s+kỳ|trung\s+quốc|hàn\s+quốc|triều\s+tiên|nga|"
    r"ukraine|israel|palestine|gaza|pháp|đức|anh|thái\s+lan|indonesia|"
    r"philippines|singapore|campuchia|lào)\b",
    re.IGNORECASE,
)
DOMESTIC_EDUCATION_RE = re.compile(
    r"\b(?:kỳ\s+thi\s+vào\s+(?:lớp\s*10|cấp\s*3)|xét\s+tuyển\s+(?:đại\s+học|cao\s+đẳng)|"
    r"điểm\s+cộng\s+ielts|sách\s+giáo\s+khoa|cơ\s+sở\s+giáo\s+dục\s+phổ\s+thông|"
    r"tuyển\s+sinh\s+(?:đại\s+học|cao\s+đẳng))\b",
    re.IGNORECASE,
)
HOSPITAL_RE = re.compile(r"\bbệnh\s+viện\b", re.IGNORECASE)
UNIVERSITY_RE = re.compile(r"\b(?:trường\s+)?(?:đại\s+học|đh)\b", re.IGNORECASE)
DOMESTIC_GEOGRAPHY_RE = re.compile(r"\bnước\s+ta\b", re.IGNORECASE)
HOUSEHOLD_BUSINESS_RE = re.compile(r"\bhộ\s+kinh\s+doanh\b", re.IGNORECASE)
TAX_POLICY_RE = re.compile(
    r"\b(?:thuế|doanh\s+thu|lợi\s+nhuận|kỳ\s+tính\s+thuế)\b",
    re.IGNORECASE,
)

# Localities are strong domestic signals except in recognized advice/profile
# contexts below. "Vinh" is handled separately because it is also a person name.
LOCALITY_PATTERNS = [
    r"\bhà\s*nội\b", r"\b(?:tp\.?\s*hcm|tphcm|hồ\s*chí\s*minh|sài\s*gòn)\b",
    r"\bđà\s*nẵng\b", r"\bhải\s*phòng\b", r"\bcần\s*thơ\b", r"\bnha\s*trang\b", r"\bmũi\s*né\b",
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
]
LOCALITY_RE = re.compile("|".join(LOCALITY_PATTERNS), re.IGNORECASE)

# "Vinh" is also a common personal name, so it requires event/institutional
# context instead of acting as an unconditional location signal.
AMBIGUOUS_LOCALITY_RE = re.compile(r"\b(?:tp\.?\s*)?vinh\b", re.IGNORECASE)
LOCAL_NEWS_CONTEXT_RE = re.compile(
    r"\b(?:công\s+an|tòa\s+án|viện\s+kiểm\s+sát|sở\s+[a-zà-ỹ]+|cục\s+[a-zà-ỹ]+|"
    r"chính\s+quyền|trung\s+tâm\s+hành\s+chính|trường(?:\s+đại\s+học)?|bệnh\s+viện|"
    r"khởi\s+tố|bắt(?:\s+tạm\s+giam)?|truy\s+nã|điều\s+tra|xét\s+xử|tử\s+vong|thiệt\s+mạng|"
    r"tai\s+nạn|cháy|ngập|mưa|lũ|sạt\s+lở|cướp|trộm|tấn\s+công|"
    r"dự\s+án|quy\s+hoạch|cao\s+tốc|giao\s+thông|dân\s+số|thu\s+phí|xổ\s+số)\b",
    re.IGNORECASE,
)
PERSONAL_CONTEXT_RE = re.compile(
    r"\b(?:tìm\s+bạn\s+đời|tìm\s+người\s+yêu|hẹn\s+hò|kết\s+bạn|làm\s+quen|"
    r"hiếm\s+muộn|điều\s+trị\s+thế\s+nào\s+để\s+có\s+con|tư\s+vấn\s+tình\s+cảm)\b",
    re.IGNORECASE,
)
NON_NEWS_PERSONAL_ADVICE_RE = re.compile(
    r"^(?:\d+\s+)?(?:cách|mẹo|thói\s+quen|dưỡng\s+chất|nguyên\s+nhân\s+khiến)\b|"
    r"^điều\s+gì\s+xảy\s+ra\s+khi\s+bạn\b|^kiểm\s+tra\s+triệu\s+chứng\b|"
    r"\b(?:tôi|con\s+gái\s+tôi|chồng\s+tôi|vợ\s+tôi).{0,100}(?:được\s+không|nên\s+làm\s+gì)\b|"
    r"\b(?:dùng\s+thế\s+nào|nên\s+bổ\s+sung)\b",
    re.IGNORECASE,
)

# The domestic feed is already source-scoped to established Vietnamese
# publishers. These patterns therefore identify exceptions to that prior,
# rather than trying to prove Vietnam relevance from a growing keyword list.
DOMESTIC_NEWS_CONTEXT_RE = re.compile(
    r"\b(?:biển\s+đông|vịnh\s+bắc\s+bộ|miền\s+(?:bắc|trung|nam)|nam\s+bộ|trung\s+bộ|"
    r"thủ\s+đô|quốc\s+khánh|vietlott|người\s+việt|hàng\s+không\s+việt|"
    r"công\s+an|cảnh\s+sát|khởi\s+tố|bắt\s+(?:giữ|tạm\s+giam)|truy\s+nã|"
    r"viện\s+kiểm\s+sát|tòa\s+án|lĩnh\s+án|phạt\s+(?:tiền|nguội)|"
    r"luật\s+(?:sư|đất\s+đai|giao\s+thông)|nghị\s+định|quy\s+định|"
    r"cán\s+bộ|liệt\s+sĩ|hải\s+quân|"
    r"bão\s+số|dự\s+báo\s+thời\s+tiết|không\s+khí\s+lạnh|mưa\s+lũ|ngập\s+lụt|"
    r"cao\s+tốc|quốc\s+lộ|đại\s+lộ|sân\s+bay|metro|dự\s+án|"
    r"tỷ\s+đồng|triệu\s+đồng|đồng\/lít)\b",
    re.IGNORECASE,
)
FOREIGN_NEWS_PATH_RE = re.compile(r"/(?:the-gioi|world|quoc-te)(?:/|$)", re.IGNORECASE)
FOREIGN_PLACE_OR_BODY_RE = re.compile(
    r"\b(?:nato|liên\s+hợp\s+quốc|hoa\s+kỳ|nước\s+mỹ|trung\s+quốc|nhật\s+bản|"
    r"hàn\s+quốc|triều\s+tiên|nga|ukraine|israel|palestine|gaza|iran|houthi|"
    r"a\s*rập\s*xê\s*út|riyadh|anh|pháp|đức|italy|tây\s+ban\s+nha|"
    r"greenland|london|siberia|dubai|santorini)\b",
    re.IGNORECASE,
)
FOREIGN_SPORT_RE = re.compile(
    r"\b(?:arsenal|real\s+madrid|atletico|brighton|premier\s+league|la\s+liga|"
    r"champions\s+league|nba|u\.?23\s+(?:thái\s+lan|hong\s+kong|nhật\s+bản)|"
    r"asiad)\b",
    re.IGNORECASE,
)
FOREIGN_CORPORATE_RE = re.compile(
    r"\b(?:apple|iphone|fed|goldman\s+sachs)\b",
    re.IGNORECASE,
)
SPACE_ONLY_RE = re.compile(
    r"\b(?:mặt\s+trăng|sao\s+hỏa|nasa|không\s+gian\s+vũ\s+trụ|thiên\s+văn)\b",
    re.IGNORECASE,
)


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


def is_vietnam_relevant(title: str, description: str, url: str = "") -> bool:
    combined = f"{title} {description}"
    semantic_text = TIMEZONE_ONLY_RE.sub("", combined)

    # Strong domestic context wins even when the article also names another
    # country (for example a Vietnamese official's foreign visit or a
    # cross-border case investigated by Vietnamese authorities).
    if NATIONAL_CONTEXT_RE.search(semantic_text):
        return True
    if MINISTRY_RE.search(semantic_text) and not FOREIGN_MINISTRY_RE.search(semantic_text):
        return True
    if VIETNAM_SPECIFIC_PUBLIC_BODY_RE.search(semantic_text):
        return True
    if GENERIC_NATIONAL_OFFICE_RE.search(semantic_text) and not FOREIGN_OFFICIAL_RE.search(semantic_text):
        return True
    if DOMESTIC_EDUCATION_RE.search(semantic_text) and not FOREIGN_OFFICIAL_RE.search(semantic_text):
        return True
    if HOSPITAL_RE.search(semantic_text) and UNIVERSITY_RE.search(semantic_text):
        return True
    if DOMESTIC_GEOGRAPHY_RE.search(semantic_text):
        return True
    if HOUSEHOLD_BUSINESS_RE.search(semantic_text) and TAX_POLICY_RE.search(semantic_text):
        return True

    # Advice/profile material can mention a Vietnamese hometown incidentally;
    # that mention is not sufficient for news relevance.
    if PERSONAL_CONTEXT_RE.search(title) or NON_NEWS_PERSONAL_ADVICE_RE.search(title):
        return False
    if DOMESTIC_NEWS_CONTEXT_RE.search(semantic_text):
        return True
    if LOCALITY_RE.search(semantic_text):
        return True
    if AMBIGUOUS_LOCALITY_RE.search(semantic_text) and LOCAL_NEWS_CONTEXT_RE.search(semantic_text):
        return True

    # Reject only clear foreign-only subjects. A country name alone is not
    # enough because domestic reporting often covers cross-border events.
    if FOREIGN_NEWS_PATH_RE.search(url):
        return False
    if FOREIGN_SPORT_RE.search(semantic_text):
        return False
    if SPACE_ONLY_RE.search(semantic_text):
        return False
    if FOREIGN_CORPORATE_RE.search(semantic_text):
        return False
    if FOREIGN_PLACE_OR_BODY_RE.search(semantic_text) and re.search(
        r"\b(?:chính\s+phủ|quốc\s+hội|tổng\s+thống|thủ\s+tướng|quân\s+đội|"
        r"chiến\s+sự|xung\s+đột|tên\s+lửa|tập\s+kích|trừng\s+phạt|bầu\s+cử|"
        r"lãi\s+suất|du\s+lịch|đặc\s+sản)\b",
        semantic_text,
        re.IGNORECASE,
    ):
        return False

    return True


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
        relevant = is_vietnam_relevant(title, description, canonical) if title else False
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
    parts = []
    for offset, value in enumerate((True, False)):
        class_rows = valid[valid["vietnam_relevance"].eq(value)].sort_values("raw_payload_ref")
        parts.append(
            class_rows.sample(
                n=min(per_class, len(class_rows)),
                random_state=AUDIT_SAMPLE_RANDOM_SEED + offset,
            )
        )
    sample = pd.concat(parts).drop_duplicates(subset=["raw_payload_ref"])
    if len(sample) < size:
        remaining = valid[~valid["raw_payload_ref"].isin(sample["raw_payload_ref"])].sort_values("raw_payload_ref")
        fill_count = min(size - len(sample), len(remaining))
        sample = pd.concat(
            [
                sample,
                remaining.sample(
                    n=fill_count,
                    random_state=AUDIT_SAMPLE_RANDOM_SEED + 2,
                ),
            ]
        )
    return sample.sample(frac=1, random_state=AUDIT_SAMPLE_RANDOM_SEED + 3).head(size).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean Vietnamese Phase 1 candidates.")
    parser.add_argument("--collection-mode", choices=("prospective", "historical_backfill"), default="prospective")
    parser.add_argument("--input", default=None)
    parser.add_argument("--audit-output", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--audit-sample-output", "--sample-output", dest="audit_sample_output", default=None)
    parser.add_argument("--relevant-sample-output", default=None)
    parser.add_argument("--sample-size", type=int, default=50)
    parser.add_argument("--pilot-start", default=None, help="Shared pilot T_start in ISO 8601 form.")
    args = parser.parse_args()

    historical = args.collection_mode == "historical_backfill"
    raw_suffix = "historical" if historical else "raw"
    clean_suffix = "historical" if historical else "clean"
    input_path = Path(args.input or f"data/raw/vietnamese/vietnamese_{raw_suffix}.parquet")
    audit_path = Path(args.audit_output or f"data/processed/vietnamese/vietnamese_{clean_suffix}_audit.parquet")
    output_path = Path(args.output or f"data/processed/vietnamese/vietnamese_{clean_suffix}.parquet")
    sample_prefix = "sample_vn_historical" if historical else "sample_vn"
    audit_sample_path = Path(args.audit_sample_output or f"team_work/phases/phase1_collection_cleaning/vietnamese_team/sample_output/{sample_prefix}_audit.csv")
    relevant_sample_path = Path(args.relevant_sample_output or f"team_work/phases/phase1_collection_cleaning/vietnamese_team/sample_output/{sample_prefix}_relevant.csv")
    if not input_path.exists():
        raise SystemExit(f"No raw candidates found at {input_path}. Run collect_vn.py first.")

    audit_df = clean(pd.read_parquet(input_path))
    for path in (audit_path, output_path, audit_sample_path, relevant_sample_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    audit_df.to_parquet(audit_path, index=False)

    relevant = audit_df[
        audit_df["rejection_reason"].isna() & audit_df["vietnam_relevance"].eq(True)
    ].sort_values("first_seen_at").drop_duplicates(subset=["canonical_url"], keep="first")
    final_df = filter_pilot_window(relevant, args.pilot_start)[SHARED_SCHEMA]
    final_df.to_parquet(output_path, index=False)
    sample_size = max(1, min(args.sample_size, 100))
    review_sample(audit_df, sample_size).to_csv(audit_sample_path, index=False)
    final_df[SHARED_SCHEMA].head(sample_size).to_csv(relevant_sample_path, index=False)

    counts = audit_df["vietnam_relevance"].value_counts().to_dict()
    print(f"Audited rows : {len(audit_df):,} (True={counts.get(True, 0):,}, False={counts.get(False, 0):,})")
    print(f"Final rows   : {len(final_df):,}")
    print(f"Audit output : {audit_path}")
    print(f"Final output : {output_path}")
    print(f"Audit sample : {audit_sample_path}")
    print(f"Relevant sample: {relevant_sample_path}")


if __name__ == "__main__":
    main()

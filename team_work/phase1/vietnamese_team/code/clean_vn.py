import hashlib
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from datetime import datetime, timezone
import dateutil.parser
from bs4 import BeautifulSoup

def clean_canonical_url(url: str) -> str:
    """Loại bỏ tracking parameters và chuẩn hóa domain."""
    try:
        parsed = urlparse(url)
        # Bỏ query param rác
        query = parse_qs(parsed.query)
        clean_query = {k: v for k, v in query.items() if not k.startswith("utm_") 
                       and k not in ("fbclid", "gidzl", "ref", "source", "token")}
        
        # Hạ chữ thường và bỏ 'www.' hoặc 'm.'
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        elif netloc.startswith("m."):
            netloc = netloc[2:]
            
        path = parsed.path.rstrip('/')
        
        # Tạo lại URL
        canonical = urlunparse((
            parsed.scheme.lower() or "https",
            netloc,
            path,
            parsed.params,
            urlencode(clean_query, doseq=True),
            "" # Bỏ fragment (#)
        ))
        return canonical
    except Exception:
        return url

def get_article_id(canonical_url: str) -> str:
    """Tạo article_id bằng SHA-256 từ canonical url."""
    return hashlib.sha256(canonical_url.encode('utf-8')).hexdigest()[:16]

def parse_time(date_str: str, default_time: str) -> tuple[str, str]:
    """Parse thời gian pubDate, trả về (iso_time, confidence)."""
    if not date_str:
        return default_time, "low"
    try:
        dt = dateutil.parser.parse(date_str)
        # Chuyển về UTC
        if dt.tzinfo is None:
            # Assume it's local ICT (UTC+7) if no timezone info in Vietnam news
            from dateutil.tz import gettz
            tz = gettz('Asia/Ho_Chi_Minh')
            if tz:
                dt = dt.replace(tzinfo=tz)
        
        dt_utc = dt.astimezone(timezone.utc)
        return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), "high"
    except Exception:
        return default_time, "low"

def clean_html_text(html_content: str) -> str:
    """Dùng BeautifulSoup loại bỏ thẻ HTML, trả về text thuần."""
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    return text if len(text.split()) >= 5 else text

def get_publisher_info(domain: str) -> tuple[str, str, str]:
    """Phân loại publisher_id và group_id dựa trên domain."""
    if "vnexpress.net" in domain:
        return domain, "vnexpress", "fpt_telecom"
    elif "tuoitre.vn" in domain:
        return domain, "tuoitre", "doan_tntp"
    elif "thanhnien.vn" in domain:
        return domain, "thanhnien", "thanh_nien_group"
    elif "dantri.com.vn" in domain:
        return domain, "dantri", "bo_ld_tb_xh"
    elif "vietnamnet.vn" in domain:
        return domain, "vietnamnet", "bo_tt_tt"
    return domain, domain.replace(".vn", "").replace(".com", ""), "unknown"

def process_raw_entry(entry: dict, observed_at_utc: str, raw_ref: str) -> dict:
    """Chuẩn hóa một bản ghi thô thành Shared Schema 20 cột."""
    url = entry.get("link", "").strip()
    canonical = clean_canonical_url(url)
    
    parsed_domain = urlparse(canonical).netloc
    pub_domain, pub_id, group_id = get_publisher_info(parsed_domain)
    
    pub_time, conf = parse_time(entry.get("published") or entry.get("pubDate"), observed_at_utc)
    
    # 20 Trường theo đúng đặc tả
    return {
        "article_id": get_article_id(canonical),
        "title": clean_html_text(entry.get("title", "")),
        "url": url,
        "canonical_url": canonical,
        "publisher_domain": pub_domain,
        "publisher_id": pub_id,
        "publisher_group_id": group_id,
        "source_system": "domestic_rss",
        "first_seen_at": observed_at_utc,
        "published_at": pub_time,
        "timestamp_confidence": conf,
        "language": "vi",
        "publisher_country": "VN",
        "description": clean_html_text(entry.get("summary", "") or entry.get("description", "")),
        "category": clean_html_text(entry.get("category", "")),
        "vietnam_relevance": True,
        "duplicate_family_id": None,
        "branch": "domestic",
        "collection_mode": "prospective",
        "raw_payload_ref": raw_ref
    }

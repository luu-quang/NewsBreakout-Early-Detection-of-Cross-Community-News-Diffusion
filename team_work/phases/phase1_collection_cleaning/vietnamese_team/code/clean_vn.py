import os
import json
import hashlib
import argparse
import pandas as pd
import dateutil.parser
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from bs4 import BeautifulSoup

# Registry for publishers
PUBLISHER_REGISTRY = {
    "vnexpress.net": "vnexpress",
    "tuoitre.vn": "tuoitre",
    "thanhnien.vn": "thanhnien",
    "dantri.com.vn": "dantri",
    "vietnamnet.vn": "vietnamnet",
}

# Heuristic constants for vietnam_relevance
VN_ENTITIES = [
    "việt nam", "vietnam", "vn", "nội địa", "trong nước",
    "hà nội", "tp.hcm", "tp hcm", "tphcm", "hồ chí minh", "sài gòn", "đà nẵng", "hải phòng", "cần thơ", "nha trang",
    "chính phủ", "thủ tướng", "quốc hội", "bộ công an", "bộ y tế", "bộ gd-đt", "bộ giáo dục",
    "bộ ngoại giao", "bộ gtvt", "bộ giao thông", "bộ xây dựng", "bộ tài chính", "ubnd", "hđnd",
    "v-league", "v.league", "tuyển việt nam", "u23 việt nam", "đtqg",
    "an giang", "bà rịa - vũng tàu", "bắc giang", "bắc kạn", "bạc liêu", "bắc ninh", "bến tre", 
    "bình định", "bình dương", "bình phước", "bình thuận", "cà mau", "cao bằng", "đắk lắk", 
    "đắk nông", "điện biên", "đồng nai", "đồng tháp", "gia lai", "hà giang", "hà nam", 
    "hà tĩnh", "hải dương", "hậu giang", "hòa bình", "hưng yên", "khánh hòa", "kiên giang", 
    "kon tum", "lai châu", "lâm đồng", "lạng sơn", "lào cai", "long an", "nam định", 
    "nghệ an", "ninh bình", "ninh thuận", "phú thọ", "phú yên", "quảng bình", "quảng nam", 
    "quảng ngãi", "quảng ninh", "quảng trị", "sóc trăng", "sơn la", "tây ninh", "thái bình", 
    "thái nguyên", "thanh hóa", "thừa thiên huế", "tiền giang", "trà vinh", "tuyên quang", 
    "vĩnh long", "vĩnh phúc", "yên bái"
]

NEGATIVE_URL_PATHS = ["/the-gioi/", "/world/", "/quoc-te/", "/suc-khoe/", "/y-te/", "/xe/"]

def clean_canonical_url(url: str) -> str:
    """Loại bỏ tracking parameters và chuẩn hóa domain."""
    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        # Conservative stripping: only remove explicit tracking
        clean_query = {k: v for k, v in query.items() if not k.startswith("utm_") 
                       and k not in ("fbclid", "gidzl")}
        
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        elif netloc.startswith("m."):
            netloc = netloc[2:]
            
        path = parsed.path.rstrip('/')
        
        canonical = urlunparse((
            parsed.scheme.lower() or "https",
            netloc,
            path,
            parsed.params,
            urlencode(clean_query, doseq=True),
            "" 
        ))
        return canonical
    except Exception:
        return url

def get_article_id(canonical_url: str) -> str:
    return hashlib.sha256(canonical_url.encode('utf-8')).hexdigest()[:16]

def parse_time(date_str: str) -> tuple[str | None, str | None]:
    if not date_str:
        return None, None
    try:
        dt = dateutil.parser.parse(date_str)
        
        has_explicit_tz = (dt.tzinfo is not None)
        
        if not has_explicit_tz:
            # Assume local ICT
            from dateutil.tz import gettz
            tz = gettz('Asia/Ho_Chi_Minh')
            if tz:
                dt = dt.replace(tzinfo=tz)
                
        dt_utc = dt.astimezone(timezone.utc)
        iso_str = dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        return iso_str, "high" if has_explicit_tz else "medium"
    except Exception:
        return None, None

def clean_html_text(html_content: str) -> str:
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    return text if len(text.split()) >= 5 else text

def get_publisher_info(domain: str) -> tuple[str, str, None]:
    for base_domain, pub_id in PUBLISHER_REGISTRY.items():
        if base_domain in domain:
            return domain, pub_id, None
    fallback_id = domain.split(".")[0]
    return domain, fallback_id, None

def check_vietnam_relevance(title: str, description: str, url: str) -> bool:
    text_to_check = f"{title} {description}".lower()
    url_lower = url.lower()
    
    # Negative paths penalty
    has_negative_path = any(neg in url_lower for neg in NEGATIVE_URL_PATHS)
    
    # Check positive entities
    has_vn_entity = any(entity in text_to_check for entity in VN_ENTITIES)
    
    if has_negative_path:
        # If it's a generic or foreign path, MUST have a VN entity in title/desc to be relevant
        return has_vn_entity
    
    # Otherwise, if it has a VN entity, definitely True
    if has_vn_entity:
        return True
        
    # If no VN entity found but path is not negative, it might be generic. 
    # For Phase 1, we strictly return True ONLY if there's a positive entity to avoid False Positives
    # on generic articles like omega-3, thyroid, Polish F-16 etc.
    return False

def process_raw_entry(entry: dict, observed_at_utc: str, raw_ref: str) -> dict:
    url = entry.get("link", "").strip()
    canonical = clean_canonical_url(url)
    
    parsed_domain = urlparse(canonical).netloc
    pub_domain, pub_id, group_id = get_publisher_info(parsed_domain)
    
    pub_time, conf = parse_time(entry.get("published") or entry.get("pubDate"))
    
    title = clean_html_text(entry.get("title", ""))
    description = clean_html_text(entry.get("summary", "") or entry.get("description", ""))
    
    is_vn = check_vietnam_relevance(title, description, url)
    
    return {
        "article_id": get_article_id(canonical),
        "title": title,
        "url": url,
        "canonical_url": canonical,
        "publisher_domain": pub_domain,
        "publisher_id": pub_id,
        "publisher_group_id": group_id,
        "source_system": "rss",
        "first_seen_at": observed_at_utc,
        "published_at": pub_time,
        "timestamp_confidence": conf,
        "language": "vi",
        "publisher_country": "VN",
        "description": description,
        "category": clean_html_text(entry.get("category", "")),
        "vietnam_relevance": is_vn,
        "duplicate_family_id": None,
        "branch": "domestic",
        "collection_mode": "prospective",
        "raw_payload_ref": raw_ref
    }

def main():
    parser = argparse.ArgumentParser(description="Clean raw Vietnamese news RSS payloads.")
    parser.add_argument("--input", default="team_work/phases/phase1_collection_cleaning/vietnamese_team/sample_output/sample_vn_raw.json", help="Path to raw JSON input file.")
    parser.add_argument("--output-dir", default="team_work/phases/phase1_collection_cleaning/vietnamese_team/sample_output/", help="Directory to save cleaned JSONL and Parquet.")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}")
        return

    os.makedirs(args.output_dir, exist_ok=True)
    
    with open(args.input, 'r', encoding='utf-8') as f:
        raw_payloads = json.load(f)
        
    cleaned_entries = []
    raw_filename = os.path.basename(args.input)
    
    for payload in raw_payloads:
        # Payload format: {"feed": ..., "publisher": ..., "observed_at_utc": ..., "entry": {...}}
        entry = payload.get("entry", {})
        observed_at = payload.get("observed_at_utc", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        
        cleaned = process_raw_entry(entry, observed_at, raw_filename)
        cleaned_entries.append(cleaned)
        
    # Output paths
    cleaned_jsonl_path = os.path.join(args.output_dir, "sample_vn_cleaned.jsonl")
    cleaned_parquet_path = os.path.join(args.output_dir, "sample_vn_cleaned.parquet")
    
    # Save Cleaned JSONL
    with open(cleaned_jsonl_path, 'w', encoding='utf-8') as f:
        for entry in cleaned_entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            
    # Save Cleaned Parquet
    df = pd.DataFrame(cleaned_entries)
    if not df.empty:
        df["vietnam_relevance"] = df["vietnam_relevance"].astype(bool)
        df.to_parquet(cleaned_parquet_path, index=False)
        
    print(f"Done! Cleaned {len(cleaned_entries)} articles.")
    print(f"   -> JSONL: {cleaned_jsonl_path}")
    print(f"   -> Parquet: {cleaned_parquet_path}")

if __name__ == "__main__":
    main()

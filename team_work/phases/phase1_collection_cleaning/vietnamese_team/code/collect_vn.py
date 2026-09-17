import os
import json
import feedparser
from datetime import datetime, timezone
import pandas as pd
from clean_vn import process_raw_entry

RSS_FEEDS = {
    "vnexpress": "https://vnexpress.net/rss/tin-moi-nhat.rss",
    "tuoitre": "https://tuoitre.vn/rss/tin-moi-nhat.rss",
    "thanhnien": "https://thanhnien.vn/rss/home.rss",
    "dantri": "https://dantri.com.vn/rss/home.rss",
    "vietnamnet": "https://vietnamnet.vn/rss/thoi-su.rss"
}

USER_AGENT = "NewsBreakout/1.0 (+https://github.com/luu-quang/NewsBreakout)"

def main():
    observed_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    raw_payloads = []
    cleaned_entries = []
    
    # Ensure output dir exists
    output_dir = os.path.join(os.path.dirname(__file__), "..", "sample_output")
    os.makedirs(output_dir, exist_ok=True)
    
    # Snapshot reference
    raw_ref = f"sample_vn_raw_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.json"
    
    for pub_id, url in RSS_FEEDS.items():
        print(f"Fetching {pub_id} from {url}...")
        try:
            # Set User-Agent
            d = feedparser.parse(url, agent=USER_AGENT)
            if d.bozo and not d.entries:
                print(f"  -> Failed to parse feed: {d.bozo_exception}")
                continue
                
            entries = d.entries[:20]  # Take top 20 per feed for sample
            print(f"  -> Found {len(entries)} entries.")
            
            for entry in entries:
                # Store raw
                raw_payloads.append({
                    "feed": url,
                    "publisher": pub_id,
                    "entry": dict(entry)
                })
                
                # Clean and process
                cleaned = process_raw_entry(dict(entry), observed_at_utc, raw_ref)
                cleaned_entries.append(cleaned)
                
        except Exception as e:
            print(f"  -> Error: {e}")

    # Output paths
    raw_path = os.path.join(output_dir, raw_ref)
    cleaned_jsonl_path = os.path.join(output_dir, "sample_vn_cleaned.jsonl")
    cleaned_parquet_path = os.path.join(output_dir, "sample_vn_cleaned.parquet")
    
    # Save Raw
    with open(raw_path, 'w', encoding='utf-8') as f:
        json.dump(raw_payloads, f, ensure_ascii=False, indent=2, default=str)
        
    # Save Cleaned JSONL
    with open(cleaned_jsonl_path, 'w', encoding='utf-8') as f:
        for entry in cleaned_entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            
    # Save Cleaned Parquet using Pandas
    if cleaned_entries:
        df = pd.DataFrame(cleaned_entries)
        # Ensure schema types for parquet
        df["vietnam_relevance"] = df["vietnam_relevance"].astype(bool)
        df.to_parquet(cleaned_parquet_path, index=False)
        
    print(f"\nDone! Collected {len(cleaned_entries)} articles.")
    print(f"Raw payload saved to: {raw_path}")
    print(f"Cleaned JSONL saved to: {cleaned_jsonl_path}")
    print(f"Cleaned Parquet saved to: {cleaned_parquet_path}")

if __name__ == "__main__":
    main()

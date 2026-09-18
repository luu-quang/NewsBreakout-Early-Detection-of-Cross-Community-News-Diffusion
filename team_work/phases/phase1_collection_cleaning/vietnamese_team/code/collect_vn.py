import os
import json
import feedparser
from datetime import datetime, timezone

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
    
    # Ensure output dir exists
    output_dir = os.path.join(os.path.dirname(__file__), "..", "sample_output")
    os.makedirs(output_dir, exist_ok=True)
    
    for pub_id, url in RSS_FEEDS.items():
        print(f"Fetching {pub_id} from {url}...")
        try:
            # Set User-Agent
            d = feedparser.parse(url, agent=USER_AGENT)
            if getattr(d, 'bozo', False) and not d.entries:
                print(f"  -> Failed to parse feed: {d.bozo_exception}")
                continue
                
            entries = d.entries[:20]  # Take top 20 per feed for sample
            print(f"  -> Found {len(entries)} entries.")
            
            for entry in entries:
                # Store raw
                raw_payloads.append({
                    "feed": url,
                    "publisher": pub_id,
                    "observed_at_utc": observed_at_utc,
                    "entry": dict(entry)
                })
                
        except Exception as e:
            print(f"  -> Error: {e}")

    # Output paths
    raw_path = os.path.join(output_dir, "sample_vn_raw.json")
    
    # Save Raw
    with open(raw_path, 'w', encoding='utf-8') as f:
        json.dump(raw_payloads, f, ensure_ascii=False, indent=2, default=str)
        
    print(f"\nDone! Collected {len(raw_payloads)} raw articles.")
    print(f"Raw payload saved to: {raw_path}")

if __name__ == "__main__":
    main()

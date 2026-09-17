# NewsBreakout — Phase 1 International Team

## Goal
Collect articles about Vietnam from **international publishers**, perform basic cleaning/normalization, and produce output compatible with the Vietnamese team.

Do **not** collect generic world news unrelated to Vietnam.

Working branch:
```text
international
```

## Team
- Member 1:
- Member 2:

## Important distinction
A publisher is not the same thing as a collection system.

Example:
```text
Reuters = publisher
GDELT = collection/discovery system
```

A row may look like:
```text
publisher_domain = reuters.com
source_system = gdelt_doc
branch = international
```

Do not label GDELT as the publisher.

## Tasks

### 1. Find reliable international publishers covering Vietnam
Possible starting points:
- Reuters
- BBC
- Nikkei
- Channel NewsAsia
- AP
- SCMP
- Straits Times

Collection methods may include:
- RSS
- live GDELT
- other stable public feeds

### 2. Build or update the collector
Put code in:
```text
team_work/phases/phase1_collection_cleaning/international_team/code/
```

Files:
```text
collect_intl.py   # GDELT DOC 2.0 search + direct publisher RSS -> data/raw/international/international_raw.parquet
clean_intl.py     # basic cleaning + relevance filter -> data/processed/international/international_clean.parquet + sample_output/sample_intl.csv
```

Run:
```bash
python3 team_work/phases/phase1_collection_cleaning/international_team/code/collect_intl.py
python3 team_work/phases/phase1_collection_cleaning/international_team/code/clean_intl.py
```

### 3. Verify Vietnam relevance
Returned articles must actually concern Vietnam, not merely mention Vietnam incidentally.

### 4. Basic cleaning
- standardize column names
- normalize timestamps
- normalize publisher/domain names
- preserve language
- flag Vietnam relevance
- preserve raw data

## Shared output schema
```text
article_id
title
url
canonical_url
publisher_domain
publisher_id
publisher_group_id
source_system
first_seen_at
published_at
timestamp_confidence
language
publisher_country
description
category
vietnam_relevance
duplicate_family_id
branch
collection_mode
raw_payload_ref
```

For live international collection:
```text
branch = international
collection_mode = prospective
```

Historical GDELT data must use:
```text
collection_mode = historical_backfill
```

Historical backfill must not be mixed into the live 48-hour pilot.

## Sample output
Put a 20–100 row review sample in:
```text
team_work/phases/phase1_collection_cleaning/international_team/sample_output/
```

Do not commit large raw archives.

## Source tracker
| Publisher / source | Feed / query | Method | Working? | Notes |
|---|---|---|---|---|
| Reuters | domain:reuters.com + "Vietnam" | GDELT DOC | Registered, 0 hits in first snapshot | included in the GDELT domain filter; just didn't surface in this run |
| BBC | domain:bbc.com/bbc.co.uk + "Vietnam"; feeds.bbci.co.uk/news/world/asia/rss.xml | GDELT DOC + RSS | Yes | GDELT DOC found both English and Vietnamese-language BBC articles |
| Nikkei Asia | domain:asia.nikkei.com + "Vietnam" | GDELT DOC | Yes | |
| CNA | domain:channelnewsasia.com + "Vietnam"; channelnewsasia.com/rssfeeds/8395986 | GDELT DOC + RSS | Yes (GDELT); RSS returned 0 in this run | |
| SCMP | domain:scmp.com + "Vietnam" | GDELT DOC | Yes | |
| Straits Times | domain:straitstimes.com + "Vietnam" | GDELT DOC | Yes, but noisiest source | see known issues |
| AP | domain:apnews.com + "Vietnam" | GDELT DOC | Registered, 0 hits in first snapshot | |
| GDELT DOC 2.0 | `(domain:... OR ...) Vietnam` | GDELT | Yes | collection system, not a publisher — this is `source_system = gdelt_doc` |

## Known issues
- GDELT DOC search matches full article text, not just the headline. Before filtering, a large share of Straits Times hits (~90% in our first snapshot) mentioned Vietnam only in sidebar/related-story text, not the actual article. Fixed in `clean_intl.py` by recomputing `vietnam_relevance` from title/description only and dropping non-matching rows during cleaning (raw data is kept as-is).
- `published_at` for `gdelt_doc` rows comes from GDELT's `seendate`, i.e. when GDELT's crawler observed the article — not a confirmed publisher timestamp. Reflected via `timestamp_confidence = gdelt_seen_time`.
- RSS collection only checks the current ~20-30 items in each feed, so a given snapshot can easily return 0 Vietnam-relevant entries even though the feed is working; GDELT DOC is the more reliable primary source, RSS is a supplementary/lower-confidence source (`timestamp_confidence = publisher_reported` when the feed provides a date, else `first_seen_only`).
- GDELT DOC's API rate-limits to roughly one request per 5 seconds per IP; on some networks (e.g. shared/sandboxed ones) this returns HTTP 429. `collect_intl.py` retries with backoff and skips the GDELT source for that run rather than failing, so the RSS path still runs.
- `publisher_group_id`, `category`, `duplicate_family_id`, and `raw_payload_ref` are not yet populated (left `None`) — no source currently supplies them and syndication-family grouping is a Phase 2 concern.
- Reuters and AP are registered as target domains but returned 0 articles in the first snapshot; worth re-checking on a later run before concluding they don't work.

## Done when
- [x] Several working international publishers/sources
- [x] Collection runs automatically (`collect_intl.py` then `clean_intl.py`)
- [x] Articles are actually about Vietnam (title/description-based relevance filter)
- [x] Small cleaned sample is committed (`sample_output/sample_intl.csv`)
- [x] Real publisher is identified (`publisher_domain`)
- [x] `source_system` is correct (`gdelt_doc` / `rss`)
- [x] `first_seen_at` is present
- [x] `branch = international`
- [x] `collection_mode = prospective`
- [x] Output follows the same schema as Vietnamese team
- [x] Known issues are documented

## Git workflow
Before working:
```bash
git checkout international
git pull origin international
```

After changes:
```bash
git add team_work/phases/phase1_collection_cleaning/international_team
git commit -m "Update international Phase 1 collection"
git push origin international
```

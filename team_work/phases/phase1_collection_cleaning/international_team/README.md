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

Run (live/prospective, for the actual 48h pilot):
```bash
python3 team_work/phases/phase1_collection_cleaning/international_team/code/collect_intl.py
python3 team_work/phases/phase1_collection_cleaning/international_team/code/clean_intl.py
```

Run (backfill, only to build a review sample when the live window is too sparse — see known issues):
```bash
python3 team_work/phases/phase1_collection_cleaning/international_team/code/collect_intl.py --historical-days 60
python3 team_work/phases/phase1_collection_cleaning/international_team/code/clean_intl.py \
    --input data/raw/international/international_historical.parquet \
    --output data/processed/international/international_historical_clean.parquet
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
- **Without an explicit `timespan`, GDELT DOC searches its full default corpus (empirically ~2-3 months back), not "recent" articles** — even with `sort=datedesc`. Our first snapshot's sample looked like "old news" because of this, not because the collector was broken. `collect_intl.py` now sets `GDELT_TIMESPAN = "1w"` for live/prospective runs.
- **Dedicated Vietnam coverage from these specific major outlets is genuinely sparse**: with a proper 1-week window across all 7 target domains, only ~5 articles matched, and only 3 of those actually mentioned Vietnam in the title (the other 2 were the same sidebar-mention false positive above). This matches the main project README's own stated limitation ("international volume may be sparse") — it is not a bug, but it does mean a single live snapshot will rarely be enough for a 20-100 row review sample on its own.
- To get a properly sized review sample despite that sparsity, `collect_intl.py --historical-days N` runs the same GDELT search over a wider backward window and tags rows `collection_mode = historical_backfill`, writing to a separate file (`international_historical.parquet`) so it never mixes into the live prospective/48h-pilot data. `sample_intl.csv` was built this way (`--historical-days 60`, 45 clean rows) — the live prospective collector alone would not have had enough volume to produce a compliant sample yet.
- `published_at` for `gdelt_doc` rows comes from GDELT's `seendate`, i.e. when GDELT's crawler observed the article — not a confirmed publisher timestamp. Reflected via `timestamp_confidence = gdelt_seen_time`.
- RSS collection only checks the current ~20-30 items in each feed, so a given snapshot can easily return 0 Vietnam-relevant entries even though the feed is working; GDELT DOC is the more reliable primary source, RSS is a supplementary/lower-confidence source (`timestamp_confidence = publisher_reported` when the feed provides a date, else `first_seen_only`).
- GDELT DOC's API rate-limits to roughly one request per 5 seconds per IP; on some networks (e.g. shared/sandboxed ones) this returns HTTP 429, sometimes for several minutes at a stretch. `collect_intl.py` retries with backoff and skips the GDELT source for that run rather than failing, so the RSS path still runs.
- `vietnam_relevance` is populated in this branch's code (not the Vietnamese team's) because it's a required per-row shared-schema column both branches must produce — see `team_work/phases/phase1_collection_cleaning/README.md`'s shared schema list. The Vietnamese team's `clean_vn.py` also sets it (hardcoded `True`, since their domestic RSS sources are Vietnam-focused by construction); ours needs real filtering because GDELT's search casts a much wider, noisier net.
- 15/30/60-minute event-visibility timing (RQ4 in the main README) cannot come from this data yet: it needs (a) the same real-world event independently observed by multiple publishers, which requires Phase 2 event clustering, not built yet, and (b) a collector that runs repeatedly across the 48h pilot window to actually capture timestamps at those intervals, not a single manual run. The main README's own section 7 describes the 48h pilot as a separate, later, coordinated step.
- `publisher_group_id`, `category`, `duplicate_family_id`, and `raw_payload_ref` are not yet populated (left `None`) — no source currently supplies them and syndication-family grouping is a Phase 2 concern.
- Reuters and AP are registered as target domains but returned 0 articles across every window tested so far; worth re-checking on a later run before concluding they don't work.

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

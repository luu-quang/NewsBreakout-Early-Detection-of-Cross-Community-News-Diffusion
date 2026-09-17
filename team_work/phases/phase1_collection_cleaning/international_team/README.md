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

`clean_intl.py` always writes an audit table (both `vietnam_relevance=True` and `False` rows) to `international_clean_audit.parquet`, and the official 48h pilot deliverable should be built with `--pilot-start <T_start ISO8601>` once T_start is agreed with the Vietnamese team, so pre-pilot warm-up runs don't silently count as pilot data — see known issues.

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
Direct publisher RSS is now the primary path where a feed exists; GDELT DOC is supplementary/fallback (see known issues on why GDELT stopped being treated as primary).

| Publisher / source | Feed / query | Method | Working? | Notes |
|---|---|---|---|---|
| Reuters | domain:reuters.com + "Vietnam" | GDELT DOC only | Registered, 0-8 hits depending on window | no public RSS feed exists anymore (every candidate URL we tried returned 403/404) |
| BBC | domain:bbc.com/bbc.co.uk + "Vietnam"; feeds.bbci.co.uk/news/world/asia/rss.xml | GDELT DOC + RSS | Yes | GDELT DOC found both English and Vietnamese-language BBC articles |
| Nikkei Asia | domain:asia.nikkei.com + "Vietnam"; asia.nikkei.com/rss/feed/nar | GDELT DOC + RSS | Yes, real URLs confirmed on both paths | direct feed added — general/latest, not Vietnam-specific, relies on our own relevance filter |
| CNA | domain:channelnewsasia.com + "Vietnam"; channelnewsasia.com/rssfeeds/8395986 | GDELT DOC + RSS | Yes | |
| SCMP | domain:scmp.com + "Vietnam"; scmp.com/rss/91/feed | GDELT DOC + RSS | Yes, real URLs confirmed on both paths | direct feed added — general "News" feed, not Vietnam-specific |
| Straits Times | domain:straitstimes.com + "Vietnam"; straitstimes.com/news/asia/rss.xml | GDELT DOC + RSS | Yes, real URLs confirmed on both paths | direct feed added — noisiest GDELT DOC source (see known issues), but its own RSS is clean |
| AP | domain:apnews.com + "Vietnam" | GDELT DOC only | Registered, 0 hits across every window tested | no public RSS feed exists anymore (apnews.com/rss returned 403) |
| GDELT DOC 2.0 | `(domain:... OR ...) Vietnam` | GDELT | Yes | collection system, not a publisher — this is `source_system = gdelt_doc` |

We also evaluated Google News RSS search (`site:domain + Vietnam` query) as a way to get per-publisher Vietnam-filtered results without GDELT, including for Reuters/AP. It finds far more matches (~35/week across 6 domains vs GDELT's ~5), but its `<link>` is an opaque `news.google.com/rss/articles/...` redirect token, not the real article URL — resolving it to the actual publisher URL requires reverse-engineering Google's undocumented encoding, which we're not willing to build into a schema-critical field (`url`/`canonical_url`/`publisher_domain`). Rejected for now; noted here so it isn't re-proposed without re-checking whether Google ever exposes a stable direct link.

## Known issues

Resolved after leader review (2026-09-17):
- **T_start / warm-up vs. official pilot data.** Any collection run before both branches' collectors are confirmed healthy and T_start is agreed should not automatically count as official pilot data. `clean_intl.py --pilot-start <ISO8601 UTC>` now excludes rows with `first_seen_at` earlier than T_start from the final clean table/sample (verified: with a test cutoff, 41 of 45 pre-cutoff relevant rows were correctly excluded, 4 post-cutoff rows kept). Excluded rows are never deleted — they stay in the raw archive and the audit table. Warm-up/seeding should happen before T_start is set; once the team agrees on T_start, pass it to every `clean_intl.py` run that produces the official pilot deliverable.
- **GDELT's `seendate` was being stored as `published_at`.** That's wrong — `seendate` is when GDELT's crawler observed the article, not when the publisher published it. Fixed: `published_at` is now always `null` for `gdelt_doc` rows (verified on a fresh 112-row pull). `seendate` is still useful as an earliest-known-observation bound, so it's now used for `first_seen_at` instead (often earlier/more accurate than our own poll time), with `timestamp_confidence = gdelt_seen_time` marking it as an aggregator observation time, not a confirmed publish time.
- **`vietnam_relevance=False` rows were being silently dropped.** `clean_intl.py` now writes an audit/QC table with every row that survives basic cleaning, both `True` and `False`, to `international_clean_audit.parquet` (112 rows, 45 True / 67 False in our test run). The final relevant-only table and sample are filtered from that audit table, so the filter's behavior stays inspectable instead of vanishing.
- **Direct publisher coverage expanded, GDELT no longer treated as primary.** Added real, verified RSS feeds for SCMP, Nikkei Asia, and Straits Times (5 of 7 domains now have direct RSS, up from 2). Reuters and AP genuinely have no public RSS anymore (verified: every candidate URL returned 403/404) and remain GDELT-DOC-only. We also evaluated Google News RSS search as a way to cover all 7 domains without GDELT — much higher volume (~35/week vs GDELT's ~5), but its links are opaque Google redirect tokens, not real article URLs, so we rejected it rather than ship a broken `url`/`publisher_domain`. See source tracker for details.
- **Repeated-run `last_seen_at` was silently wrong.** The original merge logic reset `last_seen_at = first_seen_at` for every row (old and new) on every run, which meant a URL's `last_seen_at` regressed back to its original first-seen time on any run where it wasn't freshly re-fetched — after a few runs it would no longer reflect "most recently confirmed still there." Fixed by tracking each run's own poll time separately (`polled_at`, not part of the shared schema) and only using it to seed `last_seen_at` for genuinely new rows, preserving already-persisted `last_seen_at` values from disk otherwise. Verified with a 3-run simulation: a URL re-observed in run 2 correctly advances `last_seen_at`, and a URL NOT re-observed in run 3 correctly keeps its run-1 `last_seen_at` instead of resetting.

Still open / accepted:
- GDELT DOC search matches full article text, not just the headline. A large share of Straits Times GDELT hits (~90% in one snapshot) mentioned Vietnam only in sidebar/related-story text, not the actual article — caught by the same title/description relevance recheck in `clean_intl.py` (now visible in the audit table rather than silently dropped).
- Without an explicit `timespan`, GDELT DOC searches its full default corpus (empirically ~2-3 months back), not "recent" articles, even with `sort=datedesc`. Live/prospective runs use `GDELT_TIMESPAN = "1w"`, the narrowest window that reliably returns anything.
- Dedicated Vietnam coverage from major international outlets is genuinely sparse — matches the main README's own stated limitation ("international volume may be sparse"). `collect_intl.py --historical-days N` (tagged `collection_mode = historical_backfill`, written to a separate file, never mixed into live pilot data) is used only to build a properly-sized (20-100 row) review sample when the live window can't supply enough on its own.
- RSS collection only checks the current ~20-30 items in each feed, so a given snapshot can return 0 new Vietnam-relevant entries even though the feed is working.
- GDELT DOC's API rate-limits to roughly one request per 5 seconds per IP; on some networks this returns HTTP 429 for several minutes at a stretch. `collect_intl.py` retries with backoff and skips the GDELT source for that run rather than failing, so the RSS path still runs.
- `vietnam_relevance` is correctly populated in this branch's code, not the Vietnamese team's — it's a required per-row shared-schema column both branches must produce independently (see `team_work/phases/phase1_collection_cleaning/README.md`'s shared schema list). The Vietnamese team's `clean_vn.py` also sets it (hardcoded `True`, since domestic RSS sources are Vietnam-focused by construction); ours needs real filtering because GDELT's full-text search and general-topic RSS feeds are much noisier.
- 15/30/60-minute event-visibility timing (RQ4 in the main README) cannot come from Phase 1 collection alone: it needs Phase 2 event clustering (to know multiple publishers covered the *same* event) plus a collector running repeatedly across the actual 48h pilot window, not a one-off snapshot. The main README's own section 7 treats the 48h pilot as a separate, later, coordinated step.
- `publisher_group_id`, `category`, `duplicate_family_id`, and `raw_payload_ref` are not yet populated (left `None`) — no source currently supplies them and syndication-family grouping is a Phase 2 concern.

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

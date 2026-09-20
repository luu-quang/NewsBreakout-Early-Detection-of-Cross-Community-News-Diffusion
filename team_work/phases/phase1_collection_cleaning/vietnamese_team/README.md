# NewsBreakout — Phase 1 Vietnamese Team

## Goal
Collect Vietnam-related news from **Vietnamese publishers**, perform basic cleaning/normalization, and produce a small sample that follows the shared NewsBreakout schema.

This phase is only about **reliable data collection + compatible cleaned output**.

Do **not** start event clustering, graph analysis, prediction, or final visualization yet.

## Team
- Member 1:
- Member 2:

Working branch:
```text
vnese
```

## Tasks

### 1. Find reliable Vietnamese publishers
Possible starting points:
- VnExpress
- Tuổi Trẻ
- Thanh Niên
- VietnamNet
- Dân Trí
- Lao Động
- VTV
- Tiền Phong

Prefer direct publisher RSS whenever available. GDELT is supplementary discovery/fallback; keep the actual publisher distinct from `source_system`.

### 2. Build or update the collector
Put code in:
```text
team_work/phases/phase1_collection_cleaning/vietnamese_team/code/
```

Suggested files:
```text
collect_vn.py
clean_vn.py
```

### 3. Basic cleaning
For Phase 1:
- standardize column names
- normalize timestamps
- normalize publisher/domain names
- keep language information
- flag Vietnam relevance
- identify broken rows
- preserve raw data

Do not remove syndicated/duplicate articles yet.

## Frozen contract and relevance audit

Follow the [shared Phase 1 data contract](../README.md#shared-data-contract-frozen).

- `first_seen_at` is when our collector first observed the URL, preserved across repeated polls.
- `published_at` is publisher-reported publication time only; leave it null when missing or unparseable. Do not substitute observation time.
- `source_seen_at` is auxiliary source observation metadata, such as GDELT `seendate`, retained in raw/audit data when available rather than required in the shared export. It cannot replace either timestamp above.
- Normalize timestamps to UTC with explicit timezone information.

`vietnam_relevance` means that the article substantively concerns Vietnam. Use documented, source-aware rule-based heuristics over the available title, description, Vietnamese entities, and local context. Vietnamese publishers also report foreign and general-interest stories: neither publisher origin, language, nor `branch = domestic` implies `True`. Evaluate relevance per article; the Vietnamese team does not assign `True` to every domestic article. Category/URL hints can help but can also miss local stories, so document limitations and review both classes.

Preserve all fetched raw/candidate records before final relevance filtering. Do not discard RSS entries at collection time merely because they lack a Vietnam keyword. Keep `vietnam_relevance=True` and `False` rows in a cleaned candidate/audit table, retain raw traceability through `raw_payload_ref`, and record broken-row rejection reasons. Produce any relevant-only export from that audit table without replacing it. Include examples from both classes in review samples when available; do not manufacture missing classes.

Missed early articles can shift observed event onset and publisher diversity; irrelevant articles can distort later event clusters and cross-community spread. This relevance audit supports later early breakout-risk prediction. Phase 1 itself stops before event clustering, graph construction/analysis, and prediction.

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

For live Vietnamese collection:
```text
branch = domestic
collection_mode = prospective
```

Deliberate retrospective collection uses `collection_mode = historical_backfill` with separate files, samples, and counts. It must never be mixed into the live pilot or have historical source time substituted for `first_seen_at`.

## Shared 48-hour pilot

Use the single team-lead-recorded ISO 8601 UTC `T_start` agreed with the international team after both collectors and pre-pilot requirements are ready. Follow the [shared pilot rules](../README.md#shared-48-hour-prospective-pilot): include prospective rows only when `T_start <= first_seen_at < T_start + 48 hours`. Keep both relevance classes auditable, and derive the relevant-only pilot view separately. Preserve but exclude pre-start warm-up rows and all backfill; do not reset first-seen times. International `raw_payload_ref` remains unfinished and must be completed before this shared pilot begins.

## Sample output
Put a small review sample in:
```text
team_work/phases/phase1_collection_cleaning/vietnamese_team/sample_output/
```

Recommended size:
```text
20–100 rows
```

Do not commit a large raw news archive.

## Source tracker
| Publisher | Feed / URL | Method | Working? | Notes |
|---|---|---|---|---|
| VnExpress |  | RSS |  |  |
| Tuổi Trẻ |  | RSS |  |  |
| Thanh Niên |  | RSS |  |  |
| VietnamNet |  | RSS |  |  |
| Dân Trí |  | RSS |  |  |

## Done when
- [ ] Several working Vietnamese publishers
- [ ] Collection runs automatically
- [ ] Raw records are preserved
- [ ] Both relevance classes are auditable and manually reviewed
- [ ] Timestamp meanings and separate collection modes are verified
- [ ] Small cleaned sample is committed
- [ ] `title` is present
- [ ] `url` is present
- [ ] `publisher_domain` is correct
- [ ] `first_seen_at` is present
- [ ] `branch = domestic`
- [ ] `collection_mode = prospective`
- [ ] Output follows the shared schema
- [ ] Known issues are documented

## Git workflow
Before working:
```bash
git checkout vnese
git pull origin vnese
```

After changes:
```bash
git add team_work/phases/phase1_collection_cleaning/vietnamese_team
git commit -m "Update Vietnamese Phase 1 collection"
git push origin vnese
```

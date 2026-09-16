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
phase1-vietnamese
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

Prefer RSS feeds or another stable automated source.

### 2. Build or update the collector
Put code in:
```text
team_work/phase1/vietnamese_team/code/
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

## Sample output
Put a small review sample in:
```text
team_work/phase1/vietnamese_team/sample_output/
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
git checkout phase1-vietnamese
git pull origin phase1-vietnamese
```

After changes:
```bash
git add team_work/phase1/vietnamese_team
git commit -m "Update Vietnamese Phase 1 collection"
git push origin phase1-vietnamese
```

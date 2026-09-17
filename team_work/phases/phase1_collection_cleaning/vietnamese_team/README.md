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

Prefer RSS feeds or another stable automated source.

### 2. Build or update the collector
Put code in:
```text
team_work/phases/phase1_collection_cleaning/vietnamese_team/code/
```

Suggested files:
```text
collect_vn.py (Cào dữ liệu từ 5 RSS feeds, lưu thô, và gọi hàm làm sạch)
clean_vn.py (Xử lý chuỗi, chuẩn hóa URL, băm SHA-256, parse ngày giờ UTC, và map 20 trường)
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
| VnExpress | `https://vnexpress.net/rss/tin-moi-nhat.rss` | RSS | Yes | |
| Tuổi Trẻ | `https://tuoitre.vn/rss/tin-moi-nhat.rss` | RSS | Yes | |
| Thanh Niên | `https://thanhnien.vn/rss/home.rss` | RSS | Yes | |
| VietnamNet | `https://vietnamnet.vn/rss/thoi-su.rss` | RSS | Yes | |
| Dân Trí | `https://dantri.com.vn/rss/home.rss` | RSS | Yes | |

## Done when
- [x] Several working Vietnamese publishers
- [x] Collection runs automatically
- [x] Raw records are preserved
- [x] Small cleaned sample is committed
- [x] `title` is present
- [x] `url` is present
- [x] `publisher_domain` is correct
- [x] `first_seen_at` is present
- [x] `branch = domestic`
- [x] `collection_mode = prospective`
- [x] Output follows the shared schema
- [x] Known issues are documented

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

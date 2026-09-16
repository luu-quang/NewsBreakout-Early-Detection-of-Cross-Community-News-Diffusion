# NewsBreakout — Phase 1 International Team

## Goal
Collect articles about Vietnam from **international publishers**, perform basic cleaning/normalization, and produce output compatible with the Vietnamese team.

Do **not** collect generic world news unrelated to Vietnam.

Working branch:
```text
phase1-international
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
team_work/phase1/international_team/code/
```

Suggested files:
```text
collect_intl.py
clean_intl.py
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
team_work/phase1/international_team/sample_output/
```

Do not commit large raw archives.

## Source tracker
| Publisher / source | Feed / query | Method | Working? | Notes |
|---|---|---|---|---|
| Reuters |  | RSS / GDELT |  |  |
| BBC |  | RSS / GDELT |  |  |
| Nikkei |  | RSS / GDELT |  |  |
| CNA |  | RSS / GDELT |  |  |
| GDELT live | Vietnam query | GDELT |  | collection system |

## Done when
- [ ] Several working international publishers/sources
- [ ] Collection runs automatically
- [ ] Articles are actually about Vietnam
- [ ] Small cleaned sample is committed
- [ ] Real publisher is identified
- [ ] `source_system` is correct
- [ ] `first_seen_at` is present
- [ ] `branch = international`
- [ ] `collection_mode = prospective`
- [ ] Output follows the same schema as Vietnamese team
- [ ] Known issues are documented

## Git workflow
Before working:
```bash
git checkout phase1-international
git pull origin phase1-international
```

After changes:
```bash
git add team_work/phase1/international_team
git commit -m "Update international Phase 1 collection"
git push origin phase1-international
```

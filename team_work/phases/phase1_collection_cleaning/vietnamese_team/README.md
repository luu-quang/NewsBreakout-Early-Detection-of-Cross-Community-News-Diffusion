# NewsBreakout — Phase 1 Vietnamese Team

## Goal

Collect Vietnam-related news from Vietnamese publishers, preserve the raw/candidate records, perform basic cleaning/normalization, audit Vietnam relevance, and produce outputs compatible with the shared Phase 1 contract.

Phase 1 is complete for the Vietnamese branch.

## Implementation

Code:

```text
team_work/phases/phase1_collection_cleaning/vietnamese_team/code/
```

Main scripts:

```text
collect_vn.py
clean_vn.py
```

The branch used during implementation was:

```text
vnese
```

## Collection

The Vietnamese collector uses direct publisher feeds where available.

Candidate publishers include outlets such as:

- VnExpress
- Tuổi Trẻ
- Thanh Niên
- VietnamNet
- Dân Trí
- Lao Động
- VTV
- Tiền Phong

Publisher identity and collection system remain separate concepts.

## Cleaning and relevance

Phase 1 cleaning includes:

- standardizing column names;
- normalizing timestamps;
- normalizing publisher/domain identifiers;
- preserving language information;
- assigning `vietnam_relevance`;
- preserving raw traceability;
- recording broken/rejected rows for audit.

Do not remove syndicated/duplicate stories in Phase 1.

`vietnam_relevance` is evaluated per article. A Vietnamese publisher, Vietnamese language, or `branch = domestic` does not automatically imply relevance.

## Timestamp contract

- `first_seen_at`: when our collector first observed the URL;
- `published_at`: publisher-reported publication time only;
- `source_seen_at`: auxiliary source observation metadata retained in audit/raw data when available.

Timestamps are normalized to UTC.

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

For prospective Vietnamese collection:

```text
branch = domestic
collection_mode = prospective
```

`duplicate_family_id` remains null until Phase 2B.

## Final outputs

Relevant-only:

```text
data/processed/vietnamese/vietnamese_clean.parquet
```

Audit:

```text
data/processed/vietnamese/vietnamese_clean_audit.parquet
```

Validated snapshot:

```text
Audit rows:          1,259
Relevant-only rows:  1,221
```

Small review samples are tracked in:

```text
team_work/phases/phase1_collection_cleaning/vietnamese_team/sample_output/
```

Large datasets remain local/ignored by Git.

## Completion status

- [x] Collection implementation completed
- [x] Cleaning/normalization completed
- [x] Raw/candidate preservation completed
- [x] Relevance audit produced
- [x] Relevant-only output produced
- [x] Shared schema satisfied
- [x] Timestamp semantics validated
- [x] `raw_payload_ref` traceability preserved
- [x] Small review samples committed
- [x] Output successfully consumed by Phase 2A

Phase 1 Vietnamese work is complete.

Downstream duplicate/syndication detection belongs to Phase 2B.

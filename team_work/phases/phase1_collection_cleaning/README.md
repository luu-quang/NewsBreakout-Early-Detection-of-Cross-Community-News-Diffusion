# NewsBreakout — Phase 1 Team Workspace

## Goal

Phase 1 collects Vietnam-related news, preserves raw/candidate records, performs basic cleaning and normalization, audits Vietnam relevance, and produces compatible Vietnamese and international outputs for downstream integration.

Phase 1 is complete. Deduplication, event clustering, graph analysis, and prediction belong to later phases.

## Team split

```text
Vietnamese team
→ Vietnamese publishers

International team
→ international publishers covering Vietnam
```

Both teams follow the same shared data contract.

## Workflow

```text
sources
  ↓
collection
  ↓
raw / candidate preservation
  ↓
basic cleaning + normalization
  ↓
Vietnam relevance audit
  ↓
audit table containing True + False rows
  ↓
relevant-only export
  ↓
Phase 2A master integration
```

## Shared rules

1. Preserve raw/candidate data.
2. Use automated collection where possible.
3. Do not commit large raw or processed datasets to Git.
4. Commit code, documentation, and small review samples.
5. Both teams must follow the same shared schema.
6. Prefer direct publisher RSS where usable.
7. GDELT is supplementary discovery/fallback, not a publisher.
8. Keep `prospective` collection separate from `historical_backfill`.

## Shared data contract — frozen

| Field | Shared meaning |
|---|---|
| `first_seen_at` | Time our collector first observed the article URL. Preserve the earliest stored observation across repeated polls. |
| `published_at` | Publisher-reported publication time only. Null when unavailable or unparseable. |
| `source_seen_at` | Auxiliary source observation time retained in raw/audit metadata when available. It is not part of the frozen 20-column shared export. |
| `vietnam_relevance` | Whether the article substantively concerns Vietnam rather than merely mentioning it incidentally. |
| `raw_payload_ref` | Reference that allows a cleaned/audit row to be traced to its preserved raw source payload. |

Normalize timestamps to UTC with explicit timezone information.

Do not replace one timestamp meaning with another. In particular, do not fill `first_seen_at` from publication time or GDELT observation time.

## Relevance and preservation

Publisher origin, language, and branch do not automatically determine Vietnam relevance.

The Vietnamese and international pipelines use source-aware rule-based heuristics over available title/description evidence and relevant entities/places. These heuristics are not ground truth, so review samples from both relevance classes are retained.

Preserve raw/candidate records before final relevance filtering. Keep a cleaned audit table containing both `vietnam_relevance=True` and `False`, with rejection reasons where applicable and traceability through `raw_payload_ref`.

The relevant-only export is derived from the audit table rather than replacing it.

## Frozen 20-column shared schema

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

Branches:

```text
domestic
international
```

Collection modes:

```text
prospective
historical_backfill
```

`duplicate_family_id` remains null in Phase 1.

## Folder structure

```text
team_work/phases/phase1_collection_cleaning/
├── README.md
├── vietnamese_team/
│   ├── README.md
│   ├── code/
│   └── sample_output/
└── international_team/
    ├── README.md
    ├── code/
    └── sample_output/
```

## Final Phase 1 outputs used by Phase 2A

Relevant-only article outputs:

```text
data/processed/vietnamese/vietnamese_clean.parquet
data/processed/international/international_clean.parquet
```

Audit outputs:

```text
data/processed/vietnamese/vietnamese_clean_audit.parquet
data/processed/international/international_clean_audit.parquet
```

These full Parquet files remain local/ignored by Git.

Phase 2A validates and combines them using:

```text
src/integration/build_master.py
```

## Validated snapshot passed to Phase 2A

Vietnamese audit:

```text
1,259 rows
```

Vietnamese relevant-only:

```text
1,221 rows
```

International audit:

```text
185 rows
```

International relevant-only:

```text
2 rows
```

The sparse international relevant count is preserved as an observed limitation rather than being artificially increased.

## Phase 1 completion status

- [x] Vietnamese collection/cleaning implementation completed
- [x] International collection/cleaning implementation completed
- [x] Raw/candidate records preserved
- [x] Relevance audit outputs produced
- [x] Relevant-only outputs produced
- [x] Shared 20-column schema aligned
- [x] Timestamp semantics aligned
- [x] `raw_payload_ref` traceability completed for the finalized Phase 1 outputs
- [x] Prospective/backfill semantics separated
- [x] Small review samples committed
- [x] Final outputs successfully consumed and validated by Phase 2A

Phase 1 is complete.

Next:

```text
team_work/phases/phase2_processing/phase2a_master_integration/
```

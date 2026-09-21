# NewsBreakout — Phase 1 International Team

## Goal

Collect Vietnam-related news from international publishers, preserve raw/candidate records, perform basic cleaning/normalization, audit Vietnam relevance, and deliver outputs compatible with the shared Phase 1 contract.

Phase 1 is complete for the international branch.

## Implementation

Code:

```text
team_work/phases/phase1_collection_cleaning/international_team/code/
```

Main scripts:

```text
collect_intl.py
clean_intl.py
```

The implementation branch was:

```text
international
```

## Sources and collection

Prefer direct publisher RSS whenever a usable feed exists.

GDELT may be used as supplementary discovery/fallback. GDELT is not the publisher: an article discovered through GDELT keeps its actual publisher identity while `source_system` records the collection path.

Direct RSS uses:

```text
source_system = rss
```

When applicable, GDELT discovery uses its own source-system value rather than replacing publisher identity.

## Timestamp contract

Normalize timestamps to UTC.

| Field | Meaning |
|---|---|
| `first_seen_at` | When our collector first observed the article URL. |
| `published_at` | Publisher-reported publication time only; null if unavailable or unparseable. |
| `source_seen_at` | Auxiliary source observation time retained in raw/audit metadata when available. |

Do not copy publication or source observation time into `first_seen_at`.

## Relevance and preservation

`vietnam_relevance` means the article substantively concerns Vietnam.

International relevance is source-aware and uses available title/description evidence, including relevant place/entity variants. A keyword match is not ground truth.

Preserve fetched raw/candidate records before final relevance filtering. Keep both `True` and `False` rows in the audit output, preserve `raw_payload_ref`, and derive the relevant-only output separately.

The small number of accepted international articles in the current prospective snapshot is treated as a data limitation rather than being artificially increased.

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

Use:

```text
branch = international
```

Prospective collection uses:

```text
collection_mode = prospective
```

Historical backfill must remain separately labeled.

`duplicate_family_id` remains null until Phase 2B.

## Final outputs

Relevant-only:

```text
data/processed/international/international_clean.parquet
```

Audit:

```text
data/processed/international/international_clean_audit.parquet
```

Validated snapshot:

```text
Audit rows:          185
Relevant-only rows:    2
```

Small review samples are tracked in:

```text
team_work/phases/phase1_collection_cleaning/international_team/sample_output/
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
- [x] `raw_payload_ref` traceability completed for the finalized Phase 1 outputs
- [x] Small review samples committed
- [x] Output successfully consumed by Phase 2A

## Known limitation

The current prospective international snapshot is sparse: 185 audit rows produced only 2 Vietnam-relevant rows.

This limitation should be reported transparently and may motivate later controlled historical backfill or broader international source coverage, but historical data must remain separate from prospective timing analyses.

Phase 1 international work is complete.

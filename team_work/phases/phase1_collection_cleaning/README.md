# NewsBreakout — Phase 1 Team Workspace

## Goal
Phase 1 is about **collecting and basic cleaning** of Vietnam-related news.

We split into two teams:
- Vietnamese team: Vietnamese publishers
- International team: international publishers covering Vietnam

Both teams must produce compatible outputs so the data can later be merged.

## Current workflow
```text
Vietnamese sources ─────┐
                        ├──> collect
International sources ──┘
                             ↓
                  preserve raw/candidates
                             ↓
                  basic cleaning + relevance flags
                             ↓
                  audit table (True and False)
                             ↓
                  relevant-only shared export
                             ↓
                  review by team lead
```

Do not start event clustering, graph analysis, prediction, or final visualization yet.

## Shared rules
1. Preserve raw data.
2. Use automated collection when possible.
3. Do not commit large raw datasets to GitHub.
4. Commit only code, notes, and small sample outputs.
5. Both teams must follow the same schema.
6. Prefer direct publisher RSS when available; use GDELT as supplementary discovery/fallback, not as a publisher.

## Shared data contract (frozen)

These definitions apply to both teams. They specify the required handoff, not a claim that all implementation work is finished.

| Field | Shared meaning |
|---|---|
| `first_seen_at` | Time our collector first observed the article URL. Preserve the earliest stored observation across repeated polls; never backdate it from publication or source timestamps. |
| `published_at` | Publisher-reported publication time only. Null when absent or unparseable; never fill from GDELT `seendate` or collector time. |
| `source_seen_at` | Auxiliary source observation time, e.g. GDELT `seendate`. Preserve when available in raw/audit metadata; it is not a required column in the shared 20-column export below. |
| `vietnam_relevance` | Whether the article substantively concerns Vietnam, rather than an incidental mention. Same semantic meaning for both teams, implemented through documented source-aware rule-based heuristics. |
| `raw_payload_ref` | Reference enabling a cleaned row to be traced to its original source payload. International support remains unfinished and must be completed before the pilot. |

Normalize timestamps to UTC with explicit timezone information. `timestamp_confidence` describes timestamp quality; it does not permit replacing one timestamp's meaning with another.

### Relevance and preservation

A domestic publisher, Vietnamese language, or `branch = domestic` must not imply `vietnam_relevance=True`. Domestic rules should consider Vietnamese entities and local context; international rules should consider English/other-language variants and reject incidental or sidebar mentions. A literal match for "Vietnam" alone is neither required nor sufficient. Document each team's rules and known false positives/false negatives.

Preserve every fetched raw/candidate record before final relevance filtering, including RSS entries that lack an explicit Vietnam keyword. Source queries may constrain discovery, so record those constraints as coverage limitations. Retain a cleaned candidate/audit table with both `True` and `False` rows and traceability to raw inputs; record rejected/broken rows and their reasons rather than silently losing them. Derive relevant-only exports from the audit table, without overwriting it. Review examples from both classes, and keep warm-up and backfill records available for audit.

Relevance quality affects later early breakout-risk prediction: false negatives can hide early coverage and shift observed event onset, and false positives can distort event clusters, publisher diversity, and cross-community spread. Phase 1 establishes auditable inputs; event clustering, graph construction/analysis, and prediction are outside this phase.

## Shared schema
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

For live collection:
```text
collection_mode = prospective
```

Use `collection_mode = historical_backfill` for deliberate retrospective collection. Keep backfill files, samples, and counts separate from prospective outputs; never relabel backfill as live data. Even for backfill, `first_seen_at` records our actual collection time, not a historical source timestamp. Publisher branch and collection mode are independent.

Publisher branch:
```text
domestic
international
```

## Folder structure
```text
team_work/phases/
└── phase1_collection_cleaning/
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

## Phase 1 completion target
Each team should provide:
- working collector code
- several reliable sources
- a small 20–100 row sample
- basic cleaning/normalization
- documented known issues
- compatible schema

## Shared 48-hour prospective pilot

Once both collectors are stable, both teams have reviewed relevance audit samples, and international `raw_payload_ref` is complete and verified, the team lead records one agreed `T_start` (ISO 8601 UTC) in the pilot run notes for both teams. The actual timestamp is set at launch, not independently by each team.

Run repeated collection over the same fixed interval `[T_start, T_start + 48 hours)`. Official pilot rows must have `collection_mode = prospective` and `T_start <= first_seen_at < T_start + 48 hours`; the final relevant-only view additionally requires `vietnam_relevance=True`. Preserve both relevance classes for the pilot audit. Neither `published_at` nor `source_seen_at` determines pilot membership.

Exclude pre-pilot warm-up observations and all historical backfill from official pilot counts while retaining them for audit. Do not reset an existing `first_seen_at` when the pilot starts. Record collector outages and source coverage limitations. Event-level 15/30/60-minute visibility requires later event clustering and cannot be established by Phase 1 alone.

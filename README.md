# NewsBreakout
Early Detection of Cross-Community News Diffusion

## Project Overview

NewsBreakout studies how Vietnam-related news spreads across publishers and publisher communities.

The midterm pipeline focuses on building a reliable multilingual corpus, removing duplicate/syndicated copies, reconstructing real-world events, and analyzing publisher co-reporting. The later project direction is to study whether early observations of an event can help predict expansion into previously unrepresented publisher communities.

## Research Motivation

Raw article volume can be misleading because the same written story may be duplicated or syndicated across multiple outlets. NewsBreakout therefore separates:

- collection and relevance filtering;
- duplicate / syndication detection;
- event clustering;
- publisher co-reporting analysis; and
- later breakout-risk prediction.

A syndicated copy is not the same as an independently written report of the same event.

## Current Pipeline

```text
Phase 1 — Collection + cleaning + relevance
        ↓
Phase 2A — Master dataset integration
        ↓
Phase 2B — Duplicate / syndication detection
        ↓
Phase 2C — Event clustering
        ↓
Phase 3 — Publisher co-reporting + descriptive analysis
        ↓
Phase 4 — Report + presentation
```

## Current Status

- Phase 1 — collection / cleaning: complete
- Phase 2A — master integration: complete
- Phase 2B — duplicate / syndication detection: in progress
- Phase 2C — event clustering: not started
- Phase 3 — analysis / publisher graph: not started
- Phase 4 — report / presentation: not started

See:

```text
team_work/phases/phase2_processing/README.md
```

for the current Phase 2 workflow.

## Data Sources

Prefer direct publisher RSS for domestic and international coverage whenever available.

GDELT may be used as supplementary discovery or fallback, but GDELT is a collection system, not the publisher. For example, an article published by Reuters but discovered through GDELT still keeps Reuters as its publisher.

## Shared Data Contract

The frozen Phase 1 shared contract is defined in:

```text
team_work/phases/phase1_collection_cleaning/README.md
```

The shared 20-column article schema is:

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

Important timestamp meanings:

- `first_seen_at`: when our collector first observed the article URL;
- `published_at`: publisher-reported publication time only;
- `source_seen_at`: auxiliary source observation time retained in audit/raw metadata when available.

`first_seen_at` must not be backdated from publication or source timestamps.

## Phase 1 Outputs

Phase 1 maintains separate Vietnamese and international collection/cleaning pipelines.

Relevant-only outputs:

```text
data/processed/vietnamese/vietnamese_clean.parquet
data/processed/international/international_clean.parquet
```

Audit outputs:

```text
data/processed/vietnamese/vietnamese_clean_audit.parquet
data/processed/international/international_clean_audit.parquet
```

Large data files under `data/raw/`, `data/interim/`, and `data/processed/` are intentionally ignored by Git, except `data/processed/master/articles_master.parquet`, which is tracked as the frozen Phase 2A handoff snapshot.

## Phase 2A — Master Integration

Implementation:

```text
src/integration/build_master.py
```

Run from the repository root:

```powershell
python src/integration/build_master.py
```

It validates the frozen Phase 1 contract and combines the Vietnamese and international outputs into:

```text
data/processed/master/articles_master.parquet
data/processed/master/articles_audit.parquet
```

Validated current snapshot:

```text
articles_master.parquet
Total rows:          1,223
Domestic rows:       1,221
International rows:      2

articles_audit.parquet
Total rows:          1,444
Domestic rows:       1,259
International rows:    185
```

The master relevant dataset is the official input to Phase 2B.

Current master SHA-256:

```text
b021a43395a46af3ca36586b1042b061c644e90a92178a9b9d5779c11ea156f3
```

See:

```text
team_work/phases/phase2_processing/phase2a_master_integration/
```

for provenance, manifest generation, and snapshot details.

## Phase 2B — Duplicate / Syndication Detection

Phase 2B identifies exact duplicates and likely syndicated / near-copy stories while preserving independently written reports of the same real-world event.

Input:

```text
data/processed/master/articles_master.parquet
```

Expected local output:

```text
data/processed/master/articles_dedup.parquet
```

The independent teammate assignment is documented in:

```text
team_work/phases/phase2_processing/phase2b_dedup_syndication/README.md
```

## Phase 2C — Event Clustering

Phase 2C starts only after Phase 2B is frozen.

Its purpose is to determine which independent articles describe the same real-world event.

A duplicate family is not an event cluster.

## Midterm Scope

In scope:

- corpus collection and relevance quality;
- duplicate / syndication detection;
- event clustering;
- publisher co-reporting;
- descriptive analysis;
- feasibility analysis for early event visibility.

Out of scope for the midterm:

- final breakout-risk prediction;
- GNN-based prediction;
- fake-news classification;
- causal influence claims.

## Repository Structure

```text
data/        local raw/interim/processed datasets
src/         canonical reusable project code
team_work/   phase-specific contracts, assignments, notes, QC, and summaries
notebooks/   analysis notebooks
figures/     generated figures
config/      configuration
```

## Future Direction

Given an event and only its early observed articles, study whether it later expands into previously unrepresented publisher communities and whether historical publisher-network features improve prediction beyond early volume, timing, source diversity, publisher history, and text.

## Known Limitations

- prospective international volume is currently sparse;
- timestamps depend on publisher/source availability;
- syndication detection currently relies mainly on title + description rather than full article bodies;
- event clustering will remain approximate and must be manually audited.

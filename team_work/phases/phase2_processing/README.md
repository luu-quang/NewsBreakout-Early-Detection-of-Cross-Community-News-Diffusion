# NewsBreakout — Phase 2 Processing

## Purpose

Phase 2 converts the cleaned, relevance-filtered Phase 1 outputs into event-ready data.

```text
Phase 1 — collection + cleaning + relevance
        ↓
Phase 2A — master dataset integration
        ↓
Phase 2B — duplicate / syndication detection
        ↓
Phase 2C — event clustering
        ↓
Phase 3 — publisher co-reporting + descriptive analysis
```

The three Phase 2 sub-stages solve different problems and must not be collapsed into one step.

## Phase 2A — Master Dataset Integration

Folder:

```text
team_work/phases/phase2_processing/phase2a_master_integration/
```

Implementation:

```text
src/integration/build_master.py
```

Main output:

```text
data/processed/master/articles_master.parquet
```

Purpose: validate and combine the compatible Vietnamese and international Phase 1 relevant outputs into one frozen 20-column master corpus.

Phase 2A does not perform deduplication or event clustering.

## Phase 2B — Duplicate / Syndication Detection

Folder:

```text
team_work/phases/phase2_processing/phase2b_dedup_syndication/
```

Main input:

```text
data/processed/master/articles_master.parquet
```

Expected local output:

```text
data/processed/master/articles_dedup.parquet
```

Purpose: identify exact duplicates and likely syndicated / near-copy stories while keeping independently written reports of the same event separate.

The teammate assignment is defined in the Phase 2B README. Independent implementations must use the same Phase 2A master snapshot and verify its SHA-256 before comparison.

## Phase 2C — Event Clustering

Folder:

```text
team_work/phases/phase2_processing/phase2c_event_clustering/
```

Phase 2C starts only after the Phase 2B comparison and final deduplication method are frozen.

Its input will be the dedup-annotated article corpus. Its job is to determine which independent articles describe the same real-world event.

Duplicate families and event clusters are not the same thing.

## Data policy

Large files under `data/raw/`, `data/interim/`, and `data/processed/` remain local and ignored by Git.

Git should contain:
- source code;
- contracts and READMEs;
- small QC samples;
- small summaries / manifests.

## Phase 2 status

- Phase 2A — master integration: complete
- Phase 2B — dedup / syndication: in progress
- Phase 2C — event clustering: not started

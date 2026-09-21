# NewsBreakout — Phase 2A: Master Dataset Integration

## 1. Purpose

Phase 2A is the controlled handoff from Phase 1 collection/cleaning to Phase 2B duplicate and syndication detection.

It combines the compatible Vietnamese and international Phase 1 outputs into one validated master corpus while preserving the frozen shared data contract.

```text
Vietnamese Phase 1 relevant output ──────┐
                                         ├── Phase 2A master integration
International Phase 1 relevant output ───┘
                                                   ↓
                                       articles_master.parquet
                                                   ↓
                                      Phase 2B dedup/syndication
```

Phase 2A does not perform deduplication, syndication detection, event clustering, graph construction, or prediction.

## 2. Implementation

The implementation is:

```text
src/integration/build_master.py
```

Run from the repository root:

```powershell
python src/integration/build_master.py
```

The builder validates the Phase 1 data contract before producing the combined outputs.

## 3. Inputs

Relevant-only article inputs:

```text
data/processed/vietnamese/vietnamese_clean.parquet
data/processed/international/international_clean.parquet
```

Audit inputs:

```text
data/processed/vietnamese/vietnamese_clean_audit.parquet
data/processed/international/international_clean_audit.parquet
```

These full datasets are local/ignored rather than committed to Git.

## 4. Outputs

Phase 2A produces:

```text
data/processed/master/articles_master.parquet
data/processed/master/articles_audit.parquet
```

### `articles_master.parquet`

This is the relevant-only shared master corpus and the official input to Phase 2B.

It:
- preserves the frozen 20-column schema;
- contains accepted Vietnam-relevant articles from both branches;
- preserves IDs, URLs, timestamps, publisher metadata, collection mode, and raw traceability;
- leaves `duplicate_family_id` unassigned;
- performs no deduplication or event clustering.

### `articles_audit.parquet`

This combines the Phase 1 audit tables and preserves both accepted and rejected relevance decisions.

It includes the 20 shared fields plus:

```text
source_seen_at
rejection_reason
```

It is used for audit and traceability, not as the primary Phase 2B input.

## 5. Frozen master schema

`articles_master.parquet` contains exactly these 20 columns in this order:

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

Phase 2A must not change the meaning of these fields.

## 6. Validated current snapshot

Current validated master build:

```text
articles_master.parquet
Total rows:          1,223
Domestic rows:       1,221
International rows:      2
```

Combined audit:

```text
articles_audit.parquet
Total rows:          1,444
Domestic rows:       1,259
International rows:    185
```

The low international relevant count reflects the available prospective collection snapshot. It must not be artificially increased or relabeled.

## 7. Validation responsibilities

The builder validates the shared contract, including:
- exact schema and column order;
- allowed branch values;
- allowed collection modes;
- timestamp-confidence vocabulary;
- UTC timestamp semantics;
- required identifiers;
- canonical URLs where required;
- raw-payload traceability;
- relevance-field validity;
- domestic/international compatibility.

Contract violations should fail clearly rather than being silently repaired.

## 8. Why this stage is the foundation of Phase 2B

Phase 2B must operate on one controlled article table.

Without Phase 2A, domestic and international outputs remain separate and downstream methods could accidentally use different schemas or assumptions.

Phase 2A establishes:

```text
one frozen schema
+ one combined relevant corpus
+ one auditable provenance path
= one controlled Phase 2B input
```

Therefore the handoff is:

```text
Phase 2A
data/processed/master/articles_master.parquet
        ↓
Phase 2B
duplicate / syndication annotation
```

## 9. Snapshot identity and teammate handoff

The frozen `articles_master.parquet` snapshot is tracked in Git at `data/processed/master/articles_master.parquet`, so teammates implementing Phase 2B should obtain the exact snapshot by pulling the repository and verify its SHA-256 before use.

Before comparison, everyone must verify the same SHA-256:

```powershell
Get-FileHash -Algorithm SHA256 `
  "data\processed\master\articles_master.parquet"
```

The Phase 2A manifest records the current snapshot hash and provenance.

Do not provide an independent Phase 2B teammate with an already-deduplicated output or implementation-specific assignments before their first version is frozen.

## 10. Tracked artifacts

Tracked:
- this README;
- `src/integration/build_master.py`;
- `sample_output/master_build_summary.csv`;
- `sample_output/master_build_manifest.json`.

Not tracked:
- `data/processed/master/articles_master.parquet`;
- `data/processed/master/articles_audit.parquet`.

## 11. Completion status

- [x] Phase 1 outputs integrated
- [x] Frozen article schema validated
- [x] Audit schema validated
- [x] Relevant-only master dataset generated
- [x] Combined audit dataset generated
- [x] Provenance preserved
- [x] Full outputs kept out of Git
- [x] Master dataset established as Phase 2B input
- [x] Master-builder code merged into `main`

Phase 2A is complete.

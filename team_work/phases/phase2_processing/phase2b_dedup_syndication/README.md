# Phase 2B Independent Teammate Assignment

Audience: the teammate building a separate duplicate and syndication detector for method comparison after both first versions are frozen.

## Context

NewsBreakout studies how Vietnam-relevant news spreads across publisher communities and whether early cross-community activity can indicate later breakout risk. Phase 1 collected, cleaned, audited, and relevance-filtered domestic and international articles under a shared data contract. Phase 2A combined the relevant-only Phase 1 outputs into one master article dataset.

This assignment is Phase 2B. Its job is to identify duplicate records and syndicated copies before any event-level analysis. Phase 2B must preserve the article corpus while annotating articles that represent the same written story. Event clustering comes later and is a different problem.

## Objective and relation labels

Design and implement an independent, deterministic method that can distinguish these relations between article pairs:

- `EXACT_DUPLICATE`: the same article or effectively identical text represented more than once.
- `SYNDICATED_COPY`: substantially the same written story was republished, copied, or lightly rewritten, including copies carried by different publishers.
- `SAME_EVENT_INDEPENDENT`: two articles report the same real-world event but were written independently.
- `UNRELATED`: the articles do not represent the same written story or event.

`SYNDICATED_COPY` is not equivalent to `SAME_EVENT_INDEPENDENT`. Shared entities, dates, locations, facts, or topics can make independent reports highly similar. A duplicate family should represent the same written story, not every article about the same event. Semantic similarity alone does not prove syndication.

Only `title` and `description` are currently available as comparison text. Full article bodies are unavailable, so syndication detection is necessarily a proxy. Treat that limitation explicitly in the design, QC, and presentation.

## Independence requirement

This is an independent implementation for later comparison. Before finishing and freezing the first working version, do not inspect:

- `src/deduplication/annotate_duplicates.py`;
- `team_work/phases/phase2_processing/phase2b_dedup_syndication/IMPLEMENTATION.md`;
- our implementation-specific QC samples or family summaries; or
- our populated duplicate assignments in any previously generated dedup output.

Do not try to reproduce the other implementation. Choose and justify your own representation, normalization, candidate generation, similarity evidence, decision method, and family construction. After your first version and its QC artifacts are complete, both methods will be compared openly.

## Input and snapshot identity

Use this relevant-only master dataset:

```text
data/processed/master/articles_master.parquet
```

Both implementations must run on the identical master snapshot. Before implementation or comparison, record:

- the absolute or repository-relative input path;
- row count;
- file size;
- SHA-256 of `articles_master.parquet`; and
- run date and code revision.

On Windows PowerShell, the hash can be recorded with:

```powershell
Get-FileHash -Algorithm SHA256 data/processed/master/articles_master.parquet
```

Do not compare family counts or disagreements unless the recorded input hashes match exactly.

## Frozen 20-column schema

The input and dedup-annotated output must use these columns in exactly this order:

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

Preserve every original row, column, value, and row order. The only field that may be populated is the existing `duplicate_family_id`. Do not add output columns to the Parquet schema and do not collapse or delete family members.

Family IDs must be deterministic: identical input and settings must produce identical assignments. Assign one shared family ID to all members of an exact-duplicate or syndicated-copy family. Genuinely independent or singleton articles must keep `duplicate_family_id` null.

Keep `collection_mode`, `branch`, timestamps, relevance, and raw traceability unchanged. Fail clearly if the input schema is incompatible.

## Required processing behavior

Perform exact-duplicate detection first. Then evaluate non-exact candidates for near-duplicate or syndicated-copy relationships. The specific algorithms and thresholds are yours to choose and justify.

Your method must use `title` and `description` consistently, account for missing descriptions, and avoid turning general topic or event similarity into syndication. It must be deterministic, including candidate sampling and QC selection.

Produce this local output:

```text
data/processed/master/articles_dedup.parquet
```

The Phase 2B output `data/processed/master/articles_dedup.parquet` remains ignored by Git. Do not force-add this output file. The frozen Phase 2A input `articles_master.parquet` is the tracked exception.

## Required tracked QC artifacts

Create a small pair-level QC CSV under:

```text
team_work/phases/phase2_processing/phase2b_dedup_syndication/sample_output/
```

Use a teammate-specific filename so the two implementations can coexist during comparison. At minimum, each QC row must contain:

- pair or review-bucket identifier;
- left and right `article_id`;
- left and right publisher;
- left and right URL;
- left and right title;
- left and right description;
- similarity evidence or decision features where applicable;
- predicted relation using `EXACT_DUPLICATE`, `SYNDICATED_COPY`, `SAME_EVENT_INDEPENDENT`, or `UNRELATED`;
- blank or reviewer-editable manual relation;
- assigned `duplicate_family_id`, if any; and
- review notes.

The deterministic QC set must cover:

- positive exact-duplicate matches;
- positive syndicated-copy matches;
- rejected high-similarity or borderline pairs;
- plausible missed duplicates or syndication cases that probe recall;
- examples predicted as `SAME_EVENT_INDEPENDENT`;
- unrelated controls; and
- pairs from suspiciously large families, if such families exist.

Also create a small tracked family-level summary under the same folder. It should make every assigned family inspectable and include at least family ID, family type, family size, publishers, article IDs, and titles.

QC artifacts must be small enough for Git review. They must not contain hidden model state, large embeddings, or full-corpus exports.

## Run summary

Every run must report and record:

- total articles;
- articles assigned to duplicate families;
- singleton articles;
- total number of families;
- exact-duplicate family count;
- near-duplicate or syndicated family count;
- family-size distribution;
- largest family size and identifier; and
- number of reviewed QC pairs, including counts by QC category.

Verify that the output row count equals the input row count, the frozen column order is unchanged, all non-family fields are identical, every non-null family contains at least two articles, and rerunning with the same input produces the same assignments.

## Method documentation

Document your own choices without consulting the other implementation. Include:

- text representation;
- normalization steps;
- candidate-generation or blocking strategy;
- similarity metrics or model signals;
- decision thresholds and how they were selected;
- time, language, publisher, or other blocking rules;
- exact-versus-syndicated decision order;
- family-construction procedure, including how transitive links are handled;
- deterministic seed and all other reproducibility settings;
- computational cost and dependency requirements; and
- known limitations and expected false-positive/false-negative modes.

Explain why the selected evidence supports copying or syndication rather than merely indicating a shared event.

## Later comparison protocol

Do not view the other implementation's assignments until your first version, documentation, and QC set are frozen. Then compare both methods on the matching SHA-256 master snapshot using:

- total family count;
- assigned article count;
- singleton count;
- family-size distribution and largest families;
- exact-versus-syndicated family counts;
- pair-level and family-level assignment disagreements;
- `SYNDICATED_COPY` versus `SAME_EVENT_INDEPENDENT` disagreements; and
- examples one implementation groups while the other leaves independent.

Manually inspect disagreement cases before selecting one method or fusing parts of both. Do not choose a final method only because it produces more families, fewer families, or higher internal similarity. Record the rationale for the final choice and any changes made after comparison.

## Presentation responsibility

The teammate implementing this assignment will present Phase 2B. Be prepared to explain:

- why deduplication and syndication detection are necessary before downstream analysis;
- the difference between copied stories and independent reports of one event;
- your representation, candidate generation, evidence, thresholds, and family construction;
- how deterministic behavior was verified;
- QC design and findings;
- comparison results against the other independent implementation;
- important pair and family disagreements;
- the final method selected or fused and why;
- how duplicate-family annotation changes the corpus used downstream; and
- limitations caused by using titles and descriptions instead of full article bodies.

## Out of scope

Do not implement any of the following in this assignment:

- event clustering;
- event IDs;
- cross-language event matching;
- publisher graph or community detection;
- breakout-risk prediction;
- fake-news classification;
- causal analysis; or
- any downstream feature engineering that depends on event clusters or graphs.

Phase 2B may annotate duplicate families only. Do not treat duplicate families as event clusters.

## Git workflow

1. Update local `main` and confirm it is the latest shared baseline.
2. Create your own branch from that `main`. Do not branch from, merge from, or continue our implementation branch.
3. Record the master-input SHA-256 before running your method.
4. Keep large raw, interim, and processed datasets ignored, except the frozen Phase 2A `articles_master.parquet` handoff snapshot explicitly tracked by the repository.
5. Stage only intended source code, documentation, and small QC or summary artifacts.
6. Review `git status` and the staged diff for accidental data, Phase 1, event-clustering, or unrelated changes.
7. Do not merge your branch until the independent comparison and manual disagreement review are complete.

## Completion checklist

### Setup and independence

- [ ] Started a new branch from the latest `main`, not from the other implementation branch.
- [ ] Did not inspect the other deduplication code, implementation notes, QC files, or assignments before freezing the first version.
- [ ] Recorded input path, row count, file size, SHA-256, run date, and code revision.
- [ ] Confirmed the master SHA-256 matches the snapshot intended for later comparison.

### Contract and implementation

- [ ] Reads `data/processed/master/articles_master.parquet`.
- [ ] Validates the exact frozen 20-column schema and column order.
- [ ] Preserves every input row, original row order, and every non-family value.
- [ ] Populates only `duplicate_family_id`.
- [ ] Leaves singletons and independent reports null.
- [ ] Uses deterministic family IDs and deterministic settings.
- [ ] Detects exact duplicates before evaluating near duplicates or syndication.
- [ ] Uses both title and description and handles missing descriptions.
- [ ] Does not equate semantic or event similarity with syndication.

### Outputs and validation

- [ ] Writes local `data/processed/master/articles_dedup.parquet` without force-adding it to Git.
- [ ] Produces a small tracked pair-level QC CSV with all required fields.
- [ ] QC covers positive matches, borderline rejections, recall probes, same-event independent examples, unrelated controls, and suspiciously large families when available.
- [ ] Produces a small tracked family-level summary.
- [ ] Reports all required run-summary counts and family-size statistics.
- [ ] Confirms output row count and schema equal the input contract.
- [ ] Confirms all non-family fields are unchanged.
- [ ] Confirms every populated family contains at least two articles.
- [ ] Confirms reruns produce identical assignments.

### Documentation, comparison, and presentation

- [ ] Documents representation, normalization, candidate generation, evidence, thresholds, blocking/time rules, family construction, seed, dependencies, and limitations.
- [ ] Freezes the first version before viewing the other implementation.
- [ ] Compares only outputs produced from identical master SHA-256 snapshots.
- [ ] Compares counts, family sizes, pair/family disagreements, and copy-versus-independent disagreements.
- [ ] Manually reviews disagreements before recommending or fusing a final method.
- [ ] Prepares to present the rationale, method, QC, comparison, disagreements, corpus effect, final choice, and limitations.
- [ ] Stages only intended code, docs, and small QC artifacts.
- [ ] Does not implement event clustering, graphs, prediction, or other out-of-scope work.

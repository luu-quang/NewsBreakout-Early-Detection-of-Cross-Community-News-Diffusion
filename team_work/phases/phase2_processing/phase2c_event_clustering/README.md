# NewsBreakout — Phase 2C: Event Clustering

## Status

**Not started.**

Phase 2C begins only after:
1. the two independent Phase 2B deduplication/syndication implementations are complete;
2. their disagreements have been manually reviewed; and
3. the final Phase 2B method is frozen.

## Purpose

Phase 2C answers a different question from Phase 2B.

Phase 2B asks:

```text
Which articles are effectively copies of the same written story?
```

Phase 2C asks:

```text
Which independent articles describe the same real-world event?
```

A duplicate family is therefore not an event cluster.

## Planned input

```text
data/processed/master/articles_dedup.parquet
```

The exact Phase 2C output contract, clustering method, multilingual representation, thresholds, and QC protocol will be frozen before implementation.

Do not add event IDs or clustering logic during Phase 2B.

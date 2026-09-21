# NewsBreakout — Phase 2C: Event Clustering

## Status

**Revised, ready for review — not merged.** Regenerated from the frozen Phase 2B artifact.

## Purpose

Phase 2B asks: *which articles are copies of the same written story?* (`duplicate_family_id`)

Phase 2C asks: *which independent articles describe the same real-world event?* (`event_cluster_id`)

A duplicate family is not an event cluster. A whole family is one unit of evidence; several families and singleton articles can belong to one event.

## Input (authoritative)

```text
data/processed/master/articles_dedup.parquet
SHA-256 4d1b967a99a103c0e4ede002786e84f52cbe5c61bb011d878189cd7d4bc6244f
```

This is the Phase 2B artifact frozen on `main` at commit `3442f01` (1,223 rows, 2 duplicate families / 4 articles). The pipeline refuses to run on any other hash. Earlier local dedup outputs and hashes are not used. Phase 2B is not modified.

## Method

Code: `src/event_clustering/` (`embedder.py`, `clusterer.py`, `qc.py`, `sweep.py`, `pipeline.py`).

1. **Text** – `title. description`, HTML-unescaped (`&apos;` → `'`), NFC, whitespace-collapsed *for embedding only*. Article columns are never modified.
2. **Embedding** – `paraphrase-multilingual-MiniLM-L12-v2`, L2-normalised, cached on disk (`data/interim/`, ignored).
3. **Event time** – `published_at` (publisher-reported); `first_seen_at` only when `published_at` is null (2 rows). `first_seen_at` is not usable as event time here: all 1,223 rows were first seen on one day.
4. **Collapse families** – each `duplicate_family_id` becomes one clustering unit (mean embedding, earliest time). Families therefore cannot be split across events; no post-hoc overwriting.
5. **Cluster units** – agglomerative clustering on cosine distance. Pairs further apart than the time window (or with unknown time) are gated to distance 2.0. Default uses **complete linkage**, which makes the window a hard guarantee and prevents chaining.
6. **Propagate** – unit labels are mapped back to every article. **Every article gets an `event_cluster_id`**; articles that match nothing become singleton events (`n = 1`), so single-publisher events are available as a baseline for diffusion analysis.
7. **Event ID** – `evt_` + SHA-256 of the *anchor* article id (earliest `published_at`, tie → `article_id`). Adding a later article to an event does not change its id.
8. **Summaries** – recomputed from the final propagated frame; run metrics are derived from those summaries.

Output schema: the 20 frozen columns unchanged + `event_cluster_id` (21 columns, never null).

## Selected setting and sweep

Default: **distance threshold 0.30, time window 5 days, complete linkage.**

The full 24-setting sweep is in `sample_output/threshold_sweep.csv`. Selected rows (1,223 articles):

| setting (thr / window / linkage) | events | multi-article events | cross-publisher events | events ≥ 10 articles | largest event | max span (days) |
|---|---|---|---|---|---|---|
| 0.35 / 10 / average (previous 2C) | 814 | 215 | 39 | 5 | 16 | 9.99 |
| 0.35 / 5 / complete | 891 | 219 | 37 | 1 | 10 | 5.00 |
| **0.30 / 5 / complete (default)** | 985 | 174 | 26 | 0 | 7 | 5.00 |
| 0.25 / 5 / complete | 1056 | 125 | 24 | 0 | 7 | 5.00 |
| 0.20 / 5 / complete | 1114 | 85 | 15 | 0 | 6 | 5.00 |

The sweep only reports cluster **shape** (size, span, cohesion, publisher mix). It cannot measure precision or recall; `manual_label` in the QC file is still blank. The default was chosen because it removes oversized topic clusters (none ≥ 10 articles), keeps every event inside the time window, and keeps mean intra-event similarity high (0.79), not because it maximises the number of clusters. It should be confirmed or changed after manual review of the QC pairs.

## Outputs (`sample_output/`, tracked)

| File | Content |
|---|---|
| `event_clustering_manifest.json` | input/output hashes, parameters, time-source counts, run metrics (repo-relative paths) |
| `event_cluster_summary.csv` | one row per multi-article event; singleton events are counted in the manifest |
| `event_clusters_qc.csv` | 120 deterministic review pairs, `manual_label` blank |
| `threshold_sweep.csv` | threshold × window × linkage comparison |

`data/processed/master/articles_clustered.parquet` stays local (ignored). Regenerate with:

```powershell
python -m src.event_clustering.pipeline
```

QC strata: `INTRA_CLUSTER_WEAKEST_LINK` (least similar pair of each event — likely false merges), `INTRA_CLUSTER_CROSS_PUB`, `INTRA_CLUSTER_SAME_PUB`, and `INTER_CLUSTER_NEAR` = pairs from *different* events with the smallest cosine distance inside the time window (likely false splits). Sampling is seeded and deterministic.

## Result on the frozen input (default setting)

- 1,223 articles → 985 events: 174 multi-article events (412 articles) and 811 singleton events.
- 26 events span ≥ 2 publishers; largest event 7 articles; max span 5.0 days.
- Duplicate families collapsed: 2 (4 articles) → 1,221 clustering units.

## Known limitations

- **Precision is unmeasured** until the QC pairs are labelled.
- **Recurring formats merge.** Daily series such as "Dự báo thời tiết d/m" share wording, so several days of forecasts can land in one event (e.g. the largest event, 7 forecast/weather articles over ~5 days). The dates in these titles are an obvious feature the embedding does not use.
- **Corpus is dominated by one publisher** (`vietnamnet.vn` ≈ 82% of rows, 2 international articles), so most events are single-publisher and cross-community conclusions are weak.
- Duplicate-family signal from Phase 2B is very sparse (4 articles), so family collapsing changes little on this snapshot; the mechanism is tested on synthetic data.
- Similarity uses title + description only (no article bodies).
- Dense O(n²) distance matrices: fine for ~10³ articles, needs blocking for much larger corpora.

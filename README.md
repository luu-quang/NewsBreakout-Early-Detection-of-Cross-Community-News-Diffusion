# NewsBreakout
Early Detection of Cross-Community News Diffusion

## 1. Project Overview
One short paragraph explaining:
- collect Vietnam-related news
- domestic + international publishers
- remove duplicate/syndicated copies
- reconstruct real-world events
- analyze publisher co-reporting
- midterm = descriptive/feasibility
- final = possible breakout prediction

## 2. Research Motivation
Why raw article counts are misleading because of syndication.

## 3. Midterm Research Questions
RQ1: How much raw volume is duplicate/syndicated?
RQ2: How broadly are events independently covered?
RQ3: Which publishers frequently co-report the same events?
RQ4: How much event information is visible after 15/30/60 min?

## 4. Midterm Pipeline
Collection
→ normalization
→ relevance
→ deduplication
→ event clustering
→ publisher analysis
→ figures

## 5. Data Sources
Prefer direct publisher RSS for domestic and international coverage whenever available. GDELT is supplementary discovery or a fallback when a usable direct feed is unavailable.

`publisher` identifies the news outlet; `source_system` identifies the collection path. For example, a Reuters article discovered through GDELT still has Reuters as its publisher.

## 6. Common Data Schema
The frozen Phase 1 contract is defined in the [shared team workspace](team_work/phases/phase1_collection_cleaning/README.md#shared-data-contract-frozen). Important fields include:

```text
article_id
title
url
publisher_domain
publisher_id
source_system
first_seen_at
published_at
language
branch
collection_mode
vietnam_relevance
duplicate_family_id
raw_payload_ref
```

- `first_seen_at`: when our collector first observed the article URL; preserve it across repeat observations.
- `published_at`: publisher-reported publication time only; leave null if unavailable. Never substitute collector time or GDELT `seendate`.
- `source_seen_at`: auxiliary source observation time, such as GDELT `seendate`, retained in raw/audit metadata when available; it is not a required column in the shared 20-column export.
- `vietnam_relevance`: whether the article substantively concerns Vietnam. Both teams share this meaning but use source-aware rule-based heuristics. A domestic publisher does not imply `True`.

Preserve raw/candidate records before final relevance filtering. Keep both `True` and `False` rows in an auditable cleaned candidate table; derive relevant-only outputs from it. Keep `prospective` collection separate from `historical_backfill`.

## 7. 48-Hour Pilot
Once both live collectors are healthy and pre-pilot requirements are complete, the team lead records one shared `T_start` as an ISO 8601 UTC timestamp for both teams. The official pilot window is `[T_start, T_start + 48 hours)`, selected by `first_seen_at` with `collection_mode = prospective`. Warm-up observations and `historical_backfill` remain preserved separately and do not count toward pilot results; do not reset existing first-seen times at the boundary.

International `raw_payload_ref` remains unfinished and must be completed and checked before the pilot. A/B/C/HOLD determines international scope only.

## 8. Midterm Deliverables
8 required findings
100-pair clustering sanity check
pilot report
figures
processed datasets

## 9. Repository Structure
data/
src/
notebooks/
figures/
config/

## 10. How to Run
install requirements
run collectors
run pilot_report
later run processing notebooks

## 11. Scope
Phase 1 stops after collection, basic cleaning, relevance audit, and compatible outputs. Event clustering, graph analysis, and prediction belong to later phases; the broader midterm scope below does not authorize them in Phase 1.

### In scope
dedup
event clustering
publisher co-reporting
descriptive analysis

### Out of scope for midterm
prediction
GNN
fake-news classification
causal influence
online event discovery

## 12. Future Direction
Given early observations of an event,
predict whether it later expands into new publisher communities.

Phase 1 relevance quality is a prerequisite for this early breakout-risk prediction: missed early articles can shift observed event onset and publisher diversity, while irrelevant inclusions can distort later clusters and apparent cross-community spread. Audit both relevance classes before downstream modeling; collector observation time is not proof of an event's true start time.

## 13. Limitations
timestamp quality
syndication detection imperfect
event clustering approximate
international volume may be sparse

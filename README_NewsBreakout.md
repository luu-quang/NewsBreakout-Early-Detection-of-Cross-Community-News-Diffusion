# NewsBreakout

**Early Prediction of Cross-Community News Expansion**

NewsBreakout is a Data Science project for monitoring multi-source news streams, discovering emerging news events **causally**, and studying whether events observed during their earliest stage later expand into previously unrepresented publisher communities.

The project is designed around a strict temporal protocol so that all features used for prediction are available **before** the future outcome occurs.

> **NewsBreakout is not a fake-news classifier and is not generic popularity prediction.**  
> The main research question is whether early event signals and historical publisher-network context can help predict future cross-community expansion.

---

## 1. Research Question

> **Given a news event discovered causally from a multi-source article stream, can its future expansion into previously unrepresented publisher communities be predicted from its first 30 minutes, and do historical publisher-network features improve prediction beyond early volume, timing, source diversity, publisher identity, and textual content?**

Main scientific comparison:

```text
Early non-network signals
        vs
Early non-network signals + Historical publisher-network features
```

---

## 2. Core Idea

Suppose a new event begins appearing in the news stream.

During the first 30 minutes:

```text
09:00  Article A — Publisher 1
09:08  Article B — Publisher 2
09:21  Article C — Publisher 3
```

At that point, the system asks:

> Will this event later spread into publisher communities that were not represented during the first 30 minutes?

The prediction target is therefore **future incremental community expansion**, not simply future article count.

---

## 3. Why Event-Level Analysis?

The project uses the **news event** as the main unit of analysis.

An article is too narrow because multiple publishers can cover the same real-world event.

A broad topic is too large because one topic can contain many different events.

Example:

```text
Topic:
Banking

Events:
- Bank X ATM outage
- Bank Y quarterly earnings
- Bank Z merger announcement
```

NewsBreakout therefore models:

```text
Articles
   ↓
Online event discovery
   ↓
Event snapshots
   ↓
Future cross-community expansion
```

---

## 4. Temporal Protocol

The most important design rule is that **future information must never enter the features**.

For each event:

```text
T0
│
├──────── Observation Window ────────┐
│                                    │
│      Model may only use this       │
│                                    │
└────────────────────────────────────┘
                                     │
                                     ├──── Prediction Window ────>
```

### Primary experimental setting

```text
T0
= first time a deduplicated article creates a new online event cluster

Observation window
= first 30 minutes

Prediction horizon
= next 6 hours
```

Robustness experiments may also use:

```text
Observation:
30 min / 60 min

Prediction:
6 h / 24 h
```

For historical GDELT experiments, the clock is interpreted as:

> **time since the event was first observable in the GDELT monitoring stream**

not necessarily exact publication time.

---

## 5. Breakout Definition

Let:

```text
C_obs
= publisher communities observed during the early window

C_pred
= publisher communities appearing during the future prediction window
```

The main target is based on:

```text
new communities = C_pred - C_obs
```

A candidate starting definition is:

```text
Breakout = 1
if the event gains:

>= 2 new publisher communities
AND
>= 5 new independent publisher domains
```

These thresholds are **not fixed yet**.

Before final modeling, they must be selected using training-period feasibility analysis and then frozen before validation/test evaluation.

Events that have already broken out during the observation window must **not** be included as ordinary positive prediction samples.

---

## 6. Overall Workflow

```text
MULTI-SOURCE NEWS
GDELT / RSS / Public APIs
        │
        ▼
1. DATA COLLECTION
        │
        ▼
2. TIMESTAMP NORMALIZATION
        │
        ▼
3. PUBLISHER NORMALIZATION
        │
        ▼
4. DUPLICATE / SYNDICATION HANDLING
        │
        ▼
5. ONLINE EVENT DISCOVERY
        │
        ▼
6. EVENT SNAPSHOTS
        │
        ▼
7. HISTORICAL PUBLISHER GRAPH
        │
        ▼
8. SOURCE COMMUNITIES
        │
        ▼
9. FEASIBILITY ANALYSIS
        │
        ▼
10. VISUALIZATION
        │
        ▼
──────────── MIDTERM ────────────
        │
        ▼
11. FEATURE EXTRACTION
        │
        ▼
12. DATA ANALYSIS
        │
        ▼
13. MACHINE LEARNING
        │
        ▼
14. CROSS-COMMUNITY BREAKOUT PREDICTION
```

---

## 7. Data Sources

### GDELT — primary historical/replay backbone

GDELT is used as the main historical/replay source because it provides large-scale, multi-publisher news monitoring and historical archives.

Important:

```text
GDELT timestamp
may represent:
- exact publication time for some records
- first-seen time by GDELT for others
```

Therefore, historical experiments must be described using **GDELT first-seen/system time** unless exact publication time is explicitly available.

### RSS — prospective validation

RSS feeds are useful because the project controls the polling time.

This provides a clean system-level timestamp:

```text
first_seen_at
```

RSS is useful for:
- prospective collection,
- real-time validation,
- checking event behavior outside historical replay.

### CC-NEWS — auxiliary historical text source

CC-NEWS may be useful for:
- historical article text,
- publisher profiling,
- language/topic analysis,
- optional full-text experiments.

It is **not** the primary source for strict 15/30-minute replay because crawl time is not equivalent to reliable publication time.

### Event Registry — external reference only

Event Registry may be used as an external reference for evaluating clustering quality.

It should **not** be used as the main event source because event grouping is part of the project's own contribution.

---

## 8. Common Article Schema

All incoming sources must be normalized into one common format.

### Core fields

```text
article_id
title
url
publisher_domain
source_system
first_seen_at
```

### Strongly preferred

```text
published_at
language
description
```

### Additional engineering fields

```text
last_seen_at
timestamp_confidence
duplicate_family_id
publisher_id
event_id_at_time
embedding_reference
```

Example:

```text
article_id: a91f...
title: "Bank X reports temporary ATM outage"
url: https://example.com/...
publisher_domain: example.com
source_system: gdelt
published_at: 2026-09-12 09:01
first_seen_at: 2026-09-12 09:04
language: en
duplicate_family_id: dup_0041
```

---

## 9. Why a Common Schema?

Different sources may expose equivalent information using different field names.

Example:

```text
GDELT:
domain

RSS:
publisher

API:
source.name
```

NewsBreakout normalizes all of them into:

```text
publisher_domain
```

This allows all downstream stages to operate on one stable dataset.

---

## 10. Duplicate and Syndication Handling

Deduplication happens **before event discovery**.

Without it:

```text
1 original wire article
        ↓
copied by 10 websites
```

may incorrectly appear to be:

```text
10 independent articles
```

This can create artificial breakout signals.

Planned pipeline:

```text
URL canonicalization
        ↓
exact URL deduplication
        ↓
exact-title deduplication
        ↓
near-duplicate detection
        ↓
duplicate family assignment
        ↓
event discovery
```

Possible near-duplicate methods:
- normalized title matching
- n-gram similarity
- MinHash / SimHash
- high-threshold semantic similarity

Important distinction:

```text
same/syndicated copy
≠
independent reporting of the same event
```

Duplicate copies should remain traceable through:

```text
duplicate_family_id
```

---

## 11. Text Representation

The main experiment should avoid mixing:

```text
full body for some sources
+
title only for other sources
```

because text availability and document length may become unintended source-specific signals.

Preferred representations:

```text
Primary:
title + description

Fallback:
title only

Optional robustness:
full body on a consistently available subset
```

---

## 12. Online Event Discovery

NewsBreakout must discover events **causally**.

Incorrect:

```text
collect full day
        ↓
cluster full day
        ↓
go back to first 30 minutes
```

This leaks future information.

Correct:

```text
article arrives
      ↓
retrieve recent candidate events/articles
      ↓
semantic + temporal similarity
      ↓
assign to compatible existing event
OR
create a new event
```

Primary design:

```text
incoming article
        ↓
ANN candidate retrieval
        ↓
semantic similarity
+
temporal compatibility
        ↓
similar enough?
    /           \
  yes            no
   ↓              ↓
existing       new event
event
```

Fixed Top-K is **not** the event definition.

Top-K may be used only for candidate retrieval.

The main event assignment should use a similarity threshold and temporal constraints.

---

## 13. Event Snapshot Table

Every event will be recorded at fixed observation times.

Example fields:

```text
event_id
T0
snapshot_time
n_articles
n_domains
n_duplicate_families
n_source_communities
arrival_rate
mean_interarrival_time
text_centroid_reference
```

The snapshot must contain only information known at that exact time.

---

## 14. Historical Publisher Graph

The main graph is **not** the tiny internal graph of a new event.

It is a background graph built from historical news coverage.

### Nodes

```text
publisher domains
```

### Edge meaning

Two publishers receive stronger connection weight if they independently covered many of the same previous events.

Candidate normalized edge weight:

```text
w_ij = N_ij / sqrt(N_i * N_j)
```

where:

```text
N_i
= number of historical events covered by publisher i

N_j
= number of historical events covered by publisher j

N_ij
= number of historical events covered by both
```

The exact graph definition may be refined during the project.

---

## 15. Source Communities

After building the historical publisher graph, a graph community-detection algorithm such as Leiden can partition publishers into structural communities.

Example:

```text
Community 0
Community 1
Community 2
Community 3
```

The project should not manually assume that these communities equal:

```text
sports
finance
politics
technology
```

Interpretation happens **after** the communities are discovered.

---

## 16. Historical Publisher Features

Publisher-level graph features may include:

```text
degree / strength
PageRank
community ID
participation coefficient
bridge score
historical cross-community reach
historical event count
```

These features must be calculated using only historical information available before the current prediction time.

For an early event, publisher features can be aggregated:

```text
max publisher PageRank
mean participation coefficient
max participation coefficient
fraction of bridge publishers
number of historical source communities represented
```

---

## 17. Why Not Use Event-Internal Graph Features First?

During the first 30 minutes, many events may contain only:

```text
2
3
4
```

articles.

For such tiny graphs:

```text
density
betweenness
clustering coefficient
bridge ratio
```

may be trivial, unstable, or undefined.

Therefore, event-internal graph features are treated as an **ablation / research question**, not the main representation.

---

## 18. Midterm Scope

The midterm focuses on:

```text
Data Engineering
+
Visualization
+
Feasibility Analysis
```

### Required midterm outputs

#### Data Engineering
- multi-source ingestion
- common schema
- timestamp normalization
- publisher normalization
- raw storage
- exact deduplication
- near-duplicate / syndication analysis
- Parquet datasets
- event snapshots

#### Event pipeline
- causal online event discovery prototype
- event clustering validation
- event snapshot generation

#### Historical graph
- publisher co-reporting network
- publisher communities
- graph statistics
- graph cutoff date for leakage auditing

#### Feasibility analysis

Before ML, measure:

```text
How many events have:

2 articles after 30 min?
3?
5?
10+?

How many gain:
1 new community?
2?
3?

How many gain:
3 / 5 / 10 new independent publishers?
```

The project should estimate:

```text
P(breakout)
```

before deciding the final classification target.

---

## 19. Midterm Visualizations

Recommended visualizations:

### Data quality funnel

```text
Raw records
    ↓
Exact duplicates removed
    ↓
Near-duplicates grouped
    ↓
Independent usable articles
```

### Early event-size distribution

```text
articles available at:
15 min
30 min
60 min
```

### Publisher ecosystem graph

Show:
- historical publisher graph
- communities
- bridge publishers

### Event trajectory

```text
T0
 ↓
+30 min
 ↓
+1 h
 ↓
+3 h
 ↓
+6 h
```

with article/publisher points colored by historical source community.

### Breakout prevalence surface

Compare:

```text
community threshold
publisher threshold
observation window
prediction horizon
```

against:

```text
positive-class prevalence
```

### Syndication impact

Compare:

```text
event size before deduplication
vs
event size after deduplication
```

---

## 20. Final Feature Families

### Early temporal features

```text
early article count
unique publisher count
arrival rate
interarrival statistics
growth in short time bins
```

### Early source-diversity features

```text
publisher entropy
language diversity
country diversity
historical community coverage
```

### Text features

```text
title/description embedding
semantic novelty
early content diversity
```

### Historical publisher features

```text
degree
strength
PageRank
participation coefficient
bridge score
historical cross-community reach
publisher event frequency
```

---

## 21. Baseline Models

The project should compare feature families before comparing complex algorithms.

### Baseline 0

```text
training-period prevalence
```

### Baseline 1

```text
early volume
+
unique publishers
```

### Baseline 2

```text
volume
+
timing
+
source diversity
```

### Baseline 3

```text
+
text representation
```

### Baseline 4

```text
+
publisher identity/history
```

### Main model

```text
+
historical publisher-network features
```

Possible algorithms:

```text
Logistic Regression
Random Forest
XGBoost / LightGBM
```

A GNN is not required for the primary study.

---

## 22. Main Ablation

The most important comparison is:

```text
Early non-network features
```

vs

```text
Early non-network features
+
Historical graph features
```

This directly answers the central research question.

---

## 23. Evaluation

If breakout is imbalanced, the primary metric should emphasize positive-class performance.

Recommended metrics:

```text
PR-AUC
ROC-AUC
Precision
Recall
F1-score
Brier score / calibration
Precision@K
Lift over prevalence
```

Chronological train/validation/test splitting is mandatory.

---

## 24. Leakage-Safe Split

Do **not** randomly split events.

Use chronological blocks:

```text
TRAIN
earliest period
      ↓
VALIDATION
later period
      ↓
TEST
latest period
```

The historical publisher graph used for validation/test must be built only from past data.

Primary graph protocol:

```text
build graph from training history
        ↓
freeze graph
        ↓
use same frozen graph for validation/test
```

A later robustness experiment may update the graph causally.

---

## 25. Leakage Rules

Never use:

```text
final event cluster
final event article count
final publisher count
future publisher identities
future community count
future event centroid
future duplicate family size
graph centrality built from future data
community partition built from future data
test data to tune thresholds
```

All preprocessing that learns from data must be fitted on training/history only.

---

## 26. Event Clustering Validation Gate

Before building the breakout model, the project must validate event quality.

Order:

```text
EVENT CLUSTERING QUALITY
        ↓
HISTORICAL SOURCE GRAPH
        ↓
BREAKOUT LABEL
        ↓
PREDICTION
```

Possible clustering evaluation:
- pairwise precision / recall / F1
- B-cubed scores
- manually annotated same-event / different-event pairs
- difficult examples:
  - same topic, different event
  - same event, different wording
  - syndicated copies
  - multilingual coverage

If event discovery is unreliable, later breakout results are not trustworthy.

---

## 27. Class-Imbalance Feasibility Gate

Before model training, create a prevalence map over candidate definitions.

Example:

```text
community threshold:
1 / 2 / 3

publisher threshold:
3 / 5 / 10

prediction horizon:
3 h / 6 h / 24 h
```

If the positive class is extremely rare, the project may pivot to:

```text
number of new communities reached
```

or:

```text
time to first cross-community adoption
```

without discarding the DE/event pipeline.

---

## 28. Out of Scope

NewsBreakout does **not** attempt to:
- classify news as true or false
- perform automated fact checking
- censor or remove content
- predict public importance
- predict social-media virality directly
- prove causal influence between publishers
- treat co-reporting edges as causal diffusion links

---

## 29. Midterm vs Final

### Midterm

```text
Collection
    ↓
Standardization
    ↓
Deduplication
    ↓
Online event discovery
    ↓
Historical publisher graph
    ↓
Feasibility analysis
    ↓
Visualization
```

### Final

```text
Event snapshots
    ↓
Feature extraction
    ↓
Data analysis
    ↓
Baseline models
    ↓
Historical graph model
    ↓
Ablation
    ↓
Breakout prediction
```

---

## 30. Current Development Order

### Phase 1 — Data collection

- [x] Initial GDELT RSS prototype
- [ ] Evaluate additional RSS sources
- [ ] Evaluate additional public APIs / aggregators
- [ ] Define final common schema
- [ ] Preserve raw records

### Phase 2 — Cleaning

- [ ] URL canonicalization
- [ ] Publisher canonicalization
- [ ] Exact duplicate handling
- [ ] Near-duplicate detection
- [ ] Duplicate family IDs
- [ ] Data-quality report

### Phase 3 — Event discovery

- [ ] Embedding representation
- [ ] Temporal candidate window
- [ ] ANN candidate retrieval
- [ ] Similarity-threshold assignment
- [ ] Event start time T0
- [ ] Event snapshot table
- [ ] Clustering validation

### Phase 4 — Historical publisher graph

- [ ] Historical event co-reporting edges
- [ ] Normalize edge weights
- [ ] Detect publisher communities
- [ ] Compute publisher graph features
- [ ] Save graph cutoff date

### Phase 5 — Midterm feasibility

- [ ] Event-size distribution at 15/30/60 min
- [ ] Syndication impact
- [ ] Community expansion distribution
- [ ] Positive-class prevalence
- [ ] Visualize event trajectories

### Phase 6 — Final modeling

- [ ] Freeze label definition
- [ ] Chronological split
- [ ] Non-network baselines
- [ ] Text baseline
- [ ] Publisher-history baseline
- [ ] Historical-graph model
- [ ] Ablation
- [ ] Calibration and evaluation

---

## 31. Repository Structure

```text
NewsBreakout/
│
├── README.md
├── requirements.txt
├── .gitignore
│
├── config/
│
├── data/
│   ├── raw/
│   ├── interim/
│   └── processed/
│
├── src/
│   ├── ingestion/
│   ├── preprocessing/
│   ├── deduplication/
│   ├── embeddings/
│   ├── events/
│   ├── graph/
│   ├── features/
│   ├── models/
│   └── visualization/
│
├── notebooks/
│   ├── data_quality/
│   ├── event_discovery/
│   ├── graph_analysis/
│   └── modeling/
│
├── figures/
│
└── tests/
```

---

## 32. One-Sentence Summary

> **NewsBreakout causally discovers emerging news events from multi-source streams and tests whether historical publisher-network context improves early prediction of future cross-community source expansion.**

---

## 33. Current Project Status

The project is currently in:

```text
PHASE 1:
DATA COLLECTION
```

Immediate goal:

```text
find reliable sources
        ↓
test real ingestion
        ↓
compare available fields
        ↓
standardize output
        ↓
preserve timestamped raw data
```

No final graph architecture, breakout threshold, or ML model should be locked before the feasibility and clustering-validation stages are completed.

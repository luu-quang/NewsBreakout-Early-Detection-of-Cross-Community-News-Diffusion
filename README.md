# NewsBreakout

**Early Detection of Cross-Community News Diffusion**

NewsBreakout is a Data Science project that monitors news from multiple public sources, discovers emerging semantic events, and analyzes how those events begin spreading across the wider information ecosystem.

The long-term goal is to predict whether a small emerging event is likely to **break out across multiple news communities before it becomes obviously popular**.

> This project is **not a fake-news classifier**.  
> It focuses on **early event discovery, structural diffusion, and breakout prediction**.

---

## 1. Project Motivation

Thousands of news articles are published continuously. Most disappear quickly, while a small number spread across many publishers, topics, and information communities.

Traditional popularity forecasting often starts with a news item that is already known and predicts its future engagement.

NewsBreakout starts earlier:

```text
Whole news stream
      ↓
Discover an emerging semantic event
      ↓
Observe its early structural footprint
      ↓
Track how it moves across source communities
      ↓
Predict whether it will break out later
```

The intended use case is an **early-warning / prioritization system** that can help analysts notice potentially important information events before they become widely discussed.

---

## 2. Research Question

> **Can the early semantic and graph structure of an emerging news event predict whether it will later spread across the wider information ecosystem?**

A key hypothesis is that structural information may provide predictive value beyond simple temporal signals such as article count or growth rate.

---

## 3. Midterm Scope

The midterm focuses on:

- Data Engineering
- Multi-source news collection
- Data cleaning and normalization
- Text embeddings
- Semantic similarity
- Top-K nearest-neighbor graph construction
- Event discovery / clustering
- Source-community construction
- Temporal event snapshots
- Graph and event visualization

The midterm does **not** require:

- Fake/real classification
- Fact verification
- Graph Neural Networks
- Final breakout prediction model

The objective is to create a reliable data and representation pipeline that can be reused directly in the final project.

---

## 4. Final Scope

The final project extends the midterm pipeline with:

- Data Analysis
- Structural feature extraction
- Temporal feature extraction
- Semantic feature extraction
- Event-level feature matrix
- Machine Learning
- Ablation / feature-family comparison
- Future breakout prediction

Planned comparison:

```text
Temporal features only
        vs
Semantic features only
        vs
Graph features only
        vs
Temporal + Semantic + Graph
```

Possible models:

- Logistic Regression
- Random Forest
- XGBoost / LightGBM

A Graph Neural Network may be considered later only if there is a clear experimental reason to use one.

---

## 5. System Architecture

```text
MULTIPLE NEWS SOURCES
GDELT / RSS / APIs / Public News Sources
              │
              ▼
      DATA COLLECTION
              │
              ▼
        RAW STORAGE
              │
              ▼
   CLEAN + STANDARDIZE
              │
              ▼
       TEXT EMBEDDING
              │
              ▼
 SEMANTIC TOP-K RETRIEVAL
              │
              ▼
      ARTICLE GRAPH
              │
              ▼
       EVENT DISCOVERY
              │
              ▼
   SOURCE / COMMUNITY GRAPH
              │
              ▼
     TEMPORAL SNAPSHOTS
              │
              ▼
       VISUALIZATION
              │
              ▼
      EVENT FEATURE MATRIX
              │
              ▼
        DA + ML MODEL
              │
              ▼
 FUTURE BREAKOUT PREDICTION
```

---

## 6. Core Data Representation

### Article Schema

All collected articles should be normalized into a common schema.

Example fields:

```text
article_id
title
description
body
publisher
url
published_time
country
language
category
```

---

## 7. Semantic Representation

Articles may describe the same event using different wording.

Example:

```text
"Apple phone catches fire"

"iPhone battery explodes"

"New iPhone suffers overheating incident"
```

Keyword matching alone may fail.

Therefore, each article is converted into a semantic embedding:

```text
Article
   ↓
Embedding model
   ↓
Vector representation
```

Semantically related articles should have similar vectors.

---

## 8. Top-K Semantic Graph

For each article, retrieve its **Top-K most semantically similar recent articles**.

An edge is created only when:

```text
Article j ∈ Top-K(Article i)
AND
cosine_similarity(i, j) ≥ threshold
```

Graph interpretation:

- **Node** = article
- **Edge** = semantic relationship
- **Edge weight** = cosine similarity

Example:

```text
          Article B
             |
            0.91
             |
Article A ---+--- Article C
    0.88           0.86
```

A similarity threshold is required so that unrelated articles are not connected only because they happen to be among the nearest neighbors.

---

## 9. Event Discovery

Groups of strongly related articles form semantic **event clusters**.

Example:

```text
EVENT_001
Bank X withdrawal issue

A01 ── A02
 │    / │
A03 ── A04
```

The main unit of analysis becomes an **event**, rather than an individual article.

---

## 10. Information Communities

The project also models the wider news ecosystem.

Publishers or sources may form communities based on:

- Topic similarity
- Co-reporting behavior
- Citation / hyperlink relationships
- Semantic overlap
- Other source-level relationships

Example:

```text
[SPORT]        [FINANCE]       [POLITICS]

 ●──●            ●──●             ●──●
 │  │            │  │             │  │
 ●──●            ●──●             ●──●
```

An event may initially appear in one community and later spread into several others.

This process is called **cross-community breakout** in this project.

---

## 11. Example of Event Breakout

At an early stage:

```text
09:00

FINANCE
● ● ●
```

Later:

```text
10:00

FINANCE ───── GENERAL
● ● ●           ●
```

Later again:

```text
12:00

FINANCE ───── GENERAL ───── POLITICS
● ● ●          ● ●            ●
                 \
                  TECH
                   ●
```

The final ML task will try to predict this future breakout using only the early information available.

---

## 12. Event Feature Matrix

For Data Analysis and Machine Learning, every early event snapshot will be converted into one row of a feature matrix.

Example:

| Feature | Description |
|---|---|
| `early_volume` | Number of articles currently in the event |
| `unique_sources` | Number of publishers |
| `community_count` | Number of source communities already reached |
| `community_entropy` | Distribution of the event across communities |
| `graph_density` | Connectivity of the event graph |
| `avg_degree` | Average graph degree |
| `bridge_ratio` | Proportion of cross-community edges |
| `avg_betweenness` | Bridge-position information |
| `semantic_coherence` | Similarity among articles in the event |
| `semantic_novelty` | Difference from previously observed events |
| `growth_rate` | Early temporal growth |
| `cross_community_velocity` | Speed at which the event reaches new communities |

Example matrix:

```text
event_id | volume | sources | communities | entropy | bridge_ratio | ...
E001     |   8    |    3    |      1      |  0.12   |    0.05      |
E002     |  10    |    8    |      4      |  0.81   |    0.46      |
E003     |  11    |    4    |      2      |  0.31   |    0.11      |
```

---

## 13. Prediction Target

The final project will predict whether an early event later becomes a **cross-community breakout event**.

Possible formulation:

```text
Input:
Information available during the first 15 / 30 / 60 minutes

Output:
Probability that the event reaches multiple information communities
within the next 1 / 3 / 6 hours
```

Example:

```text
EVENT E002

Observed now:
10 articles
8 publishers
4 source communities

Model prediction:
82% probability of future breakout
```

---

## 14. Evaluation

The project should evaluate more than standard classification accuracy.

Candidate metrics:

- Accuracy
- Precision
- Recall
- F1-score
- ROC-AUC
- False alerts
- Breakout recall
- Lead time

### Lead Time

One important metric is how much earlier the system identifies an event compared with a conventional popularity threshold.

```text
Lead Time =
time conventional breakout is detected
-
time our model raises an alert
```

This directly supports the early-warning motivation of the project.

---

## 15. Team Workflow

### Member 1 — Data Engineering

Responsibilities:

- News-source collection
- API / RSS ingestion
- Common article schema
- Timestamp normalization
- Missing-value handling
- Deduplication
- Raw and processed storage

Expected output:

```text
data/processed/clean_articles.parquet
```

---

### Member 2 — NLP / Event Construction

Responsibilities:

- Text preprocessing
- Article embeddings
- Cosine similarity
- Top-K retrieval
- Similarity threshold experiments
- Event clustering

Expected outputs:

```text
data/processed/article_embeddings.*
data/processed/article_neighbors.*
data/processed/article_events.*
```

---

### Member 3 — Graph / Structural Analysis

Responsibilities:

- Article graph
- Source graph
- Community detection
- Graph statistics
- Bridge analysis
- Structural feature extraction

Expected outputs:

```text
data/processed/graph_edges.*
data/processed/source_communities.*
data/processed/graph_features.*
```

---

### Member 4 — Visualization / Integration

Responsibilities:

- Exploratory visualization
- Event timelines
- Graph visualization
- Community visualization
- Event diffusion visualization
- Event comparison
- Notebook / dashboard integration

Expected output:

```text
notebooks/
dashboard/
figures/
```

---

## 16. Team Rule

Everyone should understand the entire pipeline even if implementation work is divided.

```text
DATA
 ↓
EMBEDDING
 ↓
TOP-K
 ↓
GRAPH
 ↓
EVENT
 ↓
COMMUNITY
 ↓
VISUALIZATION
 ↓
FEATURE MATRIX
 ↓
DA
 ↓
ML
```

Each member's output must be compatible with the next stage.

Avoid building isolated notebooks with incompatible schemas or duplicated pipelines.

---

## 17. Proposed Repository Structure

```text
news-breakout/
│
├── README.md
├── requirements.txt
├── .gitignore
│
├── config/
│   └── config.yaml
│
├── data/
│   ├── raw/
│   ├── interim/
│   └── processed/
│
├── src/
│   ├── ingestion/
│   │   ├── collect_gdelt.py
│   │   ├── collect_rss.py
│   │   └── normalize.py
│   │
│   ├── preprocessing/
│   │   ├── clean_text.py
│   │   └── deduplicate.py
│   │
│   ├── embeddings/
│   │   ├── encode_articles.py
│   │   └── semantic_knn.py
│   │
│   ├── events/
│   │   └── build_events.py
│   │
│   ├── graph/
│   │   ├── build_article_graph.py
│   │   ├── build_source_graph.py
│   │   ├── detect_communities.py
│   │   └── graph_features.py
│   │
│   ├── features/
│   │   └── build_event_features.py
│   │
│   ├── models/
│   │   ├── baseline.py
│   │   └── breakout_model.py
│   │
│   └── visualization/
│       ├── timelines.py
│       └── network_plots.py
│
├── notebooks/
│   ├── 01_data_exploration.ipynb
│   ├── 02_event_analysis.ipynb
│   ├── 03_graph_analysis.ipynb
│   └── 04_modeling.ipynb
│
├── figures/
│
└── tests/
```

This structure may be simplified during the midterm and expanded for the final.

---

## 18. Current Development Roadmap

### Phase 1 — Data Pipeline

- [ ] Select news sources
- [ ] Build ingestion pipeline
- [ ] Define common schema
- [ ] Deduplicate articles
- [ ] Store clean timestamped data

### Phase 2 — Semantic Event Discovery

- [ ] Generate embeddings
- [ ] Implement cosine similarity
- [ ] Implement Top-K retrieval
- [ ] Tune similarity threshold
- [ ] Construct article graph
- [ ] Detect semantic events

### Phase 3 — Graph Analysis

- [ ] Construct source graph
- [ ] Detect source communities
- [ ] Calculate graph features
- [ ] Build event snapshots

### Phase 4 — Midterm Visualization

- [ ] News activity timeline
- [ ] Event graph
- [ ] Source/community graph
- [ ] Event diffusion visualization
- [ ] Event comparison dashboard

### Phase 5 — Final Data Analysis

- [ ] Create event feature matrix
- [ ] Analyze structural variables
- [ ] Compare breakout vs non-breakout events
- [ ] Correlation / distribution analysis
- [ ] Define final prediction target

### Phase 6 — Final Modeling

- [ ] Temporal-only baseline
- [ ] Semantic-only model
- [ ] Graph-only model
- [ ] Combined model
- [ ] Feature ablation
- [ ] Evaluate lead time

---

## 19. Out of Scope

For the current project:

- Fake-news / real-news classification
- Automatic censorship or content removal
- Automatic fact verification
- Determining whether an article is objectively true
- Large-scale production deployment
- Building a new language model from scratch

Human analysts remain responsible for interpreting and verifying any event surfaced by the system.

---

## 20. One-Sentence Summary

> **NewsBreakout discovers small emerging news events from multi-source streams and analyzes their early semantic and graph structure to predict whether they will later spread across the wider information ecosystem.**

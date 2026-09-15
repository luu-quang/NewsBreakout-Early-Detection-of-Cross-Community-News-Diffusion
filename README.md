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
Domestic RSS
International RSS
GDELT
Explain:
publisher != source_system

## 6. Common Data Schema
Only important fields:
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

## 7. 48-Hour Pilot
Explain briefly:
- both live collectors healthy
- record T_start
- fixed 48h
- A/B/C/HOLD determines international scope only

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

## 13. Limitations
timestamp quality
syndication detection imperfect
event clustering approximate
international volume may be sparse

# Midterm analysis (Phase 2C → analysis)

Built **only** from the frozen handoff artifact `data/processed/master/articles_clustered.parquet`
(SHA-256 `90fd7938…12af`, checked at run time). Nothing in collection, dedup or clustering was changed;
model settings stay at 0.30 / 5 days / complete linkage.

Reproduce: `python -m src.analysis.midterm_analysis` (code: `src/analysis/midterm_analysis.py`).

## Figure → source table

| Figure (`figures/`) | Source CSV (`tables/`) |
|---|---|
| `fig1_event_size_distribution.png` | `fig1_event_size_distribution.csv` |
| `fig2_publisher_articles_and_events.png` | `fig2_publisher_articles_and_events.csv` |
| `fig4_publisher_coreporting_network.png` | `fig4_publisher_coreporting_network.csv` (edge list; `weight_independent` is drawn) |
| `fig5_manual_qc_labels_and_failure_patterns.png` | `fig5_manual_qc_labels_and_failure_patterns.csv` (summary) ← `table5_qc_manual_labels.csv` (the 50 labelled pairs) |
| (table only) cross-publisher events | `table3_cross_publisher_events.csv` (required columns), `table3_cross_publisher_events_reviewed.csv` (+ manual verdict) |

Manual inputs (hand-entered, versioned): `manual_inputs/qc_labels.csv`, `manual_inputs/cross_publisher_event_review.csv`.
The frozen `event_clusters_qc.csv` is not edited; labels live in this folder and reference its row numbers.

## Findings

**Event sizes.** 985 events: 811 singletons (82.3%) and 174 multi-article (17.7%). Sizes: 1→811, 2→135, 3→24, 4→8, 5→5, 6→1, 7→1. Most stories are seen by one article only.

**Publishers.** `vietnamnet.vn` has 1,000 of 1,223 articles (81.8%; HHI 0.68); the other four Vietnamese publishers have 36–84 each and `asia.nikkei.com` has 2. Vietnamnet also has 802 distinct events, but only 15 events (1.8% of its articles) are cross-publisher, versus 19–22% of articles for dantri, thanhnien, tuoitre and vnexpress. The corpus is a Vietnamnet-heavy sample, not a balanced multi-publisher one.

**Cross-publisher events (26).** Manual inspection: 15 clearly the same event, 3 plausible, 3 mixed (partly correct), 5 different events wrongly merged — about 69% good or plausible. Cleanest examples are events with 3 publishers reporting within hours: Quảng Ngãi ore carrier (`evt_28284fada5b7`), Chợ Quán car-into-crowd arrests (`evt_13986f343684`), "Tang Monk" clip (`evt_61e7f2ae8669`), THPT computer-exam pilot (`evt_73749c945b8d`). Failures are same-topic-different-event merges (`evt_97dfc8706783` volleyball vs handball at the same Asiad; `evt_bd8426ef24d4` Thanh Hóa flood vs Nha Trang dam; `evt_d980a91d4492` Nghệ An landslide + a Thanh Hóa crack; `evt_690a478e4007` weather forecasts).

**Co-reporting network.** 5 Vietnamese publishers are all pairwise connected (10 edges); `asia.nikkei.com` is isolated. Raw weights follow publisher size (dantri–vietnamnet 8 is the top edge); normalised by the smaller publisher's event count the strongest pair is dantri–tuoitre (13%). Edges exclude Phase 2B duplicate copies (dantri–vnexpress 3 → 2, because `evt_9e8c7c964cbd` is a syndicated family). With only 26 events and 6 nodes this is descriptive; no direction, no influence or copying claim.

**Manual QC (50 pairs, provisional).** Weakest links: 11 same event / 13 different / 6 uncertain → ~43% of the worst pair inside an event are false-merge candidates (worst-case sample, not the overall error rate). Nearest cross-event pairs: 8 of 20 are the same event (false splits), 12 correct splits. Failure patterns over the 50 pairs: weather series 15, same-type incidents (accidents/crimes/fires, different cases) 10, same story fragmented 8, same topic but different event 6, news digests 2. Weather is the dominant recurring problem in **both** directions: daily forecasts and storm updates are sometimes merged across days and sometimes correctly split, so weather clusters are not reliable events. Other splits: the tailgating-fine rollout, storm no.4, the 14–15/9 Hanoi rain night and the ASEAN Cup celebration were split into separate events. No catastrophic failure that justifies changing thresholds tonight.

## Caveats

- QC labels and cross-publisher verdicts were assigned by an AI reviewer reading titles and descriptions; they are a screening pass, not human ground truth. A teammate should spot-check them (especially the UNCERTAIN and MIXED rows) before quoting precision figures.
- QC strata are targeted (worst links / nearest pairs), so the percentages describe those samples only.
- `first_published_at` = earliest `published_at` in the event (fallback `first_seen_at` if missing, as in Phase 2C).

# Midterm analysis (Phase 2C → analysis)

Built **only** from the frozen handoff artifact `data/processed/master/articles_clustered.parquet`
(SHA-256 `90fd7938…12af`, checked at run time). Nothing in collection, dedup or clustering was changed;
model settings stay at 0.30 / 5 days / complete linkage.

Reproduce: `python -m src.analysis.midterm_analysis` (code: `src/analysis/midterm_analysis.py`).

## Review status

**All labels in this folder are AI-assisted and have NOT yet been checked by a human.** This covers the 50 provisional QC pairs (`manual_inputs/qc_labels.csv`) and the 26 cross-publisher event verdicts (`manual_inputs/cross_publisher_event_review.csv`). A second AI pass over the 17 flagged rows (6 uncertain QC pairs + 11 non-SAME cross-publisher events) exists in `human_review_flagged_17.csv`, but a second AI pass is not human validation. The human review of those 17 rows is pending (`human_review_flagged_17_blind.csv`; `human_label` and `reviewer` are still empty); results and agreement will be added here once available. Until then, treat every label and every count derived from them as provisional.

## Figure → source table

| Figure (`figures/`) | Source CSV (`tables/`) |
|---|---|
| `fig1_event_size_distribution.png` | `fig1_event_size_distribution.csv` |
| `fig2_publisher_articles_and_events.png` | `fig2_publisher_articles_and_events.csv` |
| `fig4_publisher_coreporting_network.png` | `fig4_publisher_coreporting_network.csv` (edge list; `weight_independent` is drawn) |
| `fig5_manual_qc_labels_and_failure_patterns.png` | `fig5_manual_qc_labels_and_failure_patterns.csv` (summary) ← `table5_qc_manual_labels.csv` (the 50 labelled pairs) |
| (table only) cross-publisher events | `table3_cross_publisher_events.csv` (required columns), `table3_cross_publisher_events_reviewed.csv` (+ AI-assisted screening verdict) |

Manual inputs (hand-entered, versioned): `manual_inputs/qc_labels.csv`, `manual_inputs/cross_publisher_event_review.csv`.
The frozen `event_clusters_qc.csv` is not edited; labels live in this folder and reference its row numbers.

## Findings

**Event sizes.** 985 events: 811 singletons (82.3%) and 174 multi-article (17.7%). Sizes: 1→811, 2→135, 3→24, 4→8, 5→5, 6→1, 7→1. Most stories are seen by one article only.

**Publishers.** `vietnamnet.vn` has 1,000 of 1,223 articles (81.8%; HHI 0.68); the other four Vietnamese publishers have 36–84 each and `asia.nikkei.com` has 2. Vietnamnet also has 802 distinct events. Vietnamnet appears in 15 cross-publisher events, involving 18/1000 articles (1.8%); for dantri, thanhnien, tuoitre and vnexpress the same share is 19–22% of their articles. The corpus is a Vietnamnet-heavy sample, not a balanced multi-publisher one.

**Cross-publisher events (26).** AI-assisted qualitative screening: 15 SAME_EVENT, 3 PLAUSIBLE, 3 MIXED (partly correct), 5 DIFFERENT (wrongly merged). The 15 SAME + 3 PLAUSIBLE out of 26 is **not a precision estimate**: it is one AI reviewer's screening of a small, non-random set, without human ground truth or a defined sampling design. Cleanest examples are events with 3 publishers reporting within hours: Quảng Ngãi ore carrier (`evt_28284fada5b7`), Chợ Quán car-into-crowd arrests (`evt_13986f343684`), "Tang Monk" clip (`evt_61e7f2ae8669`), THPT computer-exam pilot (`evt_73749c945b8d`). Failures are same-topic-different-event merges (`evt_97dfc8706783` volleyball vs handball at the same Asiad; `evt_bd8426ef24d4` Thanh Hóa flood vs Nha Trang dam; `evt_d980a91d4492` Nghệ An landslide + a Thanh Hóa crack; `evt_690a478e4007` weather forecasts).

**Co-reporting network.** 5 Vietnamese publishers are all pairwise connected (10 edges); `asia.nikkei.com` is isolated. Raw weights follow publisher size (dantri–vietnamnet 8 is the top edge); normalised by the smaller publisher's event count the strongest pair is dantri–tuoitre (13%). Edges exclude Phase 2B duplicate copies (dantri–vnexpress 3 → 2, because `evt_9e8c7c964cbd` is a syndicated family). With only 26 events and 6 nodes this is descriptive; no direction, no influence or copying claim.

**Provisional QC screening (50 pairs).** Weakest links: 11 same event / 13 different / 6 uncertain → ~43% of the worst pair inside an event are false-merge candidates (worst-case sample, not the overall error rate). Nearest cross-event pairs: 8 of 20 are the same event (false splits), 12 correct splits. Failure patterns over the 50 pairs: weather series 15, same-type incidents (accidents/crimes/fires, different cases) 10, same story fragmented 8, same topic but different event 6, news digests 2. Weather is the dominant recurring problem in **both** directions: daily forecasts and storm updates are sometimes merged across days and sometimes correctly split, so weather clusters are not reliable events. Other splits: the tailgating-fine rollout, storm no.4, the 14–15/9 Hanoi rain night and the ASEAN Cup celebration were split into separate events. No catastrophic failure that justifies changing thresholds tonight.

## Caveats

- QC labels and cross-publisher verdicts were assigned by an AI reviewer reading titles and descriptions; they are a screening pass, not human ground truth. No human has checked them yet (see Review status). Do not quote precision or error-rate figures from them until the human review of the flagged rows is done.
- QC strata are targeted (worst links / nearest pairs), so the percentages describe those samples only.
- `first_published_at` = earliest `published_at` in the event (fallback `first_seen_at` if missing, as in Phase 2C).

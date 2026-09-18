# NewsBreakout — Phase 1 International Team

## Goal
Collect Vietnam-related news from international publishers, perform basic cleaning/normalization, and deliver compatible, auditable outputs under the [shared Phase 1 data contract](../README.md#shared-data-contract-frozen).

Phase 1 stops before event clustering, graph construction/analysis, prediction, and final visualization. Working branch: `international`.

## Sources and collection
Prefer direct publisher RSS whenever a usable feed is available. Use GDELT as supplementary discovery/fallback, including for publishers without a usable direct feed. Record feed/query coverage and failures in source notes rather than treating a sparse stream as evidence of no news.

The publisher and collection system are different: a Reuters article discovered through GDELT retains its actual `publisher_domain` and `publisher_id`, with `source_system = gdelt_doc`. GDELT is not the publisher. Direct RSS uses `source_system = rss`.

Team code and review samples belong in `team_work/phases/phase1_collection_cleaning/international_team/code/` and `sample_output/`, respectively. Keep large raw archives out of Git; provide a small 20–100 row review sample with its collection mode clearly identified. Team-branch implementation status must be verified before the pilot; this contract does not assert that team code has been merged into the default branch.

## Timestamp contract
Normalize timestamps to UTC with explicit timezone information.

| Field | Meaning |
|---|---|
| `first_seen_at` | When our collector first observed the article URL. Preserve the earliest stored observation across repeated polls. |
| `published_at` | Publisher-reported publication time only; null if unavailable or unparseable. GDELT `seendate` is not publication time. |
| `source_seen_at` | Auxiliary source observation time, such as GDELT `seendate`, retained in raw/audit metadata when available. It is not required in the shared 20-column export. |

Never copy `source_seen_at` or `published_at` into `first_seen_at`, or fill missing publication time with collector time. Historical collection still records our actual observation time as `first_seen_at`.

## Relevance and preservation
`vietnam_relevance` has the same semantic meaning for both teams: the article substantively concerns Vietnam, not merely an incidental mention. The rule-based heuristics are source-aware rather than identical. International rules should use available title/description evidence, including Vietnam and relevant place/entity variants such as Hanoi or Ho Chi Minh City, while checking for unrelated regional stories or sidebar-only matches. Document limitations and manually review false positives and false negatives; a keyword match is not ground truth.

The Vietnamese team also evaluates relevance per article. A domestic publisher does not imply `vietnam_relevance=True`; publisher origin and relevance are independent.

Preserve all fetched raw/candidate records before final relevance filtering, including direct RSS entries without a literal "Vietnam" match. GDELT query constraints affect what can be discovered and must be documented. Keep a cleaned candidate/audit table containing both `True` and `False` rows, retain traceability to raw inputs, and record broken-row rejection reasons. Derive relevant-only outputs from that table without overwriting it. Review both classes, including articles whose Vietnamese place names appear without the word Vietnam.

Missing an early relevant article can shift observed event onset and publisher diversity. Irrelevant inclusions can distort later event clusters and apparent cross-community spread. Phase 1 relevance quality therefore supports later early breakout-risk prediction; it does not itself perform clustering or prediction.

## Shared output schema
The shared export has these 20 columns; auxiliary `source_seen_at` belongs in raw/audit metadata.

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

Use `branch = international`. Live collection uses `collection_mode = prospective`; deliberate retrospective collection uses `collection_mode = historical_backfill`. Keep their files, samples, and counts separate. Backfill may support review of sparse sources but must not count toward the prospective pilot. Leave unknown metadata null; syndication-family assignment belongs to a later phase.

## Shared 48-hour pilot
The team lead records one agreed ISO 8601 UTC `T_start` for both teams after collectors are healthy and pre-pilot requirements are complete. Apply the [shared pilot rules](../README.md#shared-48-hour-prospective-pilot): the fixed interval is `[T_start, T_start + 48 hours)`, with membership determined by `collection_mode = prospective` and `first_seen_at`, not publication time or GDELT observation time.

Retain both relevance classes in the pilot audit and derive the relevant-only view from it. Preserve but exclude warm-up observations before `T_start` and all historical backfill from official counts. Do not reset earlier first-seen times. Run collection repeatedly and record outages; a one-off sample cannot establish event-level 15/30/60-minute visibility, which also requires later clustering.

## Known unfinished work before the pilot
- **`raw_payload_ref` remains unfinished for international collection.** It is currently unpopulated (`None`); the normalized raw table is not an exact original GDELT/RSS payload archive. Before the pilot, preserve original source records and populate references so cleaned/audit rows can be traced to their exact input. Verify that references resolve. This documentation update does not implement that work.
- Source-aware relevance remains a heuristic with potential false positives and false negatives. Audit both classes and document source/query coverage limitations before downstream use.

## Pilot readiness checklist
- [ ] Reliable repeated collection and source coverage documented
- [ ] Raw/candidate records preserved before final relevance filtering
- [ ] Both `True` and `False` rows retained and reviewed
- [ ] Timestamp semantics and collection-mode separation verified
- [ ] Original payload preservation and `raw_payload_ref` completed and verified
- [ ] Small review sample and shared schema checked
- [ ] One shared `T_start` recorded with the Vietnamese team

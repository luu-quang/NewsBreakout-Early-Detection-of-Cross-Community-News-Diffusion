# Phase 2B — Independent duplicate / syndication method

Status: **frozen first version (2026-09-21), not yet compared** with the other implementation,
frozen at the leader's request before any comparison. Written without inspecting that
implementation, its notes, QC files, or assignments. Any later change must be a separate,
explicitly labeled commit made after the first comparison.

## Run

```bash
python team_work/phases/phase2_processing/phase2b_dedup_syndication/independent_impl/dedup_independent.py \
    --expect-sha256 b021a43395a46af3ca36586b1042b061c644e90a92178a9b9d5779c11ea156f3
python -m unittest test_dedup_independent -v     # from independent_impl/, 9 fixture tests
```

Dependencies: pandas + pyarrow only (already in `requirements.txt`). No randomness, no models.
Cost on the 1,223-row snapshot: about 1.4 s, ~270 MB peak; 26,547 candidate pairs scored.

## Snapshot identity

Input `data/processed/master/articles_master.parquet`, 1,223 rows, 480,461 bytes,
SHA-256 `b021a433…156f3` (matches the Phase 2A manifest). Each run records path, rows, size,
hash, UTC run date and code revision in `sample_output/dedup_run_summary_independent.json`.
The recorded revision is the frozen code commit `a27f8c1`. The `+uncommitted-changes` suffix in the summary is an
artifact: the script's dirty check also counts its own not-yet-committed output files, so it appears on
every run that produces new outputs; the code itself is identical to `a27f8c1` (verified by `git diff`).

## Method

1. **Text representation.** Only `title` and `description`. HTML entities unescaped
   (titles contain e.g. `&apos;`), NFC-normalized, lowercased, tags and punctuation removed.
   Vietnamese diacritics are **kept** (tone marks distinguish words). Tokens are whitespace
   syllables; features are **word bigrams** (a single token if the text has only one word).
2. **Exact duplicates first.** Identical normalized title *and* identical normalized
   description (two empty descriptions count as identical) → `EXACT_DUPLICATE`.
3. **Candidate generation / blocking.** Inverted index over word bigrams (title ∪ description).
   A pair becomes a candidate if it shares ≥ 2 bigrams; bigrams present in > 60 articles are
   treated as boilerplate and ignored. This scores 26,547 of 747,253 possible pairs.
4. **Evidence per pair.** Jaccard of title bigrams, Jaccard of description bigrams, Jaccard of
   digit-token sets, hours between `published_at` values (when both exist).
5. **Decision (evaluated in this order).**
   - Language mismatch (both known, different) → `UNRELATED` (cross-language is out of scope).
   - `SYNDICATED_COPY` requires **description evidence**: both descriptions ≥ 6 tokens and
     description Jaccard ≥ **0.60**, unless vetoed by (a) `published_at` more than 168 h apart,
     or (b) digit-token Jaccard < 0.5 when both sides contain numbers (different figures ⇒ a
     different report, e.g. a verdict vs the earlier prosecutor request). Vetoed pairs are
     reported as `SAME_EVENT_INDEPENDENT`.
   - Otherwise headline Jaccard ≥ 0.50 or description Jaccard ≥ 0.40 → `SAME_EVENT_INDEPENDENT`.
     This is a *proxy label for QC only*; real event grouping is Phase 2C.
   - Otherwise `UNRELATED`.
   Titles alone never create a family: outlets routinely give an official announcement
   near-identical headlines while writing their own text.
6. **Families.** Connected components (union-find) over accepted `EXACT_DUPLICATE` and
   `SYNDICATED_COPY` edges. Family id = `dupfam_` + first 12 hex of SHA-256 of the sorted
   member `article_id`s, so ids do not depend on row order. Families with ≥ 4 members or
   edge density < 0.5 are flagged for review (none exist in this snapshot). Singletons and
   independent reports keep `duplicate_family_id` null.
7. **Output.** `articles_dedup.parquet` (git-ignored): same rows, order and 19 other columns;
   only `duplicate_family_id` populated. Fails if the input schema/order differs from the
   frozen 20 columns or `article_id` is missing/duplicated.

## How the thresholds were chosen (and how weak that evidence is)

I scored all candidate pairs and read the descriptions of every pair with description
Jaccard ≥ 0.45 or title Jaccard ≥ 0.60 (~25 pairs). Description Jaccard fell into a visible gap:
the nearest non-copies were 0.56 (a daily weather bulletin with different dates) and 0.54
(two different arrests), while the two accepted pairs scored 0.74 and 1.00. 0.60 sits in that
gap. **This is a threshold picked from about two positive examples**, so it is a conservative
placeholder rather than a validated operating point; it favors precision over recall.

## Result on the snapshot

| Quantity | Value |
|---|---|
| Articles / in families / singletons | 1,223 / 4 / 1,219 |
| Families (exact / syndicated) | 2 (0 / 2), both size 2 |
| Largest family | size 2 |
| QC pairs (positives / borderline rejects / same-event / recall probes / controls) | 2 / 6 / 4 / 14 / 12 |

The corpus contains **no exact duplicates** (no two rows share a normalized title, or a
`canonical_url`), so stage 2 is exercised only by fixture tests. The two families are a
verbatim lede republished under a different headline (vietnamnet, ~9 h apart) and a near-verbatim
brief carried by Dân trí and VnExpress (~1 h apart).

## Known limitations and expected error modes

- **Titles + descriptions are a proxy for copying.** Two independently written ledes of the same
  official statement can look alike. Example flagged for review: Tuổi Trẻ / VnExpress / Thanh Niên
  on the 2027 computer-based exam (title Jaccard 0.69–0.83, description 0.19–0.40) is predicted
  `SAME_EVENT_INDEPENDENT`; if these are in fact copies of one government release, this method
  misses them (false negative). Conversely, a lede reused verbatim across independent reports
  of a quoted statement would be a false positive.
- **Small-sample thresholds** (see above). Expect recall to be low.
- **Numeric-conflict veto was not decisive on real data**: the weather and verdict pairs it
  targets were already below 0.60. It is covered by fixture tests only.
- **Chaining.** Components are transitive; a chain A~B, B~C could join A and C without direct
  similarity. Not observable here (all families are pairs); large/sparse families are flagged.
- **Cross-community syndication cannot be tested**: 1,221 of 1,223 rows are Vietnamese and only
  2 are international (language null), so domestic-vs-international copying is out of reach.
- **Whitespace syllable tokens** are used for Vietnamese; no word segmentation.
- **Missing/short descriptions** (2 rows empty) can never trigger a copy call except as exact match.
- `SAME_EVENT_INDEPENDENT` is a coarse QC proxy, not an event cluster.

## Determinism

No random numbers. Candidate pairs, edges, components, QC selection and family ids are ordered
by sorted positions or SHA-256 of ids (unrelated controls: articles sorted by
`sha256(article_id)`, consecutive ones paired). Each run analyzes the input twice and fails if
assignments differ; run summary records `rerun_identical_assignments`.

## Tracked artifacts

`sample_output/dedup_qc_pairs_independent.csv` (pair-level QC, `manual_relation` left blank for
a human reviewer), `dedup_family_summary_independent.csv`, `dedup_run_summary_independent.json`.
No `EXACT_DUPLICATE` positives or large-family QC rows exist because the data has none.

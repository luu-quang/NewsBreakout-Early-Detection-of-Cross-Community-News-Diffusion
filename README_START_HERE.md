# NewsBreakout — Start Here

This starter pack implements **Phase 1: news ingestion**.

## Goal

Before embeddings, Top-K graphs, event clustering, visualization, or ML, we need a reproducible stream of timestamped articles.

The first prototype uses GDELT's Global Article List RSS feed.

`first_seen_at` means **when our collector first observed the URL**. It is not assumed to be the publisher's original publication time.

Because the feed is a rolling window, the same URL may appear repeatedly. We deduplicate URLs while preserving:

- `first_seen_at`
- `last_seen_at`

## Setup

### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Collect one snapshot

```bash
python -m src.ingestion.collect_gdelt_rss
```

## Inspect collected data

```bash
python -m src.ingestion.inspect_data
```

## Current schema

| Column | Meaning |
|---|---|
| `article_id` | Stable URL-derived ID |
| `title` | Headline |
| `url` | Article URL |
| `publisher_domain` | Domain extracted from URL |
| `source` | Collection source |
| `first_seen_at` | First time our collector observed it |
| `last_seen_at` | Most recent time our collector observed it |

## First checkpoint

Before moving on, confirm:

1. The collector runs successfully.
2. `data/raw/gdelt_articles.parquet` is created.
3. Multiple publishers are present.
4. Running the collector twice does not duplicate the same URL.
5. `first_seen_at` stays fixed while `last_seen_at` can update.

## Next milestone

After this works:

1. add more sources,
2. improve deduplication,
3. enrich article metadata,
4. generate semantic embeddings,
5. build Top-K neighbors,
6. discover events.

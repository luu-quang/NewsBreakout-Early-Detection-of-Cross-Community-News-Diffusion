# NewsBreakout — Phase 1 Team Workspace

## Goal
Phase 1 is about **collecting and basic cleaning** of Vietnam-related news.

We split into two teams:
- Vietnamese team: Vietnamese publishers
- International team: international publishers covering Vietnam

Both teams must produce compatible outputs so the data can later be merged.

## Current workflow
```text
Vietnamese sources ─────┐
                        ├──> collect
International sources ──┘
                             ↓
                       basic cleaning
                             ↓
                       shared schema
                             ↓
                  review by team lead
```

Do not start event clustering, graph analysis, prediction, or final visualization yet.

## Shared rules
1. Preserve raw data.
2. Use automated collection when possible.
3. Do not commit large raw datasets to GitHub.
4. Commit only code, notes, and small sample outputs.
5. Both teams must follow the same schema.

## Shared schema
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

For live collection:
```text
collection_mode = prospective
```

Publisher branch:
```text
domestic
international
```

## Folder structure
```text
team_work/
└── phase1/
    ├── README.md
    ├── vietnamese_team/
    │   ├── README.md
    │   ├── code/
    │   └── sample_output/
    └── international_team/
        ├── README.md
        ├── code/
        └── sample_output/
```

## Phase 1 completion target
Each team should provide:
- working collector code
- several reliable sources
- a small 20–100 row sample
- basic cleaning/normalization
- documented known issues
- compatible schema

Once both sides are stable, the team lead starts the shared 48-hour prospective pilot.

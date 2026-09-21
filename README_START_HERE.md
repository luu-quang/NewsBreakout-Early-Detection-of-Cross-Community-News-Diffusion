# NewsBreakout — Start Here

This file is the shortest entry point to the current repository.

## 1. Project flow

```text
Phase 1 — collection + cleaning + relevance
        ↓
Phase 2A — master dataset integration
        ↓
Phase 2B — duplicate / syndication detection
        ↓
Phase 2C — event clustering
        ↓
Phase 3 — publisher co-reporting + descriptive analysis
        ↓
Phase 4 — report + presentation
```

Current status:

```text
Phase 1   complete
Phase 2A  complete
Phase 2B  in progress
Phase 2C  not started
```

## 2. Environment setup

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

## 3. Phase 1

The final Phase 1 team workspace is:

```text
team_work/phases/phase1_collection_cleaning/
```

Vietnamese implementation:

```text
team_work/phases/phase1_collection_cleaning/vietnamese_team/code/
```

International implementation:

```text
team_work/phases/phase1_collection_cleaning/international_team/code/
```

Phase 1 produces cleaned relevant-only outputs and audit outputs under `data/processed/`.

Large datasets are intentionally ignored by Git, except `data/processed/master/articles_master.parquet`, which is tracked as the frozen Phase 2A handoff snapshot.

## 4. Phase 2A — build the master dataset

Canonical implementation:

```text
src/integration/build_master.py
```

Run:

```powershell
python src/integration/build_master.py
```

Expected outputs:

```text
data/processed/master/articles_master.parquet
data/processed/master/articles_audit.parquet
```

The validated current master contains 1,223 relevant articles:

```text
1,221 domestic
2 international
```

The combined audit contains 1,444 rows:

```text
1,259 domestic
185 international
```

Current `articles_master.parquet` SHA-256:

```text
b021a43395a46af3ca36586b1042b061c644e90a92178a9b9d5779c11ea156f3
```

Detailed Phase 2A documentation:

```text
team_work/phases/phase2_processing/phase2a_master_integration/
```

## 5. Phase 2B — current work

Phase 2B receives:

```text
data/processed/master/articles_master.parquet
```

and annotates duplicate/syndication families without deleting rows.

Expected output:

```text
data/processed/master/articles_dedup.parquet
```

Teammate assignment:

```text
team_work/phases/phase2_processing/phase2b_dedup_syndication/README.md
```

The teammate implementation must use the same master snapshot and verify the SHA-256 before comparing methods.

## 6. Phase 2C

Event clustering has not started yet.

Phase 2C will use the dedup-annotated article corpus to determine which independent articles describe the same real-world event.

Do not treat duplicate families as event clusters.

## 7. Where to read next

For project overview:

```text
README.md
```

For Phase 1 contract:

```text
team_work/phases/phase1_collection_cleaning/README.md
```

For the current Phase 2 workflow:

```text
team_work/phases/phase2_processing/README.md
```

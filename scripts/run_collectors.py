#!/usr/bin/env python3
"""STABLE ENTRYPOINT for systemd - do not move or rename this file.

This is the one fixed path the collector-runner systemd service/timer points
at (see deploy/). Everything it calls (currently src/collect_v2/runner.py)
may be freely reorganized by later refactors (see "Phase 4" in
docs/HANDOFF_2026-09-26.md) as long as this file keeps living at
scripts/run_collectors.py and keeps working the same way.

Usage (identical to ``python -m src.collect_v2.runner``, which this wraps):

    python3 scripts/run_collectors.py --collector-host <host> [--fetch-timeout N] [--child-timeout M]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.collect_v2.runner import main  # noqa: E402

if __name__ == "__main__":
    main()

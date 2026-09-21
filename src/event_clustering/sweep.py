"""Threshold / time-window / linkage sweep for Phase 2C (label-free guard metrics only)."""

from __future__ import annotations

import itertools
import logging
from typing import Iterable

import numpy as np
import pandas as pd

from src.event_clustering.clusterer import (
    Units,
    build_summaries,
    cluster_units,
    propagate,
    summarize_metrics,
)

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLDS = (0.20, 0.25, 0.30, 0.35)
DEFAULT_WINDOWS_DAYS = (3.0, 5.0, 10.0)
DEFAULT_LINKAGES = ("average", "complete")

# The previous (vnese) 2C setting: cosine distance 0.35, 10-day gate, average linkage.
BASELINE = (0.35, 10.0, "average")

SWEEP_COLUMNS = [
    "distance_threshold",
    "window_days",
    "linkage",
    "is_previous_baseline",
    "total_events",
    "multi_article_events",
    "singleton_events",
    "singleton_article_share",
    "articles_in_multi_article_events",
    "cross_publisher_events",
    "events_ge_10_articles",
    "largest_event_size",
    "max_span_days",
    "mean_span_days_multi",
    "mean_intra_similarity_multi",
]


def run_sweep(
    df: pd.DataFrame,
    embeddings: np.ndarray,
    times: np.ndarray,
    units: Units,
    thresholds: Iterable[float] = DEFAULT_THRESHOLDS,
    windows_days: Iterable[float] = DEFAULT_WINDOWS_DAYS,
    linkages: Iterable[str] = DEFAULT_LINKAGES,
) -> pd.DataFrame:
    """Cluster under every (threshold, window, linkage) combination and report guard metrics.

    These metrics describe cluster *shape* (size, span, cohesion, publisher mix). They cannot measure
    precision/recall — that needs manual labels on the QC pairs — so they must not be maximised blindly.
    """
    rows = []
    for threshold, window, linkage in itertools.product(thresholds, windows_days, linkages):
        labels = cluster_units(units.embeddings, units.times, threshold, window, linkage)
        out = df.copy()
        out["event_cluster_id"] = propagate(df, units, labels, times)
        summary = build_summaries(out, embeddings, times)
        metrics = summarize_metrics(summary, len(out))
        rows.append(
            {
                "distance_threshold": threshold,
                "window_days": window,
                "linkage": linkage,
                "is_previous_baseline": (threshold, window, linkage) == BASELINE,
                "total_events": metrics["total_events"],
                "multi_article_events": metrics["multi_article_events"],
                "singleton_events": metrics["singleton_events"],
                "singleton_article_share": round(
                    1.0 - metrics["articles_in_multi_article_events"] / len(out), 4
                ),
                "articles_in_multi_article_events": metrics["articles_in_multi_article_events"],
                "cross_publisher_events": metrics["cross_publisher_events"],
                "events_ge_10_articles": metrics["events_ge_10_articles"],
                "largest_event_size": metrics["largest_event_size"],
                "max_span_days": metrics["max_span_days"],
                "mean_span_days_multi": metrics["mean_span_days_multi"],
                "mean_intra_similarity_multi": metrics["mean_intra_similarity_multi"],
            }
        )
        logger.info("sweep thr=%.2f window=%.0fd %s → %d events", threshold, window, linkage, metrics["total_events"])
    return pd.DataFrame(rows, columns=SWEEP_COLUMNS)

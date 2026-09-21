"""Event clustering of article embeddings.

Pipeline building blocks (all pure functions, unit-testable with synthetic embeddings):

1. ``event_time``        – published_at is the primary event time, first_seen_at only as fallback.
2. ``collapse_families`` – each Phase 2B duplicate family becomes ONE clustering unit.
3. ``cluster_units``     – agglomerative clustering on cosine distance with a hard time-window gate.
4. ``propagate``         – unit labels are mapped back to every article; every article gets an event id.
5. ``build_summaries``   – per-event summaries recomputed from the final propagated frame.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering

logger = logging.getLogger(__name__)

# Distance assigned to article pairs that must never be merged (outside the time window).
# Cosine distance is at most 2.0, so with any threshold < 2 this can never satisfy a merge criterion.
GATED_DISTANCE = 2.0

VALID_LINKAGES = ("average", "complete")


@dataclass
class Units:
    """Clustering units after collapsing duplicate families.

    ``members[u]`` holds the row positions (into the article frame) that make up unit ``u``.
    """

    members: List[np.ndarray]
    embeddings: np.ndarray  # (n_units, dim), L2-normalised
    times: np.ndarray  # (n_units,) days since epoch, NaN if unknown


# ── time ─────────────────────────────────────────────────────────────────────


def event_time(df: pd.DataFrame) -> Tuple[np.ndarray, pd.Series]:
    """Return (event time in days since epoch, time source label) per article.

    ``published_at`` (publisher-reported) is the primary event time. ``first_seen_at`` is only
    used when ``published_at`` is missing, because it is the collector's observation time.
    """
    published = pd.to_datetime(df["published_at"], utc=True, errors="coerce")
    first_seen = pd.to_datetime(df["first_seen_at"], utc=True, errors="coerce")
    effective = published.fillna(first_seen)

    source = pd.Series("missing", index=df.index, dtype=object)
    source[first_seen.notna()] = "first_seen_at"
    source[published.notna()] = "published_at"

    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    days = ((effective - epoch).dt.total_seconds() / 86400.0).to_numpy(dtype="float64")
    return days, source


def days_to_iso(days: float) -> str:
    """Format a days-since-epoch value as an ISO-8601 UTC string ('' when unknown)."""
    if days is None or np.isnan(days):
        return ""
    return pd.to_datetime(float(days) * 86400.0, unit="s", utc=True).isoformat()


# ── distance helpers ─────────────────────────────────────────────────────────


def cosine_distance_matrix(embeddings: np.ndarray) -> np.ndarray:
    """Dense cosine distance matrix for L2-normalised embeddings (float64, zero diagonal)."""
    emb = np.asarray(embeddings, dtype="float64")
    dist = 1.0 - emb @ emb.T
    np.clip(dist, 0.0, 2.0, out=dist)
    dist = (dist + dist.T) / 2.0
    np.fill_diagonal(dist, 0.0)
    return dist


def time_gap_matrix(times: np.ndarray) -> np.ndarray:
    """Absolute time gap in days between all pairs (NaN if either time is unknown)."""
    t = np.asarray(times, dtype="float64")
    return np.abs(t[:, None] - t[None, :])


# ── units ────────────────────────────────────────────────────────────────────


def collapse_families(df: pd.DataFrame, embeddings: np.ndarray, times: np.ndarray) -> Units:
    """Collapse each duplicate family into one unit; every non-family article is its own unit.

    A unit's embedding is the L2-normalised mean of its members' embeddings and its time is the
    earliest member time. Because a family is a single unit, all its members necessarily receive
    the same event id after propagation.
    """
    if not (len(df) == len(embeddings) == len(times)):
        raise ValueError("df, embeddings and times must have the same length")

    family_ids = df["duplicate_family_id"].to_numpy(dtype=object)
    members_by_family: Dict[str, List[int]] = {}
    unit_members: List[List[int]] = []
    for pos, family in enumerate(family_ids):
        if pd.isna(family):
            unit_members.append([pos])
        elif family in members_by_family:
            members_by_family[family].append(pos)
        else:
            members: List[int] = [pos]
            members_by_family[family] = members
            unit_members.append(members)

    members_arr = [np.asarray(m, dtype="int64") for m in unit_members]
    emb = np.asarray(embeddings, dtype="float64")
    unit_emb = np.vstack([emb[m].mean(axis=0) for m in members_arr])
    norms = np.linalg.norm(unit_emb, axis=1, keepdims=True)
    unit_emb = unit_emb / np.where(norms == 0.0, 1.0, norms)

    unit_times = np.array(
        [np.nan if np.isnan(times[m]).all() else np.nanmin(times[m]) for m in members_arr],
        dtype="float64",
    )
    return Units(members=members_arr, embeddings=unit_emb, times=unit_times)


# ── clustering ───────────────────────────────────────────────────────────────


def cluster_units(
    unit_embeddings: np.ndarray,
    unit_times: np.ndarray,
    distance_threshold: float,
    window_days: float,
    linkage: str = "average",
) -> np.ndarray:
    """Cluster units with agglomerative clustering on cosine distance.

    Pairs whose event times are more than ``window_days`` apart (or unknown) are gated to distance 2.0.
    With ``linkage="complete"`` this is a hard guarantee (a cluster's time span never exceeds the
    window and no chain of loosely-related articles forms). With ``"average"`` the gate is only
    a strong penalty, so callers should measure the resulting spans.
    """
    if linkage not in VALID_LINKAGES:
        raise ValueError(f"linkage must be one of {VALID_LINKAGES}, got {linkage!r}")
    n = len(unit_embeddings)
    if n < 2:
        return np.zeros(n, dtype="int64")

    dist = cosine_distance_matrix(unit_embeddings)
    gap = time_gap_matrix(unit_times)
    gated = ~(gap <= window_days)  # NaN gaps compare False → gated (unknown time never merges)
    dist[gated] = GATED_DISTANCE
    np.fill_diagonal(dist, 0.0)

    model = AgglomerativeClustering(
        n_clusters=None,
        metric="precomputed",
        linkage=linkage,
        distance_threshold=distance_threshold,
    )
    return model.fit_predict(dist)


# ── propagation ──────────────────────────────────────────────────────────────


def event_id_for(anchor_article_id: str) -> str:
    """Deterministic event id anchored on one article (stable when a cluster gains members)."""
    return "evt_" + hashlib.sha256(str(anchor_article_id).encode("utf-8")).hexdigest()[:12]


def propagate(
    df: pd.DataFrame,
    units: Units,
    unit_labels: np.ndarray,
    times: np.ndarray,
) -> np.ndarray:
    """Map unit cluster labels to an ``event_cluster_id`` for every article (never null).

    The anchor of an event is its earliest article (event time, then article_id); singleton
    events are anchored on their only article.
    """
    article_ids = df["article_id"].astype(str).to_numpy()
    rows_by_label: Dict[int, List[int]] = {}
    for unit_idx, label in enumerate(unit_labels):
        rows_by_label.setdefault(int(label), []).extend(units.members[unit_idx].tolist())

    event_ids = np.empty(len(df), dtype=object)
    for rows in rows_by_label.values():
        anchor = min(
            rows,
            key=lambda r: (np.inf if np.isnan(times[r]) else times[r], article_ids[r]),
        )
        event_id = event_id_for(article_ids[anchor])
        for r in rows:
            event_ids[r] = event_id
    return event_ids


# ── summaries ────────────────────────────────────────────────────────────────


def _mean_pairwise_similarity(member_emb: np.ndarray) -> float:
    k = len(member_emb)
    if k < 2:
        return float("nan")
    total = member_emb.sum(axis=0)
    return float((total @ total - k) / (k * (k - 1)))


def build_summaries(
    output_df: pd.DataFrame,
    embeddings: np.ndarray,
    times: np.ndarray,
) -> pd.DataFrame:
    """Per-event summary computed from the FINAL propagated frame (one row per event).

    Every event is included (singletons too). Sorted by anchor time then event id.
    """
    emb = np.asarray(embeddings, dtype="float64")
    groups = output_df.groupby("event_cluster_id", sort=False).indices

    rows: List[Dict[str, object]] = []
    for event_id, positions in groups.items():
        pos = np.asarray(positions)
        members = output_df.iloc[pos]
        t = times[pos]
        order = np.lexsort((members["article_id"].astype(str).to_numpy(), np.where(np.isnan(t), np.inf, t)))
        publishers = sorted(members["publisher_domain"].unique().tolist())
        family_ids = members["duplicate_family_id"].dropna().unique().tolist()
        unit_keys = members["duplicate_family_id"].where(
            members["duplicate_family_id"].notna(), members["article_id"]
        )
        known = t[~np.isnan(t)]
        span = float(known.max() - known.min()) if len(known) else float("nan")
        rows.append(
            {
                "event_cluster_id": event_id,
                "cluster_size": int(len(pos)),
                "n_units": int(unit_keys.nunique()),
                "n_publishers": int(len(publishers)),
                "n_duplicate_families": int(len(family_ids)),
                "first_published_at": days_to_iso(known.min()) if len(known) else "",
                "last_published_at": days_to_iso(known.max()) if len(known) else "",
                "span_days": round(span, 3) if not np.isnan(span) else "",
                "mean_intra_similarity": round(_mean_pairwise_similarity(emb[pos]), 4)
                if len(pos) > 1
                else "",
                "publishers": "; ".join(publishers),
                "duplicate_families": "; ".join(sorted(family_ids)),
                "article_ids": "; ".join(members["article_id"].astype(str).to_numpy()[order]),
                "sample_titles": " | ".join(members["title"].astype(str).to_numpy()[order][:5]),
                "_anchor_time": float(t[order[0]]) if len(pos) else float("nan"),
            }
        )

    summary = pd.DataFrame(rows)
    if summary.empty:
        return summary.drop(columns=["_anchor_time"], errors="ignore")
    summary["_sort_time"] = summary["_anchor_time"].fillna(np.inf)
    summary = summary.sort_values(["_sort_time", "event_cluster_id"], kind="mergesort")
    return summary.drop(columns=["_anchor_time", "_sort_time"]).reset_index(drop=True)


def summarize_metrics(summary: pd.DataFrame, n_articles: int) -> Dict[str, object]:
    """Run-level metrics derived from the event summary (so they always reconcile with it)."""
    if summary.empty:
        return {"total_articles": int(n_articles), "total_events": 0}

    sizes = summary["cluster_size"].astype(int)
    multi = summary[sizes >= 2]
    spans = pd.to_numeric(multi["span_days"], errors="coerce")
    sims = pd.to_numeric(multi["mean_intra_similarity"], errors="coerce")
    largest = summary.loc[sizes.idxmax()]
    distribution = {int(k): int(v) for k, v in sizes[sizes >= 2].value_counts().sort_index().items()}
    return {
        "total_articles": int(n_articles),
        "total_events": int(len(summary)),
        "singleton_events": int((sizes == 1).sum()),
        "multi_article_events": int(len(multi)),
        "articles_in_multi_article_events": int(multi["cluster_size"].sum()),
        "cross_publisher_events": int((summary["n_publishers"] >= 2).sum()),
        "events_ge_10_articles": int((sizes >= 10).sum()),
        "largest_event_size": int(largest["cluster_size"]),
        "largest_event_id": str(largest["event_cluster_id"]),
        "max_span_days": round(float(spans.max()), 3) if spans.notna().any() else 0.0,
        "mean_span_days_multi": round(float(spans.mean()), 3) if spans.notna().any() else 0.0,
        "mean_intra_similarity_multi": round(float(sims.mean()), 4) if sims.notna().any() else 0.0,
        "multi_article_event_size_distribution": distribution,
    }

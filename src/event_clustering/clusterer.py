"""Agglomerative clustering of article embeddings into event clusters."""

from __future__ import annotations

import hashlib
import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics.pairwise import cosine_distances

logger = logging.getLogger(__name__)

# Default cosine-distance threshold — articles closer than this are same event
DEFAULT_DISTANCE_THRESHOLD = 0.35


class EventClusterer:
    """Deterministic event clustering using Agglomerative Clustering with cosine distance."""

    def __init__(
        self,
        distance_threshold: float = DEFAULT_DISTANCE_THRESHOLD,
        max_event_days: float = 10.0,
    ) -> None:
        """
        Args:
            distance_threshold: Cosine distance threshold for merging clusters.
                Lower = stricter (fewer, tighter clusters).
            max_event_days: Maximum temporal span (days) for articles in the same event.
        """
        self.distance_threshold = distance_threshold
        self.max_event_days = max_event_days

    def cluster(
        self,
        embeddings: np.ndarray,
        df: pd.DataFrame,
        representative_indices: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """Assign event cluster labels to each article.

        Args:
            embeddings: (n_articles, dim) L2-normalized embeddings.
            df: Full DataFrame (used for temporal gating).
            representative_indices: If provided, only cluster these rows first,
                then propagate labels to duplicate family members.

        Returns:
            np.ndarray of integer cluster labels, length = len(df).
        """
        n = len(df)
        assert embeddings.shape[0] == n, (
            f"Embedding count {embeddings.shape[0]} != DataFrame rows {n}"
        )

        logger.info(
            "Clustering %d articles with distance_threshold=%.3f …",
            n,
            self.distance_threshold,
        )

        # Compute cosine distance matrix
        dist_matrix = cosine_distances(embeddings)

        # Temporal gating: inflate distance for articles far apart in time
        parsed_dates = pd.to_datetime(df["published_at"], utc=True, errors="coerce")
        fallback_dates = pd.to_datetime(df["first_seen_at"], utc=True, errors="coerce")
        effective_dates = parsed_dates.fillna(fallback_dates)

        for i in range(n):
            for j in range(i + 1, n):
                d1, d2 = effective_dates.iloc[i], effective_dates.iloc[j]
                if pd.notna(d1) and pd.notna(d2):
                    days_diff = abs((d1 - d2).total_seconds()) / 86400.0
                    if days_diff > self.max_event_days:
                        # Push apart articles that are temporally distant
                        dist_matrix[i, j] = 2.0
                        dist_matrix[j, i] = 2.0

        # Run Agglomerative Clustering
        clustering = AgglomerativeClustering(
            n_clusters=None,
            metric="precomputed",
            linkage="average",
            distance_threshold=self.distance_threshold,
        )
        labels = clustering.fit_predict(dist_matrix)

        logger.info(
            "Agglomerative clustering produced %d clusters from %d articles.",
            len(set(labels)),
            n,
        )
        return labels

    def assign_event_ids(
        self,
        df: pd.DataFrame,
        labels: np.ndarray,
    ) -> Tuple[pd.DataFrame, List[Dict[str, object]], Dict[str, object]]:
        """Convert numeric cluster labels into deterministic event_cluster_id strings.

        Rules:
        - Singleton clusters (1 article) get event_cluster_id = None.
        - Multi-article clusters get event_cluster_id = 'evt_<hash>'.
        - All members of the same duplicate_family_id MUST share the same event_cluster_id.

        Returns:
            (output_df, cluster_summaries, metrics)
        """
        output_df = df.copy()
        n = len(output_df)

        # Build cluster -> member indices mapping
        cluster_members: Dict[int, List[int]] = {}
        for idx, label in enumerate(labels):
            cluster_members.setdefault(int(label), []).append(idx)

        # Sort clusters deterministically: by earliest first_seen_at, then article_id
        def cluster_sort_key(cluster_id: int) -> Tuple[str, str]:
            members = cluster_members[cluster_id]
            first_idx = min(members)
            row = df.iloc[first_idx]
            return (str(row["first_seen_at"]), str(row["article_id"]))

        sorted_cluster_ids = sorted(cluster_members.keys(), key=cluster_sort_key)

        # Assign event IDs
        output_df["event_cluster_id"] = None
        cluster_summaries: List[Dict[str, object]] = []
        event_count = 0

        for cluster_label in sorted_cluster_ids:
            member_indices = sorted(cluster_members[cluster_label])

            if len(member_indices) < 2:
                # Singleton — no event cluster
                continue

            event_count += 1
            member_rows = df.iloc[member_indices]
            article_ids_sorted = sorted(member_rows["article_id"].tolist())
            event_hash = hashlib.sha256(
                "".join(article_ids_sorted).encode("utf-8")
            ).hexdigest()[:12]
            event_id = f"evt_{event_hash}"

            for idx in member_indices:
                output_df.at[idx, "event_cluster_id"] = event_id

            publishers = sorted(member_rows["publisher_domain"].unique().tolist())
            titles = member_rows["title"].tolist()

            # Check if cluster spans multiple duplicate families
            family_ids_in_cluster = set(
                member_rows["duplicate_family_id"].dropna().unique()
            )

            cluster_summaries.append({
                "event_cluster_id": event_id,
                "cluster_size": len(member_indices),
                "publishers": "; ".join(publishers),
                "n_publishers": len(publishers),
                "duplicate_families_in_cluster": "; ".join(sorted(family_ids_in_cluster)) if family_ids_in_cluster else "",
                "article_ids": "; ".join(article_ids_sorted),
                "sample_titles": " | ".join(titles[:5]),
            })

        # Enforce constraint: all members of same duplicate_family must share event_cluster_id
        family_groups = output_df[output_df["duplicate_family_id"].notna()].groupby("duplicate_family_id")
        for fam_id, group in family_groups:
            event_ids = group["event_cluster_id"].dropna().unique()
            if len(event_ids) >= 1:
                # Use the first non-null event_cluster_id for all members
                canonical_event_id = event_ids[0]
                output_df.loc[group.index, "event_cluster_id"] = canonical_event_id
            # If no member got an event_cluster_id, they stay as None (singleton family)

        # Metrics
        assigned_articles = int(output_df["event_cluster_id"].notna().sum())
        singleton_articles = n - assigned_articles
        cluster_sizes = [s["cluster_size"] for s in cluster_summaries]
        largest_cluster_size = max(cluster_sizes) if cluster_sizes else 0
        largest_cluster_id = (
            max(cluster_summaries, key=lambda x: x["cluster_size"])["event_cluster_id"]
            if cluster_summaries
            else None
        )

        size_distribution = {}
        if cluster_sizes:
            for size in cluster_sizes:
                size_distribution[size] = size_distribution.get(size, 0) + 1
            size_distribution = dict(sorted(size_distribution.items()))

        # Count cross-publisher clusters (the interesting ones for diffusion analysis)
        cross_pub_clusters = sum(1 for s in cluster_summaries if s["n_publishers"] >= 2)

        metrics = {
            "total_articles": n,
            "assigned_articles": assigned_articles,
            "singleton_articles": singleton_articles,
            "total_event_clusters": event_count,
            "cross_publisher_clusters": cross_pub_clusters,
            "cluster_size_distribution": size_distribution,
            "largest_cluster_size": largest_cluster_size,
            "largest_cluster_id": largest_cluster_id,
            "distance_threshold": self.distance_threshold,
            "max_event_days": self.max_event_days,
        }

        return output_df, cluster_summaries, metrics

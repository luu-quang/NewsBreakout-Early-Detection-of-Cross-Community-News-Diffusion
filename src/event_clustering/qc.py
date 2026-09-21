"""Deterministic QC sampling of article pairs for manual review of Phase 2C event clusters."""

from __future__ import annotations

from typing import Dict, List, Set, Tuple

import numpy as np
import pandas as pd

from src.event_clustering.clusterer import cosine_distance_matrix, time_gap_matrix

STRATUM_WEAKEST = "INTRA_CLUSTER_WEAKEST_LINK"
STRATUM_CROSS_PUB = "INTRA_CLUSTER_CROSS_PUB"
STRATUM_SAME_PUB = "INTRA_CLUSTER_SAME_PUB"
STRATUM_INTER_NEAR = "INTER_CLUSTER_NEAR"

QC_COLUMNS = [
    "stratum",
    "left_article_id",
    "right_article_id",
    "left_publisher",
    "right_publisher",
    "left_title",
    "right_title",
    "left_description",
    "right_description",
    "left_event_cluster_id",
    "right_event_cluster_id",
    "cosine_distance",
    "days_apart",
    "manual_label",
    "review_notes",
]

MAX_PAIRS_PER_EVENT = 2  # spread the sample across events instead of letting big events dominate


def _row(df: pd.DataFrame, dist: np.ndarray, gap: np.ndarray, i: int, j: int, stratum: str) -> Dict[str, object]:
    a, b = df.iloc[i], df.iloc[j]
    days = gap[i, j]
    return {
        "stratum": stratum,
        "left_article_id": a["article_id"],
        "right_article_id": b["article_id"],
        "left_publisher": a["publisher_domain"],
        "right_publisher": b["publisher_domain"],
        "left_title": a["title"],
        "right_title": b["title"],
        "left_description": "" if pd.isna(a["description"]) else str(a["description"]),
        "right_description": "" if pd.isna(b["description"]) else str(b["description"]),
        "left_event_cluster_id": a["event_cluster_id"],
        "right_event_cluster_id": b["event_cluster_id"],
        "cosine_distance": round(float(dist[i, j]), 4),
        "days_apart": "" if np.isnan(days) else round(float(days), 3),
        "manual_label": "",
        "review_notes": "",
    }


def select_qc_pairs(
    output_df: pd.DataFrame,
    embeddings: np.ndarray,
    times: np.ndarray,
    window_days: float,
    per_stratum: int = 30,
    seed: int = 42,
) -> pd.DataFrame:
    """Pick a small, deterministic, stratified set of article pairs for manual labelling.

    Strata:
      * INTRA_CLUSTER_WEAKEST_LINK – the least similar pair of each multi-article event (worst first);
        the most likely false merges.
      * INTRA_CLUSTER_CROSS_PUB / INTRA_CLUSTER_SAME_PUB – random pairs inside events, by publisher relation.
      * INTER_CLUSTER_NEAR – pairs from DIFFERENT events with the smallest cosine distance that still fall
        within the time window (one pair per event pair): the most likely false splits / hard negatives.
        Selection is by embedding distance, not random.

    Pairs inside one duplicate family are excluded (they are same-event by construction).
    """
    df = output_df.reset_index(drop=True)
    n = len(df)
    if n < 2:
        return pd.DataFrame(columns=QC_COLUMNS)

    dist = cosine_distance_matrix(embeddings)
    gap = time_gap_matrix(times)
    rng = np.random.default_rng(seed)

    codes, _ = pd.factorize(df["event_cluster_id"])
    pubs, _ = pd.factorize(df["publisher_domain"])
    fam = df["duplicate_family_id"].astype(object).where(df["duplicate_family_id"].notna(), "").to_numpy()

    i_idx, j_idx = np.triu_indices(n, k=1)
    same_event = codes[i_idx] == codes[j_idx]
    same_family = (fam[i_idx] != "") & (fam[i_idx] == fam[j_idx])
    d_pairs = dist[i_idx, j_idx]

    chosen: Set[Tuple[int, int]] = set()
    picked: List[Tuple[int, int, str]] = []

    def take(pos: int, stratum: str) -> None:
        pair = (int(i_idx[pos]), int(j_idx[pos]))
        if pair not in chosen:
            chosen.add(pair)
            picked.append((*pair, stratum))

    # ── intra-cluster strata ────────────────────────────────────────────────
    intra = np.flatnonzero(same_event & ~same_family)
    if len(intra):
        intra_frame = pd.DataFrame({"pos": intra, "code": codes[i_idx[intra]], "d": d_pairs[intra]})

        # Weakest link per event (largest distance); worst events first.
        weakest = intra_frame.loc[intra_frame.groupby("code")["d"].idxmax()]
        weakest = weakest.sort_values(["d", "pos"], ascending=[False, True]).head(per_stratum)
        for pos in weakest["pos"]:
            take(int(pos), STRATUM_WEAKEST)

        def sample_stratum(mask_pubs: np.ndarray, stratum: str) -> None:
            cand = intra[mask_pubs]
            cand = np.array([p for p in cand if (int(i_idx[p]), int(j_idx[p])) not in chosen], dtype="int64")
            if not len(cand):
                return
            per_event: Dict[int, int] = {}
            taken = 0
            for p in rng.permutation(cand):
                code = int(codes[i_idx[p]])
                if per_event.get(code, 0) >= MAX_PAIRS_PER_EVENT:
                    continue
                per_event[code] = per_event.get(code, 0) + 1
                take(int(p), stratum)
                taken += 1
                if taken >= per_stratum:
                    break

        cross = pubs[i_idx[intra]] != pubs[j_idx[intra]]
        sample_stratum(cross, STRATUM_CROSS_PUB)
        sample_stratum(~cross, STRATUM_SAME_PUB)

    # ── inter-cluster near pairs (by embedding distance) ────────────────────
    with np.errstate(invalid="ignore"):
        in_window = gap[i_idx, j_idx] <= window_days  # NaN → False
    inter = np.flatnonzero(~same_event & in_window & ~same_family)
    if len(inter):
        ci, cj = codes[i_idx[inter]], codes[j_idx[inter]]
        inter_frame = pd.DataFrame(
            {
                "pos": inter,
                "lo": np.minimum(ci, cj),
                "hi": np.maximum(ci, cj),
                "d": d_pairs[inter],
                "i": i_idx[inter],
                "j": j_idx[inter],
            }
        )
        inter_frame = inter_frame.sort_values(["d", "i", "j"], kind="mergesort")
        inter_frame = inter_frame.drop_duplicates(["lo", "hi"], keep="first").head(per_stratum)
        for pos in inter_frame["pos"]:
            take(int(pos), STRATUM_INTER_NEAR)

    rows = [_row(df, dist, gap, i, j, stratum) for i, j, stratum in picked]
    return pd.DataFrame(rows, columns=QC_COLUMNS)

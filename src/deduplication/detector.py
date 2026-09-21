"""Duplicate and syndication detection algorithms, candidate generation, and family clustering."""

from __future__ import annotations

import hashlib
import sys
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import pandas as pd

from src.deduplication.normalize import (
    calculate_containment,
    calculate_jaccard,
    get_tokens,
    get_token_sort_string,
    get_word_ngrams,
    normalize_text,
    normalize_url,
)


@dataclass
class PairEvidence:
    """Evidence metrics computed between an article pair."""
    pair_id: str
    left_article_id: str
    right_article_id: str
    left_publisher: str
    right_publisher: str
    left_url: str
    right_url: str
    left_title: str
    right_title: str
    left_description: str
    right_description: str
    similarity_evidence: str
    predicted_relation: str
    duplicate_family_id: Optional[str] = None
    manual_relation: str = ""
    review_notes: str = ""
    title_sim: float = 0.0
    desc_2g_cont: float = 0.0
    desc_3g_cont: float = 0.0
    days_diff: float = 0.0


class DeduplicationDetector:
    """Deterministic duplicate and syndication detection engine."""

    def __init__(
        self,
        *,
        max_syndication_days: float = 5.0,
        max_event_days: float = 10.0,
        min_title_shingle_overlap: int = 2,
    ) -> None:
        self.max_syndication_days = max_syndication_days
        self.max_event_days = max_event_days
        self.min_title_shingle_overlap = min_title_shingle_overlap

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Precompute normalized text, URL, and n-gram representations."""
        prepared = df.copy()

        prepared["norm_url"] = prepared["canonical_url"].fillna("").apply(normalize_url)
        prepared["norm_title"] = prepared["title"].fillna("").apply(normalize_text)
        prepared["sort_title"] = prepared["norm_title"].apply(get_token_sort_string)
        prepared["norm_desc"] = prepared["description"].fillna("").apply(normalize_text)

        prepared["title_tokens"] = prepared["norm_title"].apply(get_tokens)
        prepared["desc_tokens"] = prepared["norm_desc"].apply(get_tokens)

        prepared["title_2grams"] = prepared["title_tokens"].apply(lambda t: get_word_ngrams(t, 2))
        prepared["desc_2grams"] = prepared["desc_tokens"].apply(lambda t: get_word_ngrams(t, 2))
        prepared["desc_3grams"] = prepared["desc_tokens"].apply(lambda t: get_word_ngrams(t, 3))

        prepared["parsed_published_at"] = pd.to_datetime(prepared["published_at"], utc=True, errors="coerce")
        prepared["parsed_first_seen_at"] = pd.to_datetime(prepared["first_seen_at"], utc=True, errors="coerce")

        return prepared

    def generate_candidate_pairs(self, df: pd.DataFrame) -> Set[Tuple[int, int]]:
        """Generate candidate pairs using inverted title token index and exact URL matching."""
        candidates: Set[Tuple[int, int]] = set()
        n = len(df)

        # 1. Exact canonical URL candidate blocking
        url_groups = defaultdict(list)
        for idx, url in enumerate(df["norm_url"]):
            if url:
                url_groups[url].append(idx)
        for group in url_groups.values():
            if len(group) > 1:
                for i in range(len(group)):
                    for j in range(i + 1, len(group)):
                        candidates.add((group[i], group[j]))

        # 2. Inverted index on significant title tokens
        token_index = defaultdict(list)
        for idx, tokens in enumerate(df["title_tokens"]):
            for token in set(tokens):
                if len(token) > 2:
                    token_index[token].append(idx)

        # Filter out high-frequency stopwords (> 15% of corpus)
        stopword_threshold = max(20, int(0.15 * n))
        for token, doc_indices in token_index.items():
            if len(doc_indices) > stopword_threshold:
                continue
            for i in range(len(doc_indices)):
                for j in range(i + 1, len(doc_indices)):
                    u, v = doc_indices[i], doc_indices[j]
                    if u != v:
                        candidates.add((min(u, v), max(u, v)))

        return candidates

    def evaluate_pair(
        self,
        left: dict,
        right: dict,
    ) -> PairEvidence:
        """Evaluate relationship between article i and article j with multi-signal evidence."""

        # Calculate temporal distance
        d1 = left["parsed_published_at"] if pd.notna(left["parsed_published_at"]) else left["parsed_first_seen_at"]
        d2 = right["parsed_published_at"] if pd.notna(right["parsed_published_at"]) else right["parsed_first_seen_at"]
        if pd.notna(d1) and pd.notna(d2):
            days_diff = abs((d1 - d2).total_seconds()) / 86400.0
        else:
            days_diff = 0.0

        # Title similarity (Levenshtein ratio and token-sorted ratio)
        t1, t2 = left["norm_title"], right["norm_title"]
        s1, s2 = left["sort_title"], right["sort_title"]
        t_ratio = SequenceMatcher(None, t1, t2).ratio() if (t1 and t2) else 0.0
        s_ratio = SequenceMatcher(None, s1, s2).ratio() if (s1 and s2) else 0.0
        max_title_sim = max(t_ratio, s_ratio)

        # Description containment and Jaccard
        sh2_1, sh2_2 = left["desc_2grams"], right["desc_2grams"]
        d2g_cont = calculate_containment(sh2_1, sh2_2)

        sh3_1, sh3_2 = left["desc_3grams"], right["desc_3grams"]
        d3g_cont = calculate_containment(sh3_1, sh3_2)

        # Title token overlap
        w1, w2 = set(left["title_tokens"]), set(right["title_tokens"])
        common_words = len(w1 & w2)

        # URL match
        url_match = bool(left["norm_url"] and right["norm_url"] and left["norm_url"] == right["norm_url"])

        # Determine relation
        rel = "UNRELATED"
        evidence: List[str] = []

        # 1. Exact Duplicate Rules
        if url_match:
            rel = "EXACT_DUPLICATE"
            evidence.append("identical_canonical_url")
        elif t1 == t2 and (left["norm_desc"] == right["norm_desc"] or not left["norm_desc"] or not right["norm_desc"]):
            rel = "EXACT_DUPLICATE"
            evidence.append("identical_title_and_description")
        elif (
            left["publisher_domain"] == right["publisher_domain"]
            and left["norm_desc"] == right["norm_desc"]
            and len(left["norm_desc"]) >= 50
        ):
            rel = "EXACT_DUPLICATE"
            evidence.append("same_publisher_verbatim_description")
        elif max_title_sim >= 0.98 and d2g_cont >= 0.95:
            rel = "EXACT_DUPLICATE"
            evidence.append(f"near_identical_title_{max_title_sim:.2f}_desc_cont_{d2g_cont:.2f}")

        # 2. Syndicated Copy Rules (Within max_syndication_days)
        elif days_diff <= self.max_syndication_days and (
            (max_title_sim >= 0.85 and d2g_cont >= 0.65)
            or (d2g_cont >= 0.80 and d3g_cont >= 0.65 and max_title_sim >= 0.55)
            or (max_title_sim >= 0.92 and d2g_cont >= 0.55)
        ):
            rel = "SYNDICATED_COPY"
            evidence.append(f"high_shingle_containment_d2g={d2g_cont:.2f}_d3g={d3g_cont:.2f}_title_sim={max_title_sim:.2f}")

        # 3. Same Event Independent Rules (Within max_event_days)
        elif days_diff <= self.max_event_days and (
            max_title_sim >= 0.50 or d2g_cont >= 0.30 or common_words >= 3
        ):
            rel = "SAME_EVENT_INDEPENDENT"
            evidence.append(f"event_semantic_overlap_title_sim={max_title_sim:.2f}_desc_cont={d2g_cont:.2f}")

        else:
            evidence.append(f"low_similarity_title_sim={max_title_sim:.2f}_desc_cont={d2g_cont:.2f}")

        pair_hash = hashlib.sha256(f"{left['article_id']}:{right['article_id']}".encode("utf-8")).hexdigest()[:12]
        pair_id = f"pair_{pair_hash}"

        return PairEvidence(
            pair_id=pair_id,
            left_article_id=left["article_id"],
            right_article_id=right["article_id"],
            left_publisher=left["publisher_domain"],
            right_publisher=right["publisher_domain"],
            left_url=left["url"],
            right_url=right["url"],
            left_title=left["title"],
            right_title=right["title"],
            left_description=str(left["description"] or ""),
            right_description=str(right["description"] or ""),
            similarity_evidence="; ".join(evidence),
            predicted_relation=rel,
            title_sim=max_title_sim,
            desc_2g_cont=d2g_cont,
            desc_3g_cont=d3g_cont,
            days_diff=days_diff,
        )

    def detect_and_cluster(
        self,
        df: pd.DataFrame,
    ) -> Tuple[pd.DataFrame, List[PairEvidence], List[Dict[str, object]], Dict[str, object]]:
        """Run candidate generation, pair classification, and deterministic family clustering."""
        prepared = self.prepare_features(df)
        candidate_pairs = sorted(self.generate_candidate_pairs(prepared))

        evaluated_pairs: List[PairEvidence] = []
        adjacency: Dict[int, List[Tuple[int, str]]] = defaultdict(list)

        prepared_records = prepared.to_dict("records")

        for u, v in candidate_pairs:
            # Require minimum token overlap before running fine-grained distance
            w1 = set(prepared_records[u]["title_tokens"])
            w2 = set(prepared_records[v]["title_tokens"])
            common = w1 & w2
            if not common and not (prepared_records[u]["norm_url"] and prepared_records[u]["norm_url"] == prepared_records[v]["norm_url"]):
                continue

            evidence = self.evaluate_pair(prepared_records[u], prepared_records[v])
            evaluated_pairs.append(evidence)

            if evidence.predicted_relation in ("EXACT_DUPLICATE", "SYNDICATED_COPY"):
                adjacency[u].append((v, evidence.predicted_relation))
                adjacency[v].append((u, evidence.predicted_relation))

        # Graph connected components for duplicate families
        visited: Set[int] = set()
        components: List[List[int]] = []

        # Process in deterministic order by original index
        for node in range(len(prepared)):
            if node in adjacency and node not in visited:
                comp: List[int] = []
                queue = [node]
                visited.add(node)
                while queue:
                    curr = queue.pop(0)
                    comp.append(curr)
                    for neighbor, _ in sorted(adjacency[curr], key=lambda x: x[0]):
                        if neighbor not in visited:
                            visited.add(neighbor)
                            queue.append(neighbor)
                if len(comp) >= 2:
                    components.append(sorted(comp))

        # Deterministic family assignment
        # Output must be a pure copy of df with only duplicate_family_id updated
        output_df = df.copy()
        output_df["duplicate_family_id"] = None

        family_summaries: List[Dict[str, object]] = []
        exact_family_count = 0
        syndicated_family_count = 0

        # Sort components deterministically by earliest article in component
        def component_sort_key(comp_indices: List[int]) -> Tuple[str, str]:
            first_idx = comp_indices[0]
            row = prepared.iloc[first_idx]
            return (str(row["first_seen_at"]), str(row["article_id"]))

        components = sorted(components, key=component_sort_key)

        for comp_idx, comp_indices in enumerate(components, 1):
            comp_rows = prepared.iloc[comp_indices]
            # Primary article is the earliest first_seen_at then article_id
            primary_row = comp_rows.sort_values(["first_seen_at", "article_id"]).iloc[0]
            family_hash = hashlib.sha256(
                "".join(sorted(comp_rows["article_id"])).encode("utf-8")
            ).hexdigest()[:12]

            # Determine family type: EXACT vs SYNDICATED
            # Check edge types in this component
            comp_set = set(comp_indices)
            has_syndicated = False
            for u in comp_indices:
                for v, rel in adjacency[u]:
                    if v in comp_set and rel == "SYNDICATED_COPY":
                        has_syndicated = True
                        break
                if has_syndicated:
                    break

            family_type = "SYNDICATED" if has_syndicated else "EXACT"
            if family_type == "EXACT":
                exact_family_count += 1
                family_id = f"fam_exact_{family_hash}"
            else:
                syndicated_family_count += 1
                family_id = f"fam_synd_{family_hash}"

            # Assign family ID to output dataframe
            for idx in comp_indices:
                output_df.at[idx, "duplicate_family_id"] = family_id

            # Update evaluated_pairs with assigned family ID
            for pair in evaluated_pairs:
                if (pair.left_article_id in comp_rows["article_id"].values) and (
                    pair.right_article_id in comp_rows["article_id"].values
                ):
                    pair.duplicate_family_id = family_id

            publishers = sorted(comp_rows["publisher_domain"].unique().tolist())
            article_ids = comp_rows["article_id"].tolist()
            titles = comp_rows["title"].tolist()

            family_summaries.append({
                "family_id": family_id,
                "family_type": family_type,
                "family_size": len(comp_indices),
                "publishers": "; ".join(publishers),
                "article_ids": "; ".join(article_ids),
                "titles": " | ".join(titles),
            })

        # Generate run metrics
        total_articles = len(output_df)
        assigned_articles = int(output_df["duplicate_family_id"].notna().sum())
        singleton_articles = total_articles - assigned_articles
        total_families = len(family_summaries)
        family_sizes = [f["family_size"] for f in family_summaries]
        largest_family_size = max(family_sizes) if family_sizes else 0
        largest_family_id = (
            max(family_summaries, key=lambda x: x["family_size"])["family_id"]
            if family_summaries
            else None
        )

        size_distribution = (
            {int(k): int(v) for k, v in pd.Series(family_sizes).value_counts().sort_index().items()}
            if family_sizes
            else {}
        )

        metrics = {
            "total_articles": int(total_articles),
            "assigned_articles": int(assigned_articles),
            "singleton_articles": int(singleton_articles),
            "total_families": int(total_families),
            "exact_duplicate_families": int(exact_family_count),
            "syndicated_families": int(syndicated_family_count),
            "family_size_distribution": size_distribution,
            "largest_family_size": int(largest_family_size),
            "largest_family_id": largest_family_id,
        }

        return output_df, evaluated_pairs, family_summaries, metrics

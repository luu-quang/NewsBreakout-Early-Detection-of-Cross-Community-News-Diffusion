"""Phase 2B (independent implementation): duplicate / syndication annotation.

Reads the frozen Phase 2A master snapshot, populates ONLY ``duplicate_family_id``,
and writes small QC artifacts. Deterministic: no randomness anywhere; every
ordering is by sorted ids or sha256 of ids. See METHOD.md for the design and
threshold rationale.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd

FROZEN_SCHEMA = [
    "article_id", "title", "url", "canonical_url", "publisher_domain", "publisher_id",
    "publisher_group_id", "source_system", "first_seen_at", "published_at",
    "timestamp_confidence", "language", "publisher_country", "description", "category",
    "vietnam_relevance", "duplicate_family_id", "branch", "collection_mode", "raw_payload_ref",
]

# --- decision constants (rationale in METHOD.md) ---------------------------------------
DESC_COPY_THRESHOLD = 0.60      # description word-bigram Jaccard needed to call a copy
MIN_DESC_TOKENS = 6             # both descriptions must carry enough text to be evidence
MAX_HOURS_APART = 168.0         # copies of one story do not straddle weeks (when both times known)
NUMBER_CONFLICT_JACCARD = 0.5   # digit-token sets this dissimilar => different reports
SAME_EVENT_TITLE = 0.50         # proxy: strong headline overlap without copy evidence
SAME_EVENT_DESC = 0.40          # proxy: moderate lede overlap without copy evidence
MIN_SHARED_SHINGLES = 2         # blocking: candidate pairs share >= 2 word bigrams
MAX_SHINGLE_DF = 60             # blocking: ignore bigrams appearing in more articles than this
LARGE_FAMILY_SIZE = 4
LOW_DENSITY = 0.5

TAG_RE = re.compile(r"<[^>]+>")
NONWORD_RE = re.compile(r"[^\w\s]")
DIGITS_RE = re.compile(r"\d+")
TRACKING_QUERY_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid",
}


# --- text handling ---------------------------------------------------------------------
def normalize(text: object) -> str:
    """Unescape HTML entities, NFC-normalize, lowercase, drop tags/punctuation.

    Diacritics are kept: Vietnamese tone marks distinguish words.
    """
    if text is None:
        return ""
    try:
        if pd.isna(text):
            return ""
    except (TypeError, ValueError):
        pass
    s = html.unescape(str(text))
    s = unicodedata.normalize("NFC", s).lower()
    s = TAG_RE.sub(" ", s)
    s = NONWORD_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_canonical_url(value: object) -> str:
    """Conservatively normalize a canonical URL for exact matching only.

    The stored ``canonical_url`` is never changed. Invalid or relative values return an
    empty key and therefore cannot establish an exact duplicate.
    """
    if value is None or (not isinstance(value, (list, dict, tuple, set)) and pd.isna(value)):
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        if not parts.scheme or not parts.hostname:
            return ""
        scheme = parts.scheme.lower()
        host = parts.hostname.lower()
        if host.startswith("www."):
            host = host[4:]
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = parts.port
        netloc = host if port is None else f"{host}:{port}"
        path = parts.path.rstrip("/")
        query_items = [
            (key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() not in TRACKING_QUERY_PARAMS
        ]
        query = urlencode(sorted(query_items))
        return urlunsplit((scheme, netloc, path, query, ""))
    except (TypeError, ValueError):
        return ""


def bigrams(text: str) -> frozenset:
    tokens = text.split()
    if len(tokens) < 2:
        return frozenset([tuple(tokens)]) if tokens else frozenset()
    return frozenset(zip(tokens, tokens[1:]))


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def number_tokens(*texts: str) -> frozenset:
    return frozenset(DIGITS_RE.findall(" ".join(texts)))


# --- prepared per-article features -----------------------------------------------------
def prepare(df: pd.DataFrame) -> list[dict]:
    times = pd.to_datetime(df["published_at"], utc=True, errors="coerce")
    feats = []
    for pos, row in enumerate(df.itertuples(index=False)):
        title = normalize(row.title)
        desc = normalize(row.description)
        feats.append(
            {
                "pos": pos,
                "id": row.article_id,
                "canonical_url": normalize_canonical_url(row.canonical_url),
                "title": title,
                "desc": desc,
                "title_bg": bigrams(title),
                "desc_bg": bigrams(desc),
                "desc_tokens": len(desc.split()),
                "numbers": number_tokens(title, desc),
                "time": None if pd.isna(times.iloc[pos]) else times.iloc[pos],
                "language": None if pd.isna(row.language) else row.language,
            }
        )
    return feats


# --- pair scoring and decision ---------------------------------------------------------
def score_pair(a: dict, b: dict) -> dict:
    ts = jaccard(a["title_bg"], b["title_bg"])
    ds = jaccard(a["desc_bg"], b["desc_bg"])
    if a["numbers"] and b["numbers"]:
        nj = len(a["numbers"] & b["numbers"]) / len(a["numbers"] | b["numbers"])
    else:
        nj = None
    hours = None
    if a["time"] is not None and b["time"] is not None:
        hours = abs((a["time"] - b["time"]).total_seconds()) / 3600.0
    return {"title_sim": ts, "desc_sim": ds, "number_sim": nj, "hours_apart": hours}


def classify(a: dict, b: dict, s: dict) -> tuple[str, str]:
    """Return (relation, reason). Exact duplicates are handled before this step."""
    if a["language"] and b["language"] and a["language"] != b["language"]:
        return "UNRELATED", "language_mismatch (cross-language matching is out of scope)"

    both_desc = a["desc_tokens"] >= MIN_DESC_TOKENS and b["desc_tokens"] >= MIN_DESC_TOKENS
    same_event_signal = s["title_sim"] >= SAME_EVENT_TITLE or s["desc_sim"] >= SAME_EVENT_DESC

    if both_desc and s["desc_sim"] >= DESC_COPY_THRESHOLD:
        if s["hours_apart"] is not None and s["hours_apart"] > MAX_HOURS_APART:
            return "SAME_EVENT_INDEPENDENT", "copy_evidence_vetoed: published more than a week apart"
        if s["number_sim"] is not None and s["number_sim"] < NUMBER_CONFLICT_JACCARD:
            return "SAME_EVENT_INDEPENDENT", "copy_evidence_vetoed: numeric details conflict"
        return "SYNDICATED_COPY", f"description_overlap>={DESC_COPY_THRESHOLD}"

    if same_event_signal:
        if not both_desc and s["title_sim"] >= SAME_EVENT_TITLE:
            return "SAME_EVENT_INDEPENDENT", "headline_overlap_but_description_missing_or_short: copy cannot be confirmed"
        return "SAME_EVENT_INDEPENDENT", "headline_or_lede_overlap_without_copy_level_description_match"
    return "UNRELATED", "below_all_similarity_thresholds"


# --- candidate generation --------------------------------------------------------------
def candidate_pairs(feats: list[dict]) -> list[tuple[int, int]]:
    """Pairs sharing >= MIN_SHARED_SHINGLES word bigrams (title or description).

    Bigrams present in more than MAX_SHINGLE_DF articles are boilerplate and skipped.
    """
    index: dict[tuple, list[int]] = defaultdict(list)
    for f in feats:
        for sh in f["title_bg"] | f["desc_bg"]:
            index[sh].append(f["pos"])
    counts: Counter = Counter()
    for members in index.values():
        if 2 <= len(members) <= MAX_SHINGLE_DF:
            for i, j in combinations(sorted(members), 2):
                counts[(i, j)] += 1
    return sorted(pair for pair, c in counts.items() if c >= MIN_SHARED_SHINGLES)


# --- families --------------------------------------------------------------------------
class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def family_id(article_ids: list[str]) -> str:
    return "dupfam_" + hashlib.sha256("|".join(sorted(article_ids)).encode("utf-8")).hexdigest()[:12]


def analyze(df: pd.DataFrame) -> dict:
    """Run detection. Pure function of the input frame (deterministic)."""
    feats = prepare(df)
    n = len(feats)

    # Stage 1a: exact duplicates by the same non-empty normalized canonical URL.
    edges: dict[tuple[int, int], tuple[str, dict, str]] = {}
    url_groups: dict[str, list[int]] = defaultdict(list)
    for f in feats:
        if f["canonical_url"]:
            url_groups[f["canonical_url"]].append(f["pos"])
    for members in url_groups.values():
        if len(members) > 1:
            for i, j in combinations(sorted(members), 2):
                edges[(i, j)] = (
                    "EXACT_DUPLICATE", score_pair(feats[i], feats[j]),
                    "identical_normalized_canonical_url",
                )

    # Stage 1b: exact duplicates by identical non-empty normalized title AND description.
    text_groups: dict[tuple, list[int]] = defaultdict(list)
    for f in feats:
        if f["title"] and f["desc"]:
            text_groups[(f["title"], f["desc"])].append(f["pos"])
    for members in text_groups.values():
        if len(members) > 1:
            for i, j in combinations(sorted(members), 2):
                edges.setdefault(
                    (i, j),
                    ("EXACT_DUPLICATE", score_pair(feats[i], feats[j]),
                     "identical_normalized_title_and_description"),
                )

    # Stage 2: candidate generation and classification of non-exact pairs.
    pair_info: dict[tuple[int, int], tuple[str, dict, str]] = {}
    for i, j in candidate_pairs(feats):
        if (i, j) in edges:
            continue
        s = score_pair(feats[i], feats[j])
        rel, reason = classify(feats[i], feats[j], s)
        pair_info[(i, j)] = (rel, s, reason)

    accepted = dict(edges)
    accepted.update({k: v for k, v in pair_info.items() if v[0] == "SYNDICATED_COPY"})

    # Stage 3: families = connected components of accepted (exact + syndicated) edges.
    uf = UnionFind(n)
    for i, j in sorted(accepted):
        uf.union(i, j)
    comps: dict[int, list[int]] = defaultdict(list)
    for pos in range(n):
        comps[uf.find(pos)].append(pos)
    families = {}
    assignment: list[str | None] = [None] * n
    for members in comps.values():
        if len(members) < 2:
            continue
        ids = [feats[m]["id"] for m in members]
        fid = family_id(ids)
        member_edges = [(i, j) for (i, j) in accepted if i in set(members)]
        kinds = {accepted[e][0] for e in member_edges}
        possible = len(members) * (len(members) - 1) / 2
        density = len(member_edges) / possible
        families[fid] = {
            "members": sorted(members),
            "type": "EXACT_DUPLICATE" if kinds == {"EXACT_DUPLICATE"} else "SYNDICATED_COPY",
            "density": density,
            "flag": "review_large_or_sparse" if (len(members) >= LARGE_FAMILY_SIZE or density < LOW_DENSITY) else "",
        }
        for m in members:
            assignment[m] = fid

    return {"feats": feats, "accepted": accepted, "pair_info": pair_info, "families": families, "assignment": assignment}


# --- QC selection ----------------------------------------------------------------------
def _qc_row(df, feats, i, j, rel, s, reason, bucket, assignment):
    a, b = df.iloc[i], df.iloc[j]
    return {
        "bucket": bucket,
        "left_article_id": a.article_id, "right_article_id": b.article_id,
        "left_publisher": a.publisher_id, "right_publisher": b.publisher_id,
        "left_url": a.url, "right_url": b.url,
        "left_title": a.title, "right_title": b.title,
        "left_description": a.description, "right_description": b.description,
        "title_jaccard": round(s["title_sim"], 3), "desc_jaccard": round(s["desc_sim"], 3),
        "number_jaccard": None if s["number_sim"] is None else round(s["number_sim"], 3),
        "hours_apart": None if s["hours_apart"] is None else round(s["hours_apart"], 1),
        "predicted_relation": rel,
        "manual_relation": "",
        "duplicate_family_id": assignment[i] if assignment[i] and assignment[i] == assignment[j] else "",
        "review_notes": reason,
    }


def build_qc(df: pd.DataFrame, result: dict) -> pd.DataFrame:
    feats, accepted, pair_info, families, assignment = (
        result[k] for k in ("feats", "accepted", "pair_info", "families", "assignment")
    )
    rows: list[dict] = []
    seen: set[tuple[int, int]] = set()

    def add(bucket, i, j, rel, s, reason):
        if (i, j) in seen:
            return
        seen.add((i, j))
        rows.append(_qc_row(df, feats, i, j, rel, s, reason, bucket, assignment))

    for (i, j), (rel, s, reason) in sorted(accepted.items()):
        add("POSITIVE_EXACT_DUPLICATE" if rel == "EXACT_DUPLICATE" else "POSITIVE_SYNDICATED_COPY", i, j, rel, s, reason)

    rejected = [(k, v) for k, v in pair_info.items() if v[0] != "SYNDICATED_COPY"]

    def top(items, key, limit):
        return sorted(items, key=lambda kv: (-key(kv), kv[0]))[:limit]

    # rejected pairs closest to the copy threshold (borderline rejections)
    border = [kv for kv in rejected if 0.45 <= kv[1][1]["desc_sim"] < DESC_COPY_THRESHOLD or "vetoed" in kv[1][2]]
    for (i, j), (rel, s, reason) in top(border, lambda kv: kv[1][1]["desc_sim"], 15):
        add("REJECTED_BORDERLINE", i, j, rel, s, reason)

    # predicted same-event examples, chosen by lede (description) overlap ...
    same_event = [kv for kv in rejected if kv[1][0] == "SAME_EVENT_INDEPENDENT"]
    for (i, j), (rel, s, reason) in top(same_event, lambda kv: kv[1][1]["desc_sim"], 10):
        add("PREDICTED_SAME_EVENT_INDEPENDENT", i, j, rel, s, reason)

    # ... and recall probes chosen by headline overlap: near-identical headlines whose
    # descriptions did not reach copy level are where a missed syndication would hide.
    # (Pairs already emitted above are skipped, so each bucket shows distinct pairs.)
    probes = [kv for kv in rejected if kv[1][1]["title_sim"] >= 0.6]
    for (i, j), (rel, s, reason) in top(probes, lambda kv: kv[1][1]["title_sim"], 15):
        add("RECALL_PROBE_HIGH_TITLE_LOW_DESC", i, j, rel, s, reason)

    # unrelated controls: articles ordered by sha256(article_id); consecutive ones are paired
    order = sorted(range(len(feats)), key=lambda p: hashlib.sha256(feats[p]["id"].encode()).hexdigest())
    for a_pos, b_pos in zip(order[:24:2], order[1:24:2]):
        i, j = sorted((a_pos, b_pos))
        s = score_pair(feats[i], feats[j])
        rel, reason = classify(feats[i], feats[j], s)
        add("UNRELATED_CONTROL", i, j, rel, s, reason)

    for fid, fam in sorted(families.items()):
        if fam["flag"]:
            for i, j in combinations(fam["members"], 2):
                if (i, j) in accepted:
                    rel, s, reason = accepted[(i, j)]
                    add("SUSPICIOUS_LARGE_FAMILY", i, j, rel, s, reason)

    qc = pd.DataFrame(rows)
    qc.insert(0, "pair_id", [f"qc_{k:04d}" for k in range(1, len(qc) + 1)])
    return qc


def family_summary(df: pd.DataFrame, result: dict) -> pd.DataFrame:
    rows = []
    for fid, fam in sorted(result["families"].items()):
        sub = df.iloc[fam["members"]]
        rows.append(
            {
                "duplicate_family_id": fid,
                "family_type": fam["type"],
                "family_size": len(sub),
                "publishers": ";".join(sorted(set(sub.publisher_id))),
                "article_ids": ";".join(sub.article_id),
                "titles": " || ".join(sub.title),
                "edge_density": round(fam["density"], 3),
                "flag": fam["flag"],
            }
        )
    return pd.DataFrame(rows, columns=["duplicate_family_id", "family_type", "family_size", "publishers", "article_ids", "titles", "edge_density", "flag"])


# --- validation, provenance, CLI -------------------------------------------------------
def load_master(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if list(df.columns) != FROZEN_SCHEMA:
        raise SystemExit(f"Input schema/column order differs from the frozen 20-column contract: {list(df.columns)}")
    if df["article_id"].isna().any() or df["article_id"].duplicated().any():
        raise SystemExit("article_id must be present and unique in the master input")
    return df


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def annotated_output(df: pd.DataFrame, assignment: list[str | None]) -> pd.DataFrame:
    """Populate only the existing family column while preserving the frozen contract."""
    if list(df.columns) != FROZEN_SCHEMA:
        raise ValueError("Cannot annotate a frame outside the frozen 20-column contract")
    if len(assignment) != len(df):
        raise ValueError("Assignment length does not match input row count")
    out = df.copy()
    out["duplicate_family_id"] = pd.Series(assignment, index=out.index, dtype="object")
    return out


def git_revision() -> str:
    try:
        rev = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "."], text=True).strip()
        return rev + ("+uncommitted-changes" if dirty else "")
    except Exception:
        return "unknown"


def main() -> None:
    ap = argparse.ArgumentParser(description="Independent Phase 2B duplicate/syndication annotation.")
    ap.add_argument("--input", default="data/processed/master/articles_master.parquet")
    ap.add_argument("--output", default="data/processed/master/articles_dedup.parquet")
    out_dir = "team_work/phases/phase2_processing/phase2b_dedup_syndication/sample_output"
    ap.add_argument("--qc-output", default=f"{out_dir}/dedup_qc_pairs_independent.csv")
    ap.add_argument("--family-output", default=f"{out_dir}/dedup_family_summary_independent.csv")
    ap.add_argument("--summary-output", default=f"{out_dir}/dedup_run_summary_independent.json")
    ap.add_argument("--expect-sha256", default=None, help="fail unless the input hash matches")
    args = ap.parse_args()

    in_path = Path(args.input)
    digest = sha256_file(in_path)
    if args.expect_sha256 and digest != args.expect_sha256:
        raise SystemExit(f"Input SHA-256 {digest} does not match expected {args.expect_sha256}")
    df = load_master(in_path)

    result = analyze(df)
    rerun = analyze(df)
    deterministic = result["assignment"] == rerun["assignment"]

    out = annotated_output(df, result["assignment"])
    assert list(out.columns) == FROZEN_SCHEMA and len(out) == len(df)

    # verification against the assignment's checklist
    non_family = [c for c in FROZEN_SCHEMA if c != "duplicate_family_id"]
    unchanged = bool(out[non_family].equals(df[non_family]))
    fam_sizes = Counter(a for a in result["assignment"] if a)
    all_ge2 = all(v >= 2 for v in fam_sizes.values())

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.output, index=False)
    reread = pd.read_parquet(args.output)
    roundtrip_ok = bool(reread[non_family].equals(df[non_family]) and list(reread.columns) == FROZEN_SCHEMA)

    qc = build_qc(df, result)
    fam = family_summary(df, result)
    for p in (args.qc_output, args.family_output, args.summary_output):
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    qc.to_csv(args.qc_output, index=False)
    fam.to_csv(args.family_output, index=False)

    size_dist = Counter(fam_sizes.values())
    largest = max(fam_sizes.items(), key=lambda kv: (kv[1], kv[0])) if fam_sizes else None
    types = Counter(f["type"] for f in result["families"].values())
    summary = {
        "input_path": str(in_path),
        "input_rows": len(df),
        "input_size_bytes": in_path.stat().st_size,
        "input_sha256": digest,
        "run_date_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "code_revision": git_revision(),
        "total_articles": len(df),
        "articles_in_families": int(sum(fam_sizes.values())),
        "singleton_articles": int(len(df) - sum(fam_sizes.values())),
        "total_families": len(fam_sizes),
        "exact_duplicate_families": types.get("EXACT_DUPLICATE", 0),
        "syndicated_copy_families": types.get("SYNDICATED_COPY", 0),
        "family_size_distribution": {str(k): v for k, v in sorted(size_dist.items())},
        "largest_family": None if largest is None else {"duplicate_family_id": largest[0], "size": largest[1]},
        "candidate_pairs_scored": len(result["pair_info"]),
        "qc_pairs_total": len(qc),
        "qc_pairs_by_bucket": {k: int(v) for k, v in qc["bucket"].value_counts().sort_index().items()},
        "thresholds": {
            "DESC_COPY_THRESHOLD": DESC_COPY_THRESHOLD, "MIN_DESC_TOKENS": MIN_DESC_TOKENS,
            "MAX_HOURS_APART": MAX_HOURS_APART, "NUMBER_CONFLICT_JACCARD": NUMBER_CONFLICT_JACCARD,
            "SAME_EVENT_TITLE": SAME_EVENT_TITLE, "SAME_EVENT_DESC": SAME_EVENT_DESC,
            "MIN_SHARED_SHINGLES": MIN_SHARED_SHINGLES, "MAX_SHINGLE_DF": MAX_SHINGLE_DF,
        },
        "checks": {
            "row_count_equal": len(out) == len(df),
            "column_order_frozen": list(out.columns) == FROZEN_SCHEMA,
            "non_family_fields_unchanged": unchanged,
            "written_file_roundtrip_ok": roundtrip_ok,
            "every_family_has_2plus_articles": all_ge2,
            "rerun_identical_assignments": deterministic,
        },
    }
    Path(args.summary_output).write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps({k: summary[k] for k in ("input_sha256", "total_articles", "total_families", "articles_in_families", "singleton_articles", "family_size_distribution", "qc_pairs_by_bucket", "checks")}, indent=2))
    if not all(summary["checks"].values()):
        raise SystemExit("One or more verification checks failed")


if __name__ == "__main__":
    main()

"""Midterm analysis + figures built ONLY from the frozen Phase 2C artifact.

Input : data/processed/master/articles_clustered.parquet  (SHA-256 pinned below)
Manual: team_work/phases/phase3_analysis_graph/midterm_analysis/manual_inputs/*.csv
Output: team_work/phases/phase3_analysis_graph/midterm_analysis/{tables,figures}/

Every figure is written as PNG next to the CSV it was drawn from
(same base name: ``figN_<name>.png`` <-> ``figN_<name>.csv``).

Run from the repository root:  python -m src.analysis.midterm_analysis
"""

from __future__ import annotations

import hashlib
import html
import itertools
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import Circle  # noqa: E402

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

INPUT = REPOSITORY_ROOT / "data/processed/master/articles_clustered.parquet"
EXPECTED_SHA256 = "90fd7938277b7f4138e12fd14be6ee328c854734ca9db2240da5d367b67412af"
QC_CSV = (
    REPOSITORY_ROOT
    / "team_work/phases/phase2_processing/phase2c_event_clustering/sample_output/event_clusters_qc.csv"
)
OUT = REPOSITORY_ROOT / "team_work/phases/phase3_analysis_graph/midterm_analysis"
MANUAL = OUT / "manual_inputs"
TABLES = OUT / "tables"
FIGURES = OUT / "figures"

# ── palette (validated reference palette, light mode) ────────────────────────
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
BLUE = "#2a78d6"  # categorical slot 1: default bars
ORANGE = "#eb6834"  # categorical slot 2: highlight (vietnamnet.vn)
BLUE_LIGHT = "#9ec5f4"  # sequential blue 200: singleton events
GRAY = "#8d8c86"  # neutral: uncertain / isolated nodes
LABEL_COLORS = {"SAME_EVENT": BLUE, "DIFFERENT_EVENT": ORANGE, "UNCERTAIN": GRAY}

DOMINANT = "vietnamnet.vn"


def _style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "axes.edgecolor": GRID,
            "axes.labelcolor": INK_2,
            "xtick.color": INK_2,
            "ytick.color": INK_2,
            "text.color": INK,
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
            "axes.titlesize": 13,
        }
    )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _save(fig, name: str, table: pd.DataFrame) -> None:
    """Write figure PNG + its source CSV with the same base name."""
    FIGURES.mkdir(parents=True, exist_ok=True)
    TABLES.mkdir(parents=True, exist_ok=True)
    table.to_csv(TABLES / f"{name}.csv", index=False, encoding="utf-8-sig")
    fig.savefig(FIGURES / f"{name}.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def _title(fig, title: str, subtitle: str) -> None:
    fig.text(0.01, 0.985, title, ha="left", va="top", fontsize=15, fontweight="bold", color=INK)
    fig.text(0.01, 0.925, subtitle, ha="left", va="top", fontsize=10.5, color=INK_2)


# ── data ─────────────────────────────────────────────────────────────────────


def load() -> pd.DataFrame:
    sha = _sha256(INPUT)
    if sha != EXPECTED_SHA256:
        raise SystemExit(f"articles_clustered.parquet SHA-256 {sha} != frozen artifact {EXPECTED_SHA256}")
    df = pd.read_parquet(INPUT).reset_index(drop=True)
    published = pd.to_datetime(df["published_at"], utc=True, errors="coerce")
    first_seen = pd.to_datetime(df["first_seen_at"], utc=True, errors="coerce")
    df["event_time"] = published.fillna(first_seen)  # same rule as Phase 2C
    df["unit_key"] = df["duplicate_family_id"].where(df["duplicate_family_id"].notna(), df["article_id"])
    return df


def event_frame(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("event_cluster_id")
    ev = pd.DataFrame(
        {
            "cluster_size": g.size(),
            "n_publishers": g["publisher_domain"].nunique(),
            "first_published_at": g["event_time"].min(),
            "last_published_at": g["event_time"].max(),
        }
    )
    ev["publishers"] = g["publisher_domain"].agg(lambda s: "; ".join(sorted(s.unique())))
    ev["sample_titles"] = df.sort_values(["event_time", "article_id"]).groupby("event_cluster_id")["title"].agg(
        lambda s: " | ".join(html.unescape(t) for t in list(s)[:5])
    )
    ev["span_days"] = (ev["last_published_at"] - ev["first_published_at"]).dt.total_seconds() / 86400
    return ev.reset_index()


# ── 1. event size ────────────────────────────────────────────────────────────


def fig1_event_sizes(ev: pd.DataFrame) -> dict:
    n_events = len(ev)
    counts = ev["cluster_size"].value_counts().sort_index()
    table = pd.DataFrame(
        {
            "event_size_articles": counts.index,
            "n_events": counts.values,
            "share_of_events": (counts.values / n_events).round(4),
            "n_articles": counts.index * counts.values,
            "event_type": np.where(counts.index == 1, "singleton", "multi-article"),
        }
    )
    n_single = int(counts.get(1, 0))
    n_multi = n_events - n_single

    fig, ax = plt.subplots(figsize=(9, 5.6))
    colors = [BLUE_LIGHT if s == 1 else BLUE for s in table["event_size_articles"]]
    bars = ax.bar(table["event_size_articles"].astype(str), table["n_events"], color=colors, width=0.72)
    for bar, n, share in zip(bars, table["n_events"], table["share_of_events"]):
        ax.text(bar.get_x() + bar.get_width() / 2, n + 12, f"{n:,}", ha="center", va="bottom", fontsize=11, fontweight="bold")
        ax.text(bar.get_x() + bar.get_width() / 2, n + 12 + 42, f"{share:.1%}", ha="center", va="bottom", fontsize=9, color=INK_2)
    ax.set_xlabel("Articles per event (event size)")
    ax.set_ylabel("Number of events")
    ax.set_ylim(0, counts.max() * 1.18)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    _title(
        fig,
        f"{n_events:,} events: {n_single:,} singletons ({n_single / n_events:.1%}) and {n_multi:,} multi-article ({n_multi / n_events:.1%})",
        "Event size = number of articles in an event_cluster_id. 1,223 articles in total; largest event has 7.",
    )
    ax.text(0.99, 0.62, "light = singleton events\ndark = multi-article events", transform=ax.transAxes, ha="right", va="top", fontsize=10, color=INK_2)
    fig.subplots_adjust(top=0.84)
    _save(fig, "fig1_event_size_distribution", table)
    return {"total_events": n_events, "singleton_events": n_single, "multi_article_events": n_multi}


# ── 2. publishers ────────────────────────────────────────────────────────────


def publisher_table(df: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    cross_ids = set(ev.loc[ev["n_publishers"] >= 2, "event_cluster_id"])
    multi_ids = set(ev.loc[ev["cluster_size"] >= 2, "event_cluster_id"])
    rows = []
    for pub, g in df.groupby("publisher_domain"):
        rows.append(
            {
                "publisher_domain": pub,
                "n_articles": len(g),
                "share_of_articles": round(len(g) / len(df), 4),
                "n_distinct_events": g["event_cluster_id"].nunique(),
                "n_multi_article_events": g.loc[g["event_cluster_id"].isin(multi_ids), "event_cluster_id"].nunique(),
                "n_cross_publisher_events": g.loc[g["event_cluster_id"].isin(cross_ids), "event_cluster_id"].nunique(),
                "articles_in_cross_publisher_events": int(g["event_cluster_id"].isin(cross_ids).sum()),
            }
        )
    t = pd.DataFrame(rows).sort_values("n_articles", ascending=False).reset_index(drop=True)
    t["share_articles_in_cross_publisher_events"] = (t["articles_in_cross_publisher_events"] / t["n_articles"]).round(4)
    t["articles_per_event"] = (t["n_articles"] / t["n_distinct_events"]).round(3)
    t.insert(0, "rank_by_articles", range(1, len(t) + 1))
    return t


def fig2_publishers(t: pd.DataFrame) -> dict:
    order = t.sort_values("n_articles")  # bottom → top so the largest is on top
    colors = [ORANGE if p == DOMINANT else BLUE for p in order["publisher_domain"]]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2), sharey=True)
    for ax, col, label in zip(axes, ["n_articles", "n_distinct_events"], ["Articles", "Distinct events"]):
        bars = ax.barh(order["publisher_domain"], order[col], color=colors, height=0.66)
        for bar, v in zip(bars, order[col]):
            ax.text(v + t[col].max() * 0.015, bar.get_y() + bar.get_height() / 2, f"{v:,}", va="center", fontsize=10.5, fontweight="bold")
        ax.set_xlim(0, t[col].max() * 1.18)
        ax.set_xlabel(label)
        ax.xaxis.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.tick_params(length=0)
    share = t.loc[t["publisher_domain"] == DOMINANT, "share_of_articles"].iloc[0]
    n_pub = len(t)
    _title(
        fig,
        f"{DOMINANT} supplies {share:.1%} of the corpus",
        f"Only {n_pub} publishers in total (5 Vietnamese, 1 international with 2 articles). Every other publisher combined has {int(t['n_articles'].sum() - t['n_articles'].max()):,} articles.",
    )
    fig.subplots_adjust(top=0.82, wspace=0.08)
    _save(fig, "fig2_publisher_articles_and_events", t)
    hhi = float(((t["n_articles"] / t["n_articles"].sum()) ** 2).sum())
    return {"dominant_publisher": DOMINANT, "dominant_share": float(share), "n_publishers": int(n_pub), "hhi_articles": round(hhi, 4)}


# ── 3. cross-publisher events ────────────────────────────────────────────────


def cross_publisher_tables(ev: pd.DataFrame) -> pd.DataFrame:
    cols = ["event_cluster_id", "first_published_at", "cluster_size", "n_publishers", "publishers", "sample_titles"]
    x = ev[ev["n_publishers"] >= 2].sort_values(["first_published_at", "event_cluster_id"]).reset_index(drop=True)
    x = x.assign(first_published_at=x["first_published_at"].dt.strftime("%Y-%m-%dT%H:%M:%SZ"))
    x[cols].to_csv(TABLES / "table3_cross_publisher_events.csv", index=False, encoding="utf-8-sig")

    review = pd.read_csv(MANUAL / "cross_publisher_event_review.csv")
    merged = x[cols + ["span_days"]].merge(review, on="event_cluster_id", how="left", validate="one_to_one")
    if merged["inspection_verdict"].isna().any():
        raise SystemExit("cross_publisher_event_review.csv does not cover every cross-publisher event")
    merged["span_days"] = merged["span_days"].round(2)
    merged.to_csv(TABLES / "table3_cross_publisher_events_reviewed.csv", index=False, encoding="utf-8-sig")
    return merged


# ── 4. co-reporting network ──────────────────────────────────────────────────


def coreporting_edges(df: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    """Publisher pairs that reported the same event.

    weight_all         = events (>=2 publishers) containing both publishers
    weight_independent = events where the two publishers have articles that are NOT the same
                         Phase 2B duplicate family (i.e. not a syndicated/duplicate copy)
    """
    cross_ids = ev.loc[ev["n_publishers"] >= 2, "event_cluster_id"]
    sub = df[df["event_cluster_id"].isin(cross_ids)]
    rows: dict[tuple, dict] = {}
    for _, g in sub.groupby("event_cluster_id"):
        by_pub = {p: set(gp["unit_key"]) for p, gp in g.groupby("publisher_domain")}
        for a, b in itertools.combinations(sorted(by_pub), 2):
            r = rows.setdefault((a, b), {"publisher_a": a, "publisher_b": b, "weight_all": 0, "weight_independent": 0})
            r["weight_all"] += 1
            # independent if some unit (family or single article) of A differs from some unit of B
            if any(ua != ub for ua in by_pub[a] for ub in by_pub[b]):
                r["weight_independent"] += 1
    edges = pd.DataFrame(rows.values())
    events_per_pub = df.groupby("publisher_domain")["event_cluster_id"].nunique()
    edges["events_a"] = edges["publisher_a"].map(events_per_pub)
    edges["events_b"] = edges["publisher_b"].map(events_per_pub)
    edges["shared_over_smaller_publisher_events"] = (
        edges["weight_independent"] / edges[["events_a", "events_b"]].min(axis=1)
    ).round(4)
    return edges.sort_values(["weight_independent", "weight_all"], ascending=False).reset_index(drop=True)


def fig4_network(df: pd.DataFrame, edges: pd.DataFrame, pub_table: pd.DataFrame) -> dict:
    nodes = pub_table[["publisher_domain", "n_articles"]].copy()
    domestic = [p for p in nodes["publisher_domain"] if p != "asia.nikkei.com"]
    # circular layout for the domestic publishers; international publisher off to the side
    angles = np.linspace(np.pi / 2, np.pi / 2 + 2 * np.pi, len(domestic), endpoint=False)
    pos = {p: (np.cos(a) * 1.0, np.sin(a) * 1.0) for p, a in zip(domestic, angles)}
    pos["asia.nikkei.com"] = (1.85, -0.85)

    used = edges[edges["weight_independent"] > 0]
    wmax = used["weight_independent"].max()
    fig, ax = plt.subplots(figsize=(9.5, 8))
    ax.set_aspect("equal")
    ax.axis("off")

    for _, e in used.sort_values("weight_independent").iterrows():
        (x1, y1), (x2, y2) = pos[e["publisher_a"]], pos[e["publisher_b"]]
        w = e["weight_independent"]
        ax.plot([x1, x2], [y1, y2], color=BLUE, alpha=0.30 + 0.5 * w / wmax, linewidth=1.2 + 9 * w / wmax, solid_capstyle="round", zorder=1)
    for _, e in used.iterrows():
        (x1, y1), (x2, y2) = pos[e["publisher_a"]], pos[e["publisher_b"]]
        t = 0.5
        ax.text(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, str(int(e["weight_independent"])), ha="center", va="center", fontsize=11, fontweight="bold", color=INK,
                bbox=dict(boxstyle="round,pad=0.22", fc=SURFACE, ec=GRID, lw=0.8), zorder=3)

    amax = nodes["n_articles"].max()
    for _, r in nodes.iterrows():
        p = r["publisher_domain"]
        x, y = pos[p]
        radius = 0.09 + 0.20 * np.sqrt(r["n_articles"] / amax)
        colour = ORANGE if p == DOMINANT else (GRAY if p == "asia.nikkei.com" else BLUE)
        ax.add_patch(Circle((x, y), radius, fc=colour, ec=SURFACE, lw=2.5, zorder=4))
        dy = radius + 0.10
        ax.text(x, y + (dy if y >= 0 else -dy), f"{p}\n{int(r['n_articles']):,} articles", ha="center", va="bottom" if y >= 0 else "top", fontsize=10.5, color=INK, zorder=5)
    ax.text(pos["asia.nikkei.com"][0], pos["asia.nikkei.com"][1] - 0.62, "no shared events", ha="center", fontsize=9.5, color=INK_2, style="italic")
    ax.set_xlim(-1.75, 2.35)
    ax.set_ylim(-1.75, 1.6)
    n_edges = len(used)
    n_events = int(edges["weight_all"].max()) if len(edges) else 0
    _title(
        fig,
        "Publisher co-reporting network (undirected)",
        f"Edge = publishers with articles in the same event; number and thickness = shared events (excluding Phase 2B duplicate copies). {n_edges} edges.",
    )
    fig.text(0.01, 0.06, "Node area ~ number of articles. No direction: co-reporting is not influence or copying.\nNode/edge counts come from the 26 cross-publisher events only; thin data, treat as descriptive.", fontsize=9.5, color=INK_2, ha="left")
    fig.subplots_adjust(top=0.88, bottom=0.08)
    _save(fig, "fig4_publisher_coreporting_network", edges)
    return {"n_edges": int(n_edges), "max_edge_weight": int(wmax), "n_nodes": int(len(nodes))}


# ── 5. manual QC ─────────────────────────────────────────────────────────────


def qc_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    qc = pd.read_csv(QC_CSV)
    qc.insert(0, "qc_row", range(len(qc)))
    labels = pd.read_csv(MANUAL / "qc_labels.csv")
    merged = labels.merge(
        qc[["qc_row", "left_publisher", "right_publisher", "left_title", "right_title", "left_event_cluster_id", "right_event_cluster_id", "cosine_distance", "days_apart"]],
        on="qc_row",
        how="left",
        validate="one_to_one",
    )
    for c in ["left_title", "right_title"]:
        merged[c] = merged[c].map(html.unescape)
    merged["labeler"] = "Claude (provisional; needs human spot-check)"
    merged.to_csv(TABLES / "table5_qc_manual_labels.csv", index=False, encoding="utf-8-sig")

    by_stratum = merged.pivot_table(index="stratum", columns="manual_label", values="qc_row", aggfunc="count", fill_value=0).reindex(
        columns=["SAME_EVENT", "DIFFERENT_EVENT", "UNCERTAIN"], fill_value=0
    )
    by_stratum["total"] = by_stratum.sum(axis=1)
    by_stratum = by_stratum.reset_index()
    pattern = merged.pivot_table(index="failure_pattern", columns="manual_label", values="qc_row", aggfunc="count", fill_value=0).reindex(
        columns=["SAME_EVENT", "DIFFERENT_EVENT", "UNCERTAIN"], fill_value=0
    )
    pattern["total"] = pattern.sum(axis=1)
    pattern = pattern.sort_values("total", ascending=False).reset_index()
    return merged, by_stratum, pattern


def fig5_qc(by_stratum: pd.DataFrame, pattern: pd.DataFrame, merged: pd.DataFrame) -> dict:
    pretty = {
        "INTRA_CLUSTER_WEAKEST_LINK": "Weakest link inside an event\n(possible false MERGE)",
        "INTER_CLUSTER_NEAR": "Closest pair across two events\n(possible false SPLIT)",
    }
    order = ["INTRA_CLUSTER_WEAKEST_LINK", "INTER_CLUSTER_NEAR"]
    bs = by_stratum.set_index("stratum").loc[order]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.2), gridspec_kw={"width_ratios": [1.05, 1]})

    y = np.arange(len(order))[::-1]
    left = np.zeros(len(order))
    for lab in ["SAME_EVENT", "DIFFERENT_EVENT", "UNCERTAIN"]:
        vals = bs[lab].to_numpy()
        ax1.barh(y, vals, left=left, color=LABEL_COLORS[lab], height=0.55, edgecolor=SURFACE, linewidth=2, label=lab.replace("_", " ").title())
        for yi, l, v in zip(y, left, vals):
            if v:
                ax1.text(l + v / 2, yi, str(int(v)), ha="center", va="center", color="white", fontsize=12, fontweight="bold")
        left += vals
    ax1.set_yticks(y)
    ax1.set_yticklabels([pretty[s] for s in order], fontsize=10)
    ax1.set_xlabel("Labelled pairs")
    ax1.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=3, frameon=False, fontsize=10)
    ax1.tick_params(length=0)
    ax1.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax1.set_axisbelow(True)
    ax1.set_title("Manual label by sampling stratum", loc="left", fontsize=12)

    p = pattern[pattern["failure_pattern"] != "NONE"].sort_values("total")
    ax2.barh(p["failure_pattern"].str.replace("_", " ").str.title(), p["total"], color=INK_2, height=0.6)  # neutral: blue/orange are reserved for labels in the left panel
    for i, v in enumerate(p["total"]):
        ax2.text(v + 0.3, i, str(int(v)), va="center", fontweight="bold")
    ax2.set_xlabel("Labelled pairs showing the pattern")
    ax2.tick_params(length=0)
    ax2.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax2.set_axisbelow(True)
    ax2.set_title("Recurring failure patterns", loc="left", fontsize=12)

    w = bs.loc["INTRA_CLUSTER_WEAKEST_LINK"]
    n_ = bs.loc["INTER_CLUSTER_NEAR"]
    _title(
        fig,
        "Manual QC of 50 pairs: weather series and same-type incidents drive the errors",
        f"Weakest links: {int(w['DIFFERENT_EVENT'])}/{int(w['total'])} look like different events. Nearest cross-event pairs: {int(n_['SAME_EVENT'])}/{int(n_['total'])} look like the same event. Labels are provisional.",
    )
    fig.subplots_adjust(top=0.82, wspace=0.55, bottom=0.2)
    _save(fig, "fig5_manual_qc_labels_and_failure_patterns", pd.concat([by_stratum.assign(table="by_stratum").rename(columns={"stratum": "group"}), pattern.assign(table="by_failure_pattern").rename(columns={"failure_pattern": "group"})], ignore_index=True))
    weather = merged[merged["failure_pattern"] == "WEATHER_SERIES"]
    return {
        "labelled_pairs": int(len(merged)),
        "weakest_link_different": int(w["DIFFERENT_EVENT"]),
        "weakest_link_total": int(w["total"]),
        "near_pair_same_event_false_split": int(n_["SAME_EVENT"]),
        "near_pair_total": int(n_["total"]),
        "weather_series_pairs": int(len(weather)),
    }


# ── main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    _style()
    TABLES.mkdir(parents=True, exist_ok=True)
    df = load()
    ev = event_frame(df)

    summary: dict = {"input_path": INPUT.relative_to(REPOSITORY_ROOT).as_posix(), "input_sha256": EXPECTED_SHA256, "n_articles": len(df)}
    summary["event_size"] = fig1_event_sizes(ev)

    pub = publisher_table(df, ev)
    summary["publishers"] = fig2_publishers(pub)

    cross = cross_publisher_tables(ev)
    verdicts = cross["inspection_verdict"].value_counts().to_dict()
    summary["cross_publisher_events"] = {"n": int(len(cross)), "manual_verdicts": verdicts}

    edges = coreporting_edges(df, ev)
    summary["network"] = fig4_network(df, edges, pub)

    merged, by_stratum, pattern = qc_tables()
    summary["qc"] = fig5_qc(by_stratum, pattern, merged)
    summary["qc"]["label_counts"] = merged["manual_label"].value_counts().to_dict()

    with open(OUT / "midterm_analysis_manifest.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

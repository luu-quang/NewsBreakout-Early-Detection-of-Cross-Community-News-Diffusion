"""Blind sheet + merge/agreement for the human spot-check of the 17 flagged rows.

    python -m src.analysis.human_review blind    # write the blind sheet (no AI labels)
    python -m src.analysis.human_review merge    # copy human columns into the main sheet, report agreement

The main sheet keeps the AI labels; the blind sheet only carries what a reviewer needs to judge
independently. Merging never edits AI / second-pass fields and never touches manual_inputs/*.csv.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BASE = REPOSITORY_ROOT / "team_work/phases/phase3_analysis_graph/midterm_analysis"
MAIN_SHEET = BASE / "human_review_flagged_17.csv"
BLIND_SHEET = BASE / "human_review_flagged_17_blind.csv"

BLIND_INPUT = ["review_id", "item_type", "reference", "stratum_or_event", "publishers", "context", "allowed_human_labels"]
HUMAN = ["human_label", "reviewer", "comment"]


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig").fillna("")


def make_blind() -> None:
    main = _read(MAIN_SHEET)
    blind = main[BLIND_INPUT].copy()
    for col in HUMAN:
        blind[col] = ""
    blind.to_csv(BLIND_SHEET, index=False, encoding="utf-8-sig")
    print(f"wrote {BLIND_SHEET.relative_to(REPOSITORY_ROOT)} ({len(blind)} rows)")


def merge(blind_path: Path = BLIND_SHEET, main_path: Path = MAIN_SHEET, write: bool = True) -> pd.DataFrame:
    main = _read(main_path)
    blind = _read(blind_path)

    if list(blind["review_id"]) != list(main["review_id"]):
        sys.exit("blind sheet rows/order differ from the main sheet")
    for col in BLIND_INPUT:
        if not blind[col].astype(str).equals(main[col].astype(str)):
            sys.exit(f"blind sheet column {col!r} was modified; reviewers must only fill {HUMAN}")

    problems = []
    for _, r in blind.iterrows():
        allowed = [a.strip() for a in r["allowed_human_labels"].split("/")]
        if r["human_label"] not in allowed:
            problems.append(f"review_id {r['review_id']}: human_label {r['human_label']!r} not in {allowed}")
        if not str(r["reviewer"]).strip():
            problems.append(f"review_id {r['review_id']}: reviewer is empty")
    if problems:
        sys.exit("\n".join(problems))

    out = main.copy()
    for col in HUMAN:
        out[col] = blind[col].values
    out["human_vs_first_pass (Y/N)"] = ["Y" if h == a else "N" for h, a in zip(out["human_label"], out["ai_label"])]
    out["human_vs_second_pass (Y/N)"] = ["Y" if h == s else "N" for h, s in zip(out["human_label"], out["second_pass_label"])]
    if write:
        out.to_csv(main_path, index=False, encoding="utf-8-sig")

    n = len(out)
    print(f"Human vs first-pass AI : {(out['human_vs_first_pass (Y/N)'] == 'Y').sum()} / {n} exact agreement")
    print(f"Human vs second-pass AI: {(out['human_vs_second_pass (Y/N)'] == 'Y').sum()} / {n} exact agreement")
    diff = out[(out["human_vs_first_pass (Y/N)"] == "N") | (out["human_vs_second_pass (Y/N)"] == "N")]
    if len(diff):
        print("\nRows where the human differs from at least one AI pass:")
        print(diff[["review_id", "reference", "ai_label", "second_pass_label", "human_label"]].to_string(index=False))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["blind", "merge"])
    args = parser.parse_args()
    make_blind() if args.command == "blind" else merge()


if __name__ == "__main__":
    main()

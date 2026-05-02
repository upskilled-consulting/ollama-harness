"""
build_dpo_dataset.py — Build DPO preference dataset from runs.jsonl.

Two signal sources:

  1. CROSS-RUN pairs  (available now)
     Same task text, two runs with different final_content and different
     wiggum final scores.  chosen = higher-scoring content.
     Requires: both runs have final_content, score_delta >= min_delta.

  2. WIGGUM-REVISION pairs  (available for runs after wiggum.py was updated
     to store content per round — 2026-04-14+)
     Within a single run: round-1 content (rejected) vs best-round content
     (chosen).  The wiggum feedback provides a rationale for the preference.
     Requires: wiggum_eval_log entries have "content" field.

Output:
  hf_datasets/dpo.jsonl  — one JSON object per pair:

  {
    "prompt":          "<task string>",
    "chosen":          "<higher-quality synthesis>",
    "rejected":        "<lower-quality synthesis>",
    "chosen_score":    8.8,
    "rejected_score":  6.2,
    "score_delta":     2.6,
    "source":          "cross_run" | "wiggum_revision",
    "task_type":       "research" | "annotate" | ...,
    "producer_model":  "pi-qwen-32b",
    "evaluator_model": "Qwen3-Coder:30b",
    "chosen_dims":     {...},
    "rejected_dims":   {...},
    "wiggum_feedback": "<feedback that led to revision>",  # revision pairs only
    "timestamp":       "<ISO timestamp of chosen run>"
  }

Usage:
    python build_dpo_dataset.py                   # default: min_delta=0.5
    python build_dpo_dataset.py --min-delta 1.0   # stricter
    python build_dpo_dataset.py --stats           # print stats only, no write
    python build_dpo_dataset.py --source cross    # only cross-run pairs
    python build_dpo_dataset.py --source revision # only revision pairs
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

RUNS_FILE   = Path("runs.jsonl")
OUT_DIR     = Path("hf_datasets")
OUT_FILE    = OUT_DIR / "dpo.jsonl"

_DEFAULT_MIN_DELTA = 0.5   # minimum score difference to qualify as a pair


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_runs(path: Path) -> list[dict]:
    runs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    runs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return runs


def _normalize_task(task: str) -> str:
    """Stable key for grouping same-task runs."""
    # Lowercase, collapse whitespace, strip leading /skill tokens, take first 120 chars
    t = task.strip().lower()
    t = re.sub(r"^(/\w+\s+)+", "", t)           # strip /skill prefixes
    t = re.sub(r"\s+", " ", t)
    return t[:120]


def _final_score(run: dict) -> float | None:
    """Return the final (last) wiggum score, or None if not available."""
    scores = run.get("wiggum_scores", [])
    if scores and all(isinstance(s, (int, float)) for s in scores):
        return float(scores[-1])
    return None


def _final_dims(run: dict) -> dict:
    """Return dims for the last wiggum round."""
    dims = run.get("wiggum_dims", [])
    if dims and isinstance(dims[-1], dict):
        return dims[-1]
    return {}


# ---------------------------------------------------------------------------
# Source 1: cross-run pairs
# ---------------------------------------------------------------------------

def build_cross_run_pairs(runs: list[dict], min_delta: float) -> list[dict]:
    """
    Group runs by normalized task.  For each group with >= 2 runs that have
    final_content and a wiggum score, emit chosen/rejected pairs.
    Only pairs with score_delta >= min_delta are kept.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in runs:
        task = r.get("task", "").strip()
        if not task:
            continue
        score = _final_score(r)
        content = r.get("final_content", "")
        if score is None or not content:
            continue
        key = _normalize_task(task)
        groups[key].append(r)

    pairs = []
    for key, group in groups.items():
        if len(group) < 2:
            continue

        # Sort by score descending
        group.sort(key=lambda r: _final_score(r), reverse=True)

        # Emit pairs: best vs each worse run
        best = group[0]
        for worse in group[1:]:
            chosen_score   = _final_score(best)
            rejected_score = _final_score(worse)
            delta = chosen_score - rejected_score
            if delta < min_delta:
                continue

            # Prefer runs from same producer_model for cleaner signal
            if best.get("producer_model") != worse.get("producer_model"):
                continue

            pairs.append({
                "prompt":          best.get("task", "").strip(),
                "chosen":          best["final_content"],
                "rejected":        worse["final_content"],
                "chosen_score":    chosen_score,
                "rejected_score":  rejected_score,
                "score_delta":     round(delta, 2),
                "source":          "cross_run",
                "task_type":       best.get("task_type") or worse.get("task_type"),
                "producer_model":  best.get("producer_model"),
                "evaluator_model": best.get("evaluator_model"),
                "chosen_dims":     _final_dims(best),
                "rejected_dims":   _final_dims(worse),
                "wiggum_feedback": "",
                "timestamp":       best.get("timestamp", ""),
            })

    return pairs


# ---------------------------------------------------------------------------
# Source 2: wiggum-revision pairs
# ---------------------------------------------------------------------------

def build_revision_pairs(runs: list[dict], min_delta: float) -> list[dict]:
    """
    For each run where wiggum_eval_log entries carry a "content" field,
    emit chosen/rejected pairs from the best-scoring round vs round 1.
    Requires wiggum.py >= 2026-04-14 (content field added to round_record).
    """
    pairs = []

    for r in runs:
        log = r.get("wiggum_eval_log", [])
        if not log or not isinstance(log, list):
            continue

        # Filter to rounds that have content
        rounds_with_content = [e for e in log if e.get("content")]
        if len(rounds_with_content) < 2:
            continue

        scores_with_content = [e["score"] for e in rounds_with_content]
        max_score = max(scores_with_content)
        min_score = min(scores_with_content)
        delta = max_score - min_score

        if delta < min_delta:
            continue

        # chosen = round with highest score; rejected = round with lowest score
        best_entry  = max(rounds_with_content, key=lambda e: e["score"])
        worst_entry = min(rounds_with_content, key=lambda e: e["score"])

        # Use the round immediately preceding best as the rejected if delta allows
        # (more useful signal than worst-of-all when they're far apart)
        round_num_best  = best_entry["round"]
        round_num_worst = worst_entry["round"]

        # Prefer round 1 (initial output) as rejected — shows pre-revision quality
        round1 = next((e for e in rounds_with_content if e["round"] == 1), None)
        if round1 and round1 is not best_entry:
            rejected_entry = round1
        else:
            rejected_entry = worst_entry

        chosen_score   = float(best_entry["score"])
        rejected_score = float(rejected_entry["score"])
        actual_delta   = chosen_score - rejected_score

        if actual_delta < min_delta:
            continue

        # Gather feedback from the round that led to the revision
        feedback_round = next(
            (e for e in rounds_with_content if e["round"] == rejected_entry["round"]),
            rejected_entry,
        )
        feedback = feedback_round.get("feedback", "")

        pairs.append({
            "prompt":          r.get("task", "").strip(),
            "chosen":          best_entry["content"],
            "rejected":        rejected_entry["content"],
            "chosen_score":    chosen_score,
            "rejected_score":  rejected_score,
            "score_delta":     round(actual_delta, 2),
            "source":          "wiggum_revision",
            "task_type":       r.get("task_type"),
            "producer_model":  r.get("producer_model"),
            "evaluator_model": r.get("evaluator_model"),
            "chosen_dims":     best_entry.get("dims", {}),
            "rejected_dims":   rejected_entry.get("dims", {}),
            "wiggum_feedback": feedback,
            "timestamp":       r.get("timestamp", ""),
        })

    return pairs


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def _print_stats(pairs: list[dict]) -> None:
    if not pairs:
        print("No pairs generated.")
        return

    from statistics import mean, median

    by_source: dict[str, list[dict]] = defaultdict(list)
    for p in pairs:
        by_source[p["source"]].append(p)

    print(f"\nTotal pairs: {len(pairs)}")
    deltas = [p["score_delta"] for p in pairs]
    print(f"  score_delta — min={min(deltas):.2f}  mean={mean(deltas):.2f}  "
          f"median={median(deltas):.2f}  max={max(deltas):.2f}")

    for source, ps in sorted(by_source.items()):
        d = [p["score_delta"] for p in ps]
        print(f"\n  [{source}] {len(ps)} pairs")
        print(f"    delta — min={min(d):.2f}  mean={mean(d):.2f}  max={max(d):.2f}")
        task_types = {p.get("task_type") for p in ps}
        print(f"    task_types: {sorted(t for t in task_types if t)}")
        producers = {p.get("producer_model") for p in ps}
        print(f"    producers: {sorted(p for p in producers if p)}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Build DPO preference dataset from runs.jsonl")
    ap.add_argument("--min-delta",  type=float, default=_DEFAULT_MIN_DELTA,
                    help=f"Minimum score gap to qualify as a preference pair (default {_DEFAULT_MIN_DELTA})")
    ap.add_argument("--source",     choices=["all", "cross", "revision"], default="all",
                    help="Which signal sources to include (default: all)")
    ap.add_argument("--stats",      action="store_true",
                    help="Print stats only — do not write output file")
    ap.add_argument("--runs",       default=str(RUNS_FILE),
                    help=f"Path to runs.jsonl (default: {RUNS_FILE})")
    ap.add_argument("--out",        default=str(OUT_FILE),
                    help=f"Output path (default: {OUT_FILE})")
    args = ap.parse_args()

    runs_path = Path(args.runs)
    if not runs_path.exists():
        print(f"[dpo] runs file not found: {runs_path}")
        sys.exit(1)

    print(f"[dpo] loading {runs_path} ...")
    runs = _load_runs(runs_path)
    print(f"[dpo] {len(runs)} runs loaded")

    pairs: list[dict] = []

    if args.source in ("all", "cross"):
        cross = build_cross_run_pairs(runs, args.min_delta)
        print(f"[dpo] cross-run pairs: {len(cross)}")
        pairs.extend(cross)

    if args.source in ("all", "revision"):
        revision = build_revision_pairs(runs, args.min_delta)
        print(f"[dpo] wiggum-revision pairs: {len(revision)}")
        pairs.extend(revision)

    _print_stats(pairs)

    if args.stats or not pairs:
        if not pairs:
            print("[dpo] nothing to write.")
        return

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    print(f"\n[dpo] wrote {len(pairs)} pairs -> {out_path}")


if __name__ == "__main__":
    main()

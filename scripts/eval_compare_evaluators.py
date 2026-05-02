"""
eval_compare_evaluators.py — compare two wiggum evaluator models on existing output files.

Scores each output file with both evaluators (single round, no revision) and
prints a side-by-side table. Useful for evaluator diversity checks.

Usage:
    python eval_compare_evaluators.py
    python eval_compare_evaluators.py --files eval-context-engineering.md eval-cost-management.md
    python eval_compare_evaluators.py --evaluators "Qwen3-Coder:30b" "gemma4:26b"
"""

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import os
import sys

# Default evaluators and files
DEFAULT_EVALUATORS = ["Qwen3-Coder:30b", "gemma4:26b"]
BASE = os.path.expanduser("~/Desktop/harness-engineering")
DEFAULT_FILES = [
    ("T_A: context engineering",   f"{BASE}/eval-context-engineering.md",
     "Search for the top 5 context engineering techniques used in production LLM agents"),
    ("T_B: cost management",        f"{BASE}/eval-cost-management.md",
     "Search for best practices for cost envelope management in production AI agents"),
    ("T_C: agent failure modes",    f"{BASE}/eval-agent-failure-modes.md",
     "Search for the 3 most common failure modes in multi-agent AI systems"),
    ("T_D: context window",         f"{BASE}/eval-context-window.md",
     "Search for the top 3 context window management strategies for production LLM applications"),
]


def score_one(task: str, path: str, evaluator: str) -> dict:
    """Run a single wiggum evaluate() call and return the result dict."""
    from harness import wiggum as _w
    from harness.wiggum import evaluate, normalize
    _w.EVALUATOR_MODEL = evaluator

    expanded = os.path.expanduser(path)
    if not os.path.exists(expanded):
        return {"score": None, "dims": {}, "error": "file not found"}

    content = normalize(expanded)
    result = evaluate(task, content)
    return result


def main():
    args = sys.argv[1:]

    # Parse --evaluators
    evaluators = DEFAULT_EVALUATORS
    if "--evaluators" in args:
        idx = args.index("--evaluators")
        evaluators = []
        i = idx + 1
        while i < len(args) and not args[i].startswith("--"):
            evaluators.append(args[i])
            i += 1

    # Parse --files (expects pairs: label path task)
    files = DEFAULT_FILES
    if "--files" in args:
        idx = args.index("--files")
        files = []
        i = idx + 1
        while i < len(args) and not args[i].startswith("--"):
            files.append((args[i], os.path.join(BASE, args[i]), args[i]))
            i += 1

    print(f"\n{'='*70}")
    print(" Evaluator Diversity Comparison")
    print(f" Evaluators: {' vs '.join(evaluators)}")
    print(f" Files: {len(files)}")
    print(f"{'='*70}\n")

    # Score each file with each evaluator
    results = {}  # {label: {evaluator: result}}
    for label, path, task in files:
        results[label] = {}
        for ev in evaluators:
            print(f"  [{ev[:20]}] scoring {label}...")
            results[label][ev] = score_one(task, path, ev)

    # Print comparison table
    print(f"\n{'─'*70}")
    print(f"{'Task':<28} {'Evaluator':<22} {'Score':>6}  Dims")
    print(f"{'─'*70}")

    dim_abbrev = {"relevance": "rel", "completeness": "cmp", "depth": "dep",
                  "specificity": "spc", "structure": "str"}

    divergences = []
    for label, ev_results in results.items():
        scores = []
        for ev in evaluators:
            r = ev_results[ev]
            if r.get("error"):
                print(f"  {label:<26} {ev:<22} {'ERR':>6}  {r['error']}")
                continue
            score = r.get("score", 0.0)
            scores.append(score)
            dims = r.get("dims", {})
            dim_str = "  ".join(f"{dim_abbrev.get(k,k)}={v}" for k, v in dims.items())
            print(f"  {label:<26} {ev[:20]:<22} {score:>5.1f}  {dim_str}")

        if len(scores) == 2:
            delta = scores[1] - scores[0]
            direction = "↑" if delta > 0 else "↓" if delta < 0 else "="
            print(f"  {'':26} {'delta':<22} {delta:>+5.1f}  {direction}")
            if abs(delta) >= 1.0:
                divergences.append((label, scores[0], scores[1], delta))
        print()

    # Summary
    print(f"{'─'*70}")
    print("\nSummary:")
    if divergences:
        print("  Significant divergences (|Δ| ≥ 1.0):")
        for label, s0, s1, delta in divergences:
            print(f"    {label}: {evaluators[0]}={s0:.1f}  {evaluators[1]}={s1:.1f}  Δ={delta:+.1f}")
        print(f"\n  → Evaluator bias detected: models disagree on {len(divergences)}/{len(results)} task(s).")
        print("    Consider rotating evaluators in autoresearch or adding as panel member.")
    else:
        print("  No significant divergences (all |Δ| < 1.0).")
        print("  → Evaluators agree: current rubric is robust to evaluator choice.")


if __name__ == "__main__":
    main()

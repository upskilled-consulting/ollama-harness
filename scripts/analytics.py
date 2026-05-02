"""
analytics.py — summarize runs.jsonl

Usage:
    python analytics.py
    python analytics.py --full   # show per-run detail
"""

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from harness.utils import load_runs  # noqa: E402
from harness.utils import print_summary as _print_summary


def fmt(val, width=10):
    return str(val).rjust(width)


def print_summary(runs: list[dict]):
    total = len(runs)
    passed = sum(1 for r in runs if r.get("final") == "PASS")
    errors = sum(1 for r in runs if r.get("final") == "ERROR")

    dual_runs = [r for r in runs if len(r.get("tool_calls", [])) >= 2]
    single_runs = [r for r in runs if len(r.get("tool_calls", [])) == 1]

    def avg(lst, key):
        vals = [r.get(key) for r in lst if r.get(key) is not None]
        return round(sum(vals) / len(vals), 1) if vals else "n/a"

    def avg_first_score(lst):
        scores = [r["wiggum_scores"][0] for r in lst if r.get("wiggum_scores")]
        return round(sum(scores) / len(scores), 1) if scores else "n/a"

    def avg_rounds(lst):
        rounds = [r.get("wiggum_rounds", 0) for r in lst]
        return round(sum(rounds) / len(rounds), 1) if rounds else "n/a"

    floor_hits = sum(1 for r in runs if r.get("quality_floor_hit"))

    print("\n======================================")
    print(" Pipeline Analytics")
    print("======================================")
    print(f"  Total runs     : {total}")
    print(f"  PASS           : {passed}  ({round(passed/total*100)}%)")
    print(f"  ERROR          : {errors}")
    print(f"  Quality floor  : {floor_hits} hits")
    print()
    print(f"  {'':20}  {'single':>8}  {'dual':>8}")
    print(f"  {'':20}  {'------':>8}  {'------':>8}")
    print(f"  {'runs':20}  {len(single_runs):>8}  {len(dual_runs):>8}")
    print(f"  {'avg search chars':20}  {avg(single_runs, 'total_search_chars'):>8}  {avg(dual_runs, 'total_search_chars'):>8}")
    print(f"  {'avg output bytes':20}  {avg(single_runs, 'output_bytes'):>8}  {avg(dual_runs, 'output_bytes'):>8}")
    print(f"  {'avg output lines':20}  {avg(single_runs, 'output_lines'):>8}  {avg(dual_runs, 'output_lines'):>8}")
    print(f"  {'avg 1st wiggum score':20}  {avg_first_score(single_runs):>8}  {avg_first_score(dual_runs):>8}")
    print(f"  {'avg wiggum rounds':20}  {avg_rounds(single_runs):>8}  {avg_rounds(dual_runs):>8}")
    print("======================================\n")


def print_full(runs: list[dict]):
    print("\n--- per-run detail ---\n")
    for i, r in enumerate(runs, 1):
        ts = r.get("timestamp", "")[:19].replace("T", " ")
        searches = len(r.get("tool_calls", []))
        chars = r.get("total_search_chars") or sum(
            t.get("result_chars", 0) for t in r.get("tool_calls", [])
        )
        lines = r.get("output_lines", "?")
        size = r.get("output_bytes", "?")
        scores = r.get("wiggum_scores", [])
        final = r.get("final", "?")
        floor = " [floor hit]" if r.get("quality_floor_hit") else ""
        print(f"  [{i}] {ts}  searches={searches}  chars={chars}{floor}")
        print(f"       lines={lines}  bytes={size}  scores={scores}  {final}")
    print()


if __name__ == "__main__":
    runs = load_runs()
    _print_summary(runs)
    if "--full" in sys.argv:
        print_full(runs)

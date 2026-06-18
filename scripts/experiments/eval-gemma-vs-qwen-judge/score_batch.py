"""
score_batch.py — score a fixed batch of existing outputs with ONE judge model.

Reuses harness.wiggum.evaluate() verbatim (same prompt, parse, recompute) and
only swaps the evaluator model, so scores match production exactly. Run once per
judge; results append to results.jsonl keyed by (task_id, judge) for offline compare.

    python scripts/experiments/eval-gemma-vs-qwen-judge/score_batch.py --judge qwen3-8b --limit 8
"""
import argparse, json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]   # harness-refactor/
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import harness.wiggum as w

BENCH = ROOT / "data" / "task_suite" / "benchmark.jsonl"
EVALDIR = ROOT / "data" / "eval"
RESULTS = Path(__file__).resolve().parent / "results.jsonl"


def load_pairs(limit):
    pairs = []
    for line in open(BENCH, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        tid = r["task_id"]
        f = EVALDIR / f"benchmark_{tid}.md"
        if f.exists() and f.stat().st_size > 400:
            pairs.append((tid, r["task"], f))
    # spread across the list rather than first-N of one type
    if limit and len(pairs) > limit:
        step = len(pairs) / limit
        pairs = [pairs[int(i * step)] for i in range(limit)]
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", required=True, help="evaluator model tag (routed via HARNESS_ENDPOINTS)")
    ap.add_argument("--limit", type=int, default=8)
    args = ap.parse_args()

    w.EVALUATOR_MODEL = args.judge          # the only thing we change
    pairs = load_pairs(args.limit)
    print(f"[score] judge={args.judge}  files={len(pairs)}")

    out = open(RESULTS, "a", encoding="utf-8")
    for tid, task, f in pairs:
        content = f.read_text(encoding="utf-8", errors="replace")
        try:
            res = w.evaluate(task, content)
        except Exception as e:
            print(f"  ! {tid}: {e!s:.120}")
            continue
        dims = {k: res.get(k) for k in
                ("relevance", "completeness", "depth", "grounded", "specificity", "structure")}
        rec = {"task_id": tid, "judge": args.judge, "score": res.get("score"),
               "passed": res.get("passed"), "dims": dims, "tac_hours": res.get("tac_hours")}
        out.write(json.dumps(rec) + "\n"); out.flush()
        print(f"  {tid:42} score={res.get('score')}  dims={dims}")
    out.close()
    print(f"[score] appended to {RESULTS}")


if __name__ == "__main__":
    main()

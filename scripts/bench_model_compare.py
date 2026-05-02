"""
bench_model_compare.py — quality comparison between producer models on the eval suite.

Reads historical runs.jsonl for the baseline model and runs the eval suite live
with the test model, then prints a side-by-side score table.

Usage:
    # Live test (pi-qwen3.6) vs historical baseline (pi-qwen-32b):
    python bench_model_compare.py

    # Run both models live for a clean head-to-head:
    python bench_model_compare.py --run-both

    # Custom models:
    python bench_model_compare.py --test-model pi-qwen3.6 --baseline-model pi-qwen-32b

    # Subset of task types:
    python bench_model_compare.py --task-types T_A,T_B,T_F

    # Only print historical comparison (no new runs):
    python bench_model_compare.py --historical-only --baseline-model pi-qwen-32b --test-model pi-qwen3.6

Output: bench_compare_results.jsonl (one row per task × model)
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import argparse
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
except ImportError:
    pass

BASE      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root
RUNS_FILE = os.path.join(BASE, "runs.jsonl")
OUT_FILE  = os.path.join(BASE, "data", "bench_compare_results.jsonl")
AGENT     = None  # use -m harness.agent


# ---------------------------------------------------------------------------
# Historical run loading
# ---------------------------------------------------------------------------

def load_runs(path: str = RUNS_FILE) -> list[dict]:
    if not os.path.exists(path):
        return []
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


def historical_stats(runs: list[dict], model: str, task_type: str, output_path: str | None = None) -> dict | None:
    """Aggregate stats from historical runs matching model + output_path (preferred) or task_type."""
    if output_path:
        matching = [
            r for r in runs
            if r.get("producer_model") == model and r.get("output_path") == output_path
        ]
    else:
        matching = [
            r for r in runs
            if r.get("producer_model") == model and r.get("task_type") == task_type
        ]
    if not matching:
        return None

    scores   = [r["wiggum_scores"][-1] for r in matching if r.get("wiggum_scores")]
    durations = [r["run_duration_s"] for r in matching if r.get("run_duration_s")]
    bytes_   = [r["output_bytes"] for r in matching if r.get("output_bytes")]
    passes   = [1 if r.get("final") == "PASS" else 0 for r in matching]

    def _mean(vs): return sum(vs) / len(vs) if vs else float("nan")

    think_chars = []
    for r in matching:
        tbs = r.get("tokens_by_stage", {})
        tc = sum(s.get("thinking_chars", 0) for s in tbs.values())
        if tc:
            think_chars.append(tc)

    cot_lens = []
    for r in matching:
        cots = r.get("synth_cot", [])
        if cots:
            cot_lens.append(sum(len(c) for c in cots))

    leverages = [r["leverage"] for r in matching if r.get("leverage") is not None]
    tac_vals  = [r["tac_hours"] for r in matching if r.get("tac_hours") is not None]

    return {
        "model":         model,
        "task_type":     task_type,
        "n":             len(matching),
        "pass_rate":     _mean(passes),
        "mean_score":    _mean(scores),
        "mean_bytes":    _mean(bytes_),
        "mean_duration": _mean(durations),
        "mean_think_chars": _mean(think_chars) if think_chars else float("nan"),
        "mean_cot_len":  _mean(cot_lens) if cot_lens else float("nan"),
        "mean_leverage": _mean(leverages) if leverages else float("nan"),
        "mean_tac_h":   _mean(tac_vals) if tac_vals else float("nan"),
        "source":        "historical",
    }


# ---------------------------------------------------------------------------
# Live run
# ---------------------------------------------------------------------------

def run_task_live(task: str, task_type: str, model: str) -> dict:
    """Run one eval task with a specific producer model via subprocess."""
    env = os.environ.copy()
    env["HARNESS_PRODUCER_MODEL"] = model

    # Snapshot run count so we can find the new record by position, not task_type.
    # agent.py writes semantic types ("best_practices", "research", etc.) which don't
    # match the bench task IDs ("T_A", "T_B", etc.), so filtering by task_type would
    # always miss.
    pre_count = len(load_runs())

    print(f"\n  → running {task_type} live with {model}...")
    t0 = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-m", "harness.agent", task],
        capture_output=False,
        text=True,
        cwd=BASE,
        env=env,
    )
    wall_s = round(time.monotonic() - t0, 1)

    if result.returncode != 0:
        print(f"  [warn] {task_type} exited with code {result.returncode}")

    # Find the run record appended during this subprocess call.
    all_runs = load_runs()
    new_runs = [r for r in all_runs[pre_count:] if r.get("producer_model") == model]
    run_record = new_runs[-1] if new_runs else {}

    scores = run_record.get("wiggum_scores", [])
    tbs    = run_record.get("tokens_by_stage", {})
    think_chars = sum(s.get("thinking_chars", 0) for s in tbs.values())
    cots   = run_record.get("synth_cot", [])
    cot_len = sum(len(c) for c in cots)

    return {
        "model":         model,
        "task_type":     task_type,
        "n":             1,
        "pass_rate":     1.0 if run_record.get("final") == "PASS" else 0.0,
        "mean_score":    scores[-1] if scores else float("nan"),
        "mean_bytes":    run_record.get("output_bytes") or float("nan"),
        "mean_duration": run_record.get("run_duration_s") or wall_s,
        "mean_think_chars": think_chars or float("nan"),
        "mean_cot_len":  cot_len or float("nan"),
        "mean_leverage": run_record.get("leverage") or float("nan"),
        "mean_tac_h":   run_record.get("tac_hours") or float("nan"),
        "source":        "live",
        "wall_s":        wall_s,
        "returncode":    result.returncode,
        "cot_preview":   cots[0][:300] if cots else "",
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

_ANSI = {"bold": "\033[1m", "green": "\033[92m", "red": "\033[91m",
         "yellow": "\033[93m", "reset": "\033[0m"}


def _c(text, color, use_color=True):
    return f"{_ANSI[color]}{text}{_ANSI['reset']}" if use_color else text


def _fmt(v, fmt=".1f"):
    return f"{v:{fmt}}" if not (isinstance(v, float) and math.isnan(v)) else "  n/a"


def print_report(rows: list[dict], use_color: bool = True):
    task_types = sorted({r["task_type"] for r in rows})
    models     = list(dict.fromkeys(r["model"] for r in rows))  # preserve insertion order

    header = f"{'Task':<8} {'Model':<20} {'Score':>6} {'Pass%':>6} {'KB':>6} {'Dur(s)':>7} {'TAC(h)':>7} {'Lev':>6} {'Src':<10}"
    print(f"\n{_c('=== Model Quality Comparison ===', 'bold', use_color)}\n")
    print(header)
    print("-" * len(header))

    by_task: dict[str, dict[str, dict]] = {}
    for r in rows:
        by_task.setdefault(r["task_type"], {})[r["model"]] = r

    for tt in task_types:
        model_rows = by_task.get(tt, {})
        for mi, model in enumerate(models):
            r = model_rows.get(model)
            if not r:
                continue
            score    = _fmt(r["mean_score"])
            pass_pct = _fmt(r["pass_rate"] * 100, ".0f") + "%"
            kb       = _fmt((r["mean_bytes"] or 0) / 1024, ".1f")
            dur      = _fmt(r["mean_duration"])
            tac_h    = _fmt(r.get("mean_tac_h") or float("nan"), ".1f")
            lev      = _fmt(r.get("mean_leverage") or float("nan"), ".1f") + "x"
            src      = f"({r['source']}, n={r['n']})"
            tag      = tt if mi == 0 else "  "
            line     = f"{tag:<8} {model:<20} {score:>6} {pass_pct:>6} {kb:>6} {dur:>7} {tac_h:>7} {lev:>6} {src:<10}"
            print(line)

        # Delta row when two models present
        model_list = [m for m in models if m in model_rows]
        if len(model_list) == 2:
            a, b = model_list
            ra, rb = model_rows[a], model_rows[b]
            ds = rb["mean_score"] - ra["mean_score"]
            if not math.isnan(ds):
                sign  = "+" if ds >= 0 else ""
                color = "green" if ds > 0 else ("red" if ds < 0 else "yellow")
                print(f"{'':8} {'  Δ score':20} {_c(f'{sign}{ds:.1f}', color, use_color)}")
            dl_a = ra.get("mean_leverage") or float("nan")
            dl_b = rb.get("mean_leverage") or float("nan")
            if not math.isnan(dl_a) and not math.isnan(dl_b):
                dl = dl_b - dl_a
                sign  = "+" if dl >= 0 else ""
                color = "green" if dl > 0 else ("red" if dl < 0 else "yellow")
                print(f"{'':8} {'  Δ leverage':20} {_c(f'{sign}{dl:.1f}x', color, use_color)}")
        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Model quality comparison bench")
    parser.add_argument("--test-model",     default="pi-qwen3.6")
    parser.add_argument("--baseline-model", default="pi-qwen-32b")
    parser.add_argument("--task-types",     default=None,
                        help="Comma-separated list of task IDs to run, e.g. T_A,T_B,T_F")
    parser.add_argument("--run-both",       action="store_true",
                        help="Run both models live instead of using historical baseline")
    parser.add_argument("--historical-only", action="store_true",
                        help="Only compare from historical runs.jsonl — no live runs")
    parser.add_argument("--no-color",       action="store_true")
    args = parser.parse_args()

    use_color = not args.no_color and sys.stdout.isatty()

    # Load eval suite
    from eval_suite import SUITE
    tasks = SUITE
    if args.task_types:
        wanted = {t.strip() for t in args.task_types.split(",")}
        tasks  = [t for t in tasks if t["id"] in wanted]

    if not tasks:
        print("[bench] no tasks matched — check --task-types filter")
        sys.exit(1)

    print(f"[bench] {len(tasks)} tasks | test={args.test_model} | baseline={args.baseline_model}")
    all_runs = load_runs()
    rows: list[dict] = []

    for spec in tasks:
        tt   = spec["id"]
        task = spec["task"]

        out_path = spec.get("output")

        # Baseline
        if args.run_both and not args.historical_only:
            stat = run_task_live(task, tt, args.baseline_model)
        else:
            stat = historical_stats(all_runs, args.baseline_model, tt, output_path=out_path)
            if stat is None:
                print(f"  [warn] no historical runs for {args.baseline_model} / {tt} — skipping baseline")

        if stat:
            rows.append(stat)

        # Test model
        if not args.historical_only:
            stat = run_task_live(task, tt, args.test_model)
            rows.append(stat)
        else:
            stat = historical_stats(all_runs, args.test_model, tt, output_path=out_path)
            if stat:
                rows.append(stat)
            else:
                print(f"  [warn] no historical runs for {args.test_model} / {tt}")

    # Print report
    print_report(rows, use_color=use_color)

    # Save
    ts = datetime.now(timezone.utc).isoformat()
    with open(OUT_FILE, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({**r, "bench_timestamp": ts}) + "\n")
    print(f"Results appended to {OUT_FILE}")


if __name__ == "__main__":
    main()

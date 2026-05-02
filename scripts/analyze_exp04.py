"""
analyze_exp04.py — analysis for experiment-04.

Identifies exp-04 runs by: Qwen3-Coder:30b evaluator + pi-qwen-32b producer +
experiment task strings. Exp-03 runs (same evaluator, different producer) are
the comparison baseline.

Usage:
    python analyze_exp04.py
    python analyze_exp04.py --all   # show raw per-run data too
"""

import json
import math
import sys


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def mean(vals):
    return sum(vals) / len(vals) if vals else 0

def std(vals):
    if len(vals) < 2:
        return 0
    m = mean(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))

def cv(vals):
    m = mean(vals)
    return std(vals) / m * 100 if m else 0


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

runs = []
with open("runs.jsonl", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            runs.append(json.loads(line))

# Experiment task fingerprints
EXP_TASKS = {
    "T_A": "top 5 context engineering techniques",
    "T_B": "cost envelope management",
    "T_C": "3 most common failure modes",
}

def classify_task(task_str: str):
    for tid, fragment in EXP_TASKS.items():
        if fragment.lower() in task_str.lower():
            return tid
    return None

def is_exp_run(r):
    return classify_task(r.get("task", "")) is not None

# Exp-04: Qwen3-Coder:30b evaluator + pi-qwen-32b producer
exp4_runs = [(r, classify_task(r["task"])) for r in runs
             if r.get("evaluator_model", "").startswith("Qwen3")
             and r.get("producer_model", "") == "pi-qwen-32b"
             and is_exp_run(r)]

# Exp-03: Qwen3-Coder:30b evaluator + pi-qwen (7B) producer
exp3_runs = [(r, classify_task(r["task"])) for r in runs
             if r.get("evaluator_model", "").startswith("Qwen3")
             and r.get("producer_model", "") == "pi-qwen"
             and is_exp_run(r)]

print(f"Runs identified: exp-03={len(exp3_runs)}  exp-04={len(exp4_runs)}")
if len(exp4_runs) < 9:
    print(f"  [warn] exp-04 has only {len(exp4_runs)}/9 runs — analysis may be partial")
print()


# ---------------------------------------------------------------------------
# Per-run extraction
# ---------------------------------------------------------------------------

def extract_run(r, task_id):
    scores = r.get("wiggum_scores", [])
    dims_list = r.get("wiggum_dims", [])
    rounds = r.get("wiggum_rounds", 0)
    score_r1 = scores[0] if scores else None
    score_final = scores[-1] if scores else None
    score_gain = round(score_final - score_r1, 1) if (score_r1 is not None and score_final is not None and rounds > 1) else 0
    dims_r1 = dims_list[0] if dims_list else {}
    return {
        "task": task_id,
        "task_type": r.get("task_type", "?"),
        "search_chars": r.get("total_search_chars", 0),
        "output_bytes": r.get("output_bytes", 0),
        "output_lines": r.get("output_lines", 0),
        "score_r1": score_r1,
        "score_final": score_final,
        "score_gain": score_gain,
        "wiggum_rounds": rounds,
        "count_retry": r.get("count_check_retry", False),
        "final": r.get("final", "?"),
        "dims_r1": dims_r1,
        "memory_hits": r.get("memory_hits", 0),
        "timestamp": r.get("timestamp", "?")[:16],
        "input_tokens": r.get("input_tokens", 0),
        "output_tokens": r.get("output_tokens", 0),
        "run_duration_s": r.get("run_duration_s", 0),
    }

exp4_data = [extract_run(r, t) for r, t in exp4_runs]
exp3_data = [extract_run(r, t) for r, t in exp3_runs]


# ---------------------------------------------------------------------------
# Per-run table
# ---------------------------------------------------------------------------

if "--all" in sys.argv:
    print("=== Experiment-04 per-run data ===")
    for i, d in enumerate(exp4_data, 1):
        dims = d["dims_r1"]
        dim_str = " ".join(f"{k[:3]}={v}" for k, v in dims.items()) if dims else "n/a"
        print(f"  Run {i} {d['task']} [{d['timestamp']}]: type={d['task_type']} "
              f"chars={d['search_chars']} bytes={d['output_bytes']} lines={d['output_lines']} "
              f"score_r1={d['score_r1']} score_final={d['score_final']} "
              f"gain={d['score_gain']} rounds={d['wiggum_rounds']} "
              f"retry={d['count_retry']} final={d['final']} "
              f"tok_in={d['input_tokens']} tok_out={d['output_tokens']} dur={d['run_duration_s']}s")
        if dims:
            print(f"         dims_r1: {dim_str}")
    print()


# ---------------------------------------------------------------------------
# Results table
# ---------------------------------------------------------------------------

print("=== Experiment-04 results table ===")
header = (f"{'Run':>3}  {'Task':>4}  {'task_type':>14}  {'chars':>6}  "
          f"{'bytes':>6}  {'lines':>5}  {'s_r1':>5}  {'s_fin':>5}  "
          f"{'rounds':>6}  {'gain':>5}  {'retry':>5}  {'final':>5}")
print(header)
for i, d in enumerate(exp4_data, 1):
    print(f"  {i:>3}  {d['task']:>4}  {d['task_type']:>14}  {d['search_chars']:>6}  "
          f"{d['output_bytes']:>6}  {d['output_lines']:>5}  "
          f"{str(d['score_r1']):>5}  {str(d['score_final']):>5}  "
          f"{d['wiggum_rounds']:>6}  {d['score_gain']:>5}  "
          f"{str(d['count_retry']):>5}  {d['final']:>5}")
print()


# ---------------------------------------------------------------------------
# Per-task stats (exp-04)
# ---------------------------------------------------------------------------

task_data4 = {"T_A": [], "T_B": [], "T_C": []}
for d in exp4_data:
    if d["task"] in task_data4:
        task_data4[d["task"]].append(d)

print("=== Experiment-04 per-task stats ===")
for task in ["T_A", "T_B", "T_C"]:
    rows = task_data4[task]
    if not rows:
        print(f"  {task}: no data yet")
        continue
    bv = [r["output_bytes"] for r in rows]
    lv = [r["output_lines"] for r in rows]
    sv = [r["score_r1"] for r in rows if r["score_r1"] is not None]
    rv = [r["wiggum_rounds"] for r in rows]
    gv = [r["score_gain"] for r in rows if r["wiggum_rounds"] > 1]
    retries = sum(1 for r in rows if r["count_retry"])
    tok_in = [r["input_tokens"] for r in rows if r["input_tokens"]]
    dur = [r["run_duration_s"] for r in rows if r["run_duration_s"]]

    print(f"  {task}: bytes mean={mean(bv):.0f} std={std(bv):.0f} CV={cv(bv):.1f}%  "
          f"lines mean={mean(lv):.1f}  "
          f"score_r1 mean={mean(sv):.2f} std={std(sv):.2f}  "
          f"rounds mean={mean(rv):.2f}  "
          f"revised={sum(1 for r in rv if r > 1)}/{len(rows)}  "
          f"retries={retries}")
    if gv:
        print(f"       score gains: {gv}  mean={mean(gv):.2f}")
    if tok_in:
        print(f"       tokens mean: in={mean(tok_in):.0f}  dur={mean(dur):.0f}s")
print()


# ---------------------------------------------------------------------------
# Dimension score analysis
# ---------------------------------------------------------------------------

print("=== Dimension scores by task type — round 1 (exp-04 vs exp-03) ===")
dim_keys = ["relevance", "completeness", "depth", "specificity", "structure"]
dim_abbrev = ["rel", "cmp", "dep", "spc", "str"]

task_data3 = {"T_A": [], "T_B": [], "T_C": []}
for d in exp3_data:
    if d["task"] in task_data3:
        task_data3[d["task"]].append(d)

for task in ["T_A", "T_B", "T_C"]:
    rows4 = task_data4.get(task, [])
    rows3 = task_data3.get(task, [])
    dims4 = [r["dims_r1"] for r in rows4 if r["dims_r1"]]
    dims3 = [r["dims_r1"] for r in rows3 if r["dims_r1"]]
    if dims4:
        means4 = {k: mean([d.get(k, 0) for d in dims4]) for k in dim_keys}
        str4 = "  ".join(f"{a}={means4[k]:.1f}" for a, k in zip(dim_abbrev, dim_keys))
        print(f"  {task} exp-04: {str4}")
    if dims3:
        means3 = {k: mean([d.get(k, 0) for d in dims3]) for k in dim_keys}
        str3 = "  ".join(f"{a}={means3[k]:.1f}" for a, k in zip(dim_abbrev, dim_keys))
        delta_str = "  ".join(
            f"{a}={means4.get(k, 0) - means3[k]:+.1f}"
            for a, k in zip(dim_abbrev, dim_keys)
        ) if dims4 else ""
        print(f"  {task} exp-03: {str3}")
        if delta_str:
            print(f"  {task}   delta: {delta_str}")
    print()


# ---------------------------------------------------------------------------
# Cross-experiment comparison (exp-03 vs exp-04)
# ---------------------------------------------------------------------------

def task_stats(data_list, task):
    rows = [d for d in data_list if d["task"] == task]
    scores = [r["score_r1"] for r in rows if r["score_r1"] is not None]
    return {
        "bytes": mean([r["output_bytes"] for r in rows]),
        "lines": mean([r["output_lines"] for r in rows]),
        "score": mean(scores),
        "rounds": mean([r["wiggum_rounds"] for r in rows]),
        "passes": sum(1 for r in rows if r["final"] == "PASS"),
        "n": len(rows),
    }

print("=== Cross-experiment comparison (exp-03 vs exp-04) ===")
print(f"  {'task':4}  {'metric':20}  {'exp-03 (7B)':>12}  {'exp-04 (32B)':>12}  {'delta':>8}")
print(f"  {'----':4}  {'------':20}  {'----------':>12}  {'-----------':>12}  {'-----':>8}")
for task in ["T_A", "T_B", "T_C"]:
    s3 = task_stats(exp3_data, task)
    s4 = task_stats(exp4_data, task)
    if s3["n"] == 0 or s4["n"] == 0:
        continue
    metrics = [
        ("bytes", "bytes mean"),
        ("lines", "lines mean"),
        ("score", "score_r1 mean"),
        ("rounds", "rounds mean"),
    ]
    for key, label in metrics:
        v3 = s3[key]
        v4 = s4[key]
        delta = v4 - v3
        sign = "+" if delta >= 0 else ""
        print(f"  {task:4}  {label:20}  {v3:>12.1f}  {v4:>12.1f}  {sign}{delta:>7.1f}")
    print(f"  {task:4}  {'pass rate':20}  {s3['passes']:>10}/{s3['n']}  "
          f"{s4['passes']:>10}/{s4['n']}  "
          f"{'+'if s4['passes']>s3['passes'] else ''}{s4['passes']-s3['passes']:>7}")
    print()


# ---------------------------------------------------------------------------
# Hypothesis assessment
# ---------------------------------------------------------------------------

all_rounds4 = [d["wiggum_rounds"] for d in exp4_data]
all_scores_r1_4 = [d["score_r1"] for d in exp4_data if d["score_r1"] is not None]
all_gains4 = [d["score_gain"] for d in exp4_data if d["wiggum_rounds"] > 1]
passes4 = sum(1 for d in exp4_data if d["final"] == "PASS")
revised_count4 = sum(1 for r in all_rounds4 if r > 1)

ta_rows4 = [d for d in exp4_data if d["task"] == "T_A"]
ta_passes4 = sum(1 for r in ta_rows4 if r["final"] == "PASS")

regressions4 = sum(1 for d in exp4_data
                   if d["wiggum_rounds"] > 1 and d["score_final"] is not None
                   and d["score_r1"] is not None and d["score_final"] < d["score_r1"])

# exp-03 baseline
exp3_score_r1_mean = mean([d["score_r1"] for d in exp3_data if d["score_r1"] is not None])

ta_dims4 = [d["dims_r1"] for d in ta_rows4 if d["dims_r1"]]
ta_depth_mean = mean([d.get("depth", 0) for d in ta_dims4]) if ta_dims4 else None
ta_spc_mean = mean([d.get("specificity", 0) for d in ta_dims4]) if ta_dims4 else None

n = len(exp4_data)
print(f"=== Hypothesis assessment ({n}/9 runs) ===")
print(f"H1 (pass rate > 4/9):  {passes4}/{n} PASS  "
      f"-> {'CONFIRMED' if passes4 > 4 else ('FALSIFIED' if n == 9 else 'PENDING')}")
print(f"H2 (T_A pass rate 3/3):  {ta_passes4}/{len(ta_rows4)} T_A PASS  "
      f"-> {'CONFIRMED' if ta_passes4 == 3 else ('FALSIFIED' if len(ta_rows4) == 3 else 'PENDING')}")
print(f"H3 (no revision regression):  regressions={regressions4}  "
      f"-> {'CONFIRMED' if regressions4 == 0 and n >= 3 else ('FALSIFIED' if regressions4 > 0 else 'PENDING')}")
print(f"H4 (score_r1 mean > {exp3_score_r1_mean:.2f}):  mean={mean(all_scores_r1_4):.2f}  "
      f"-> {'CONFIRMED' if mean(all_scores_r1_4) > exp3_score_r1_mean else ('FALSIFIED' if n == 9 else 'PENDING')}")
if ta_depth_mean is not None:
    print(f"H5 (T_A depth_r1 > 6):  depth_mean={ta_depth_mean:.1f}  spc_mean={ta_spc_mean:.1f}  "
          f"-> {'CONFIRMED' if ta_depth_mean > 6 and ta_spc_mean > 6 else ('FALSIFIED' if len(ta_rows4) == 3 else 'PENDING')}")
else:
    print(f"H5 (T_A dimension improvement):  no T_A data yet — PENDING")

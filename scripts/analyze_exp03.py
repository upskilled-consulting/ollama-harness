"""
analyze_exp03.py — analysis for experiment-03.

Identifies runs by evaluator model (Qwen3-Coder:30b = exp-03) and task string
matching (exp-01 and exp-02 used glm4:9b). Robust to arbitrary runs between
experiments.

Usage:
    python analyze_exp03.py
    python analyze_exp03.py --all   # show raw per-run data too
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

# Exp-03: Qwen3-Coder:30b evaluator, experiment task strings
exp3_runs = [(r, classify_task(r["task"])) for r in runs
             if r.get("evaluator_model", "").startswith("Qwen3") and is_exp_run(r)]

# Exp-01 / Exp-02: glm4:9b evaluator, experiment task strings
# Sorted by timestamp; split last 18 into exp2 (more recent) and exp1 (older)
glm4_exp_runs = [(r, classify_task(r["task"])) for r in runs
                 if r.get("evaluator_model", "") == "glm4:9b" and is_exp_run(r)
                 and r.get("wiggum_scores")]  # must have completed wiggum
glm4_exp_runs.sort(key=lambda x: x[0].get("timestamp", ""))

exp2_runs = glm4_exp_runs[-9:] if len(glm4_exp_runs) >= 18 else []
exp1_runs = glm4_exp_runs[-18:-9] if len(glm4_exp_runs) >= 18 else glm4_exp_runs[:-9]

print(f"Runs identified: exp-01={len(exp1_runs)}  exp-02={len(exp2_runs)}  exp-03={len(exp3_runs)}")
if len(exp3_runs) < 9:
    print(f"  [warn] exp-03 has only {len(exp3_runs)}/9 runs — analysis may be partial")
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
    }

exp3_data = [extract_run(r, t) for r, t in exp3_runs]


# ---------------------------------------------------------------------------
# Per-run table
# ---------------------------------------------------------------------------

if "--all" in sys.argv:
    print("=== Experiment-03 per-run data ===")
    for i, d in enumerate(exp3_data, 1):
        dims = d["dims_r1"]
        dim_str = " ".join(f"{k[:3]}={v}" for k, v in dims.items()) if dims else "n/a"
        print(f"  Run {i} {d['task']} [{d['timestamp']}]: type={d['task_type']} "
              f"chars={d['search_chars']} bytes={d['output_bytes']} lines={d['output_lines']} "
              f"score_r1={d['score_r1']} score_final={d['score_final']} "
              f"gain={d['score_gain']} rounds={d['wiggum_rounds']} "
              f"retry={d['count_retry']} final={d['final']}")
        if dims:
            print(f"         dims_r1: {dim_str}")
    print()


# ---------------------------------------------------------------------------
# Results table
# ---------------------------------------------------------------------------

print("=== Experiment-03 results table ===")
header = (f"{'Run':>3}  {'Task':>4}  {'task_type':>14}  {'chars':>6}  "
          f"{'bytes':>6}  {'lines':>5}  {'s_r1':>5}  {'s_fin':>5}  "
          f"{'rounds':>6}  {'gain':>5}  {'retry':>5}  {'final':>5}")
print(header)
for i, d in enumerate(exp3_data, 1):
    print(f"  {i:>3}  {d['task']:>4}  {d['task_type']:>14}  {d['search_chars']:>6}  "
          f"{d['output_bytes']:>6}  {d['output_lines']:>5}  "
          f"{str(d['score_r1']):>5}  {str(d['score_final']):>5}  "
          f"{d['wiggum_rounds']:>6}  {d['score_gain']:>5}  "
          f"{str(d['count_retry']):>5}  {d['final']:>5}")
print()


# ---------------------------------------------------------------------------
# Per-task stats
# ---------------------------------------------------------------------------

task_data3 = {"T_A": [], "T_B": [], "T_C": []}
for d in exp3_data:
    if d["task"] in task_data3:
        task_data3[d["task"]].append(d)

print("=== Experiment-03 per-task stats ===")
for task in ["T_A", "T_B", "T_C"]:
    rows = task_data3[task]
    if not rows:
        print(f"  {task}: no data yet")
        continue
    bv = [r["output_bytes"] for r in rows]
    lv = [r["output_lines"] for r in rows]
    sv = [r["score_r1"] for r in rows if r["score_r1"] is not None]
    rv = [r["wiggum_rounds"] for r in rows]
    gv = [r["score_gain"] for r in rows if r["wiggum_rounds"] > 1]
    retries = sum(1 for r in rows if r["count_retry"])

    print(f"  {task}: bytes mean={mean(bv):.0f} std={std(bv):.0f} CV={cv(bv):.1f}%  "
          f"lines mean={mean(lv):.1f}  "
          f"score_r1 mean={mean(sv):.2f} std={std(sv):.2f}  "
          f"rounds mean={mean(rv):.2f}  "
          f"revised={sum(1 for r in rv if r > 1)}/{len(rows)}  "
          f"retries={retries}")
    if gv:
        print(f"       score gains: {gv}  mean={mean(gv):.2f}")
print()


# ---------------------------------------------------------------------------
# Dimension score analysis
# ---------------------------------------------------------------------------

print("=== Dimension scores by task type (round 1) ===")
dim_keys = ["relevance", "completeness", "depth", "specificity", "structure"]
dim_abbrev = ["rel", "cmp", "dep", "spc", "str"]

for task in ["T_A", "T_B", "T_C"]:
    rows = task_data3.get(task, [])
    dims_list = [r["dims_r1"] for r in rows if r["dims_r1"]]
    if not dims_list:
        print(f"  {task}: no dimension data")
        continue
    means = {k: mean([d.get(k, 0) for d in dims_list]) for k in dim_keys}
    dim_str = "  ".join(f"{a}={means[k]:.1f}" for a, k in zip(dim_abbrev, dim_keys))
    print(f"  {task}: {dim_str}")
print()


# ---------------------------------------------------------------------------
# Cross-experiment comparison
# ---------------------------------------------------------------------------

def build_task_data_from_pairs(run_pairs):
    td = {"T_A": [], "T_B": [], "T_C": []}
    for r, t in run_pairs:
        if t not in td:
            continue
        scores = r.get("wiggum_scores", [])
        td[t].append({
            "bytes": r.get("output_bytes", 0),
            "lines": r.get("output_lines", 0),
            "score": scores[0] if scores else 0,
            "rounds": r.get("wiggum_rounds", 0),
        })
    return td

task_data1 = build_task_data_from_pairs(exp1_runs)
task_data2 = build_task_data_from_pairs(exp2_runs)

if exp1_runs and exp2_runs:
    print("=== Cross-experiment comparison (exp-01 / exp-02 / exp-03) ===")
    print(f"  {'task':4}  {'metric':20}  {'exp-01':>8}  {'exp-02':>8}  {'exp-03':>8}  {'d02-03':>8}")
    print(f"  {'----':4}  {'------':20}  {'------':>8}  {'------':>8}  {'------':>8}  {'------':>8}", flush=True)

    for task in ["T_A", "T_B", "T_C"]:
        d1 = task_data1.get(task, [])
        d2 = task_data2.get(task, [])
        d3 = task_data3.get(task, [])
        if not (d1 and d2 and d3):
            continue
        metrics = [
            ("bytes", "bytes mean", lambda rows: mean([x["bytes"] for x in rows])),
            ("lines", "lines mean", lambda rows: mean([x["lines"] for x in rows])),
            ("score", "score_r1 mean", lambda rows: mean([x["score"] for x in rows])),
            ("rounds", "rounds mean", lambda rows: mean([x["rounds"] for x in rows])),
        ]
        for key, label, fn in metrics:
            v1 = fn(d1)
            v2 = fn(d2)
            v3_rows = [{"score": r["score_r1"], "rounds": r["wiggum_rounds"],
                        "bytes": r["output_bytes"], "lines": r["output_lines"]}
                       for r in d3 if r["score_r1"] is not None]
            v3 = fn(v3_rows) if v3_rows else 0
            delta = v3 - v2
            sign = "+" if delta >= 0 else ""
            print(f"  {task:4}  {label:20}  {v1:>8.1f}  {v2:>8.1f}  {v3:>8.1f}  {sign}{delta:>7.1f}")
        print()
else:
    print("=== Cross-experiment comparison: insufficient data for exp-01/02 ===")
print()


# ---------------------------------------------------------------------------
# Hypothesis assessment
# ---------------------------------------------------------------------------

all_rounds = [d["wiggum_rounds"] for d in exp3_data]
all_scores_r1 = [d["score_r1"] for d in exp3_data if d["score_r1"] is not None]
all_gains = [d["score_gain"] for d in exp3_data if d["wiggum_rounds"] > 1]
passes = sum(1 for d in exp3_data if d["final"] == "PASS")
revised_count = sum(1 for r in all_rounds if r > 1)

t_b_scores = [d["score_r1"] for d in exp3_data if d["task"] == "T_B" and d["score_r1"] is not None]
t_c_scores = [d["score_r1"] for d in exp3_data if d["task"] == "T_C" and d["score_r1"] is not None]
task_gap = (mean(t_b_scores) - mean(t_c_scores)) if (t_b_scores and t_c_scores) else None

n = len(exp3_data)
print(f"=== Hypothesis assessment ({n}/9 runs) ===")
print(f"H1 (revision loop activates >=1 run):  revised={revised_count}/{n}  "
      f"-> {'CONFIRMED' if revised_count >= 1 else ('FALSIFIED' if n == 9 else 'PENDING')}")
print(f"H2 (score variance, std > 0.5):  score_r1 mean={mean(all_scores_r1):.2f}  "
      f"std={std(all_scores_r1):.2f}  "
      f"→ {'CONFIRMED' if std(all_scores_r1) > 0.5 else ('FALSIFIED' if n == 9 else 'PENDING')}")
print(f"H3 (pass rate 9/9):  {passes}/{n} PASS  "
      f"→ {'CONFIRMED' if passes == 9 else ('FALSIFIED' if n == 9 else 'PENDING')}")
if all_gains:
    print(f"H4 (revision adds value, gain > 0.5):  gains={all_gains}  mean={mean(all_gains):.2f}  "
          f"→ {'CONFIRMED' if mean(all_gains) > 0.5 else 'FALSIFIED'}")
else:
    print(f"H4 (revision adds value):  {'no revised runs' if n == 9 else 'none yet'} — "
          f"{'UNTESTABLE' if n == 9 else 'PENDING'}")
if task_gap is not None:
    print(f"H5 (T_B scores > T_C, gap > 0.5):  T_B mean={mean(t_b_scores):.2f}  "
          f"T_C mean={mean(t_c_scores):.2f}  gap={task_gap:.2f}  "
          f"→ {'CONFIRMED' if task_gap > 0.5 else 'FALSIFIED'}")
else:
    print(f"H5 (task-type differentiation):  insufficient data — PENDING")

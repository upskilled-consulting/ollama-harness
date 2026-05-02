import json, math

runs = []
with open("runs.jsonl", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            runs.append(json.loads(line))

# Experiment-02: last 9 runs
exp2 = runs[-9:]
# Experiment-01: 9 runs before that
exp1 = runs[-18:-9]

task_order = ["T_B","T_C","T_A","T_B","T_A","T_C","T_A","T_C","T_B"]

print("=== Experiment-02 per-run data ===")
for i, (r, t) in enumerate(zip(exp2, task_order), 1):
    sc = r.get("total_search_chars","?")
    by = r.get("output_bytes","?")
    li = r.get("output_lines","?")
    s1 = r["wiggum_scores"][0] if r.get("wiggum_scores") else "?"
    rnd = r.get("wiggum_rounds","?")
    tt = r.get("task_type","?")
    retry = r.get("count_check_retry", False)
    fin = r.get("final","?")
    print(f"  Run {i} {t}: task_type={tt} chars={sc} bytes={by} lines={li} score_r1={s1} rounds={rnd} retry={retry} final={fin}")

print()

def mean(vals): return sum(vals)/len(vals)
def std(vals):
    m = mean(vals)
    return math.sqrt(sum((v-m)**2 for v in vals)/(len(vals)-1)) if len(vals)>1 else 0

# Per-task stats for exp2
task_data2 = {"T_A":[],"T_B":[],"T_C":[]}
for r, t in zip(exp2, task_order):
    task_data2[t].append({
        "bytes": r.get("output_bytes",0),
        "lines": r.get("output_lines",0),
        "score": r["wiggum_scores"][0] if r.get("wiggum_scores") else 0,
        "rounds": r.get("wiggum_rounds",0),
        "chars": r.get("total_search_chars",0),
        "retry": r.get("count_check_retry", False),
    })

print("=== Experiment-02 per-task stats ===")
for task in ["T_A","T_B","T_C"]:
    d = task_data2[task]
    bv = [x["bytes"] for x in d]
    lv = [x["lines"] for x in d]
    mb = mean(bv); sb = std(bv); cv = sb/mb*100 if mb else 0
    retries = sum(1 for x in d if x["retry"])
    print(f"  {task}: bytes mean={mb:.0f} std={sb:.0f} CV={cv:.1f}%  lines mean={mean(lv):.1f}  retries={retries}")

print()

# Cross-experiment comparison (exp1 uses same task_order)
exp1_order = ["T_C","T_A","T_B","T_A","T_C","T_B","T_C","T_B","T_A"]
task_data1 = {"T_A":[],"T_B":[],"T_C":[]}
for r, t in zip(exp1, exp1_order):
    task_data1[t].append({
        "bytes": r.get("output_bytes",0),
        "lines": r.get("output_lines",0),
        "score": r["wiggum_scores"][0] if r.get("wiggum_scores") else 0,
        "rounds": r.get("wiggum_rounds",0),
    })

print("=== Cross-experiment comparison (exp-01 vs exp-02) ===")
print(f"  {'task':4}  {'metric':18}  {'exp-01':>8}  {'exp-02':>8}  {'delta':>8}")
print(f"  {'----':4}  {'------':18}  {'------':>8}  {'------':>8}  {'-----':>8}")
for task in ["T_A","T_B","T_C"]:
    d1 = task_data1[task]; d2 = task_data2[task]
    for key, label in [("bytes","bytes mean"),("lines","lines mean"),("score","score_r1 mean"),("rounds","rounds mean")]:
        v1 = mean([x[key] for x in d1])
        v2 = mean([x[key] for x in d2])
        delta = v2 - v1
        sign = "+" if delta >= 0 else ""
        print(f"  {task:4}  {label:18}  {v1:>8.1f}  {v2:>8.1f}  {sign}{delta:>7.1f}")
    print()

print("=== Hypothesis assessment ===")
rounds2 = [r.get("wiggum_rounds",0) for r in exp2]
scores2 = [r["wiggum_scores"][0] for r in exp2 if r.get("wiggum_scores")]
retries2 = sum(1 for r in exp2 if r.get("count_check_retry"))
passes2 = sum(1 for r in exp2 if r.get("final")=="PASS")
task_types2 = [r.get("task_type") for r in exp2]

print(f"H1 (threshold triggers revision): max rounds={max(rounds2)}  any rounds>1: {any(r>1 for r in rounds2)}")
print(f"H2 (count constraint=0 violations): retries={retries2}  (0 retries means no violations detected)")
print(f"H3 (pass rate): {passes2}/9 PASS")
print(f"H4 (task_type routing): {task_types2}")
expected_types = ["best_practices","enumerated","enumerated","best_practices","enumerated","enumerated","enumerated","enumerated","best_practices"]
correct = sum(1 for a,b in zip(task_types2, expected_types) if a==b)
print(f"  correct routing: {correct}/9")

import json, math

runs = []
with open("runs.jsonl", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            runs.append(json.loads(line))

exp = runs[-9:]
task_order = ["T_C","T_A","T_B","T_A","T_C","T_B","T_C","T_B","T_A"]

print("=== Per-run data ===")
for i, (r, t) in enumerate(zip(exp, task_order), 1):
    sc = r.get("total_search_chars","?")
    by = r.get("output_bytes","?")
    li = r.get("output_lines","?")
    s1 = r["wiggum_scores"][0] if r.get("wiggum_scores") else "?"
    rnd = r.get("wiggum_rounds","?")
    fin = r.get("final","?")
    print(f"  Run {i} {t}: chars={sc} bytes={by} lines={li} score_r1={s1} rounds={rnd} final={fin}")

print()

task_data = {"T_A":[],"T_B":[],"T_C":[]}
for r, t in zip(exp, task_order):
    task_data[t].append({
        "bytes": r.get("output_bytes", 0),
        "lines": r.get("output_lines", 0),
        "score": r["wiggum_scores"][0] if r.get("wiggum_scores") else 0,
        "rounds": r.get("wiggum_rounds", 0),
        "chars": r.get("total_search_chars", 0),
    })

def mean(vals):
    return sum(vals) / len(vals)

def std(vals):
    m = mean(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))

print("=== Per-task descriptive stats ===")
for task in ["T_A","T_B","T_C"]:
    d = task_data[task]
    bv = [x["bytes"] for x in d]
    lv = [x["lines"] for x in d]
    sv = [x["score"] for x in d]
    rv = [x["rounds"] for x in d]
    cv_chars = [x["chars"] for x in d]
    mb = mean(bv)
    sb = std(bv) if len(bv) > 1 else 0
    cv = sb / mb * 100 if mb else 0
    print(f"  {task}: bytes mean={mb:.0f} std={sb:.0f} CV={cv:.1f}%  "
          f"lines mean={mean(lv):.1f}  "
          f"score mean={mean(sv):.1f}  "
          f"rounds mean={mean(rv):.1f}  "
          f"chars mean={mean(cv_chars):.0f}")

print()
print("=== Hypothesis assessment ===")

# H1: CV per task
print("H1 (generalization):")
for task in ["T_A","T_B","T_C"]:
    d = task_data[task]
    bv = [x["bytes"] for x in d]
    mb = mean(bv); sb = std(bv)
    cv = sb / mb * 100
    verdict = "STABLE" if cv < 20 else ("BORDERLINE" if cv < 40 else "UNSTABLE")
    print(f"  {task}: CV={cv:.1f}% -> {verdict}")

# H2: wiggum_rounds variance
print("H2 (count constraint):")
for task in ["T_A","T_B","T_C"]:
    d = task_data[task]
    rv = [x["rounds"] for x in d]
    s = std(rv) if len(rv) > 1 else 0
    print(f"  {task}: rounds={rv} std={s:.2f}")

# H3: pass rate
passes = sum(1 for r in exp if r.get("final") == "PASS")
print(f"H3 (pass rate): {passes}/9 PASS")

# H4: floor hits
floor = sum(1 for r in exp if r.get("quality_floor_hit"))
print(f"H4 (search floor): {floor} floor hits")

# Correlation: search chars vs output bytes
chars = [r.get("total_search_chars",0) for r in exp]
bytes_out = [r.get("output_bytes",0) for r in exp]
n = len(chars)
mc = mean(chars); mb2 = mean(bytes_out)
cov = sum((c - mc) * (b - mb2) for c, b in zip(chars, bytes_out)) / (n - 1)
sc2 = std(chars); sb2 = std(bytes_out)
corr = cov / (sc2 * sb2) if sc2 and sb2 else 0
print(f"\nSearch chars vs output bytes correlation (r): {corr:.3f}")

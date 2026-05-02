"""
experiment_analyzer.py — Statistical analysis + report for /autoexperiment.

Reads an ExperimentSpec + runs.jsonl entries tagged with the experiment_id,
computes per-treatment per-task statistics, evaluates the hypothesis, renders
a Markdown report, and calls experiment_panel.py for epistemological evaluation.

Output:
    experiments/<experiment_id>/report.md       — human-readable analysis
    experiments/<experiment_id>/panel.json      — experiment panel reviews

Usage:
    python experiment_analyzer.py experiments/<experiment_id>/spec.json
    python experiment_analyzer.py experiments/<experiment_id>/spec.json --no-panel

Environment:
    conda activate ollama-pi
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone

from experiment_panel import ExperimentSpec, run_experiment_panel, experiment_panel_decision, experiment_panel_issues

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUNS_PATH = os.path.join(_BASE_DIR, "runs.jsonl")


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def _mean(vals: list) -> float | None:
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None

def _std(vals: list) -> float | None:
    vals = [v for v in vals if v is not None]
    if len(vals) < 2:
        return None
    m = sum(vals) / len(vals)
    return round(math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1)), 3)

def _delta(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return round(b - a, 3)


# ---------------------------------------------------------------------------
# Load and filter runs
# ---------------------------------------------------------------------------

def load_experiment_runs(experiment_id: str) -> list[dict]:
    """Load runs.jsonl entries matching the experiment_id."""
    runs = []
    try:
        with open(RUNS_PATH, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    if r.get("experiment_id", "") == experiment_id:
                        runs.append(r)
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        pass
    return runs


# ---------------------------------------------------------------------------
# Per-run extraction (mirrors analyze_exp04.py pattern)
# ---------------------------------------------------------------------------

def extract_run(r: dict) -> dict:
    scores = r.get("wiggum_scores", [])
    score_r1    = scores[0] if scores else None
    score_final = scores[-1] if scores else None
    eval_log = r.get("wiggum_eval_log", []) or []
    dims_r1  = eval_log[0].get("dims", {}) if eval_log else {}
    return {
        "task_id":       r.get("treatment_level", "") and r.get("task_type", ""),  # overridden below
        "treatment":     r.get("treatment_level", ""),
        "score_r1":      score_r1,
        "score_final":   score_final,
        "wiggum_rounds": r.get("wiggum_rounds", 0),
        "final":         r.get("final", "?"),
        "dims_r1":       dims_r1,
        "output_bytes":  r.get("output_bytes", 0),
        "run_duration_s": r.get("run_duration_s", 0),
        "input_tokens":  r.get("input_tokens", 0),
        "output_tokens": r.get("output_tokens", 0),
        "_raw":          r,
    }


def _infer_task_id(r: dict, spec: ExperimentSpec) -> str:
    """Match a run's task string to a task_id from spec.tasks."""
    task_str = r.get("task", "").lower()
    # Try SUITE fingerprints
    try:
        from eval_suite import SUITE
        suite = {t["id"]: t for t in SUITE}
        for tid in spec.tasks:
            if tid in suite:
                fragment = suite[tid].get("desc", "").lower()
                if fragment and fragment[:20] in task_str:
                    return tid
    except Exception:
        pass
    # Fallback: match by treatment-suffixed output path
    for tid in spec.tasks:
        if tid.lower() in task_str:
            return tid
    return "?"


# ---------------------------------------------------------------------------
# Wiggum trace builder (for experiment_panel.py)
# ---------------------------------------------------------------------------

def build_wiggum_traces(runs: list[dict], spec: ExperimentSpec) -> list[dict]:
    """
    Build per-treatment wiggum trace dicts in the format experiment_panel expects:
        [{task_id, treatment, rounds: [{round, score, dims, issues, feedback, content}], final}]
    """
    traces = []
    for r in runs:
        task_id   = r.get("_task_id", "?")
        treatment = r.get("treatment", "")
        eval_log  = r["_raw"].get("wiggum_eval_log", []) or []
        final     = r.get("final", "?")
        traces.append({
            "task_id":   task_id,
            "treatment": treatment,
            "rounds":    eval_log,
            "final":     final,
        })
    return traces


# ---------------------------------------------------------------------------
# Hypothesis evaluation
# ---------------------------------------------------------------------------

def _evaluate_hypothesis(spec: ExperimentSpec, stats: dict) -> dict:
    """
    Parse spec.falsified_if and evaluate against observed stats.
    Supports patterns like: "mean depth_r1 delta < 0.5"

    Returns: {"verdict": "CONFIRMED"|"FALSIFIED"|"INDETERMINATE", "observed": str, "threshold": str}
    """
    falsified_if = spec.falsified_if.lower()

    # Extract numeric threshold
    threshold_m = re.search(r"[<>]=?\s*(\d+\.?\d*)", falsified_if)
    threshold = float(threshold_m.group(1)) if threshold_m else None

    # Extract metric name (e.g. "depth_r1", "score_r1")
    metric_m = re.search(r"\b(\w+_r\d+|\w+_final)\b", falsified_if)
    metric = metric_m.group(1) if metric_m else None

    # Determine operator (< means falsified if delta < threshold)
    lt = "<" in falsified_if

    if metric is None or threshold is None:
        return {"verdict": "INDETERMINATE", "observed": "could not parse", "threshold": str(threshold)}

    # Compute delta across treatments for the metric
    levels = spec.factor["levels"]
    if len(levels) < 2:
        return {"verdict": "INDETERMINATE", "observed": "single treatment", "threshold": str(threshold)}

    baseline, treatment = levels[0], levels[1]
    # Stats keys: dimension metrics stored as "dim_{metric}_mean"; composite as "{metric}_mean"
    def _lookup(s: dict, m: str):
        return s.get(f"dim_{m}_mean", s.get(f"{m}_mean", s.get(m)))

    baseline_means  = [v for s in stats.values()
                       if s.get("treatment") == baseline
                       for v in [_lookup(s, metric)] if v is not None]
    treatment_means = [v for s in stats.values()
                       if s.get("treatment") == treatment
                       for v in [_lookup(s, metric)] if v is not None]

    mean_baseline  = _mean(baseline_means)
    mean_treatment = _mean(treatment_means)
    delta = _delta(mean_baseline, mean_treatment)

    if delta is None:
        return {"verdict": "INDETERMINATE", "observed": "insufficient data", "threshold": str(threshold)}

    # Hypothesis is falsified if delta < threshold (or > for ">" patterns)
    falsified = delta < threshold if lt else delta > threshold
    verdict = "FALSIFIED" if falsified else "CONFIRMED"

    return {
        "verdict":   verdict,
        "observed":  f"delta={delta:+.3f} ({baseline}={mean_baseline:.2f}, {treatment}={mean_treatment:.2f})",
        "threshold": f"{'<' if lt else '>'} {threshold}",
        "metric":    metric,
    }


# ---------------------------------------------------------------------------
# Markdown report renderer
# ---------------------------------------------------------------------------

def render_report(
    spec: ExperimentSpec,
    runs: list[dict],
    stats_by_key: dict,
    hypothesis_result: dict,
    panel_reviews: list[dict] | None,
    panel_decision: dict | None,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    levels = spec.factor["levels"]
    tasks  = spec.tasks

    lines = [
        f"# Experiment Report: {spec.title}",
        f"",
        f"**Date:** {now}  ",
        f"**Factor:** `{spec.factor['name']}`  levels: {levels}  ",
        f"**Tasks:** {tasks}  **Replications:** {spec.replications}  ",
        f"**Hypothesis:** {spec.hypothesis}  ",
        f"**Falsified if:** {spec.falsified_if}",
        f"",
        f"---",
        f"",
        f"## Hypothesis Verdict",
        f"",
        f"**{hypothesis_result['verdict']}**  ",
        f"Observed: {hypothesis_result['observed']}  ",
        f"Threshold: {hypothesis_result['threshold']}",
        f"",
        f"---",
        f"",
        f"## Results Table",
        f"",
    ]

    # Per-task, per-treatment stats
    header = f"| Task | Treatment | n | score_r1 (mean±sd) | score_final (mean±sd) | rounds (mean) | PASS rate |"
    sep    = f"|------|-----------|---|-------------------|----------------------|---------------|-----------|"
    lines += [header, sep]

    for task_id in tasks:
        for treatment in levels:
            key = (task_id, treatment)
            s = stats_by_key.get(key, {})
            n         = s.get("n", 0)
            sr1_m     = s.get("score_r1_mean")
            sr1_sd    = s.get("score_r1_std")
            sfin_m    = s.get("score_final_mean")
            sfin_sd   = s.get("score_final_std")
            rounds_m  = s.get("wiggum_rounds_mean")
            pass_rate = s.get("pass_rate")

            def fmt(m, sd):
                if m is None:
                    return "n/a"
                sd_str = f"±{sd:.2f}" if sd is not None else ""
                return f"{m:.2f}{sd_str}"

            rounds_str = f"{rounds_m:.1f}" if rounds_m is not None else "n/a"
            pass_str   = f"{pass_rate:.0%}" if pass_rate is not None else "n/a"

            lines.append(
                f"| {task_id} | {treatment} | {n} "
                f"| {fmt(sr1_m, sr1_sd)} | {fmt(sfin_m, sfin_sd)} "
                f"| {rounds_str} | {pass_str} |"
            )

    lines += ["", "---", "", "## Per-Dimension Analysis (r1 means)", ""]
    dim_names = ["relevance", "completeness", "depth", "grounded", "specificity", "structure"]
    dim_header = "| Task | Treatment | " + " | ".join(dim_names) + " |"
    dim_sep    = "|------|-----------|" + "|".join(["---"] * len(dim_names)) + "|"
    lines += [dim_header, dim_sep]

    for task_id in tasks:
        for treatment in levels:
            key = (task_id, treatment)
            s = stats_by_key.get(key, {})
            dim_vals = [f"{s.get(f'dim_{d}_r1_mean', 0) or 0:.1f}" for d in dim_names]
            lines.append(f"| {task_id} | {treatment} | " + " | ".join(dim_vals) + " |")

    # Raw runs summary
    lines += ["", "---", "", "## Raw Runs", ""]
    lines.append("| Run | Task | Treatment | Rep | score_r1 | score_final | rounds | final | bytes | dur(s) |")
    lines.append("|-----|------|-----------|-----|----------|-------------|--------|-------|-------|--------|")
    for i, r in enumerate(runs, 1):
        lines.append(
            f"| {i} | {r.get('_task_id','?')} | {r.get('treatment','?')} "
            f"| {r.get('_rep','?')} "
            f"| {r.get('score_r1') or 'n/a'} | {r.get('score_final') or 'n/a'} "
            f"| {r.get('wiggum_rounds',0)} | {r.get('final','?')} "
            f"| {r.get('output_bytes',0)} | {r.get('run_duration_s',0):.0f} |"
        )

    # Panel verdicts
    if panel_reviews:
        lines += ["", "---", "", "## Experiment Panel Verdicts", ""]
        for rev in panel_reviews:
            lines.append(f"### {rev['persona']} — {rev['verdict']} ({rev['score']}/10)")
            for issue in rev.get("issues", []):
                lines.append(f"- {issue}")
            if rev.get("next_experiment_suggestion"):
                lines.append(f"\n**Next experiment:** {rev['next_experiment_suggestion']}")
            lines.append("")

    if panel_decision:
        lines += [
            "---", "",
            f"## Loop Decision: **{panel_decision['decision']}**  ",
            f"Confidence: {panel_decision['confidence']}  ",
            f"Rationale: {panel_decision['rationale']}",
        ]
        if panel_decision.get("next_experiment_suggestion"):
            lines.append(f"\n**Next:** {panel_decision['next_experiment_suggestion']}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def analyze(spec_path: str, run_panel: bool = True) -> None:
    with open(spec_path, encoding="utf-8") as f:
        spec = ExperimentSpec.from_dict(json.load(f))

    experiment_id = spec.title.lower().replace(" ", "-")[:40]
    out_dir = os.path.join(_BASE_DIR, "experiments", experiment_id)
    os.makedirs(out_dir, exist_ok=True)

    print(f"\n[analyze] experiment: {spec.title}")
    print(f"  loading runs with experiment_id={experiment_id!r}...")

    raw_runs = load_experiment_runs(experiment_id)
    print(f"  {len(raw_runs)} run(s) found in runs.jsonl")

    if not raw_runs:
        print("  [warn] no runs found — run experiment_runner.py first")
        return

    # Enrich runs with task_id + rep (use explicit field if present, else infer)
    # Exclude runs where task_id resolved to "?" — they lack the tracking field
    # and were produced before task_id tagging was implemented.
    runs = []
    skipped = 0
    errored = 0
    rep_counters: dict[tuple, int] = defaultdict(int)
    for r in raw_runs:
        extracted = extract_run(r)
        if extracted.get("final") == "ERROR" and extracted.get("score_r1") is None:
            errored += 1
            continue
        task_id = r.get("task_id") or _infer_task_id(r, spec)
        if task_id == "?":
            skipped += 1
            continue
        treatment = extracted["treatment"]
        rep_counters[(task_id, treatment)] += 1
        extracted["_task_id"] = task_id
        extracted["_rep"]     = rep_counters[(task_id, treatment)]
        extracted["_raw"]     = r
        runs.append(extracted)
    if errored:
        print(f"  [warn] excluded {errored} ERROR run(s) with no scores (crashed before completion)")
    if skipped:
        print(f"  [warn] skipped {skipped} run(s) with unresolvable task_id (pre-tagging runs)")

    # Compute per-(task, treatment) statistics
    groups: dict[tuple, list] = defaultdict(list)
    for r in runs:
        groups[(r["_task_id"], r["treatment"])].append(r)

    stats_by_key: dict[tuple, dict] = {}
    for key, group in groups.items():
        task_id, treatment = key
        sr1s    = [r["score_r1"] for r in group]
        sfins   = [r["score_final"] for r in group]
        rds     = [r["wiggum_rounds"] for r in group]
        passes  = [1 if r["final"] == "PASS" else 0 for r in group]

        s = {
            "task_id":            task_id,
            "treatment":          treatment,
            "n":                  len(group),
            "score_r1_mean":      _mean(sr1s),
            "score_r1_std":       _std(sr1s),
            "score_final_mean":   _mean(sfins),
            "score_final_std":    _std(sfins),
            "wiggum_rounds_mean": _mean(rds),
            "pass_rate":          _mean(passes),
        }
        # Per-dimension r1 means
        dim_names = ["relevance", "completeness", "depth", "grounded", "specificity", "structure"]
        for dim in dim_names:
            dim_vals = [r["dims_r1"].get(dim) for r in group if r["dims_r1"].get(dim) is not None]
            s[f"dim_{dim}_r1_mean"] = _mean(dim_vals)

        stats_by_key[key] = s

    # Hypothesis evaluation
    hypothesis_result = _evaluate_hypothesis(spec, stats_by_key)
    print(f"  hypothesis: {hypothesis_result['verdict']} — {hypothesis_result['observed']}")

    # Experiment panel
    panel_reviews = None
    panel_decision = None
    if run_panel:
        print(f"\n[analyze] running experiment panel...")
        wiggum_traces = build_wiggum_traces(runs, spec)
        try:
            panel_reviews = run_experiment_panel(spec, wiggum_traces)
            panel_decision = experiment_panel_decision(panel_reviews)
            print(f"  panel decision: {panel_decision['decision']}  confidence={panel_decision['confidence']}")
            if panel_decision.get("next_experiment_suggestion"):
                print(f"  next: {panel_decision['next_experiment_suggestion']}")

            panel_path = os.path.join(out_dir, "panel.json")
            with open(panel_path, "w", encoding="utf-8") as f:
                json.dump({
                    "reviews":  panel_reviews,
                    "decision": panel_decision,
                }, f, indent=2)
            print(f"  panel saved to {panel_path}")
        except Exception as e:
            print(f"  [warn] panel failed ({e}) -- skipping")

    # Render report
    report = render_report(spec, runs, stats_by_key, hypothesis_result, panel_reviews, panel_decision)
    report_path = os.path.join(out_dir, "report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n[analyze] report written to {report_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python experiment_analyzer.py experiments/<id>/spec.json [--no-panel]")
        sys.exit(1)

    analyze(
        spec_path=sys.argv[1],
        run_panel="--no-panel" not in sys.argv,
    )

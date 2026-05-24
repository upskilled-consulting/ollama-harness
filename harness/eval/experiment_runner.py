"""
harness.eval.experiment_runner — Generalized CRD runner for /autoexperiment.

Reads an ExperimentSpec JSON, generates a randomized completely-randomized-design
(CRD) run order, applies treatments via env var overrides, executes agent
subprocesses, and logs a checkpoint after every run.

Treatment application (mutable_scope.type):
  "env"  — sets the named env var to the treatment-level value in the subprocess.
           Example: {"type":"env","var":"HARNESS_PRIOR_KNOWLEDGE_PASS","levels":{"off":"","on":"1"}}

Each run is tagged in runs.jsonl via HARNESS_EXPERIMENT_ID + HARNESS_TREATMENT_LEVEL
env vars (picked up by logger.py).

Checkpoint: experiments/<experiment_id>/run_log.jsonl, written after every run.
--resume skips (task_id, treatment, rep) tuples already in the checkpoint.

Output files use treatment-specific paths to avoid overwrites between levels:
  base:         eval-context-engineering.md
  treatment=off: eval-context-engineering-off.md
  treatment=on:  eval-context-engineering-on.md

Usage:
    python -m harness.eval.experiment_runner experiment_spec.json
    python -m harness.eval.experiment_runner experiment_spec.json --resume
    python -m harness.eval.experiment_runner experiment_spec.json --dry-run
    python -m harness.eval.experiment_runner experiment_spec.json --treatment on
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

from harness.eval.experiment_panel import ExperimentSpec

# harness/eval/ → harness/ → repo root
_BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
_HARNESS_DIR    = os.path.dirname(_BASE_DIR)
_REPO_DIR       = os.path.dirname(_HARNESS_DIR)
EXPERIMENTS_DIR = os.path.join(_REPO_DIR, "data", "experiments")


# ---------------------------------------------------------------------------
# Task registry (pull from eval_suite SUITE when not defined in spec)
# ---------------------------------------------------------------------------

def _load_suite() -> dict[str, dict]:
    try:
        from harness.eval.eval_suite import SUITE
        return {t["id"]: t for t in SUITE}
    except Exception:
        return {}


def _resolve_task(task_id: str, spec: ExperimentSpec, suite: dict) -> dict:
    """Return {task, output, output_raw} for a task ID."""
    if hasattr(spec, "task_defs") and spec.task_defs and task_id in spec.task_defs:
        td = spec.task_defs[task_id]
        expanded = os.path.expanduser(td["output"])
        home = os.path.expanduser("~").replace("\\", "/")
        raw  = td["output"].replace("\\", "/")
        tilde = raw.replace(home, "~") if home in raw else raw
        return {"task": td["task"], "output": expanded, "output_raw": tilde}

    if task_id in suite:
        entry = suite[task_id]
        return {
            "task":       entry["task"],
            "output":     os.path.expanduser(entry["output"]),
            "output_raw": entry["output"],
        }

    raise ValueError(f"Task {task_id!r} not found in spec.task_defs or eval_suite.SUITE")


def _treatment_output_path(base_output: str, treatment: str) -> str:
    """Derive a treatment-specific output path to avoid overwrites."""
    sep = "/" if "/" in base_output and not base_output.startswith(("C:", "D:")) else None
    p   = Path(base_output)
    result = str(p.with_stem(f"{p.stem}-{treatment}"))
    if sep:
        result = result.replace("\\", "/")
    return result


# ---------------------------------------------------------------------------
# CRD run order generation
# ---------------------------------------------------------------------------

def generate_crd_order(spec: ExperimentSpec, seed: int | None = None) -> list[dict]:
    """Return a randomized CRD run list with keys: task_id, treatment, rep, run_num."""
    rng = random.Random(seed)
    runs = [
        {"task_id": task_id, "treatment": treatment, "rep": rep}
        for treatment in spec.factor["levels"]
        for task_id in spec.tasks
        for rep in range(1, spec.replications + 1)
    ]
    rng.shuffle(runs)
    for i, r in enumerate(runs, 1):
        r["run_num"] = i
    return runs


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------

def _checkpoint_path(experiment_id: str) -> str:
    return os.path.join(EXPERIMENTS_DIR, experiment_id, "run_log.jsonl")


def _load_checkpoint(experiment_id: str) -> set[tuple]:
    path = _checkpoint_path(experiment_id)
    completed: set[tuple] = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    if r.get("ok"):
                        completed.add((r["task_id"], r["treatment"], r["rep"]))
    return completed


def _write_checkpoint(experiment_id: str, record: dict) -> None:
    path = _checkpoint_path(experiment_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _save_spec(experiment_id: str, spec: ExperimentSpec) -> None:
    path = os.path.join(EXPERIMENTS_DIR, experiment_id, "spec.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(spec.to_json())


# ---------------------------------------------------------------------------
# Treatment env var application
# ---------------------------------------------------------------------------

def _build_env(spec: ExperimentSpec, treatment: str, task_id: str = "") -> dict:
    """Return subprocess env with treatment applied."""
    env   = os.environ.copy()
    scope = spec.mutable_scope
    if scope.get("type") == "env":
        var = scope["var"]
        val = scope.get("levels", {}).get(treatment, "")
        if val:
            env[var] = val
        elif var in env:
            del env[var]
    if spec.fixed_env:
        env.update(spec.fixed_env)
    env["HARNESS_EXPERIMENT_ID"]   = spec.title.lower().replace(" ", "-")[:40]
    env["HARNESS_TREATMENT_LEVEL"] = treatment
    env["HARNESS_TASK_ID"]         = task_id
    return env


# ---------------------------------------------------------------------------
# Single run executor
# ---------------------------------------------------------------------------

def run_one(
    run_entry: dict,
    spec:      ExperimentSpec,
    suite:     dict,
    total:     int,
    dry_run:   bool = False,
) -> dict:
    task_id   = run_entry["task_id"]
    treatment = run_entry["treatment"]
    rep       = run_entry["rep"]
    run_num   = run_entry["run_num"]

    task_def    = _resolve_task(task_id, spec, suite)
    output_base = task_def["output"]
    output_raw  = task_def.get("output_raw", output_base)
    output_path = _treatment_output_path(output_base, treatment)

    task_str        = task_def["task"]
    output_raw_path = _treatment_output_path(output_raw, treatment)
    if output_raw in task_str:
        task_str = task_str.replace(output_raw, output_raw_path)
    elif output_base in task_str:
        task_str = task_str.replace(output_base, output_path)
    else:
        task_str = f"{task_str} save to {output_path}"

    label = f"[run {run_num}/{total}] {task_id} treatment={treatment} rep={rep}"
    print(f"\n{'='*60}\n {label}\n  output: {output_path}\n{'='*60}")

    if dry_run:
        print(f"  [dry-run] would execute: {task_str[:120]}")
        return {**run_entry, "ok": None, "elapsed": 0, "dry_run": True}

    env = _build_env(spec, treatment, task_id=task_id)
    t0  = time.time()
    result = subprocess.run(
        [sys.executable, "-m", "harness.agent", "--no-onboard", task_str],
        cwd=_REPO_DIR,
        env=env,
    )
    elapsed = round(time.time() - t0, 1)
    ok      = result.returncode == 0 and os.path.exists(output_path)
    print(f"\n {label} -- {'OK' if ok else 'FAILED'} ({elapsed}s)")

    return {
        **run_entry,
        "ok":       ok,
        "elapsed":  elapsed,
        "output":   output_path,
        "task_str": task_str[:200],
    }


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def run_experiment(
    spec_path:       str,
    resume:          bool = False,
    dry_run:         bool = False,
    only_treatment:  str | None = None,
) -> None:
    with open(spec_path, encoding="utf-8") as f:
        spec = ExperimentSpec.from_dict(json.load(f))

    experiment_id = spec.title.lower().replace(" ", "-")[:40]
    suite = _load_suite()
    crd   = generate_crd_order(spec, seed=42)
    total = len(crd)

    _save_spec(experiment_id, spec)
    completed = _load_checkpoint(experiment_id) if resume else set()

    print("\n" + "="*60)
    print(f" {spec.title}")
    print(f" {total} runs  |  factor={spec.factor['name']}  |  "
          f"levels={spec.factor['levels']}  |  tasks={spec.tasks}  |  reps={spec.replications}")
    print(f" hypothesis: {spec.hypothesis}")
    if only_treatment:
        print(f" mode: treatment filter — only '{only_treatment}' runs")
    if resume:
        print(f" mode: resume ({len(completed)} already completed)")
    if dry_run:
        print(" mode: dry-run (no agent calls)")
    print("="*60)

    if dry_run:
        for entry in crd:
            print(f"  run {entry['run_num']:>2}: {entry['task_id']}  "
                  f"treatment={entry['treatment']}  rep={entry['rep']}")
        return

    results: list[dict] = []
    t_wall = time.time()

    for entry in crd:
        if only_treatment and entry["treatment"] != only_treatment:
            continue
        key = (entry["task_id"], entry["treatment"], entry["rep"])
        if resume and key in completed:
            print(f"\n[run {entry['run_num']}/{total}] {entry['task_id']} "
                  f"treatment={entry['treatment']} rep={entry['rep']} -- SKIPPED (checkpoint)")
            results.append({**entry, "ok": None, "elapsed": 0, "skipped": True})
            continue

        record = run_one(entry, spec, suite, total)
        results.append(record)
        _write_checkpoint(experiment_id, record)

    wall     = round(time.time() - t_wall, 1)
    executed = [r for r in results if not r.get("skipped") and not r.get("dry_run")]
    failed   = [r for r in executed if not r.get("ok")]

    print(f"\n{'='*60}")
    print(f" {spec.title} -- complete")
    print(f" {len(executed)} executed, {len(failed)} failed, wall time: {wall}s")
    for r in failed:
        print(f"  FAILED: run {r['run_num']} ({r['task_id']} treatment={r['treatment']})")
    print(f"\nNext: python -m harness.eval.experiment_runner experiments/{experiment_id}/spec.json")
    print("="*60)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m harness.eval.experiment_runner experiment_spec.json [--resume] [--dry-run] [--treatment <level>]")
        sys.exit(1)

    _treatment = None
    if "--treatment" in sys.argv:
        idx = sys.argv.index("--treatment")
        if idx + 1 < len(sys.argv):
            _treatment = sys.argv[idx + 1]

    run_experiment(
        spec_path=sys.argv[1],
        resume="--resume" in sys.argv,
        dry_run="--dry-run" in sys.argv,
        only_treatment=_treatment,
    )

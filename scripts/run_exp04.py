"""
run_exp04.py — execute the 9-run CRD for experiment-04.

Runs agent.py for each task in the randomized order defined in experiment-04.md.
Producer is now pi-qwen-32b (default in agent.py after the upgrade).
Each run appends one record to runs.jsonl. Run analyze_exp04.py after completion.

Usage:
    conda activate ollama-pi
    python run_exp04.py
    python run_exp04.py --resume   # skip tasks whose output file already exists
"""

import os
import subprocess
import sys
import time

BASE = "~/Desktop/harness-engineering"

TASKS = {
    "T_A": f"Search for the top 5 context engineering techniques used in production LLM agents and save to {BASE}/eval-context-engineering.md",
    "T_B": f"Search for best practices for cost envelope management in production AI agents and save to {BASE}/eval-cost-management.md",
    "T_C": f"Search for the 3 most common failure modes in multi-agent AI systems and save to {BASE}/eval-agent-failure-modes.md",
}

OUTPUT_PATHS = {
    "T_A": os.path.expanduser(f"{BASE}/eval-context-engineering.md"),
    "T_B": os.path.expanduser(f"{BASE}/eval-cost-management.md"),
    "T_C": os.path.expanduser(f"{BASE}/eval-agent-failure-modes.md"),
}

# Randomized run order from experiment-04.md
RUN_ORDER = ["T_B", "T_A", "T_C", "T_A", "T_C", "T_B", "T_C", "T_A", "T_B"]

AGENT_SCRIPT = os.path.join(os.path.dirname(__file__), "agent.py")


def run_one(run_num: int, task_id: str, resume: bool) -> dict:
    output_path = OUTPUT_PATHS[task_id]

    if resume and os.path.exists(output_path):
        size = os.path.getsize(output_path)
        print(f"\n[run {run_num}/9] {task_id} — SKIPPED (output exists, {size} bytes)")
        return {"run": run_num, "task": task_id, "skipped": True}

    print(f"\n{'='*60}")
    print(f"[run {run_num}/9] {task_id}")
    print(f"{'='*60}")

    t0 = time.time()
    result = subprocess.run(
        [sys.executable, AGENT_SCRIPT, TASKS[task_id]],
        cwd=os.path.dirname(__file__),
    )
    elapsed = round(time.time() - t0, 1)

    ok = result.returncode == 0 and os.path.exists(output_path)
    status = "OK" if ok else "FAILED"
    print(f"\n[run {run_num}/9] {task_id} — {status} ({elapsed}s)")

    return {"run": run_num, "task": task_id, "elapsed": elapsed, "ok": ok}


def main():
    resume = "--resume" in sys.argv

    print("\n" + "="*60)
    print(" Experiment-04: Producer Upgrade Impact")
    print(f" {len(RUN_ORDER)} runs  |  producer: pi-qwen-32b  |  evaluator: Qwen3-Coder:30b  |  threshold: 8.0")
    if resume:
        print(" mode: resume (skipping existing outputs)")
    print("="*60)

    results = []
    t_wall = time.time()

    for i, task_id in enumerate(RUN_ORDER, 1):
        r = run_one(i, task_id, resume)
        results.append(r)

    wall = round(time.time() - t_wall, 1)
    completed = [r for r in results if not r.get("skipped")]
    failed = [r for r in completed if not r.get("ok")]

    print(f"\n{'='*60}")
    print(f" Experiment-04 complete")
    print(f" {len(completed)} run(s) executed, {len(failed)} failed, wall time: {wall}s")
    if failed:
        for r in failed:
            print(f"  FAILED: run {r['run']} ({r['task']})")
    print(f"{'='*60}")
    print(f"\nNext: python analyze_exp04.py")


if __name__ == "__main__":
    main()

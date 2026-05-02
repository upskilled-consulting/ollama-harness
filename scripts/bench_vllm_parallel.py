"""
bench_vllm_parallel.py — measure wall-time speedup of vLLM continuous batching
vs Ollama serial queue on a 4-subtask orchestrated run.

Runs the same orchestrated task twice:
  1. INFERENCE_BACKEND=ollama  (serial queue)
  2. INFERENCE_BACKEND=vllm    (continuous batching)

Prints wall time, per-subtask timing, and speedup ratio.

Usage:
    python bench_vllm_parallel.py
    python bench_vllm_parallel.py --subtasks 2   # fewer subtasks for a quicker run
    python bench_vllm_parallel.py --ollama-only  # just the ollama baseline
    python bench_vllm_parallel.py --vllm-only    # just the vllm run
"""

import os
import subprocess
import sys
import time
import json

# Load .env so VLLM_BASE_URL etc. are available in the parent env and inherited by subprocesses
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

BASE   = os.path.expanduser("~/Desktop/harness-engineering")
SCRIPT = os.path.join(BASE, "orchestrator.py")

# Task designed to produce exactly N subtasks (parallel research + assembly)
BENCH_TASKS = {
    2: (
        "Research (1) the main architectural patterns used in production multi-agent systems "
        "and (2) the key reliability patterns used to handle failures in production multi-agent "
        "systems. Synthesize into a unified guide and save to "
        f"{BASE}/bench-parallel-2.md"
    ),
    4: (
        "Research (1) the main architectural patterns in production multi-agent systems, "
        "(2) common failure modes and recovery patterns, "
        "(3) observability and tracing approaches for agent pipelines, and "
        "(4) cost control strategies for LLM-based agent workloads. "
        "Synthesize into a unified engineering guide and save to "
        f"{BASE}/bench-parallel-4.md"
    ),
}


def run_backend(task: str, backend: str, label: str) -> dict:
    """Run the orchestrator with a specific backend. Returns timing + metadata."""
    env = os.environ.copy()
    env["INFERENCE_BACKEND"] = backend
    env["WIGGUM_MAX_ROUNDS"] = "1"   # cap wiggum to 1 round so timing reflects parallel work

    if backend == "vllm":
        # When running vLLM-only (Ollama stopped), map ALL harness models to the
        # served model so no call silently falls back to a dead Ollama daemon.
        # Planner (glm4:9b) and evaluator both use the same served model.
        served = env.get("VLLM_MODEL_MAP", "")
        import json as _json
        try:
            served_map = _json.loads(served)
            served_model = next(iter(served_map.values())) if served_map else "Qwen/Qwen2.5-14B-Instruct-AWQ"
        except Exception:
            served_model = "Qwen/Qwen2.5-14B-Instruct-AWQ"
        full_map = {
            "pi-qwen-32b":              served_model,
            "pi-qwen":                  served_model,
            "Qwen3-Coder:30b":          served_model,
            "glm4:9b":                  served_model,
            "llama3.2:3b":              served_model,
        }
        env["VLLM_MODEL_MAP"] = _json.dumps(full_map)
        print(f"  [bench] vLLM full model map active (served={served_model})")

    print(f"\n{'='*60}")
    print(f" {label}  (backend={backend})")
    print(f"{'='*60}")

    t0 = time.monotonic()
    result = subprocess.run(
        [sys.executable, SCRIPT, "--no-wiggum", task],
        capture_output=False,   # let stdout stream so user can watch
        text=True,
        cwd=BASE,
        env=env,
    )
    wall = round(time.monotonic() - t0, 1)

    return {
        "label":    label,
        "backend":  backend,
        "wall_s":   wall,
        "returncode": result.returncode,
    }


def main():
    args = sys.argv[1:]
    n_subtasks = 4
    if "--subtasks" in args:
        idx = args.index("--subtasks")
        n_subtasks = int(args[idx + 1])
    ollama_only = "--ollama-only" in args
    vllm_only   = "--vllm-only"   in args

    task = BENCH_TASKS.get(n_subtasks, BENCH_TASKS[4])
    print(f"\n[bench] subtasks={n_subtasks}")
    print(f"[bench] task: {task[:100]}...")

    runs = []

    if not vllm_only:
        r = run_backend(task, "ollama", f"Ollama ({n_subtasks} subtasks)")
        runs.append(r)

    if not ollama_only:
        r = run_backend(task, "vllm", f"vLLM ({n_subtasks} subtasks)")
        runs.append(r)

    # Results
    print(f"\n{'='*60}")
    print(f" Benchmark Results")
    print(f"{'='*60}")
    for r in runs:
        status = "OK" if r["returncode"] == 0 else f"FAIL(rc={r['returncode']})"
        print(f"  {r['label']:<30} wall={r['wall_s']:>7.1f}s  {status}")

    if len(runs) == 2 and all(r["returncode"] == 0 for r in runs):
        ollama_t = next(r["wall_s"] for r in runs if r["backend"] == "ollama")
        vllm_t   = next(r["wall_s"] for r in runs if r["backend"] == "vllm")
        speedup  = round(ollama_t / vllm_t, 2) if vllm_t > 0 else 0
        print(f"\n  Speedup: {speedup}×  (vLLM {vllm_t}s vs Ollama {ollama_t}s)")
        if speedup >= 1.5:
            print(f"  → vLLM continuous batching delivers meaningful parallelism gain.")
        elif speedup >= 1.1:
            print(f"  → Modest gain — overhead (startup, tokenization) eating into batching benefit.")
        else:
            print(f"  → Negligible gain — consider whether subtask count or model size is the bottleneck.")

    # Save results
    out = os.path.join(BASE, "data", "bench_vllm_results.jsonl")
    with open(out, "a", encoding="utf-8") as f:
        for r in runs:
            f.write(json.dumps({**r, "n_subtasks": n_subtasks,
                                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}) + "\n")
    print(f"\n  Results appended to bench_vllm_results.jsonl")


if __name__ == "__main__":
    main()

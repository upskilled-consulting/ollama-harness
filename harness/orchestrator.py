"""
orchestrator.py — Stage 3: multi-subtask coordination layer.

Decomposes complex tasks into subtasks via the planner, executes each through
agent.run(), then assembles a unified final document from the subtask outputs.

Single-focus tasks (no subtasks in plan) are delegated directly to agent.run()
so the orchestrator is a drop-in replacement for the agent entry point.

Usage:
    python orchestrator.py "Research X and Y, synthesize into a guide and save to ~/Desktop/.../out.md"
    python orchestrator.py --no-wiggum "..."

Architecture:
    orchestrate(task)
        memory.get_context()  →  make_plan()
        if subtasks:
            assign _sub_N.md paths
            agent.run(subtask) × N          # no wiggum per subtask
            assemble(task, subtask_outputs)  # cross-referencing synthesis
            write final output
            wiggum on final output
            store memory + cleanup _sub files
        else:
            agent.run(task)                  # simple passthrough
"""

import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from harness import inference as ollama
from harness.agent import (
    count_output_items,
    extract_count_constraint,
    extract_path,
    synthesize_with_count,
    write_output,
)
from harness.logger import RunTrace
from harness.memory import MemoryStore
from harness.planner import make_plan
from harness.wiggum import EVALUATOR_MODEL
from harness.wiggum import loop as wiggum_loop

ASSEMBLY_MODEL = "pi-qwen"
SUBTASK_MAX_RETRIES = 1    # retry a failed subtask this many times before skipping
SUBTASK_MAX_WORKERS = 4    # max parallel subtask threads


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

ASSEMBLE_PROMPT = """\
Task: {task}

You have the following research documents prepared by specialist agents:

{sources}

Synthesize these into a single unified markdown document.

Requirements:
- Identify themes and patterns that appear across multiple sources
- Cross-reference related findings (e.g. "this mirrors the failure mode described in section X")
- Note any tensions or conflicts between sources
- Produce a structure that emerges from the material — do not simply concatenate the sources
- Output ONLY the markdown document starting with # — no preamble, no commentary
- Each section must include a concrete implementation note or example
- Do not mention subtask file paths or the word "synthesize"
"""


def assemble(task: str, subtask_results: list[dict], memory_context: str = "") -> str:
    """
    Synthesize multiple subtask outputs into a unified final document.
    subtask_results: list of {"desc": str, "path": str, "content": str}
    """
    source_blocks = []
    for i, r in enumerate(subtask_results, 1):
        if r.get("content"):
            source_blocks.append(
                f"### Document {i}: {r['desc']}\n\n{r['content']}"
            )

    if not source_blocks:
        return ""

    sources_text = "\n\n---\n\n".join(source_blocks)
    memory_block = f"\nRelevant past context:\n{memory_context}\n" if memory_context else ""

    prompt = ASSEMBLE_PROMPT.format(task=task, sources=sources_text) + memory_block

    response = ollama.chat(
        model=ASSEMBLY_MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.1},
    )
    return response["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Subtask execution
# ---------------------------------------------------------------------------

def _assign_paths(subtask_descs: list[str], workspace: str) -> list[dict]:
    """Convert subtask descriptions to runnable task dicts with assigned output paths."""
    results = []
    for i, desc in enumerate(subtask_descs, 1):
        # Normalise: ensure the description starts with a research directive
        desc = desc.strip().rstrip(".")
        sub_path = os.path.join(workspace, f"_sub_{i}.md")
        # Use forward slashes so agent.py's path regex matches on Windows
        sub_path_fwd = sub_path.replace("\\", "/")
        task_str = f"{desc} and save to {sub_path_fwd}"
        results.append({"desc": desc, "task": task_str, "path": sub_path})
    return results


def _run_one_subtask(sub: dict, parent_env: dict | None = None) -> dict:
    """
    Run a single subtask, routing to a remote MCP agent if HARNESS_MCP_ENDPOINTS
    matches the task string; otherwise spawns a local agent.py subprocess.
    parent_env: HARNESS_* env vars to propagate into the subprocess.
    Returns sub enriched with: content, output_log, attempts, elapsed.
    """
    from harness.mcp_dispatch import resolve_endpoint, route_subtask

    # --- MCP dispatch path ---
    endpoint = resolve_endpoint(sub["task"])
    if endpoint:
        print(f"  [orchestrator] MCP dispatch: {sub['desc'][:60]} -> {endpoint}")
        result = route_subtask(sub["task"], endpoint)
        sub["output_log"] = [f"[mcp] {endpoint}"]
        sub["attempts"] = 1
        sub["elapsed"] = result.get("elapsed", 0)
        if result["ok"]:
            sub["content"] = result["content"]
            return sub
        # MCP failed — fall through to local subprocess
        print(f"  [orchestrator] MCP failed ({result.get('error')}) — falling back to local")

    # --- Local subprocess path ---
    from harness.config import ROOT as _ORCH_ROOT
    agent_script = None
    sub["output_log"] = sub.get("output_log", [])
    sub["attempts"] = 0
    t0 = time.time()

    # Build subprocess environment: inherit current env + harness tracking vars
    env = os.environ.copy()
    if parent_env:
        env.update(parent_env)

    for attempt in range(1, SUBTASK_MAX_RETRIES + 2):
        sub["attempts"] = attempt
        result = subprocess.run(
            [sys.executable, "-m", "harness.agent", "--no-wiggum", sub["task"]],
            capture_output=True,
            text=True,
            cwd=str(_ORCH_ROOT),
            env=env,
        )
        sub["output_log"].append(result.stdout + (result.stderr or ""))

        expanded = os.path.expanduser(sub["path"])
        if result.returncode == 0 and os.path.exists(expanded):
            with open(expanded, encoding="utf-8") as f:
                content = f.read()
            if content.strip():
                sub["content"] = content
                sub["elapsed"] = round(time.time() - t0, 1)
                return sub

        # Failure — retry or give up
        if attempt <= SUBTASK_MAX_RETRIES:
            sub["output_log"].append(f"[retry {attempt}/{SUBTASK_MAX_RETRIES}]")
        else:
            sub["content"] = ""
            sub["elapsed"] = round(time.time() - t0, 1)
            return sub

    sub["content"] = ""
    sub["elapsed"] = round(time.time() - t0, 1)
    return sub


def _run_subtasks_parallel(subtask_defs: list[dict], parent_env: dict | None = None) -> list[dict]:
    """
    Execute subtasks in parallel threads (each spawns its own subprocess).
    parent_env: HARNESS_* env vars to propagate for run lineage tracking.
    Returns subtask_defs enriched with content, elapsed, attempts.
    """
    n = len(subtask_defs)
    workers = min(n, SUBTASK_MAX_WORKERS)
    print(f"\n[orchestrator] running {n} subtask(s) in parallel (max {workers} workers)...")

    t_wall_start = time.time()
    results = [None] * n

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_idx = {pool.submit(_run_one_subtask, sub, parent_env): i
                         for i, sub in enumerate(subtask_defs)}
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                results[idx] = {**subtask_defs[idx], "content": "", "error": str(e),
                                "elapsed": 0, "attempts": 1}

    wall_time = round(time.time() - t_wall_start, 1)

    # Print each subtask's captured output in order
    for i, sub in enumerate(results):
        status = "OK" if sub.get("content") else "FAILED"
        attempts_str = f", {sub.get('attempts', 1)} attempt(s)" if sub.get('attempts', 1) > 1 else ""
        print(f"\n{'='*50}")
        print(f"[subtask {i+1}/{n}] {sub['desc']}  —  {status}  ({sub.get('elapsed', '?')}s{attempts_str})")
        print(f"{'='*50}")
        for line in (sub.get("output_log") or []):
            print(line, end="")

    seq_estimate = round(sum(s.get("elapsed", 0) for s in results), 1)
    print(f"\n[orchestrator] wall time: {wall_time}s  (sequential estimate: {seq_estimate}s)")

    return results


def _cleanup_subtask_files(subtask_defs: list[dict], trace: "RunTrace | None" = None):
    """Register subtask temp files as artifacts, then remove them."""
    for sub in subtask_defs:
        expanded = os.path.expanduser(sub["path"])
        if os.path.exists(expanded):
            if trace is not None:
                trace.log_artifact(expanded, artifact_type="subtask_temp")
            try:
                os.remove(expanded)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Main orchestration loop
# ---------------------------------------------------------------------------

def orchestrate(task: str, use_wiggum: bool = True):
    """
    Main entry point. Decomposes and coordinates multi-subtask runs,
    or delegates to agent.run() for single-focus tasks.
    """
    # Determine output path
    output_path = extract_path(task)
    if not output_path:
        from datetime import datetime as _dt

        from harness.config import ROOT as _ROOT
        _slug = re.sub(r"[^\w]+", "-", task.strip().lower())[:40].strip("-")
        _ts   = _dt.now().strftime("%Y%m%dT%H%M%S")
        _out  = _ROOT / "data" / "output"
        _out.mkdir(parents=True, exist_ok=True)
        output_path = str(_out / f"{_slug}-{_ts}.md")
        print(f"[orchestrator] output → {output_path}")

    workspace = os.path.dirname(os.path.expanduser(output_path))
    if workspace:
        os.makedirs(workspace, exist_ok=True)

    # Memory + planning
    memory = MemoryStore()
    memory_context = memory.get_context(task)
    if memory_context:
        print(f"[orchestrator] memory: {memory_context.count('**[')} observation(s)")
    else:
        print("[orchestrator] memory: no relevant history")

    print("[orchestrator] planning...")
    plan, _ = make_plan(task, memory_context)
    print(f"[orchestrator] plan: {plan.task_type} / {plan.complexity} / "
          f"{len(plan.subtasks)} subtask(s)")
    if plan.subtasks:
        for i, s in enumerate(plan.subtasks, 1):
            print(f"  {i}. {s}")

    # --- Simple task: no subtasks → delegate to agent ---
    if not plan.subtasks:
        print("[orchestrator] single-focus task — delegating to agent\n")
        from harness import agent as _agent_mod
        _agent_mod.run(task, use_wiggum=use_wiggum)
        return

    # --- Complex task: orchestrate subtasks ---
    trace = RunTrace(task=task, producer_model=ASSEMBLY_MODEL, evaluator_model=EVALUATOR_MODEL)
    trace.log_plan(plan.to_dict())
    trace.log_memory_hits(memory_context.count("**[") if memory_context else 0)
    trace.data["orchestrated"] = True
    trace.data["subtask_count"] = len(plan.subtasks)
    trace.data["parallel"] = True

    # Write plan record before execution so it's queryable even on crash
    plan_dict = {**plan.to_dict(), "subtasks": [s["desc"] if isinstance(s, dict) else s for s in plan.subtasks]}
    trace.log_plan_record(plan_dict, plan_type="orchestrator")

    # Propagate tracking IDs into subtask subprocesses for run lineage
    parent_env = {
        "HARNESS_PROJECT_ID":   trace.project_id,
        "HARNESS_SESSION_ID":   trace.session_id,
        "HARNESS_PARENT_RUN_ID": trace.run_id,
        "HARNESS_RUN_ID":       "",   # each subtask generates its own run_id
    }

    try:
        subtask_defs = _assign_paths(plan.subtasks, workspace)

        # Execute subtasks in parallel
        subtask_defs = _run_subtasks_parallel(subtask_defs, parent_env=parent_env)

        completed = [s for s in subtask_defs if s.get("content")]
        failed = [s for s in subtask_defs if not s.get("content")]
        print(f"\n[orchestrator] {len(completed)}/{len(subtask_defs)} subtasks produced output"
              + (f"  ({len(failed)} failed: {', '.join(s['desc'][:40] for s in failed)})" if failed else ""))

        if not completed:
            print("[error] all subtasks failed — aborting")
            trace.finish("ERROR")
            sys.exit(1)

        # Assemble final output
        print("\n[orchestrator] assembling final document...")
        content = assemble(task, completed, memory_context=memory_context)

        if not content.strip():
            print("[error] assembly produced empty content")
            trace.finish("ERROR")
            sys.exit(1)

        # Count constraint on assembled output
        expected_count = plan.expected_sections or extract_count_constraint(task)
        if expected_count is not None:
            actual_count = count_output_items(content)
            if actual_count != expected_count:
                print(f"[count check] expected {expected_count}, got {actual_count} — retrying assembly")
                content = synthesize_with_count(task, content, expected_count)

        print("\n" + content[:1000] + ("..." if len(content) > 1000 else "") + "\n")
        write_output(content, output_path, trace)

        # Wiggum verification on the final assembled output
        if use_wiggum:
            wiggum_trace = wiggum_loop(task, output_path)
            trace.log_wiggum(wiggum_trace)
            print(f"\n[wiggum] {wiggum_trace['final']} after {len(wiggum_trace['rounds'])} round(s)")
            for r in wiggum_trace["rounds"]:
                print(f"  round {r['round']}: score={r['score']}/10  passed={r['passed']}")
            final_status = wiggum_trace["final"]
        else:
            trace.finish("PASS")
            final_status = "PASS"

        # Store memory for the orchestrated run
        print("\n  [memory] compressing orchestrated run...")
        try:
            obs = memory.compress_and_store(
                task=task,
                task_type=plan.task_type,
                tool_calls=trace.data.get("tool_calls", []),
                output_content=content,
                output_lines=trace.data.get("output_lines"),
                output_bytes=trace.data.get("output_bytes"),
                output_path=trace.data.get("output_path"),
                wiggum_scores=[float(x) for x in trace.data.get("wiggum_scores") or [] if isinstance(x, (int, float))],
                final=final_status,
            )
            print(f"  [memory] stored: {obs['title']!r}")
        except Exception as e:
            print(f"  [memory] compression failed (non-fatal): {e}")

    except Exception as e:
        print(f"[error] orchestration failed: {e}")
        trace.finish("ERROR")
        raise
    finally:
        _cleanup_subtask_files(
            subtask_defs if 'subtask_defs' in dir() else [],
            trace=trace if 'trace' in dir() else None,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print('usage: python -m harness.orchestrator "<task>"')
        print('       python -m harness.orchestrator --no-wiggum "<task>"')
        sys.exit(1)

    no_wiggum = "--no-wiggum" in args
    task_args = [a for a in args if a != "--no-wiggum"]
    orchestrate(" ".join(task_args), use_wiggum=not no_wiggum)

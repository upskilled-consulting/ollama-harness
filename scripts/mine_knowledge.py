"""
mine_knowledge.py — build a per-task ground-truth knowledge base for eval_suite tasks.

For each eval task, runs agent.py with /deep to do thorough research against
authoritative sources, then saves the output to knowledge_base/{task_id}.md.

The knowledge base files are injected as file_context when eval_suite runs those
tasks, giving the producer verified facts instead of relying on DDGS snippets alone.

Usage:
    python mine_knowledge.py              # mine all tasks
    python mine_knowledge.py T_A T_B      # mine specific tasks
    python mine_knowledge.py --list       # show task topics
    python mine_knowledge.py --status     # show which KB files exist + age
"""

import os
import sys
import subprocess
import time
from datetime import datetime

KB_DIR  = os.path.join(os.path.dirname(__file__), "knowledge_base")
PYTHON  = sys.executable

# Mining tasks: deeper, source-anchored variants of the eval tasks.
# /deep forces MAX_SEARCH_ROUNDS and disables the novelty gate.
# Each task asks for authoritative implementation detail — the kind the eval
# tasks need but DDGS often can't provide in 2-3 rounds.
MINE_TASKS = {
    "T_A": {
        "desc": "context engineering techniques",
        "task": (
            "/deep Search for the top 5 context engineering techniques used in production "
            "LLM agents — include real library names, version numbers, actual API signatures "
            "(e.g. LangChain, LlamaIndex, Anthropic SDK), working code examples, and concrete "
            "production trade-offs. Save to {kb_path}"
        ),
    },
    "T_B": {
        "desc": "cost envelope management",
        "task": (
            "/deep Search for best practices for cost envelope management in production AI agents "
            "— include real token pricing, caching strategies (exact APIs), model routing patterns, "
            "budget enforcement code, and monitoring approaches with actual tools. Save to {kb_path}"
        ),
    },
    "T_C": {
        "desc": "multi-agent failure modes",
        "task": (
            "/deep Search for the 3 most common failure modes in multi-agent AI systems "
            "— include real incident examples, detection patterns, mitigation code, and "
            "specific framework behaviours (LangGraph, AutoGen, CrewAI). Save to {kb_path}"
        ),
    },
    "T_D": {
        "desc": "context window management strategies",
        "task": (
            "/deep Search for the top 3 context window management strategies for production "
            "LLM applications — include real chunking library APIs (LangChain, LlamaIndex), "
            "working RAG implementation code, summarisation with actual models, and "
            "benchmarked trade-offs. Save to {kb_path}"
        ),
    },
    "T_E": {
        "desc": "prompt injection defense",
        "task": (
            "/deep Search for best practices for prompt injection defense in production AI systems "
            "— include real defense tools (Rebuff, Guardrails AI, LangChain output parsers), "
            "working code examples, OWASP LLM Top 10 references, and detection/mitigation "
            "patterns used in production. Save to {kb_path}"
        ),
    },
}


def kb_path(task_id: str) -> str:
    return os.path.join(KB_DIR, f"{task_id}.md")


def mine_task(task_id: str) -> bool:
    """Run deep research for task_id and save to knowledge_base/{task_id}.md."""
    if task_id not in MINE_TASKS:
        print(f"[mine] unknown task id: {task_id}")
        return False

    os.makedirs(KB_DIR, exist_ok=True)
    out_path = kb_path(task_id)
    spec     = MINE_TASKS[task_id]
    task_str = spec["task"].format(kb_path=out_path)

    print(f"\n{'='*60}")
    print(f" Mining {task_id}: {spec['desc']}")
    print(f" Output: {out_path}")
    print(f"{'='*60}")

    start = time.time()
    result = subprocess.run(
        [PYTHON, "agent.py", "--no-wiggum", task_str],
        capture_output=False,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    elapsed = round(time.time() - start, 1)

    if result.returncode == 0 and os.path.exists(out_path):
        size = os.path.getsize(out_path)
        print(f"\n[mine] {task_id} done — {size} bytes in {elapsed}s")
        return True
    else:
        print(f"\n[mine] {task_id} FAILED (returncode={result.returncode}, elapsed={elapsed}s)")
        return False


def show_status():
    """Print which KB files exist and their age."""
    print(f"\n{'ID':<6} {'File':<30} {'Size':>8}  {'Age'}")
    print("-" * 60)
    for tid in MINE_TASKS:
        path = kb_path(tid)
        if os.path.exists(path):
            size  = os.path.getsize(path)
            mtime = os.path.getmtime(path)
            age   = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            print(f"{tid:<6} {os.path.basename(path):<30} {size:>8}  {age}")
        else:
            print(f"{tid:<6} {'(not mined)':<30} {'—':>8}")
    print()


def main():
    args = sys.argv[1:]

    if "--list" in args:
        for tid, spec in MINE_TASKS.items():
            print(f"  {tid}: {spec['desc']}")
        return

    if "--status" in args:
        show_status()
        return

    # Determine which tasks to mine
    requested = [a for a in args if a in MINE_TASKS]
    if not requested:
        requested = list(MINE_TASKS.keys())

    print(f"[mine_knowledge] mining {len(requested)} task(s): {', '.join(requested)}")
    results = {}
    for tid in requested:
        results[tid] = mine_task(tid)

    print(f"\n[mine_knowledge] summary:")
    for tid, ok in results.items():
        status = "OK" if ok else "FAILED"
        print(f"  {tid}: {status}")


if __name__ == "__main__":
    main()

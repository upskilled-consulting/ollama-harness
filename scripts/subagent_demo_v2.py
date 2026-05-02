"""
subagent_demo_v2.py — Harness self-analysis demo
Produces a portfolio in subagent-test-v2/ where every output is grounded in
real data files from this repo: autoresearch.tsv, runs.jsonl, bench results,
wiki docs, and source code.

Tasks are concrete and verifiable — the agent must read files and reason about
actual numbers, not summarize public literature.

Modes:
    --sequential   Submit to Flask queue (default); tasks run one at a time.
    --parallel     Submit via MCP HTTP server; up to MCP_MAX_CONCURRENCY run simultaneously.

MCP parallel mode requires mcp_server.py running:
    MCP_MAX_CONCURRENCY=3 python mcp_server.py --http
"""

import argparse
import asyncio
import json
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

from render_html import render_dir

SERVER_URL = "http://localhost:8765"
MCP_URL    = "http://localhost:8766"
OUT = Path("subagent-test-v2")
OUT.mkdir(exist_ok=True)

TASKS = [
    (
        "autoresearch-analysis",
        (
            "Read autoresearch.tsv in the current directory. Analyze the experiment history: "
            "which changes were kept vs discarded, what the score trajectory looks like, "
            "what types of changes tended to improve the score and which didn't. "
            "Identify any patterns in the discard reasons. "
            "If autoresearch.tsv is sparse or missing, note that and analyze what's available. "
            f"Save a detailed analytical report to {OUT}/autoresearch-analysis.md"
        ),
    ),
    (
        "eval-score-trends",
        (
            "Read runs.jsonl in the current directory. For every run that has a wiggum_eval_log entry, "
            "extract the task name, composite score, per-dimension scores (relevance, completeness, "
            "depth, specificity, structure), and any evaluator feedback or issues. "
            "Identify which eval tasks score highest and lowest, which dimensions are consistently weak, "
            "and what the evaluator feedback reveals about output quality patterns. "
            "Also read bench_vllm_results.jsonl if present for model comparison data. "
            f"Save a trends report to {OUT}/eval-score-trends.md"
        ),
    ),
    (
        "harness-architecture",
        (
            "Read wiki/architecture.md, wiki/pipeline.md, wiki/log.md, and wiki/skills.md "
            "in the current directory. Also read skills.py to see the actual skill registry. "
            "Synthesize an accurate characterization of how this harness works: "
            "the agent loop, skill dispatch, planner, memory, eval pipeline, and server queue. "
            "Note what's well-designed and where the seams show. Be specific — cite actual "
            "function names, file names, and design decisions visible in the source. "
            f"Save to {OUT}/harness-architecture.md"
        ),
    ),
    (
        "new-eval-tasks",
        (
            "Read wiki/eval-framework.md, wiki/experiments.md, and autoresearch.tsv. "
            "The current eval tasks are T_A through T_E (context engineering, cost management, "
            "failure modes, context window, prompt injection). "
            "Propose 3 new eval tasks — T_F, T_G, T_H — that would stress-test meaningfully "
            "different failure modes not covered by the existing suite. "
            "For each: write the task prompt as it would appear in eval_suite.py, "
            "explain what failure mode it targets and why the existing suite misses it, "
            "and describe what a high-scoring vs low-scoring response would look like. "
            f"Save to {OUT}/new-eval-tasks.md"
        ),
    ),
    (
        "synthesis-instruction-history",
        (
            "Read wiki/synthesis-instructions.md and autoresearch_program.md in the current directory. "
            "Also read the current SYNTH_INSTRUCTION value from agent.py "
            "(it's between the markers # AUTORESEARCH:SYNTH_INSTRUCTION:BEGIN and :END). "
            "Trace how the synthesis instruction has evolved: what it started as, "
            "what changes were tried, what the current version says, and what the autoresearch "
            "program has learned about what makes a good synthesis instruction for this evaluator. "
            "Assess whether the current instruction is well-tuned or has obvious remaining gaps. "
            f"Save to {OUT}/synthesis-instruction-history.md"
        ),
    ),
]
# Landing page is now generated deterministically by render_html.py after all
# tasks complete — no LLM involvement in rendering.


def post_json(path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{SERVER_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def get_json(path: str) -> dict:
    with urllib.request.urlopen(f"{SERVER_URL}{path}", timeout=10) as resp:
        return json.loads(resp.read())


def check_server() -> bool:
    try:
        get_json("/api/queue")
        return True
    except Exception:
        return False


def wait_for_idle(poll_interval: int = 5, timeout: int = 3600) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            active = get_json("/api/runs")
            queue = get_json("/api/queue")
            if not active.get("runs") and not queue.get("items"):
                return True
        except Exception:
            pass
        time.sleep(poll_interval)
    return False


# ---------------------------------------------------------------------------
# Sequential mode — Flask queue
# ---------------------------------------------------------------------------

def run_sequential():
    if not check_server():
        print(f"ERROR: server not reachable at {SERVER_URL}. Start with: python server.py")
        return False

    try:
        active = get_json("/api/runs")
        if active.get("runs"):
            print("Active run detected — tasks will queue behind it.")
    except Exception:
        pass

    print(f"Enqueueing {len(TASKS)} tasks...")
    for i, (label, task) in enumerate(TASKS, 1):
        resp = post_json("/api/queue", {"task": task})
        pos = resp.get("position", i)
        qid = resp.get("id", "?")
        print(f"  [{i}/{len(TASKS)}] {label} → position {pos} (id={qid})")

    print(f"\nAll tasks queued. Watching at {SERVER_URL} ...")
    print("Waiting for completion (Ctrl-C to stop watching)...\n")

    try:
        return wait_for_idle(poll_interval=5)
    except KeyboardInterrupt:
        print("\nStopped watching — tasks continue in server.")
        return False


# ---------------------------------------------------------------------------
# Parallel mode — MCP HTTP server
# ---------------------------------------------------------------------------

_MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

def _mcp_post(payload: dict, session_id: str = "", timeout: int = 30) -> tuple[dict, str]:
    """POST to MCP endpoint, return (parsed_body, session_id)."""
    headers = dict(_MCP_HEADERS)
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    req = urllib.request.Request(
        f"{MCP_URL}/mcp",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        sid = resp.headers.get("Mcp-Session-Id", session_id)
        raw = resp.read()
        text = raw.decode("utf-8", errors="replace")
        # SSE envelope: find first "data: ..." line
        for line in text.splitlines():
            if line.startswith("data:"):
                text = line[5:].strip()
                break
        return json.loads(text), sid


def _mcp_open_session() -> str:
    """Run MCP initialize + initialized handshake, return session_id."""
    import uuid
    body, sid = _mcp_post({
        "jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": "initialize",
        "params": {"protocolVersion": "2024-11-05",
                   "clientInfo": {"name": "subagent_demo", "version": "1.0"},
                   "capabilities": {}},
    })
    # Send initialized notification (no response expected)
    try:
        _mcp_post({"jsonrpc": "2.0", "method": "notifications/initialized"}, session_id=sid, timeout=5)
    except Exception:
        pass
    return sid


def _mcp_call_tool(tool: str, arguments: dict, timeout: int = 1800) -> str:
    """Open a session then call a tool on the MCP streamable-http server."""
    import uuid
    sid = _mcp_open_session()
    body, _ = _mcp_post({
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }, session_id=sid, timeout=timeout)
    # MCP response: {"result": {"content": [{"type": "text", "text": "..."}]}}
    content = body.get("result", {}).get("content", [])
    return content[0].get("text", "[no output]") if content else str(body)


def _check_mcp_server() -> bool:
    try:
        _mcp_open_session()
        return True
    except Exception:
        return False


def _run_one_mcp(label: str, task: str, idx: int, total: int) -> tuple[str, bool]:
    print(f"  [start] [{idx}/{total}] {label}")
    t0 = time.time()
    try:
        result = _mcp_call_tool("run_task", {"task": task})
        elapsed = time.time() - t0
        ok = not result.startswith("[error]")
        status = "OK" if ok else "FAIL"
        print(f"  [{status}]  [{idx}/{total}] {label}  ({elapsed:.0f}s)")
        return label, ok
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  [FAIL]  [{idx}/{total}] {label}  ({elapsed:.0f}s) — {e}")
        return label, False


def run_parallel(max_workers: int = 3) -> bool:
    if not _check_mcp_server():
        print(f"ERROR: MCP server not reachable at {MCP_URL}.")
        print(f"Start with:  MCP_MAX_CONCURRENCY={max_workers} python mcp_server.py --http")
        return False

    print(f"Firing {len(TASKS)} tasks in parallel (max_workers={max_workers}) via MCP...")
    total = len(TASKS)
    failures = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_run_one_mcp, label, task, i, total): label
            for i, (label, task) in enumerate(TASKS, 1)
        }
        for fut in as_completed(futures):
            label, ok = fut.result()
            if not ok:
                failures.append(label)

    if failures:
        print(f"\nFailed: {', '.join(failures)}")
    return len(failures) == 0


# ---------------------------------------------------------------------------
# Shared finish step
# ---------------------------------------------------------------------------

def finish():
    md_files = sorted(OUT.glob("*.md"))
    if md_files:
        print(f"\nMarkdown outputs in {OUT}/:")
        for f in md_files:
            print(f"  {f.name} ({f.stat().st_size:,} bytes)")

    print(f"\n[render] converting markdown → HTML...")
    landing = render_dir(
        OUT,
        title="Harness Self-Analysis",
        subtitle="A local LLM research system examining itself",
    )
    if landing and landing.exists():
        print(f"\nLanding page: {landing.resolve()}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Harness self-analysis subagent demo")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--sequential", action="store_true",
                       help="Submit to Flask queue (default, one at a time)")
    group.add_argument("--parallel", action="store_true",
                       help="Submit via MCP HTTP server (concurrent execution)")
    parser.add_argument("--workers", type=int, default=8,
                        help="Max concurrent workers in --parallel mode (default: 3)")
    args = parser.parse_args()

    print(f"subagent_demo_v2.py — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Output directory: {OUT.resolve()}")
    mode = "parallel" if args.parallel else "sequential"
    print(f"Mode: {mode}\n")

    if args.parallel:
        done = run_parallel(max_workers=args.workers)
    else:
        done = run_sequential()

    if done:
        finish()
    else:
        print("Tasks did not complete — skipping render.")


if __name__ == "__main__":
    main()

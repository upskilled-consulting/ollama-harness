"""
subagent_demo.py — Sequential agentic research demo
Produces a portfolio in subagent-test/ covering "The State of Agentic AI in 2026"

Submits all tasks to the server queue so they appear in the dashboard and are
processed sequentially by the server's runner. Requires server running on SERVER_URL.
"""

import time
import json
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

SERVER_URL = "http://localhost:8765"
OUT = Path("subagent-test")
OUT.mkdir(exist_ok=True)

TASKS = [
    (
        "agentic-architectures",
        (
            "Research the current landscape of agentic AI architectures in 2026. Cover: "
            "ReAct, plan-and-execute, reflexion, and multi-step tool-use patterns. "
            "Compare their strengths and failure modes. "
            f"Save your synthesis to {OUT}/agentic-architectures.md"
        ),
    ),
    (
        "eval-frameworks",
        (
            "Research LLM and agent evaluation frameworks prominent in 2025-2026. "
            "Cover: LMSYS Chatbot Arena, HELM, BIG-Bench, AgentBench, and emerging "
            "task-specific harnesses. Discuss what metrics matter and what they miss. "
            f"Save your synthesis to {OUT}/eval-frameworks.md"
        ),
    ),
    (
        "agent-memory-context",
        (
            "Research how AI agents manage memory and long-horizon context in 2026. "
            "Cover: RAG, vector stores, episodic memory, working-memory compression, "
            "and context-window scaling. Discuss tradeoffs between retrieval and in-context approaches. "
            f"Save your synthesis to {OUT}/agent-memory-context.md"
        ),
    ),
    (
        "local-llm-inference",
        (
            "Research the state of local LLM inference in 2026. Cover: quantization (GGUF, AWQ, GPTQ), "
            "serving runtimes (Ollama, vLLM, llama.cpp, TGI), hardware requirements, "
            "and the privacy/cost tradeoffs vs cloud APIs. "
            f"Save your synthesis to {OUT}/local-llm-inference.md"
        ),
    ),
    (
        "multi-agent-coordination",
        (
            "Research multi-agent coordination patterns in 2026. Cover: orchestrator-worker hierarchies, "
            "peer-to-peer agent messaging, shared memory buses, and debate/critic patterns. "
            "Discuss real deployments: AutoGen, CrewAI, LangGraph, and custom harnesses. "
            f"Save your synthesis to {OUT}/multi-agent-coordination.md"
        ),
    ),
    (
        "landing-page",
        (
            "Generate a self-contained HTML landing page (no external dependencies, all CSS inline or in a <style> block) "
            "summarizing the five research reports in the subagent-test/ folder: "
            "agentic-architectures.md, eval-frameworks.md, agent-memory-context.md, "
            "local-llm-inference.md, multi-agent-coordination.md. "
            "Read those files first so the synopses are accurate. "
            "Design requirements: dark background (#0d1117), accent color #58a6ff, "
            "clean sans-serif font, hero section with title 'The State of Agentic AI in 2026' and "
            "a one-paragraph executive summary, a card grid (5 cards) each with report title, "
            "2-3 sentence synopsis, and an <a> link to the .md file, "
            "a footer crediting this local LLM research harness as the engine. "
            "Add a small JS toggle so each card expands to show the first 400 chars of the report on click. "
            f"Save to {OUT}/index.html"
        ),
    ),
]


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


def enqueue(task: str) -> dict:
    return post_json("/api/queue", {"task": task})


def wait_for_idle(poll_interval: int = 5, timeout: int = 3600) -> bool:
    """Wait until both the active run and queue are empty."""
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


def main():
    print(f"subagent_demo.py — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Output directory: {OUT.resolve()}")
    print(f"Server: {SERVER_URL}")

    if not check_server():
        print(f"\nERROR: server not reachable at {SERVER_URL}. Start it with: python server.py")
        return

    # Drain any active run first so queue positions are accurate
    print("\nChecking for active runs...")
    try:
        active = get_json("/api/runs")
        if active.get("runs"):
            print(f"  Active run detected — tasks will queue behind it.")
    except Exception:
        pass

    print(f"\nEnqueueing {len(TASKS)} tasks...")
    ids = []
    for i, (label, task) in enumerate(TASKS, 1):
        resp = enqueue(task)
        qid = resp.get("id", "?")
        pos = resp.get("position", i)
        ids.append(qid)
        print(f"  [{i}/{len(TASKS)}] {label} → queued at position {pos} (id={qid})")

    print(f"\nAll tasks queued. Watching dashboard at {SERVER_URL} ...")
    print("Waiting for completion (Ctrl-C to stop watching, tasks continue in server)...\n")

    try:
        done = wait_for_idle(poll_interval=5)
    except KeyboardInterrupt:
        print("\nStopped watching — tasks are still running in the server.")
        return

    if done:
        print("All tasks complete.")
        files = list(OUT.glob("*.md"))
        if files:
            print(f"\nOutputs in {OUT}/:")
            for f in sorted(files):
                size = f.stat().st_size
                print(f"  {f.name} ({size:,} bytes)")
        landing = OUT / "index.html"
        if landing.exists():
            print(f"\nLanding page: {landing.resolve()}")
    else:
        print("Timed out waiting — check the dashboard for status.")


if __name__ == "__main__":
    main()

"""
mcp_server.py — MCP server exposing the harness as a callable agent.

Makes the harness interoperable with any MCP-compatible client:
  - Claude Code (add to .mcp.json or mcp_config.json)
  - External orchestrators via streamable-http
  - Other harness instances routing subtasks cross-team

Tools exposed:
  run_task(task)         — run agent.py, return markdown output content
  run_orchestrated(task) — run orchestrator.py for multi-subtask tasks
  get_run(run_id)        — fetch a runs.jsonl record by run_id

Resources exposed:
  runs://recent          — last N runs summary (scores, status, task preview)

Transports:
  stdio  (default) — for Claude Code / local MCP clients
    python -m harness.mcp_server
  streamable-http  — for remote cross-team dispatch
    python -m harness.mcp_server --http [--port 8766] [--host 0.0.0.0]
  sse              — legacy SSE transport
    python -m harness.mcp_server --sse

Claude Code config (.mcp.json or ~/.claude/mcp_config.json):
  {
    "mcpServers": {
      "harness": {
        "command": "python",
        "args": ["C:/Users/nicho/Desktop/harness-engineering/mcp_server.py"],
        "cwd": "C:/Users/nicho/Desktop/harness-engineering"
      }
    }
  }

Remote dispatch via HARNESS_MCP_ENDPOINTS:
  HARNESS_MCP_ENDPOINTS='{"security":  "http://team-b-harness:8766/mcp"}'
  python orchestrator.py "Research X (security aspects) and Y and save to out.md"
  → "security aspects" subtask dispatched to team-b-harness via MCP

Environment:
  MCP_SERVER_PORT   — HTTP port (default: 8766)
  MCP_SERVER_HOST   — HTTP host (default: 127.0.0.1)
  MCP_RECENT_RUNS   — number of recent runs to include in runs://recent (default: 10)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

from mcp.server.fastmcp import FastMCP

from harness.config import ROOT as _cfg_ROOT
from harness.security import check_output_path, scan_for_injection


def _build_agent_cmd(script, task: str) -> list:
    """Build subprocess command: -m harness.agent or -m harness.orchestrator."""
    if script is None or "agent" in str(script):
        return [sys.executable, "-u", "-m", "harness.agent", task]
    return [sys.executable, "-u", "-m", "harness.orchestrator", task]


_BASE_DIR = str(_cfg_ROOT)
_AGENT_SCRIPT = None  # use -m harness.agent
_ORCH_SCRIPT  = None  # use -m harness.orchestrator
from harness.config import RUNS_FILE as _RUNS_FILE

_RUNS_PATH    = str(_RUNS_FILE)
from harness.config import DATA_DIR as _DATA_DIR

_MCP_LOG_PATH = str(_DATA_DIR / "mcp_tasks.jsonl")
_RECENT_N     = int(os.environ.get("MCP_RECENT_RUNS", 10))
_log_lock     = threading.Lock()

# Security limits
_TASK_MAX_CHARS   = int(os.environ.get("MCP_TASK_MAX_CHARS", 2000))
_MAX_CONCURRENCY  = int(os.environ.get("MCP_MAX_CONCURRENCY", 2))
_API_KEY          = os.environ.get("MCP_API_KEY", "")      # empty = no auth required
_semaphore        = threading.Semaphore(_MAX_CONCURRENCY)


def _validate_task(task: str) -> tuple[bool, str]:
    """
    Gate all MCP tool inputs: length cap, UNC block, injection scan, output path check.
    Returns (ok, error_message).
    """
    if len(task) > _TASK_MAX_CHARS:
        return False, f"task too long: {len(task)} chars (max {_TASK_MAX_CHARS})"

    # Block UNC paths (\\server\share) which could reach network shares
    if "\\\\" in task or task.lstrip().startswith("//"):
        return False, "UNC/network paths are not permitted in task strings"

    clean, matches = scan_for_injection(task, source="mcp_task")
    if not clean:
        return False, f"task rejected (injection pattern): {matches[0]}"

    # Validate any output path embedded in the task
    import re as _re
    m = _re.search(
        r"(~[\w/\\.\\-]+\.md|[A-Za-z]:[\w/\\.\-]+\.md|/[\w/.\-]+\.md|[\w./\\\-]+\.md)",
        task,
    )
    if m:
        ok, reason = check_output_path(m.group(1))
        if not ok:
            return False, f"output path rejected: {reason}"

    return True, ""


def _check_api_key(provided: str) -> bool:
    """Return True if auth is not configured or the key matches."""
    if not _API_KEY:
        return True
    return provided == _API_KEY

mcp = FastMCP(
    "harness-engineering",
    instructions=(
        "Research and synthesis agent harness. "
        "Use run_task() to execute a research task and get back a markdown document. "
        "Include a .md output path in the task string (e.g. 'save to ~/Desktop/out.md'). "
        "Use get_run() to retrieve details about a previous run by run_id."
    ),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_temp_path(suffix: str = ".md") -> str:
    """Generate a temp output path if the task doesn't specify one."""
    fd, path = tempfile.mkstemp(suffix=suffix, dir=_BASE_DIR)
    os.close(fd)
    return path


def _ensure_output_path(task: str) -> tuple[str, str]:
    """
    Return (task_with_path, output_path).
    Injects a temp path if none is present in the task string.
    """
    import re
    m = re.search(r"(~[\w/\\.\\-]+\.md|[A-Za-z]:[\w/\\.\-]+\.md|/[\w/.\-]+\.md|[\w./\\\-]+\.md)", task)
    if m:
        return task, os.path.expanduser(m.group(1))
    tmp = _make_temp_path()
    return f"{task} save to {tmp}", tmp


def _log_event(task_id: str, label: str, event: str, text: str = "") -> None:
    """Append one event to mcp_tasks.jsonl (thread-safe)."""
    entry = json.dumps({
        "ts":      time.strftime("%Y-%m-%dT%H:%M:%S"),
        "task_id": task_id,
        "label":   label,
        "event":   event,
        "text":    text,
    })
    with _log_lock:
        with open(_MCP_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(entry + "\n")


def _run_subprocess(script: "str | None", task: str, timeout: int = 600,
                    task_id: str = "", label: str = "") -> dict:
    """Run agent.py or orchestrator.py, stream stdout to mcp_tasks.jsonl."""
    import re as _re
    task_with_path, output_path = _ensure_output_path(task)
    t0 = time.time()

    _log_event(task_id, label, "start", task[:120])

    _env = os.environ.copy()
    _env["PYTHONUNBUFFERED"] = "1"
    _env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        _build_agent_cmd(script, task_with_path),
        cwd=_BASE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_env,
    )

    stdout_lines: list[str] = []
    run_id = ""
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            stdout_lines.append(line)
            # Only log agent status lines — skip synthesized content
            if line.startswith("["):
                _log_event(task_id, label, "line", line)
            if not run_id:
                m = _re.search(r"run_id[=:\s]+([0-9T Z\-a-f]+)", line)
                if m:
                    run_id = m.group(1).strip()
        proc.wait(timeout=max(1, timeout - int(time.time() - t0)))
    except subprocess.TimeoutExpired:
        proc.kill()
        _log_event(task_id, label, "fail", "timeout")

    stderr_tail = (proc.stderr.read() if proc.stderr else "")[-500:]
    elapsed = round(time.time() - t0, 1)

    content = ""
    expanded = os.path.expanduser(output_path)
    if os.path.exists(expanded):
        with open(expanded, encoding="utf-8") as f:
            content = f.read()

    ok = proc.returncode == 0 and bool(content.strip())
    _log_event(task_id, label, "done" if ok else "fail",
               f"elapsed={elapsed}s rc={proc.returncode}")

    stdout_text = "\n".join(stdout_lines)
    return {
        "content": content,
        "ok":      ok,
        "run_id":  run_id,
        "elapsed": elapsed,
        "stdout":  stdout_text[-2000:],
        "stderr":  stderr_tail,
    }


def _load_recent_runs(n: int = _RECENT_N) -> list[dict]:
    runs = []
    try:
        with open(_RUNS_PATH, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        runs.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except FileNotFoundError:
        pass
    return runs[-n:]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def run_task(task: str, api_key: str = "") -> str:
    """
    Run a research or synthesis task through the harness agent pipeline.

    The task string should describe what to research and where to save the output,
    e.g.: "Search for best practices for prompt injection defense and save to ~/Desktop/out.md"

    If no output path is included, a temporary path is used and the content is
    returned directly.

    api_key: required when MCP_API_KEY is set on the server.

    Returns the markdown document content produced by the agent.
    """
    if not _check_api_key(api_key):
        return "[error] invalid or missing api_key"
    ok, err = _validate_task(task)
    if not ok:
        return f"[error] {err}"

    import uuid as _uuid
    task_id = _uuid.uuid4().hex[:8]
    _semaphore.acquire(blocking=True)
    try:
        result = _run_subprocess(_AGENT_SCRIPT, task, task_id=task_id, label="run_task")
    finally:
        _semaphore.release()

    if not result["ok"]:
        error_hint = result["stderr"] or result["stdout"] or "unknown error"
        return f"[error] Agent run failed after {result['elapsed']}s.\n{error_hint}"
    return result["content"]


@mcp.tool()
def run_orchestrated(task: str, api_key: str = "") -> str:
    """
    Run a complex multi-subtask research task through the orchestrator.

    Use this for tasks that span multiple topics or require cross-referencing
    multiple research threads, e.g.:
    "Research X and Y and Z, synthesize into a guide and save to ~/Desktop/out.md"

    The orchestrator decomposes the task into parallel subtasks, assembles the
    results, and runs wiggum verification on the final output.

    api_key: required when MCP_API_KEY is set on the server.

    Returns the assembled markdown document.
    """
    if not _check_api_key(api_key):
        return "[error] invalid or missing api_key"
    ok, err = _validate_task(task)
    if not ok:
        return f"[error] {err}"

    import uuid as _uuid
    task_id = _uuid.uuid4().hex[:8]
    _semaphore.acquire(blocking=True)
    try:
        result = _run_subprocess(_ORCH_SCRIPT, task, timeout=1800,
                                 task_id=task_id, label="run_orchestrated")
    finally:
        _semaphore.release()

    if not result["ok"]:
        error_hint = result["stderr"] or result["stdout"] or "unknown error"
        return f"[error] Orchestration failed after {result['elapsed']}s.\n{error_hint}"
    return result["content"]


@mcp.tool()
def get_run(run_id: str) -> str:
    """
    Retrieve a run record from runs.jsonl by run_id.

    Returns a JSON summary of the run: task, scores, status, duration, model info.
    """
    try:
        with open(_RUNS_PATH, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    if r.get("run_id") == run_id:
                        summary = {
                            "run_id":        r.get("run_id"),
                            "task":          r.get("task", "")[:200],
                            "final":         r.get("final"),
                            "wiggum_scores": r.get("wiggum_scores", []),
                            "output_bytes":  r.get("output_bytes"),
                            "run_duration_s": r.get("run_duration_s"),
                            "producer_model": r.get("producer_model"),
                            "task_type":     r.get("task_type"),
                            "timestamp":     r.get("timestamp"),
                        }
                        return json.dumps(summary, indent=2)
                except json.JSONDecodeError:
                    pass
    except FileNotFoundError:
        pass
    return json.dumps({"error": f"run_id {run_id!r} not found"})


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@mcp.resource("runs://recent")
def recent_runs() -> str:
    """Summary of the most recent agent runs: task, score, status, duration."""
    runs = _load_recent_runs()
    if not runs:
        return "No runs found."
    lines = [f"Recent {len(runs)} run(s):\n"]
    for r in reversed(runs):
        scores = r.get("wiggum_scores", [])
        score_str = f"  score={scores[-1]}" if scores else "  no-wiggum"
        lines.append(
            f"  [{r.get('timestamp','')[:16]}] {r.get('final','?'):4s}{score_str}"
            f"  {r.get('run_duration_s',0):.0f}s  {r.get('task','')[:80]}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Harness MCP server")
    parser.add_argument("--http",   action="store_true", help="Streamable HTTP transport")
    parser.add_argument("--sse",    action="store_true", help="Legacy SSE transport")
    parser.add_argument("--port",   type=int, default=int(os.environ.get("MCP_SERVER_PORT", 8766)))
    parser.add_argument("--host",   default=os.environ.get("MCP_SERVER_HOST", "127.0.0.1"))
    args = parser.parse_args()

    if args.http:
        import uvicorn
        print(f"[mcp_server] streamable-http on {args.host}:{args.port}")
        uvicorn.run(mcp.streamable_http_app(), host=args.host, port=args.port)
    elif args.sse:
        import uvicorn
        print(f"[mcp_server] SSE on {args.host}:{args.port}")
        uvicorn.run(mcp.sse_app(), host=args.host, port=args.port)
    else:
        print("[mcp_server] stdio transport (for Claude Code / local clients)")
        mcp.run(transport="stdio")

"""
harness/mcp_dispatch.py — MCP client for cross-agent subtask dispatch.

Used by orchestrator.py to route subtasks to remote MCP agents instead of
spawning a local subprocess. Enables cross-team interoperability: a subtask
that matches a keyword pattern in HARNESS_MCP_ENDPOINTS is dispatched to the
corresponding remote harness (or any MCP-compatible agent) instead of running
locally.

Configuration (set in env or .env):
  HARNESS_MCP_ENDPOINTS — JSON dict mapping keyword patterns to MCP endpoints:
    {"security": "http://team-security-harness:8766/mcp",
     "finance":  "http://team-finance-harness:8766/mcp"}

  Patterns are matched case-insensitively against the subtask string.
  First match wins. Local subprocess is used if no pattern matches.

Usage (module):
  from harness.mcp_dispatch import route_subtask, resolve_endpoint

  endpoint = resolve_endpoint(task_str)   # None if local
  if endpoint:
      result = route_subtask(task_str, endpoint)
      # result: {"content": str, "ok": bool, "error": str|None, "elapsed": float}
"""

from __future__ import annotations

import asyncio
import json
import os
import time

try:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False


# ---------------------------------------------------------------------------
# Endpoint resolution
# ---------------------------------------------------------------------------

def _load_endpoints() -> dict[str, str]:
    """Load HARNESS_MCP_ENDPOINTS from env. Returns {} on parse error."""
    raw = os.environ.get("HARNESS_MCP_ENDPOINTS", "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        print(f"  [mcp_dispatch] warn: HARNESS_MCP_ENDPOINTS is not valid JSON — ignoring")
        return {}


def resolve_endpoint(task: str) -> str | None:
    """
    Return the MCP endpoint URL for a task string, or None if local dispatch.
    Matches patterns from HARNESS_MCP_ENDPOINTS case-insensitively (first match wins).
    """
    endpoints = _load_endpoints()
    task_lower = task.lower()
    for pattern, url in endpoints.items():
        if pattern.lower() in task_lower:
            return url
    return None


# ---------------------------------------------------------------------------
# Async MCP call
# ---------------------------------------------------------------------------

async def _call_run_task(endpoint: str, task: str) -> dict:
    """Async: connect to remote MCP server, call run_task, return content."""
    async with streamablehttp_client(endpoint) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Verify the remote server has run_task
            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            if "run_task" not in tool_names:
                return {
                    "content": "",
                    "ok":      False,
                    "error":   f"Remote server at {endpoint} has no run_task tool. Available: {tool_names}",
                }

            result = await session.call_tool("run_task", {"task": task})
            content = "\n".join(
                c.text for c in result.content if hasattr(c, "text")
            ).strip()

            return {
                "content": content,
                "ok":      bool(content),
                "error":   None,
            }


# ---------------------------------------------------------------------------
# Public sync API
# ---------------------------------------------------------------------------

def route_subtask(task: str, endpoint: str) -> dict:
    """
    Dispatch a subtask to a remote MCP agent synchronously.

    Returns:
        {"content": str, "ok": bool, "error": str|None, "elapsed": float}

    Falls back gracefully: returns ok=False with error message if anything
    fails, so orchestrator can fall through to local subprocess.
    """
    if not _MCP_AVAILABLE:
        return {
            "content": "",
            "ok":      False,
            "error":   "mcp package not installed — pip install mcp",
            "elapsed": 0.0,
        }

    t0 = time.time()
    print(f"  [mcp_dispatch] routing to {endpoint}")
    try:
        result = asyncio.run(_call_run_task(endpoint, task))
        result["elapsed"] = round(time.time() - t0, 1)
        status = "OK" if result["ok"] else "FAILED"
        print(f"  [mcp_dispatch] {status} ({result['elapsed']}s)  "
              f"{len(result.get('content',''))} chars")
        return result
    except Exception as e:
        elapsed = round(time.time() - t0, 1)
        print(f"  [mcp_dispatch] error: {e}")
        return {
            "content": "",
            "ok":      False,
            "error":   str(e),
            "elapsed": elapsed,
        }

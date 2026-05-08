"""GET /api/mcp/log — MCP task log.  GET /api/mcp/tools — registered tool manifest."""

import json

from fastapi import APIRouter

from harness.config import LEGACY_MCP_LOG, MCP_LOG

router = APIRouter(tags=["mcp"])

_TOOLS = [
    {
        "name": "run_task",
        "description": "Run a research or synthesis task through the harness agent pipeline. Include a .md output path in the task string.",
        "parameters": [
            {"name": "task",    "type": "string", "required": True},
            {"name": "api_key", "type": "string", "required": False},
        ],
    },
    {
        "name": "run_orchestrated",
        "description": "Run a complex multi-subtask research task through the orchestrator. Decomposes into parallel subtasks.",
        "parameters": [
            {"name": "task",    "type": "string", "required": True},
            {"name": "api_key", "type": "string", "required": False},
        ],
    },
    {
        "name": "get_run",
        "description": "Retrieve a run record from runs.jsonl by run_id. Returns JSON summary of task, scores, status, and duration.",
        "parameters": [
            {"name": "run_id", "type": "string", "required": True},
        ],
    },
]


@router.get("/tools")
async def mcp_tools():
    return _TOOLS


@router.get("/log")
async def mcp_log(limit: int = 200):
    seen: set[str] = set()
    records: list[dict] = []
    for path in (MCP_LOG, LEGACY_MCP_LOG):
        if not path.exists():
            continue
        for line in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                key = f"{r.get('ts','')}{r.get('task_id','')}{r.get('label','')}"
                if key not in seen:
                    seen.add(key)
                    records.append(r)
            except json.JSONDecodeError:
                pass
        if len(records) >= limit:
            break
    return records[:limit]

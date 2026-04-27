"""GET /api/mcp/log — MCP task log."""

import json
from fastapi import APIRouter
from harness.config import MCP_LOG

router = APIRouter(tags=["mcp"])


@router.get("/log")
async def mcp_log(limit: int = 100):
    if not MCP_LOG.exists():
        return []
    lines = MCP_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    records = []
    for line in reversed(lines):
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        if len(records) >= limit:
            break
    return records

"""GET /api/mcp/log — MCP task log."""

import json

from fastapi import APIRouter

from harness.config import LEGACY_MCP_LOG, MCP_LOG

router = APIRouter(tags=["mcp"])


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

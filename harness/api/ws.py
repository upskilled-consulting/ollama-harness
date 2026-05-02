"""
WebSocket endpoint — streams live agent stdout to the dashboard.

Replaces the SSE polling pattern in the old server.py with a proper
bidirectional WebSocket. The dashboard connects at /ws/runs and receives
newline-delimited JSON events as they're emitted by running agents.
"""

import asyncio
import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from harness.config import RUNS_FILE

router = APIRouter(tags=["websocket"])

_connections: set[WebSocket] = set()


async def _tail_runs(last_pos: int = 0) -> AsyncGenerator[dict, None]:
    """Yield new run records appended to runs.jsonl since last_pos."""
    while True:
        await asyncio.sleep(1.0)
        if not RUNS_FILE.exists():
            continue
        try:
            text = RUNS_FILE.read_text(encoding="utf-8")
            new_text = text[last_pos:]
            last_pos = len(text)
            for line in new_text.splitlines():
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        pass
        except OSError:
            pass


@router.websocket("/ws/runs")
async def ws_runs(ws: WebSocket):
    await ws.accept()
    _connections.add(ws)
    try:
        async for record in _tail_runs():
            await ws.send_json(record)
    except WebSocketDisconnect:
        pass
    finally:
        _connections.discard(ws)


async def broadcast(event: dict) -> None:
    """Push an event to all connected dashboard clients."""
    dead: set[WebSocket] = set()
    for ws in _connections:
        try:
            await ws.send_json(event)
        except Exception:
            dead.add(ws)
    _connections.difference_update(dead)

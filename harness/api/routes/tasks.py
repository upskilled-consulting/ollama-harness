"""POST /api/tasks — submit a task to the agent queue."""

import asyncio
import uuid

from fastapi import APIRouter, BackgroundTasks

from harness.schema import QueueItem, TaskRequest

router = APIRouter(tags=["tasks"])

# In-memory queue — replace with SQLite-backed queue for persistence
_queue: list[QueueItem] = []
_queue_lock = asyncio.Lock()


async def _run_task(item: QueueItem, request: TaskRequest) -> None:
    import sys

    from harness.config import ROOT

    async with _queue_lock:
        item.status = "running"

    cmd = [sys.executable, str(ROOT / "oh.py"), request.task]
    if request.producer_model:
        cmd += ["--producer", request.producer_model]
    if request.no_wiggum:
        cmd.append("--no-wiggum")

    proc = await asyncio.create_subprocess_exec(*cmd, cwd=str(ROOT))
    await proc.wait()

    async with _queue_lock:
        item.status = "done" if proc.returncode == 0 else "error"


@router.post("/tasks", status_code=202)
async def submit_task(request: TaskRequest, background: BackgroundTasks):
    item = QueueItem(item_id=str(uuid.uuid4()), task=request.task)
    async with _queue_lock:
        _queue.append(item)
    background.add_task(_run_task, item, request)
    return {"item_id": item.item_id, "status": "pending"}



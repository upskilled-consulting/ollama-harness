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
    async with _queue_lock:
        item.status = "running"

    def _execute() -> None:
        from harness.agent import run as _agent_run
        try:
            _agent_run(
                request.task,
                use_wiggum=not bool(request.no_wiggum),
                producer_model=request.producer_model or None,
            )
        except SystemExit:
            # agent calls sys.exit(1) on some error paths — catch here so we
            # don't propagate SystemExit through asyncio.to_thread into the server
            pass

    try:
        await asyncio.to_thread(_execute)
        async with _queue_lock:
            item.status = "done"
    except Exception:
        async with _queue_lock:
            item.status = "error"


@router.post("/tasks", status_code=202)
async def submit_task(request: TaskRequest, background: BackgroundTasks):
    item = QueueItem(item_id=str(uuid.uuid4()), task=request.task)
    async with _queue_lock:
        _queue.append(item)
    background.add_task(_run_task, item, request)
    return {"item_id": item.item_id, "status": "pending"}

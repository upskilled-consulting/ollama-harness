"""POST /api/tasks — submit a task to the agent queue."""

import asyncio
import ctypes
import threading
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException

from harness.schema import QueueItem, TaskRequest

router = APIRouter(tags=["tasks"])

# In-memory queue — replace with SQLite-backed queue for persistence
_queue: list[QueueItem] = []
_queue_lock = asyncio.Lock()

# Maps item_id -> thread ident while the task is executing
_running_threads: dict[str, int] = {}


def _raise_in_thread(tid: int) -> bool:
    """Raise SystemExit in a running CPython thread. Returns True if exactly one thread was hit."""
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_ulong(tid),
        ctypes.py_object(SystemExit),
    )
    if res > 1:
        # Collateral damage — undo immediately
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(tid), None)
    return res == 1


async def _run_task(item: QueueItem, request: TaskRequest) -> None:
    async with _queue_lock:
        item.status = "running"

    def _execute() -> None:
        _running_threads[item.item_id] = threading.current_thread().ident  # type: ignore[assignment]
        try:
            from harness.agent import run as _agent_run
            try:
                _agent_run(
                    request.task,
                    use_wiggum=not bool(request.no_wiggum),
                    producer_model=request.producer_model or None,
                )
            except SystemExit:
                pass
        finally:
            _running_threads.pop(item.item_id, None)

    try:
        await asyncio.to_thread(_execute)
    except Exception:
        pass
    finally:
        async with _queue_lock:
            if item.status == "running":
                item.status = "done"


@router.post("/tasks", status_code=202)
async def submit_task(request: TaskRequest, background: BackgroundTasks):
    item = QueueItem(item_id=str(uuid.uuid4()), task=request.task)
    async with _queue_lock:
        _queue.append(item)
    background.add_task(_run_task, item, request)
    return {"item_id": item.item_id, "status": "pending"}


@router.delete("/tasks/{item_id}", status_code=200)
async def cancel_task(item_id: str):
    async with _queue_lock:
        item = next((i for i in _queue if i.item_id == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Task not found")
    if item.status in ("done", "error", "cancelled"):
        return {"item_id": item_id, "status": item.status}

    tid = _running_threads.get(item_id)
    if tid:
        _raise_in_thread(tid)

    async with _queue_lock:
        item.status = "cancelled"

    return {"item_id": item_id, "status": "cancelled"}

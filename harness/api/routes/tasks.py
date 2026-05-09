"""POST /api/tasks — submit a task to the agent queue; GET /api/tasks/{id}/stream — SSE log."""

import asyncio
import ctypes
import io
import sys
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse

from harness.config import TASK_LOGS_DIR
from harness.schema import QueueItem, TaskRequest

router = APIRouter(tags=["tasks"])

# In-memory queue — replace with SQLite-backed queue for persistence
_queue: list[QueueItem] = []
_queue_lock = asyncio.Lock()

# Maps item_id -> thread ident while the task is executing
_running_threads: dict[str, int] = {}


# ---------------------------------------------------------------------------
# Per-thread stdout tee — installed once, routes writes to per-thread log files
# ---------------------------------------------------------------------------

class _TaskTee(io.TextIOBase):
    """Thread-aware stdout tee. Real stdout + per-thread task log file."""

    _local: threading.local = threading.local()
    _real: io.TextIOBase | None = None

    def write(self, s: str) -> int:  # type: ignore[override]
        if self._real is not None:
            try:
                self._real.write(s)
                self._real.flush()
            except Exception:
                pass
        log = getattr(self._local, "log", None)
        if log is not None:
            try:
                log.write(s)
                log.flush()
            except Exception:
                pass
        return len(s)

    def flush(self) -> None:
        if self._real is not None:
            try:
                self._real.flush()
            except Exception:
                pass
        log = getattr(self._local, "log", None)
        if log is not None:
            try:
                log.flush()
            except Exception:
                pass

    def writable(self) -> bool:
        return True

    def isatty(self) -> bool:
        return False


_tee = _TaskTee()


def _install_tee() -> None:
    if not isinstance(sys.stdout, _TaskTee):
        _tee._real = sys.stdout
        sys.stdout = _tee


def _open_task_log(item_id: str) -> Path:
    TASK_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = TASK_LOGS_DIR / f"{item_id}.log"
    _install_tee()
    _tee._local.log = open(log_path, "w", encoding="utf-8", buffering=1)  # noqa: WPS515
    return log_path


def _close_task_log(log_path: Path) -> None:
    log = getattr(_tee._local, "log", None)
    if log is not None:
        try:
            log.close()
        except Exception:
            pass
        _tee._local.log = None
    # Write sentinel so the SSE reader knows the stream is finished
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("[DONE]\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Task runner
# ---------------------------------------------------------------------------

def _raise_in_thread(tid: int) -> bool:
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_ulong(tid),
        ctypes.py_object(SystemExit),
    )
    if res > 1:
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(tid), None)
    return res == 1


async def _run_task(item: QueueItem, request: TaskRequest) -> None:
    async with _queue_lock:
        item.status = "running"

    def _execute() -> None:
        log_path = _open_task_log(item.item_id)
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
            _close_task_log(log_path)

    try:
        await asyncio.to_thread(_execute)
    except Exception:
        pass
    finally:
        async with _queue_lock:
            if item.status == "running":
                item.status = "done"


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

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


@router.get("/tasks/{item_id}/stream")
async def stream_task_output(item_id: str):
    """SSE stream of task stdout. Yields lines as `data: <line>` events."""
    log_path = TASK_LOGS_DIR / f"{item_id}.log"

    async def _generate():
        # Wait up to 10s for the log file to appear
        for _ in range(100):
            if log_path.exists():
                break
            await asyncio.sleep(0.1)

        pos = 0
        while True:
            await asyncio.sleep(0.15)
            if not log_path.exists():
                continue
            try:
                text = log_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            new = text[pos:]
            pos = len(text)
            for line in new.splitlines():
                line = line.rstrip()
                if not line:
                    continue
                if line == "[DONE]":
                    yield "data: [DONE]\n\n"
                    return
                yield f"data: {line}\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

"""GET /api/queue, GET /api/state — queue inspection endpoints."""


from fastapi import APIRouter

router = APIRouter(tags=["queue"])


# Shared state imported from tasks to avoid duplication
def _get_queue():
    from harness.api.routes.tasks import _queue, _queue_lock
    return _queue, _queue_lock


@router.get("/queue")
async def get_queue():
    queue, lock = _get_queue()
    async with lock:
        items = list(queue[-100:])
    pending = sum(1 for i in items if i.status == "pending")
    return {"pending": pending, "items": [i.model_dump() for i in items]}


@router.get("/state")
async def get_state():
    queue, lock = _get_queue()
    async with lock:
        running = [i for i in queue if i.status == "running"]
    return {"running": len(running), "queue_depth": len(queue)}

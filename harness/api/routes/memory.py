"""GET/PATCH/DELETE /api/memories — memory store management endpoints."""


from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from harness.memory import MemoryStore

router = APIRouter(tags=["memory"])
_store = MemoryStore()


class UpdateBody(BaseModel):
    title:   str | None       = None
    tags:    list[str] | None = None
    quality: int | None       = None


class FeedbackBody(BaseModel):
    rating:  int
    comment: str = ""


@router.get("/memories")
async def list_memories(
    search:      str = Query(""),
    task_type:   str = Query(""),
    quality_min: int = Query(-3),
    quality_max: int = Query(3),
    final:       str = Query(""),
    page:        int = Query(1, ge=1),
    per_page:    int = Query(25, ge=1, le=100),
):
    return _store.list_memories(search=search, task_type=task_type,
                                quality_min=quality_min, quality_max=quality_max,
                                final=final, page=page, per_page=per_page)


@router.get("/memories/prune-candidates")
async def get_prune_candidates():
    return {"candidates": _store.prune_candidates()}


@router.get("/memories/graph")
async def get_memory_graph(limit: int = Query(600, ge=5, le=2000)):
    import asyncio
    from functools import partial
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_store.get_graph, max_nodes=limit))


@router.get("/memories/{memory_id}")
async def get_memory(memory_id: int):
    mem = _store.get_memory(memory_id)
    if mem is None:
        raise HTTPException(404, "Memory not found")
    return mem


@router.patch("/memories/{memory_id}")
async def update_memory(memory_id: int, body: UpdateBody):
    ok = _store.update_memory(memory_id, title=body.title, tags=body.tags, quality=body.quality)
    if not ok:
        raise HTTPException(404, "Memory not found")
    return {"ok": True}


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: int):
    ok = _store.delete_memory(memory_id)
    if not ok:
        raise HTTPException(404, "Memory not found")
    return {"ok": True}


@router.post("/memories/{memory_id}/feedback")
async def memory_feedback(memory_id: int, body: FeedbackBody):
    result = _store.add_feedback(memory_id, rating=body.rating, comment=body.comment)
    if result is None:
        raise HTTPException(404, "Memory not found")
    return result

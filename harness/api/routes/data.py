"""GET /api/finetune/metrics — fine-tune training metrics stream."""

import json
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from harness.config import DATA_DIR

router = APIRouter(tags=["data"])
_METRICS = DATA_DIR / "finetune_metrics.jsonl"


@router.get("/finetune/metrics")
async def finetune_metrics():
    if not _METRICS.exists():
        return []
    records = []
    for line in _METRICS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records

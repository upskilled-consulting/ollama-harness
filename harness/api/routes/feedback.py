"""POST /api/feedback, GET /api/feedback/{run_id}"""

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

from harness.config import DATA_DIR

router = APIRouter(tags=["feedback"])

FEEDBACK_FILE = DATA_DIR / "feedback.jsonl"


class FeedbackBody(BaseModel):
    run_id:  str
    node_id: str
    rating:  int    # 1 = thumbs-up, -1 = thumbs-down
    comment: str = ""


@router.post("/feedback")
async def post_feedback(body: FeedbackBody):
    record = {
        "feedback_id": uuid.uuid4().hex[:12],
        "run_id":      body.run_id,
        "node_id":     body.node_id,
        "rating":      body.rating,
        "comment":     body.comment,
        "created_at":  datetime.now(UTC).isoformat(),
    }
    FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(FEEDBACK_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return record


@router.get("/feedback/{run_id}")
async def get_feedback(run_id: str):
    if not FEEDBACK_FILE.exists():
        return []
    records = []
    for line in FEEDBACK_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("run_id") == run_id:
            records.append(r)
    return records

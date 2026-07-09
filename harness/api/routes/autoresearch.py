"""GET /api/autoresearch — real-time supervision of the autoresearch optimizer loop."""

import json
import statistics

from fastapi import APIRouter

from harness.config import ROOT

router = APIRouter(tags=["autoresearch"])

_JSONL = ROOT / "data" / "autoresearch.jsonl"


def _read_records() -> list[dict]:
    if not _JSONL.exists():
        return []
    records = []
    for line in _JSONL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return records


@router.get("/autoresearch")
async def get_autoresearch():
    records = _read_records()
    if not records:
        return {"records": [], "summary": {}}

    non_baseline = [r for r in records if r.get("status") != "baseline"]
    keeps = [r for r in non_baseline if r.get("status") == "keep"]
    discards = [r for r in non_baseline if r.get("status") == "discard"]
    scores = [r["score"] for r in non_baseline if "score" in r]
    deltas = [r["delta"] for r in non_baseline if "delta" in r]

    baseline_record = next((r for r in records if r.get("status") == "baseline"), None)
    baseline_score = baseline_record["score"] if baseline_record else None
    best_score = max((r["score"] for r in keeps), default=baseline_score)
    latest = records[-1] if records else None

    summary = {
        "total_experiments": len(non_baseline),
        "keeps": len(keeps),
        "discards": len(discards),
        "keep_rate": round(len(keeps) / len(non_baseline), 3) if non_baseline else 0,
        "baseline_score": baseline_score,
        "best_score": best_score,
        "latest_score": latest["score"] if latest else None,
        "latest_status": latest["status"] if latest else None,
        "avg_delta": round(statistics.mean(deltas), 3) if deltas else 0,
        "kimi_fires": sum(1 for r in records if r.get("kimi_fired")),
        "max_consecutive_discards": max((r.get("consecutive_discards", 0) for r in records), default=0),
    }

    return {"records": records, "summary": summary}

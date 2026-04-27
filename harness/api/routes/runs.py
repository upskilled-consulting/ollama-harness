"""GET /api/runs — active + recent runs; GET /api/data — dashboard payload."""

import json
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from harness.config import RUNS_FILE, settings
from harness.schema import RunRecord

router = APIRouter(tags=["runs"])

_MAX_RECENT = 50


def _load_runs(n: int = _MAX_RECENT) -> list[dict]:
    if not RUNS_FILE.exists():
        return []
    lines = RUNS_FILE.read_text(encoding="utf-8").splitlines()
    records = []
    for line in reversed(lines):
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        if len(records) >= n:
            break
    return records


@router.get("/runs")
async def get_runs():
    recent = _load_runs()
    active = [r for r in recent if r.get("final") is None]
    return {"active": active, "recent": recent}


@router.get("/data")
async def get_dashboard_data():
    runs = _load_runs()
    passes   = [r for r in runs if r.get("final") == "PASS"]
    scores   = [r["wiggum_scores"][-1] for r in runs if r.get("wiggum_scores")]
    durations = [r["run_duration_s"] for r in runs if r.get("run_duration_s")]

    def _mean(vs): return round(sum(vs) / len(vs), 2) if vs else 0.0

    kpi = {
        "total_runs":   len(runs),
        "pass_rate":    round(len(passes) / len(runs), 3) if runs else 0.0,
        "mean_score":   _mean(scores),
        "mean_duration_s": _mean(durations),
    }

    score_trend = [
        {"i": i, "score": r["wiggum_scores"][-1], "task_type": r.get("task_type")}
        for i, r in enumerate(reversed(runs))
        if r.get("wiggum_scores")
    ]

    cost = {
        "total_input_tokens":  sum(r.get("input_tokens", 0) for r in runs),
        "total_output_tokens": sum(r.get("output_tokens", 0) for r in runs),
    }

    return {
        "kpi":          kpi,
        "recent_runs":  runs[:20],
        "score_trend":  score_trend,
        "cost":         cost,
        "claude_stats": {},  # reserved
    }

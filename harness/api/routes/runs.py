"""GET /api/runs — active + recent runs; GET /api/data — dashboard payload."""

import json

from fastapi import APIRouter

from harness.config import LEGACY_RUNS_FILE, RUNS_FILE

router = APIRouter(tags=["runs"])

_MAX_RECENT = 200


def _load_runs(n: int = _MAX_RECENT) -> list[dict]:
    """Load runs from both current and legacy JSONL, deduped by run_id, newest first."""
    seen: set[str] = set()
    all_records: list[dict] = []

    for path in (RUNS_FILE, LEGACY_RUNS_FILE):
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = r.get("run_id") or r.get("timestamp", "") + r.get("task", "")[:30]
            if rid and rid not in seen:
                seen.add(rid)
                all_records.append(r)

    all_records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return all_records[:n]


@router.get("/runs")
async def get_runs():
    recent = _load_runs()
    active = [r for r in recent if r.get("final") is None]
    return {"active": active, "recent": recent}


@router.get("/runs/all")
async def get_all_runs():
    """Full run list for Explorer — no cap."""
    return _load_runs(n=10_000)


@router.get("/data")
async def get_dashboard_data():
    runs = _load_runs()
    passes    = [r for r in runs if r.get("final") == "PASS"]
    scores    = [r["wiggum_scores"][-1] for r in runs if r.get("wiggum_scores")]
    durations = [r["run_duration_s"] for r in runs if r.get("run_duration_s")]

    def _mean(vs: list) -> float:
        return round(sum(vs) / len(vs), 2) if vs else 0.0

    kpi = {
        "total_runs":      len(runs),
        "pass_rate":       round(len(passes) / len(runs), 3) if runs else 0.0,
        "mean_score":      _mean(scores),
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
        "recent_runs":  runs[:50],
        "score_trend":  score_trend,
        "cost":         cost,
        "claude_stats": {},
    }

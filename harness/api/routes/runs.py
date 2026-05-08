"""GET /api/runs — active + recent runs; GET /api/data — dashboard payload."""

import asyncio
import json
import os
from collections import Counter, defaultdict

from fastapi import APIRouter, HTTPException

from harness.config import LEGACY_RUNS_FILE, LIVE_RUN_FILE, RUNS_FILE

router = APIRouter(tags=["runs"])

_MAX_RECENT = 200


_STRIP_FROM_LIST = {"final_content"}


def _load_runs(n: int = _MAX_RECENT, *, full: bool = False) -> list[dict]:
    """Load runs from both current and legacy JSONL, deduped by run_id, newest first.

    Set full=True to include heavy inline fields (final_content) for single-run lookups.
    """
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
            if not r.get("run_id"):
                r["run_id"] = rid
            if rid and rid not in seen:
                seen.add(rid)
                if not full:
                    r = {k: v for k, v in r.items() if k not in _STRIP_FROM_LIST}
                all_records.append(r)

    all_records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return all_records[:n]


@router.get("/runs/live")
async def get_live_run():
    """Return the in-progress run snapshot written by RunTrace.set_stage(), or null."""
    if not LIVE_RUN_FILE.exists():
        return None
    try:
        return json.loads(LIVE_RUN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


@router.get("/runs")
async def get_runs():
    recent = _load_runs()
    active = [r for r in recent if r.get("final") is None]
    return {"active": active, "recent": recent}


@router.get("/runs/all")
async def get_all_runs():
    """Full run list for Explorer — no cap."""
    return _load_runs(n=10_000)


def _find_run_by_id(run_id: str) -> dict | None:
    """Scan JSONL files (newest-first) for a specific run_id without loading everything."""
    for path in (RUNS_FILE, LEGACY_RUNS_FILE):
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("run_id") == run_id:
                return r
    return None


@router.get("/runs/{run_id}/content")
async def get_run_content(run_id: str):
    """Return the markdown output file content for a run.

    Falls back to inline final_content stored in the run record when the output
    file is absent (common for legacy runs whose paths no longer exist on disk).
    """
    run = await asyncio.to_thread(_find_run_by_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    inline = run.get("final_content") or ""

    path = run.get("output_path")
    if path:
        expanded = os.path.expanduser(path)
        if os.path.exists(expanded):
            content = open(expanded, encoding="utf-8", errors="replace").read()
            return {"content": content, "path": path, "bytes": len(content.encode())}

    if inline:
        return {"content": inline, "path": path, "bytes": len(inline.encode())}

    # Return a readable explanation instead of a raw 404
    final   = run.get("final") or "unknown"
    task    = (run.get("task") or "")[:120]
    message = f"No output recorded for this run.\n\nStatus: {final}\nTask: {task}"
    return {"content": message, "path": None, "bytes": len(message.encode())}


@router.get("/data")
async def get_dashboard_data():
    runs = _load_runs(n=10_000)
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


@router.get("/analytics")
async def get_analytics():
    runs = _load_runs(n=10_000)

    # Daily aggregation
    daily: dict[str, dict] = defaultdict(lambda: {
        "date": "", "total": 0, "pass": 0, "fail": 0, "error": 0,
        "input_tokens": 0, "output_tokens": 0, "scores": [],
    })
    for r in runs:
        ts = r.get("timestamp", "")
        date = ts[:10] if len(ts) >= 10 else "unknown"
        d = daily[date]
        d["date"] = date
        d["total"] += 1
        final = r.get("final")
        if final == "PASS":        d["pass"]  += 1
        elif final == "FAIL":      d["fail"]  += 1
        elif final == "ERROR":     d["error"] += 1
        d["input_tokens"]  += r.get("input_tokens", 0) or 0
        d["output_tokens"] += r.get("output_tokens", 0) or 0
        if r.get("wiggum_scores"):
            d["scores"].append(r["wiggum_scores"][-1])

    result = []
    for d in daily.values():
        scores = d.pop("scores")
        d["mean_score"] = round(sum(scores) / len(scores), 2) if scores else None
        result.append(d)
    result.sort(key=lambda d: d["date"])

    # Score distribution histogram (buckets 0–10)
    all_scores = [r["wiggum_scores"][-1] for r in runs if r.get("wiggum_scores")]
    buckets = [0] * 11
    for s in all_scores:
        buckets[min(10, max(0, round(s)))] += 1
    score_dist = [{"score": i, "count": buckets[i]} for i in range(11)]

    # Task type breakdown
    task_types = Counter(r.get("task_type", "unknown") for r in runs if r.get("task_type"))

    return {
        "daily":              result,
        "score_distribution": score_dist,
        "task_types":         [{"type": k, "count": v} for k, v in task_types.most_common()],
    }

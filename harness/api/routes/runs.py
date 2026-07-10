"""GET /api/runs — active + recent runs; GET /api/data — dashboard payload."""

import asyncio
import json
import math
import os
import time
from collections import Counter, defaultdict

from fastapi import APIRouter, HTTPException

from harness.config import LEGACY_RUNS_FILE, LIVE_RUN_FILE, LIVE_TASK_FILE, RUNS_FILE

router = APIRouter(tags=["runs"])

_MAX_RECENT = 100

_STRIP_FROM_LIST = {"final_content"}

_VALID_FINALS = {None, "PASS", "FAIL", "ERROR"}


def _is_stub(r: dict) -> bool:
    """True for internal-phase records (research phases, etc.) that have no synthesis output."""
    return r.get("final") not in _VALID_FINALS

# ── Full-list cache (used by paginated endpoint) ───────────────────────────────

_full_cache: tuple[float, list[dict]] | None = None
_FULL_CACHE_TTL = 30.0  # seconds


def _load_all_runs_uncapped() -> list[dict]:
    """Load every run from disk, newest-first. Result cached for 30 s."""
    global _full_cache
    now = time.monotonic()
    if _full_cache is not None and now - _full_cache[0] < _FULL_CACHE_TTL:
        return _full_cache[1]

    seen: set[str] = set()
    records: list[dict] = []

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
            rid = r.get("run_id") or r.get("timestamp", "") + r.get("task", "")[:30]
            if not r.get("run_id"):
                r["run_id"] = rid
            if rid and rid not in seen:
                seen.add(rid)
                if _is_stub(r):
                    continue
                r = {k: v for k, v in r.items() if k not in _STRIP_FROM_LIST}
                records.append(r)

    _full_cache = (now, records)
    return records


def _load_runs(n: int = _MAX_RECENT) -> list[dict]:
    """Load the most recent N runs, newest-first.

    Reads JSONL from the end so it stops after N records without scanning
    the entire file — keeps response times fast even with thousands of runs.
    """
    seen: set[str] = set()
    records: list[dict] = []

    for path in (RUNS_FILE, LEGACY_RUNS_FILE):
        if not path.exists() or len(records) >= n:
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in reversed(lines):
            if len(records) >= n:
                break
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
                if _is_stub(r):
                    continue
                r = {k: v for k, v in r.items() if k not in _STRIP_FROM_LIST}
                records.append(r)

    return records  # already newest-first from reversed iteration


@router.get("/runs/live")
async def get_live_run():
    """Return the in-progress run snapshot written by RunTrace.set_stage(), or null."""
    if not LIVE_RUN_FILE.exists():
        return None
    try:
        snapshot = json.loads(LIVE_RUN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
    if LIVE_TASK_FILE.exists():
        try:
            task_info = json.loads(LIVE_TASK_FILE.read_text(encoding="utf-8"))
            snapshot["item_id"] = task_info.get("item_id")
        except Exception:
            pass
    return snapshot


@router.get("/runs")
async def get_runs():
    recent = await asyncio.to_thread(_load_runs)
    active = [r for r in recent if r.get("final") is None]
    return {"active": active, "recent": recent}


@router.get("/runs/all")
async def get_all_runs():
    """Run list for Explorer — capped at 100 newest."""
    return await asyncio.to_thread(_load_runs)


@router.get("/runs/paged")
async def get_paged_runs(page: int = 1, per_page: int = 25, status: str = "", search: str = ""):
    """Paginated run list with optional status/search filtering."""
    per_page = max(1, min(100, per_page))
    page     = max(1, page)
    records  = await asyncio.to_thread(_load_all_runs_uncapped)
    if status:
        records = [r for r in records if (r.get("final") or "").lower() == status.lower()]
    if search:
        q = search.lower()
        records = [r for r in records if q in (r.get("task") or "").lower() or q in (r.get("producer_model") or "").lower()]
    total    = len(records)
    pages    = math.ceil(total / per_page) if total else 1
    offset   = (page - 1) * per_page
    return {
        "runs":     records[offset : offset + per_page],
        "total":    total,
        "page":     page,
        "per_page": per_page,
        "pages":    pages,
    }


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


@router.get("/runs/{run_id}/children")
async def get_run_children(run_id: str):
    """Return all runs whose parent_run_id matches run_id (subtask child runs)."""
    def _find_children() -> list[dict]:
        seen: set[str] = set()
        results: list[dict] = []
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
                if r.get("parent_run_id") == run_id:
                    rid = r.get("run_id", "")
                    if rid and rid not in seen:
                        seen.add(rid)
                        results.append({k: v for k, v in r.items() if k not in _STRIP_FROM_LIST})
        results.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        return results

    return await asyncio.to_thread(_find_children)


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
    runs = await asyncio.to_thread(_load_all_runs_uncapped)
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
    runs = await asyncio.to_thread(_load_runs)

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

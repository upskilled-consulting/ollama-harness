"""GET /api/sessions, /api/plans, /api/artifacts, /api/curation"""

import json
import os

from fastapi import APIRouter, HTTPException

from harness.config import (
    ARTIFACTS_FILE,
    LEGACY_ARTIFACTS_FILE,
    LEGACY_CURATION_LOG,
    LEGACY_PLANS_FILE,
    LEGACY_RUNS_FILE,
    LEGACY_SESSIONS_FILE,
    PLANS_FILE,
    RUNS_FILE,
    SESSIONS_FILE,
)

router = APIRouter(tags=["history"])


def _load_jsonl(primary, legacy, id_key: str) -> list[dict]:
    seen: set[str] = set()
    records: list[dict] = []
    for path in (primary, legacy):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = r.get(id_key)
            if not rid:
                records.append(r)
                continue
            if rid not in seen:
                seen.add(rid)
                records.append(r)
    return records


def _derive_sessions_from_runs() -> list[dict]:
    """Build session summaries from runs.jsonl when sessions.jsonl is absent."""
    seen: set[str] = set()
    runs: list[dict] = []
    for path in (RUNS_FILE, LEGACY_RUNS_FILE):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = r.get("run_id")
            if rid and rid not in seen:
                seen.add(rid)
                runs.append(r)

    sessions: dict[str, dict] = {}
    for r in runs:
        sid = r.get("session_id") or r.get("timestamp", "")[:10]
        if not sid:
            continue
        if sid not in sessions:
            sessions[sid] = {
                "session_id": sid,
                "started_at": r.get("timestamp", ""),
                "ended_at": r.get("timestamp", ""),
                "runs": 0, "artifacts": 0,
                "total_input_tokens": 0, "total_output_tokens": 0,
                "duration_s": 0.0,
            }
        s = sessions[sid]
        s["runs"] += 1
        ts = r.get("timestamp", "")
        if ts < s["started_at"]:  s["started_at"] = ts
        if ts > s["ended_at"]:    s["ended_at"]   = ts
        s["total_input_tokens"]  += r.get("input_tokens",  0) or 0
        s["total_output_tokens"] += r.get("output_tokens", 0) or 0
        s["duration_s"]          += r.get("run_duration_s", 0) or 0

    return sorted(sessions.values(), key=lambda s: s.get("started_at", ""), reverse=True)


@router.get("/sessions")
async def get_sessions():
    records = _load_jsonl(SESSIONS_FILE, LEGACY_SESSIONS_FILE, "session_id")
    merged: dict[str, dict] = {}
    for r in records:
        sid = r.get("session_id")
        if not sid:
            continue
        if sid not in merged:
            merged[sid] = dict(r)
        else:
            merged[sid].update({k: v for k, v in r.items() if v is not None})

    if not merged:
        return _derive_sessions_from_runs()

    return sorted(merged.values(), key=lambda s: s.get("started_at", ""), reverse=True)


@router.get("/plans")
async def get_plans():
    records = _load_jsonl(PLANS_FILE, LEGACY_PLANS_FILE, "plan_id")
    return sorted(records, key=lambda p: p.get("created_at", ""), reverse=True)


@router.get("/artifacts")
async def get_artifacts():
    records = _load_jsonl(ARTIFACTS_FILE, LEGACY_ARTIFACTS_FILE, "artifact_id")
    return sorted(records, key=lambda a: a.get("created_at", ""), reverse=True)


@router.get("/curation")
async def get_curation():
    if not LEGACY_CURATION_LOG.exists():
        return []
    records = []
    for line in reversed(LEGACY_CURATION_LOG.read_text(encoding="utf-8", errors="replace").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return records


_PREVIEW_MAX = 50_000


@router.get("/artifacts/{artifact_id}/content")
async def get_artifact_content(artifact_id: str):
    records = _load_jsonl(ARTIFACTS_FILE, LEGACY_ARTIFACTS_FILE, "artifact_id")
    artifact = next((r for r in records if r.get("artifact_id") == artifact_id), None)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    path = artifact.get("path", "")
    expanded = os.path.expanduser(path)
    if not os.path.exists(expanded):
        raise HTTPException(status_code=404, detail="File not found on disk")

    try:
        content = open(expanded, encoding="utf-8", errors="replace").read()
        truncated = len(content) > _PREVIEW_MAX
        return {
            "content":   content[:_PREVIEW_MAX],
            "truncated": truncated,
            "bytes":     len(content.encode()),
            "path":      path,
        }
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

"""GET /api/sessions, /api/plans, /api/artifacts, /api/curation"""

import json

from fastapi import APIRouter

from harness.config import (
    ARTIFACTS_FILE,
    LEGACY_ARTIFACTS_FILE,
    LEGACY_CURATION_LOG,
    LEGACY_PLANS_FILE,
    LEGACY_SESSIONS_FILE,
    PLANS_FILE,
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


@router.get("/sessions")
async def get_sessions():
    records = _load_jsonl(SESSIONS_FILE, LEGACY_SESSIONS_FILE, "session_id")
    # Merge start+end events: last event for each session_id wins
    merged: dict[str, dict] = {}
    for r in records:
        sid = r.get("session_id")
        if not sid:
            continue
        if sid not in merged:
            merged[sid] = dict(r)
        else:
            merged[sid].update({k: v for k, v in r.items() if v is not None})
    result = sorted(merged.values(), key=lambda s: s.get("started_at", ""), reverse=True)
    return result


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

"""GET /api/security/events — security audit log endpoints."""

import json

from fastapi import APIRouter, Query

from harness.config import SECURITY_LOG

router = APIRouter(tags=["security"])


def _load_events() -> list[dict]:
    if not SECURITY_LOG.exists():
        return []
    events = []
    for line in SECURITY_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


@router.get("/security/events")
async def get_security_events(
    search:     str  = Query(""),
    severity:   str  = Query(""),
    event_type: str  = Query(""),
    layer:      str  = Query(""),
    run_id:     str  = Query(""),
    limit:      int  = Query(500),
):
    """
    Return security audit events, newest-first, with optional filters.

    Filters are ANDed — all specified filters must match.
    search applies to resource + reason fields (case-insensitive substring).
    """
    events = _load_events()
    events.reverse()

    if severity:
        events = [e for e in events if e.get("severity") == severity]
    if event_type:
        events = [e for e in events if e.get("event_type") == event_type]
    if layer:
        events = [e for e in events if e.get("layer") == layer]
    if run_id:
        events = [e for e in events if e.get("run_id") == run_id]
    if search:
        q = search.lower()
        events = [
            e for e in events
            if q in (e.get("resource") or "").lower()
            or q in (e.get("reason") or "").lower()
            or q in (e.get("caller") or "").lower()
        ]

    total = len(events)
    return {"events": events[:limit], "total": total}


@router.get("/security/summary")
async def get_security_summary():
    """Return aggregate counts by severity and event_type for KPI cards."""
    events = _load_events()
    by_severity: dict[str, int]    = {}
    by_type:     dict[str, int]    = {}
    by_layer:    dict[str, int]    = {}
    for e in events:
        sev = e.get("severity", "unknown")
        et  = e.get("event_type", "unknown")
        lay = e.get("layer", "unknown")
        by_severity[sev]  = by_severity.get(sev, 0) + 1
        by_type[et]       = by_type.get(et, 0) + 1
        by_layer[lay]     = by_layer.get(lay, 0) + 1
    return {
        "total":       len(events),
        "by_severity": by_severity,
        "by_type":     by_type,
        "by_layer":    by_layer,
    }

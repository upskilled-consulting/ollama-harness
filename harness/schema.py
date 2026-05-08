"""
harness/schema.py — data models for all structured data in the harness.

Contains two layers:
  1. Pydantic v2 models (RunRecord, TaskRequest, etc.) used by the API and
     dashboard — validated, serialisable, typed.
  2. Legacy dataclasses (Project, Session, Artifact, Message, OrchestratorPlan)
     with their lifecycle helpers — used by logger.py, orchestrator.py, and the
     project/session management CLI.

Entity hierarchy:
    Project > Session > Run > (Artifact, Message, Observation, Feedback)

All IDs use the format:  20260418T100000Z-a1b2c3d4e5f6
  └── UTC compact ISO 8601 ──┘ └─ uuid4 hex[:12] ─┘
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel
from pydantic import Field as PydanticField

from harness.config import (
    ARTIFACTS_FILE,
    DATA_DIR,
    PLANS_FILE,
    ROOT,
    RUNS_FILE,
    SESSIONS_FILE,
)

# ---------------------------------------------------------------------------
# Path constants — kept for backward-compat with logger.py and lifecycle fns
# ---------------------------------------------------------------------------

PROJECTS_PATH  = str(DATA_DIR / "projects.jsonl")
SESSIONS_PATH  = str(SESSIONS_FILE)
ARTIFACTS_PATH = str(ARTIFACTS_FILE)
MESSAGES_PATH  = str(DATA_DIR / "messages.jsonl")
PLANS_PATH     = str(PLANS_FILE)
DOTFILE        = str(ROOT / ".harness-project")


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def make_id() -> str:
    """Date-prefixed UUID: 20260418T100000Z-a1b2c3d4e5f6"""
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}-{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _append_jsonl(path: str, record: dict) -> None:
    """Append one JSON record to a JSONL file. Non-fatal on error."""
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        print(f"  [schema] JSONL write error ({path}): {e}")


def _read_jsonl(path: str) -> list[dict]:
    """Read all records from a JSONL file. Returns [] if missing."""
    if not os.path.exists(path):
        return []
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


# ---------------------------------------------------------------------------
# Legacy dataclasses — Project / Session / Artifact / Message / OrchestratorPlan
# ---------------------------------------------------------------------------

@dataclass
class Project:
    project_id:  str       = field(default_factory=make_id)
    name:        str       = ""
    description: str       = ""
    status:      str       = "active"   # active | paused | archived
    tags:        list      = field(default_factory=list)
    created_at:  str       = field(default_factory=_now_iso)
    updated_at:  str       = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Session:
    session_id:          str            = field(default_factory=make_id)
    project_id:          str            = ""
    triggered_by:        str            = "cli"  # cli | server | orchestrator | schedule
    started_at:          str            = field(default_factory=_now_iso)
    ended_at:            str | None  = None
    runs:                int            = 0
    total_input_tokens:  int            = 0
    total_output_tokens: int            = 0
    artifacts:           int            = 0
    duration_s:          float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Artifact:
    artifact_id:   str           = field(default_factory=make_id)
    run_id:        str           = ""
    session_id:    str           = ""
    project_id:    str           = ""
    type:          str           = "output"  # output | trace | kg | annotation | dataset | lit_review
    path:          str           = ""
    bytes:         int           = 0
    lines:         int | None = None
    content_hash:  str | None = None
    created_at:    str           = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Message:
    run_id:      str           = ""
    session_id:  str           = ""
    project_id:  str           = ""
    seq:         int           = 0
    role:        str           = ""        # system | user | assistant | tool
    stage:       str | None = None      # pipeline stage (synth, introspect, eval, …)
    content:     str | None = None
    cot:         str | None = None      # chain-of-thought / thinking text
    tool_calls:  list | None = None
    tool_name:   str | None = None
    chars:       int | None = None
    timestamp:   str           = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OrchestratorPlan:
    """Written to plans.jsonl before subtask execution begins."""
    plan_id:       str       = field(default_factory=make_id)
    run_id:        str       = ""
    session_id:    str       = ""
    project_id:    str       = ""
    parent_run_id: str       = ""
    task:          str       = ""
    plan_type:     str       = "orchestrator"  # orchestrator | agent
    task_type:     str       = ""
    complexity:    str       = ""
    subtasks:      list      = field(default_factory=list)  # [{"desc": str, "path": str}]
    known_facts:   list      = field(default_factory=list)
    knowledge_gaps: list     = field(default_factory=list)
    search_queries: list     = field(default_factory=list)
    created_at:    str       = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Project lifecycle
# ---------------------------------------------------------------------------

def create_project(name: str, description: str = "", tags: list | None = None) -> Project:
    """Create a new project and append to projects.jsonl."""
    p = Project(name=name, description=description, tags=tags or [])
    _append_jsonl(PROJECTS_PATH, {"event": "project_create", **p.to_dict()})
    print(f"  [schema] project created: {p.project_id} ({name})")
    return p


def list_projects() -> list[dict]:
    """Return latest state per project from projects.jsonl."""
    records = _read_jsonl(PROJECTS_PATH)
    latest: dict[str, dict] = {}
    for r in records:
        pid = r.get("project_id")
        if pid:
            latest[pid] = r
    return list(latest.values())


def resolve_project_id() -> str:
    """
    Return the active project_id. Resolution order:
    1. HARNESS_PROJECT_ID env var
    2. .harness-project dotfile in repo root
    3. Last active project in projects.jsonl
    4. Auto-create a default project
    """
    pid = os.environ.get("HARNESS_PROJECT_ID")
    if pid:
        return pid

    if os.path.exists(DOTFILE):
        pid = open(DOTFILE, encoding="utf-8").read().strip()
        if pid:
            return pid

    records = _read_jsonl(PROJECTS_PATH)
    last_active = None
    for r in records:
        if r.get("status") == "active" and r.get("project_id"):
            last_active = r["project_id"]
    if last_active:
        return last_active

    p = create_project(name="default", description="Auto-created default project")
    os.environ["HARNESS_PROJECT_ID"] = p.project_id
    return p.project_id


def set_project(project_id: str) -> None:
    """Write project_id to .harness-project dotfile and set env var."""
    with open(DOTFILE, "w", encoding="utf-8") as f:
        f.write(project_id + "\n")
    os.environ["HARNESS_PROJECT_ID"] = project_id
    print(f"  [schema] active project set: {project_id}")


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

def start_session(project_id: str = "", triggered_by: str = "cli") -> Session:
    """Create and record a new session. Sets HARNESS_SESSION_ID env var."""
    if not project_id:
        project_id = resolve_project_id()
    s = Session(project_id=project_id, triggered_by=triggered_by)
    os.environ["HARNESS_SESSION_ID"] = s.session_id
    _append_jsonl(SESSIONS_PATH, {"event": "session_start", **s.to_dict()})
    return s


def end_session(
    session: Session,
    runs: int = 0,
    total_input_tokens: int = 0,
    total_output_tokens: int = 0,
    artifacts: int = 0,
) -> None:
    """Record session end event."""
    now = _now_iso()
    started = session.started_at
    try:
        dur = (datetime.fromisoformat(now) - datetime.fromisoformat(started)).total_seconds()
    except Exception:
        dur = None
    session.ended_at  = now
    session.duration_s = dur
    session.runs      += runs
    _append_jsonl(SESSIONS_PATH, {
        "event":               "session_end",
        "session_id":          session.session_id,
        "project_id":          session.project_id,
        "ended_at":            now,
        "runs":                runs,
        "total_input_tokens":  total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "artifacts":           artifacts,
        "duration_s":          dur,
    })


# ---------------------------------------------------------------------------
# Project-stats helper
# ---------------------------------------------------------------------------

def project_stats(project_id: str) -> dict:
    """Aggregate stats for a project across all JSONL files."""
    runs      = [r for r in _read_jsonl(str(RUNS_FILE))
                 if r.get("project_id") == project_id]
    sessions  = [r for r in _read_jsonl(SESSIONS_PATH)
                 if r.get("project_id") == project_id and r.get("event") == "session_start"]
    artifacts = [r for r in _read_jsonl(ARTIFACTS_PATH)
                 if r.get("project_id") == project_id]

    total_in  = sum(r.get("input_tokens",  0) or 0 for r in runs)
    total_out = sum(r.get("output_tokens", 0) or 0 for r in runs)
    scores    = [r["wiggum_scores"][-1] for r in runs if r.get("wiggum_scores")]
    passes    = sum(1 for r in runs if r.get("final") == "PASS")

    return {
        "project_id":   project_id,
        "sessions":     len(sessions),
        "runs":         len(runs),
        "passes":       passes,
        "pass_rate":    round(passes / len(runs), 3) if runs else 0,
        "avg_score":    round(sum(scores) / len(scores), 2) if scores else None,
        "total_input_tokens":  total_in,
        "total_output_tokens": total_out,
        "artifacts":    len(artifacts),
        "artifact_types": {t: sum(1 for a in artifacts if a.get("type") == t)
                           for t in {a.get("type") for a in artifacts}},
    }


# ---------------------------------------------------------------------------
# Pydantic v2 models — API layer and dashboard
# ---------------------------------------------------------------------------

class TaskType(StrEnum):
    enumerated     = "enumerated"
    best_practices = "best_practices"
    research       = "research"
    email          = "email"
    annotate       = "annotate"
    unknown        = "unknown"


class RunFinal(StrEnum):
    PASS  = "PASS"
    FAIL  = "FAIL"
    ERROR = "ERROR"


class StageTokens(BaseModel):
    input:          int = 0
    output:         int = 0
    calls:          int = 0
    total_ms:       int = 0
    thinking_chars: int = 0


class ToolCall(BaseModel):
    name:         str
    query:        str | None = None
    path:         str | None = None
    result_chars: int  = 0
    cached:       bool = False


class WiggumDim(BaseModel):
    relevance:    float
    completeness: float
    depth:        float
    grounded:     float | None = None
    specificity:  float
    structure:    float


class Plan(BaseModel):
    search_queries:     list[str]  = PydanticField(default_factory=list)
    expected_sections:  int | None = None
    known_facts:        list[str]  = PydanticField(default_factory=list)
    knowledge_gaps:     list[str]  = PydanticField(default_factory=list)
    prior_work_summary: str        = ""
    notes:              str        = ""
    subtasks:           list[str]  = PydanticField(default_factory=list)


class RunRecord(BaseModel):
    run_id:          str
    timestamp:       datetime
    task:            str
    task_type:       TaskType    = TaskType.unknown
    producer_model:  str
    evaluator_model: str

    run_duration_s:  float = 0.0

    input_tokens:    int   = 0
    output_tokens:   int   = 0
    tokens_by_stage: dict[str, StageTokens] = PydanticField(default_factory=dict)

    tool_calls:      list[ToolCall] = PydanticField(default_factory=list)
    files_read:      list[str]      = PydanticField(default_factory=list)
    vision_images:   list[str]      = PydanticField(default_factory=list)
    memory_hits:     int            = 0
    injection_stripped: int         = 0

    output_path:     str | None     = None
    output_bytes:    int            = 0
    output_lines:    int            = 0
    synth_forced:    bool           = False

    wiggum_rounds:   int            = 0
    wiggum_scores:   list[float]    = PydanticField(default_factory=list)
    wiggum_dims:     list[WiggumDim] = PydanticField(default_factory=list)
    synth_cot:       list[str]      = PydanticField(default_factory=list)
    final:           RunFinal | None = None

    plan:            Plan | None    = None

    leverage:        float | None   = None
    tac_hours:       float | None   = None

    error:           str | None     = None
    extra:           dict[str, Any] = PydanticField(default_factory=dict)


class TaskRequest(BaseModel):
    task:           str        = PydanticField(min_length=1)
    producer_model: str | None = None
    no_wiggum:      bool       = False
    no_memory:      bool       = False


class QueueItem(BaseModel):
    item_id:   str
    task:      str
    status:    str        = "pending"   # pending | running | done | error
    run_id:    str | None = None
    queued_at: datetime   = PydanticField(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# CLI (project management)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Harness project management")
    sub = parser.add_subparsers(dest="cmd")

    cp = sub.add_parser("create-project", help="Create a new project")
    cp.add_argument("--name",        required=True)
    cp.add_argument("--description", default="")
    cp.add_argument("--tags",        default="", help="Comma-separated tags")

    sub.add_parser("list-projects", help="List all projects")

    sp = sub.add_parser("set-project", help="Set active project")
    sp.add_argument("project_id")

    ps = sub.add_parser("project-stats", help="Aggregate stats for a project")
    ps.add_argument("project_id", nargs="?", default=None)

    args = parser.parse_args()

    if args.cmd == "create-project":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        p = create_project(args.name, args.description, tags)
        print(json.dumps(p.to_dict(), indent=2))

    elif args.cmd == "list-projects":
        projects = list_projects()
        if not projects:
            print("No projects found.")
        else:
            for proj in projects:
                status = proj.get("status", "?")
                pid    = proj.get("project_id", "?")
                name   = proj.get("name", "?")
                print(f"  [{status}]  {pid}  {name}")

    elif args.cmd == "set-project":
        set_project(args.project_id)
        print(f"Active project: {args.project_id}")

    elif args.cmd == "project-stats":
        pid = args.project_id or resolve_project_id()
        stats = project_stats(pid)
        print(json.dumps(stats, indent=2))

    else:
        parser.print_help()
        sys.exit(1)

"""
harness/schema.py — Pydantic models for all structured data in the harness.

These replace the ad-hoc dict shapes currently spread across logger.py,
planner.py, wiggum.py, and agent.py.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TaskType(str, Enum):
    enumerated    = "enumerated"
    best_practices = "best_practices"
    research      = "research"
    email         = "email"
    annotate      = "annotate"
    unknown       = "unknown"


class RunFinal(str, Enum):
    PASS  = "PASS"
    FAIL  = "FAIL"
    ERROR = "ERROR"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class StageTokens(BaseModel):
    input:       int = 0
    output:      int = 0
    calls:       int = 0
    total_ms:    int = 0
    thinking_chars: int = 0


class ToolCall(BaseModel):
    name:         str
    query:        str | None = None
    path:         str | None = None
    result_chars: int = 0
    cached:       bool = False


class WiggumDim(BaseModel):
    relevance:    float
    completeness: float
    depth:        float
    specificity:  float
    structure:    float


class Plan(BaseModel):
    search_queries:    list[str]  = Field(default_factory=list)
    expected_sections: int | None = None
    known_facts:       list[str]  = Field(default_factory=list)
    knowledge_gaps:    list[str]  = Field(default_factory=list)
    prior_work_summary: str       = ""
    notes:             str        = ""
    subtasks:          list[str]  = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Run record — what gets appended to runs.jsonl
# ---------------------------------------------------------------------------

class RunRecord(BaseModel):
    run_id:         str
    timestamp:      datetime
    task:           str
    task_type:      TaskType        = TaskType.unknown
    producer_model: str
    evaluator_model: str

    # Timing
    run_duration_s: float           = 0.0

    # Tokens
    input_tokens:   int             = 0
    output_tokens:  int             = 0
    tokens_by_stage: dict[str, StageTokens] = Field(default_factory=dict)

    # Tools
    tool_calls:     list[ToolCall]  = Field(default_factory=list)
    files_read:     list[str]       = Field(default_factory=list)
    vision_images:  list[str]       = Field(default_factory=list)
    memory_hits:    int             = 0
    injection_stripped: int         = 0

    # Output
    output_path:    str | None      = None
    output_bytes:   int             = 0
    output_lines:   int             = 0
    synth_forced:   bool            = False

    # Evaluation
    wiggum_rounds:  int             = 0
    wiggum_scores:  list[float]     = Field(default_factory=list)
    wiggum_dims:    list[WiggumDim] = Field(default_factory=list)
    synth_cot:      list[str]       = Field(default_factory=list)
    final:          RunFinal | None = None

    # Planning
    plan:           Plan | None     = None

    # Derived metrics (backfilled by analytics)
    leverage:       float | None    = None
    tac_hours:      float | None    = None

    # Misc
    error:          str | None      = None
    extra:          dict[str, Any]  = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Queue / task submission
# ---------------------------------------------------------------------------

class TaskRequest(BaseModel):
    task:           str
    producer_model: str | None = None
    no_wiggum:      bool       = False
    no_memory:      bool       = False


class QueueItem(BaseModel):
    item_id:   str
    task:      str
    status:    str   = "pending"   # pending | running | done | error
    run_id:    str | None = None
    queued_at: datetime   = Field(default_factory=datetime.utcnow)

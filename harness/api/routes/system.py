"""
GET  /api/system/files          — list governance files
GET  /api/system/files/{key}    — file content (max 80KB, truncated beyond)
PATCH /api/system/files/{key}   — save editable file
GET  /api/system/config         — non-secret config + synth instructions
GET  /api/system/skills         — skills registry summary
"""

import os

from fastapi import APIRouter, Body, HTTPException

from harness.config import DATA_DIR, ROOT

router = APIRouter(tags=["system"])

# ---------------------------------------------------------------------------
# Governance file registry — explicit allowlist, no path traversal possible
# ---------------------------------------------------------------------------

_WIKI = ROOT / "harness" / "skills" / "wiki"

GOVERNANCE_FILES: dict[str, dict] = {
    "agents":        {"path": ROOT / "AGENTS.md",            "label": "AGENTS.md",          "group": "Governance",  "editable": True},
    "roadmap":       {"path": ROOT / "ROADMAP.md",           "label": "ROADMAP.md",          "group": "Governance",  "editable": False},
    "skills-wiki":   {"path": _WIKI / "skills.md",           "label": "skills.md",           "group": "Knowledge",   "editable": True},
    "eval-wiki":     {"path": _WIKI / "evaluation.md",       "label": "evaluation.md",       "group": "Knowledge",   "editable": True},
    "pipeline-wiki": {"path": _WIKI / "pipeline.md",         "label": "pipeline.md",         "group": "Knowledge",   "editable": True},
    "cli-wiki":      {"path": _WIKI / "cli.md",              "label": "cli.md",              "group": "Knowledge",   "editable": True},
    "user-profile":  {"path": DATA_DIR / "user_profile.md",  "label": "user_profile.md",     "group": "User",        "editable": True},
    "user-config":   {"path": ROOT / ".harness-user.toml",   "label": ".harness-user.toml",  "group": "User",        "editable": True},
}

_MAX_BYTES = 80_000

# Env var names that are safe to surface (no secrets, keys, or tokens)
_SAFE_ENV = {
    "INFERENCE_BACKEND", "VLLM_BASE_URL", "VLLM_MODEL_MAP",
    "HARNESS_PRODUCER_MODEL", "HARNESS_EVALUATOR_MODEL", "HARNESS_EVALUATOR_POOL",
    "HARNESS_ENDPOINTS", "HARNESS_EMBED_MODEL", "HARNESS_SYNTH_CONTEXT_MAX",
    "SUMMARIZER_MODEL", "COMPRESS_MODEL", "SUMMARIZER_EVAL_THRESHOLD", "SUMMARIZER_REVISE_THRESHOLD",
    "WIGGUM_MAX_ROUNDS", "WIGGUM_PANEL", "WIGGUM_PRODUCER_MODEL", "WIGGUM_EVALUATOR_MODEL",
    "RESEARCH_CACHE", "WHISPER_DEVICE", "LLAMA_OCR_BASE_URL",
    "SENDER_NAME", "SENDER_COMPANY", "GIT_STATE",
    "HARNESS_MCP_HOST", "HARNESS_MCP_PORT",
}


# ---------------------------------------------------------------------------
# File endpoints
# ---------------------------------------------------------------------------

@router.get("/system/files")
async def list_files():
    result = []
    for key, meta in GOVERNANCE_FILES.items():
        p = meta["path"]
        exists = p.exists()
        result.append({
            "key":      key,
            "label":    meta["label"],
            "group":    meta["group"],
            "editable": meta["editable"],
            "exists":   exists,
            "size":     p.stat().st_size if exists else 0,
        })
    return result


@router.get("/system/files/{key}")
async def get_file(key: str):
    meta = GOVERNANCE_FILES.get(key)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Unknown file key: {key!r}")
    p = meta["path"]
    if not p.exists():
        return {"key": key, "label": meta["label"], "content": "", "truncated": False,
                "editable": meta["editable"], "exists": False}
    raw = p.read_bytes()
    truncated = len(raw) > _MAX_BYTES
    content = raw[:_MAX_BYTES].decode("utf-8", errors="replace")
    return {
        "key":      key,
        "label":    meta["label"],
        "content":  content,
        "truncated": truncated,
        "editable": meta["editable"],
        "exists":   True,
        "size":     len(raw),
    }


@router.patch("/system/files/{key}")
async def save_file(key: str, body: dict = Body(...)):
    meta = GOVERNANCE_FILES.get(key)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Unknown file key: {key!r}")
    if not meta["editable"]:
        raise HTTPException(status_code=403, detail=f"{meta['label']} is read-only")
    content: str = body.get("content", "")
    p = meta["path"]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"ok": True, "key": key, "size": len(content.encode())}


# ---------------------------------------------------------------------------
# Config endpoint
# ---------------------------------------------------------------------------

@router.get("/system/config")
async def get_config():
    from harness.config import settings

    env_vars = {k: os.environ.get(k, "") for k in _SAFE_ENV if os.environ.get(k)}

    settings_dict = {
        "producer_model":    settings.producer_model,
        "evaluator_model":   settings.evaluator_model,
        "vision_model":      settings.vision_model,
        "embed_model":       settings.embed_model,
        "pass_threshold":    settings.pass_threshold,
        "wiggum_max_rounds": settings.wiggum_max_rounds,
        "subtask_max_workers": settings.subtask_max_workers,
        "research_cache":    settings.research_cache,
        "wiggum_panel":      settings.wiggum_panel,
        "port":              settings.port,
        "host":              settings.host,
    }

    synth: dict = {}
    try:
        from harness.agent import (
            SYNTH_INSTRUCTION,
            SYNTH_INSTRUCTION_COUNT,
            SYNTH_INSTRUCTION_PROSE,
        )
        synth = {
            "default": SYNTH_INSTRUCTION,
            "count":   SYNTH_INSTRUCTION_COUNT,
            "prose":   SYNTH_INSTRUCTION_PROSE,
        }
    except Exception:
        pass

    return {
        "env":      env_vars,
        "settings": settings_dict,
        "synth":    synth,
    }


# ---------------------------------------------------------------------------
# Skills endpoint
# ---------------------------------------------------------------------------

@router.get("/system/skills")
async def get_skills():
    try:
        from harness.skills import REGISTRY
        return [
            {
                "name":        name,
                "description": entry.get("description", ""),
                "hook":        entry.get("hook", ""),
                "has_auto":    entry.get("auto") is not None,
                "has_prompt":  bool(entry.get("prompt")),
            }
            for name, entry in REGISTRY.items()
        ]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

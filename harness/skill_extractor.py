"""
harness/skill_extractor.py — Post-run skill extraction.

After each completed run, extract compact procedural knowledge from the
trajectory and Wiggum feedback, and store it in the memory system so future
agents on similar tasks skip the exploration phase.

Stored as task_type="skill" observations — the memory retrieval system
surfaces them alongside regular run observations during planning.

Called from agent.py post-Wiggum (non-blocking; errors are swallowed).
Also callable as a batch pass over runs.jsonl:
    python -m harness.skill_extractor --runs data/runs.jsonl [--limit 50]
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_BROWSER_EXTRACT_PROMPT = """\
You are a browser-skill extractor for an AI navigation agent.

A browser task just completed. Extract compact, reusable knowledge about how to \
navigate this domain — what a future agent should do on the FIRST visit to find \
the same kind of content, without the exploration overhead.

TASK: {task}
START URL: {start_url}
FINAL URL (where content was found): {final_url}
GOAL: {goal}

NAVIGATION HISTORY (url → title → note):
{nav_history}

Output ONLY valid JSON (no markdown fences):
{{
  "domain": "hostname only, e.g. github.com",
  "goal_type": "snake_case label for what was sought, e.g. release_notes, api_docs, pricing",
  "entry_url": "the best direct URL to bookmark for this goal type",
  "working_path": ["url1", "url2"],
  "page_flow": ["step 1 ≤15 words", "step 2 ≤15 words", "step 3 ≤15 words"],
  "pitfalls": ["thing that wasted steps or should be avoided ≤15 words"]
}}

Rules:
- domain: hostname only (no path)
- goal_type: 2-4 words snake_case
- entry_url: the single best direct URL for this goal; omit if start_url was correct
- working_path: ordered list of URLs that led to the content (max 5)
- page_flow: 2-5 concrete navigation steps a future agent can follow
- pitfalls: 0-3 items, only if clearly wasteful or confusing
- No commentary, no extra keys."""


def _summarise_nav_history(history: list[dict]) -> str:
    if not history:
        return "(no navigation history)"
    lines = []
    for h in history:
        url   = h.get("url", "")[:80]
        title = h.get("title", "")[:50]
        note  = h.get("note", "")
        line  = f"  {url}  [{title}]"
        if note:
            line += f"  — {note}"
        lines.append(line)
    return "\n".join(lines)


def _extract_browser_skill(task: str, start_url: str, final_url: str,
                            goal: str, history: list[dict], model: str) -> dict | None:
    try:
        from harness.inference import chat as _chat
    except ImportError:
        return None

    prompt = _BROWSER_EXTRACT_PROMPT.format(
        task=task,
        start_url=start_url,
        final_url=final_url,
        goal=goal,
        nav_history=_summarise_nav_history(history),
    )
    try:
        resp = _chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.0, "num_predict": 512, "think": False},
        )
        raw = resp["message"]["content"].strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        return json.loads(raw)
    except Exception as e:
        print(f"  [browser_skill] extraction failed: {e}")
        return None


def _store_browser_skill(skill: dict, task: str, run_id: str) -> bool:
    try:
        from harness.memory import MemoryStore
        from harness.config import DATA_DIR
    except ImportError:
        return False

    domain    = skill.get("domain", "unknown")
    goal_type = skill.get("goal_type", "unknown")
    entry_url = skill.get("entry_url", "")
    path      = skill.get("working_path", [])
    flow      = skill.get("page_flow", [])
    pitfalls  = skill.get("pitfalls", [])

    if not flow:
        return False

    narrative_parts = [f"Domain: {domain}  Goal: {goal_type}"]
    if entry_url:
        narrative_parts.append(f"Direct URL: {entry_url}")
    if path:
        narrative_parts += ["Path:"] + [f"  {u}" for u in path]
    narrative_parts += ["Steps:"] + [f"- {s}" for s in flow]
    if pitfalls:
        narrative_parts += ["Pitfalls:"] + [f"- {p}" for p in pitfalls]
    narrative = "\n".join(narrative_parts)

    facts = flow + ([f"entry: {entry_url}"] if entry_url else []) + [f"pitfall: {p}" for p in pitfalls]
    tag   = f"{domain}/{goal_type}"

    db_path = str(DATA_DIR / "memory.db")
    store   = MemoryStore(db_path=db_path)
    rowid   = store.store_direct(
        task        = f"browser_skill:{tag}",
        task_type   = "browser_skill",
        title       = f"Browser skill: {tag}",
        narrative   = narrative,
        facts       = facts,
        final_score = 0.0,
        final       = "PASS",
        output_path = run_id,
    )
    return rowid > 0


def extract_browser_skill_and_store(
    task: str,
    trace_data: dict,
    model: str,
    run_id: str = "",
) -> bool:
    """
    Extract a browser navigation skill from a completed playwright run and store it.
    Called post-run when task_type == 'playwright'. Errors are non-fatal.
    """
    history   = trace_data.get("browser_history") or []
    if not history:
        return False

    from urllib.parse import urlparse as _up
    start_url = history[0].get("url", "") if history else ""
    final_url = history[-1].get("url", "") if history else ""

    # Parse goal from task (strip /browser prefix)
    goal = re.sub(r"^/browser\s*", "", task.strip(), flags=re.IGNORECASE)
    # Strip the start URL from the goal text if it appears verbatim
    if start_url:
        goal = goal.replace(start_url, "").strip()
    goal = goal.strip(" ,;") or task

    skill = _extract_browser_skill(task, start_url, final_url, goal, history, model)
    if not skill:
        return False

    stored = _store_browser_skill(skill, task, run_id)
    if stored:
        domain    = skill.get("domain", "?")
        goal_type = skill.get("goal_type", "?")
        print(f"  [browser_skill] stored: '{domain}/{goal_type}'")
    return stored


_EXTRACT_PROMPT = """\
You are a skill extractor for an AI research agent.

A run just completed. Extract compact procedural knowledge — what a future agent \
on a similar task should do differently or faster. Focus on HOW to find good \
information, not WHAT was found.

TASK:
{task}

WIGGUM SCORE: {score}/10
WIGGUM ISSUES (what was weak or missing):
{issues}

TRAJECTORY (queries run and result sizes):
{trajectory_summary}

Output ONLY valid JSON (no markdown fences):
{{
  "topic_tag": "snake_case_2_to_4_words",
  "recipe": ["action bullet 1", "action bullet 2", "action bullet 3"],
  "key_sources": ["domain.com or URL fragment that was high-signal"],
  "effective_queries": ["query text that surfaced good results"],
  "avoid": ["query or source that was low-signal or redundant"]
}}

Rules:
- topic_tag: snake_case slug (e.g. "rest_api_latency", "rag_reranking")
- recipe: 3-5 concrete action bullets, each ≤ 20 words
- key_sources: 0-3 items (omit if nothing stood out)
- effective_queries: 0-3 items
- avoid: 0-2 items (only if clearly wasteful)
- No commentary, no extra keys."""


def _summarise_trajectory(trajectory: list[dict]) -> str:
    if not trajectory:
        return "(no trajectory recorded)"
    lines = []
    for step in trajectory:
        stage = step.get("stage", "?")
        tool  = step.get("tool", "")
        query = step.get("query", "")
        chars = step.get("result_chars", 0)
        if query:
            lines.append(f"  [{stage}] {tool}: {query[:80]}  ({chars} chars)")
    return "\n".join(lines) if lines else "(no search steps recorded)"


def _extract_skill(task: str, trajectory: list[dict],
                   wiggum_issues: list[str], score: float,
                   model: str) -> dict | None:
    try:
        from harness.inference import chat as _chat
    except ImportError:
        return None

    issues_text = "\n".join(f"- {i}" for i in wiggum_issues) if wiggum_issues else "(none)"
    prompt = _EXTRACT_PROMPT.format(
        task=task,
        score=round(score, 1),
        issues=issues_text,
        trajectory_summary=_summarise_trajectory(trajectory),
    )

    try:
        resp = _chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.0, "num_predict": 512, "think": False},
        )
        raw = resp["message"]["content"].strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        return json.loads(raw)
    except Exception as e:
        print(f"  [skill] extraction failed: {e}")
        return None


def _store_skill(skill: dict, task: str, score: float, run_id: str) -> bool:
    try:
        from harness.memory import MemoryStore
        from harness.config import DATA_DIR
    except ImportError:
        return False

    topic_tag = skill.get("topic_tag", "unknown")
    recipe    = skill.get("recipe", [])
    sources   = skill.get("key_sources", [])
    queries   = skill.get("effective_queries", [])
    avoid     = skill.get("avoid", [])

    if not recipe:
        return False

    narrative_parts = ["Recipe:"] + [f"- {r}" for r in recipe]
    if sources:
        narrative_parts += ["Key sources:"] + [f"- {s}" for s in sources]
    if queries:
        narrative_parts += ["Effective queries:"] + [f"- {q}" for q in queries]
    if avoid:
        narrative_parts += ["Avoid:"] + [f"- {a}" for a in avoid]
    narrative = "\n".join(narrative_parts)

    facts = recipe + [f"source: {s}" for s in sources] + [f"query: {q}" for q in queries]

    db_path = str(DATA_DIR / "memory.db")
    store = MemoryStore(db_path=db_path)
    rowid = store.store_direct(
        task      = f"skill:{topic_tag}",
        task_type = "skill",
        title     = f"Skill: {topic_tag.replace('_', ' ')} (score={score:.1f})",
        narrative = narrative,
        facts     = facts,
        final_score = score,
        final     = "PASS",
        output_path = run_id,
    )
    return rowid > 0


def extract_and_store(
    task: str,
    trace_data: dict,
    wiggum_issues: list[str],
    score: float,
    model: str,
    run_id: str = "",
) -> bool:
    """
    Extract a skill from a completed run and store it in memory.
    Returns True if a skill was successfully stored.
    Designed to be called post-Wiggum; all errors are non-fatal.
    """
    if score < 5.0:
        return False

    trajectory = trace_data.get("trajectory") or []
    skill = _extract_skill(task, trajectory, wiggum_issues, score, model)
    if not skill:
        return False

    stored = _store_skill(skill, task, score, run_id)
    if stored:
        tag = skill.get("topic_tag", "?")
        print(f"  [skill] stored: '{tag}'  score={score:.1f}")
    return stored


# ---------------------------------------------------------------------------
# Batch mode
# ---------------------------------------------------------------------------

def _batch(runs_path: Path, limit: int, model: str, min_score: float):
    lines = runs_path.read_text(encoding="utf-8").strip().splitlines()
    if limit:
        lines = lines[-limit:]

    stored = skipped = 0
    for line in lines:
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue

        scores = r.get("wiggum_scores") or []
        if not scores:
            continue
        score = float(scores[-1])
        if score < min_score:
            skipped += 1
            continue

        task = r.get("task", "")
        if not task:
            continue

        issues = [
            issue
            for rd in (r.get("wiggum_eval_log") or [])
            for issue in (rd.get("issues") or [])
        ]
        ok = extract_and_store(
            task         = task,
            trace_data   = r,
            wiggum_issues= issues,
            score        = score,
            model        = model,
            run_id       = r.get("run_id", ""),
        )
        if ok:
            stored += 1
        else:
            skipped += 1

    print(f"\n[skill] batch done — stored={stored} skipped={skipped}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Batch-extract skills from runs.jsonl")
    ap.add_argument("--runs",      required=True,          help="Path to runs.jsonl")
    ap.add_argument("--limit",     type=int, default=0,    help="Process last N runs (0=all)")
    ap.add_argument("--min-score", type=float, default=5.0,help="Minimum wiggum score to process")
    ap.add_argument("--model",     default="",             help="Model override")
    args = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).parent.parent))

    if not args.model:
        from harness.agent import COMPRESS_MODEL
        model = COMPRESS_MODEL
    else:
        model = args.model

    _batch(Path(args.runs), args.limit, model, args.min_score)

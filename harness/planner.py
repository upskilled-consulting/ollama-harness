"""
harness/planner.py — pre-execution task analysis and query planning.

Uses memory context + glm4:9b to produce a structured Plan before research begins.
The plan informs three downstream stages:
  - gather_research : uses planned search queries instead of auto-generating them
  - synthesize      : injects prior work summary + planner notes as context
  - count check     : uses plan.expected_sections when regex misses the constraint

Usage:
    from harness.planner import make_plan, Plan
    plan = make_plan(task, memory_context)
"""

import json
import os
import re
from dataclasses import asdict, dataclass, field

from harness import inference as ollama

try:
    import dirtyjson as _dirtyjson
    _HAS_DIRTYJSON = True
except ImportError:
    _HAS_DIRTYJSON = False


def _json_loads(s: str) -> dict:
    """json.loads with dirtyjson fallback for common model-output defects."""
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        if _HAS_DIRTYJSON:
            try:
                return _dirtyjson.loads(s)
            except Exception:
                pass
        raise


def _extract_string_list(text: str, key: str) -> list[str]:
    """
    Regex extraction of a JSON array value by key — last resort when both JSON
    parsers fail. Handles the common case where the model emits valid-looking
    JSON but with an unescaped quote or literal newline inside a string.
    """
    m = re.search(rf'"{re.escape(key)}"\s*:\s*\[([^\]]*)\]', text, re.DOTALL)
    if not m:
        return []
    return [item.strip() for item in re.findall(r'"([^"]+)"', m.group(1)) if item.strip()]

PLANNER_MODEL = "glm4:9b"

# ---------------------------------------------------------------------------
# Prior knowledge pass
# ---------------------------------------------------------------------------

PRIOR_KNOWLEDGE_PROMPT = """\
You are a research assistant assessing your existing knowledge before running web searches.

Task: {task}
{memory_block}
Without searching the web, answer honestly:
1. What specific facts are you CONFIDENT about regarding this topic? \
Include facts drawn from the memory context above if present.
2. What specific aspects would you NEED to look up to answer this authoritatively? \
If the memory context already provides a complete, high-quality answer, \
gaps should be an empty list [].

Focus on gaps that a web search would actually resolve — not vague uncertainties.

Respond with ONLY valid JSON — no explanation, no markdown fences:
{{
  "known_facts": ["specific fact 1", "specific fact 2"],
  "gaps": ["specific gap requiring lookup 1", "specific gap requiring lookup 2"]
}}

Rules:
- known_facts: 2-5 concrete, specific facts you are confident about
- gaps: 2-4 specific aspects that need current/authoritative sources; \
  [] if memory already covers the task well
- Both lists should be concrete enough that they could inform a search query
"""

# ---------------------------------------------------------------------------
# Main plan prompt
# ---------------------------------------------------------------------------

PLAN_PROMPT = """\
You are a task planner for an AI research agent.

Task: {task}
{memory_block}{knowledge_block}
Produce a structured execution plan. Respond with ONLY valid JSON — no explanation, no markdown fences:

{{
  "task_type": "enumerated|best_practices|research",
  "complexity": "low|medium|high",
  "expected_sections": <integer or null>,
  "search_queries": ["query1", "query2"],
  "prior_work_summary": "<one sentence about relevant prior work, or empty string>",
  "notes": "<one actionable sentence for the producer>",
  "subtasks": []
}}

Rules:
- task_type: "enumerated" if task says "top N" or "N most/common/key/best"; "best_practices" if asking for practices/strategies/guidelines; "research" otherwise
- complexity: "low" for simple factual lookups; "medium" for standard research; "high" for tasks requiring synthesis across 2+ distinct domains
- expected_sections: the integer N from "top N" / "N most", null if not specified
- search_queries: exactly 2 specific, complementary queries targeting the identified knowledge GAPS — do not search for things already known
- prior_work_summary: one sentence summarising what the memory shows, or "" if no relevant history
- notes: one specific actionable note (e.g. "specificity was weak last time — include concrete tool names and version numbers")
- subtasks: EMPTY ARRAY [] for single-focus tasks. Populate with 2-3 items ONLY when the task explicitly asks to research multiple distinct domains and combine/synthesize/integrate them. Each item must be a self-contained WEB RESEARCH directive (e.g. "Research the top 3 failure modes in multi-agent AI systems") — NO synthesis, assembly, or writing steps (the orchestrator handles final assembly). NO file paths.
"""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Plan:
    task_type: str = "research"
    complexity: str = "medium"
    expected_sections: int | None = None
    search_queries: list[str] = field(default_factory=list)
    prior_work_summary: str = ""
    notes: str = ""
    subtasks: list[str] = field(default_factory=list)
    known_facts: list[str] = field(default_factory=list)
    knowledge_gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def synthesis_context(self) -> str:
        """Build the context block injected into synthesis alongside memory."""
        lines = []
        if self.prior_work_summary:
            lines.append(f"**Prior work:** {self.prior_work_summary}")
        if self.notes:
            lines.append(f"**Planner note:** {self.notes}")
        if self.known_facts:
            facts_block = "\n".join(f"- {f}" for f in self.known_facts)
            lines.append(f"**Verified facts (no search needed):**\n{facts_block}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def prior_knowledge_pass(task: str, memory_context: str = "") -> tuple[list[str], list[str]]:
    """
    Ask the planner model what it already knows and what gaps need web search.

    Returns (known_facts, gaps) — both are lists of strings.
    Returns ([], []) on any failure — never raises.
    Used by make_plan() to seed targeted search queries.
    """
    memory_block = f"Relevant memory from prior runs:\n{memory_context}\n\n" if memory_context else ""
    prompt = PRIOR_KNOWLEDGE_PROMPT.format(task=task, memory_block=memory_block)
    try:
        response = ollama.chat(
            model=PLANNER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1, "think": False},
        )
        text = response["message"]["content"].strip()
        text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'\s*```$', '', text, flags=re.MULTILINE)
        json_match = re.search(r'\{.*\}', text.strip(), re.DOTALL)
        if not json_match:
            return [], []
        raw = json_match.group(0)
        try:
            data = _json_loads(raw)
            known = [str(f).strip() for f in data.get("known_facts", []) if str(f).strip()]
            gaps  = [str(g).strip() for g in data.get("gaps", []) if str(g).strip()]
        except Exception:
            # Both JSON parsers failed — extract arrays directly with regex
            known = _extract_string_list(raw, "known_facts")
            gaps  = _extract_string_list(raw, "gaps")
            if known or gaps:
                print("  [planner:prior] JSON malformed — recovered via regex")
        return known, gaps
    except Exception as e:
        print(f"  [planner:prior] failed ({e}) — skipping")
        return [], []


def make_plan(task: str, memory_context: str = "") -> tuple["Plan", object]:
    """
    Analyse the task and memory context to produce a Plan.

    Runs a prior knowledge pass first: asks the model what it already knows
    and what gaps need web search. Gaps seed query generation so searches
    target unknowns rather than topics the model already handles well.

    Returns (Plan, response) — response is the raw ollama ChatResponse for token logging.
    Returns (Plan(), None) on any failure — never raises.
    """
    # Prior knowledge pass — fast single call, informs query targeting
    # Skippable via HARNESS_SKIP_PRIOR_KNOWLEDGE=1 for controlled experiments
    known_facts: list[str] = []
    gaps: list[str] = []
    if os.environ.get("HARNESS_SKIP_PRIOR_KNOWLEDGE") != "1":
        known_facts, gaps = prior_knowledge_pass(task, memory_context)
        if known_facts or gaps:
            print(f"  [planner:prior] {len(known_facts)} known fact(s), {len(gaps)} gap(s) identified")
    else:
        print("  [planner:prior] skipped (HARNESS_SKIP_PRIOR_KNOWLEDGE=1)")

    # Build knowledge block for the main plan prompt
    knowledge_block = ""
    if known_facts or gaps:
        lines = []
        if known_facts:
            lines.append("Already known (skip searching for these):")
            lines.extend(f"  - {f}" for f in known_facts)
        if gaps:
            lines.append("Gaps to fill via web search:")
            lines.extend(f"  - {g}" for g in gaps)
        knowledge_block = "\n".join(lines) + "\n\n"

    memory_block = f"Relevant past work:\n{memory_context}\n\n" if memory_context else ""
    prompt = PLAN_PROMPT.format(task=task, memory_block=memory_block, knowledge_block=knowledge_block)

    try:
        response = ollama.chat(
            model=PLANNER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1},
        )
        text = response["message"]["content"].strip()
        plan = _parse_plan(text)
        # Attach prior knowledge to the plan for downstream use
        plan.known_facts = known_facts
        plan.knowledge_gaps = gaps
        return plan, response
    except Exception as e:
        print(f"  [planner] failed ({e}) — using defaults")
        return Plan(known_facts=known_facts, knowledge_gaps=gaps), None


def _parse_plan(text: str) -> Plan:
    """Parse the JSON plan response. Falls back to defaults on any error."""
    # Strip markdown code fences if present
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```$', '', text, flags=re.MULTILINE)

    json_match = re.search(r'\{.*\}', text.strip(), re.DOTALL)
    if not json_match:
        return Plan()

    try:
        data = _json_loads(json_match.group(0))
    except Exception:
        return Plan()

    # expected_sections: accept integer or stringified integer, reject anything else
    raw_sections = data.get("expected_sections")
    expected_sections = None
    if raw_sections is not None:
        try:
            expected_sections = int(raw_sections)
        except (ValueError, TypeError):
            pass

    queries = [
        q.strip() for q in data.get("search_queries", [])
        if isinstance(q, str) and q.strip()
    ]

    # Filter out synthesis/assembly subtasks — those are the orchestrator's job
    _ASSEMBLY_WORDS = re.compile(
        r'\b(synthesize|synthesise|assemble|combine|integrate|unify|merge|compile|write|create)\b',
        re.IGNORECASE,
    )
    raw_subtasks = data.get("subtasks", [])
    subtasks = [
        s.strip() for s in raw_subtasks
        if isinstance(s, str) and s.strip() and not _ASSEMBLY_WORDS.search(s)
    ]

    return Plan(
        task_type=data.get("task_type", "research"),
        complexity=data.get("complexity", "medium"),
        expected_sections=expected_sections,
        search_queries=queries,
        prior_work_summary=str(data.get("prior_work_summary", "") or "").strip(),
        notes=str(data.get("notes", "") or "").strip(),
        subtasks=subtasks,
    )


# ---------------------------------------------------------------------------
# CLI — test the planner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    from harness.memory import MemoryStore

    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        "Search for the top 3 context window management strategies for production LLM applications "
        "and save to ~/Desktop/harness-engineering/test-plan.md"
    )

    store = MemoryStore()
    memory_ctx = store.get_context(task)

    print(f"Task: {task}")
    print(f"Memory hits: {memory_ctx.count('**[') if memory_ctx else 0}\n")
    print("[planner] generating plan...")

    plan, _ = make_plan(task, memory_ctx)

    print("\nPlan:")
    print(f"  task_type:         {plan.task_type}")
    print(f"  complexity:        {plan.complexity}")
    print(f"  expected_sections: {plan.expected_sections}")
    print("  search_queries:")
    for q in plan.search_queries:
        print(f"    - {q}")
    print(f"  prior_work_summary: {plan.prior_work_summary!r}")
    print(f"  notes:              {plan.notes!r}")
    print(f"  known_facts ({len(plan.known_facts)}):")
    for f in plan.known_facts:
        print(f"    - {f}")
    print(f"  knowledge_gaps ({len(plan.knowledge_gaps)}):")
    for g in plan.knowledge_gaps:
        print(f"    - {g}")
    print(f"  subtasks ({len(plan.subtasks)}):")
    for s in plan.subtasks:
        print(f"    - {s}")

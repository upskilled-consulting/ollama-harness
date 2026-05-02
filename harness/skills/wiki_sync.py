"""
wiki_sync.py — /sync-wiki skill

Extracts implementation facts from source code deterministically (regex, no LLM)
and writes a structured ## Implementation Reference section into wiki/pipeline.md.

Markers keep the section idempotent — re-running replaces only the generated block.

Usage (standalone):
    python wiki_sync.py

Via agent skill:
    python agent.py "/sync-wiki"
    python agent.py "/sync-wiki save to ~/Desktop/harness-engineering/sync-report.md"
"""

import re
from datetime import date
from pathlib import Path

ROOT         = Path(__file__).parent.parent
WIKI_TARGET  = ROOT / "wiki" / "pipeline.md"
MARKER_START = "<!-- sync-wiki:start -->"
MARKER_END   = "<!-- sync-wiki:end -->"


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _extract_const(src: str, name: str) -> str:
    """Extract a simple scalar constant assignment: NAME = <value>"""
    m = re.search(rf'^{re.escape(name)}\s*=\s*(.+)', src, re.MULTILINE)
    if not m:
        return "?"
    val = m.group(1).strip()
    val = re.sub(r'\s*#.*$', '', val).strip().rstrip(",")  # strip inline comments
    # Strip os.environ.get wrapper — return the default value
    env_m = re.search(r'os\.environ\.get\([^,]+,\s*["\']?([^"\')\s]+)["\']?\)', val)
    if env_m:
        return env_m.group(1).strip('"\'')
    return val.strip('"|\'')


def _extract_synth_instruction(src: str) -> str:
    """Extract SYNTH_INSTRUCTION text between the autoresearch sentinels."""
    m = re.search(
        r'AUTORESEARCH:SYNTH_INSTRUCTION:BEGIN\s*\n'
        r'SYNTH_INSTRUCTION\s*=\s*\(\s*\n\s*"(.*?)"\s*\n\s*\)',
        src, re.DOTALL
    )
    if m:
        return m.group(1).strip()
    # Fallback: single-line or parenthesised
    m2 = re.search(r'SYNTH_INSTRUCTION\s*=\s*\(?\s*"(.*?)"', src, re.DOTALL)
    return m2.group(1).strip()[:600] + "…" if m2 else "?"


def _extract_model_map(src: str) -> list[tuple[str, str]]:
    """Extract _MODEL_MAP literal entries."""
    block_m = re.search(r'_MODEL_MAP:\s*dict\[.*?\]\s*=\s*\{(.*?)\}', src, re.DOTALL)
    if not block_m:
        return []
    rows = []
    for line in block_m.group(1).splitlines():
        m = re.match(r'\s*"([^"]+)"\s*:\s*"([^"]+)"', line)
        if m:
            rows.append((m.group(1), m.group(2)))
    return rows


def _extract_dim_weights(src: str) -> list[tuple[str, str, str]]:
    """Extract wiggum dimension weights from the main EVAL_PROMPT block only."""
    # Scope to the first EVAL_PROMPT definition (research evaluator, not annotate)
    block_m = re.search(r'EVAL_PROMPT\s*=\s*"""(.*?)"""', src, re.DOTALL)
    block = block_m.group(1) if block_m else src
    rows = []
    for m in re.finditer(r'- (\w+) \(weight ([\d.]+)\): (.+)', block):
        rows.append((m.group(1), m.group(2), m.group(3).strip()))
    return rows


# ---------------------------------------------------------------------------
# Section builder
# ---------------------------------------------------------------------------

def build_section() -> tuple[str, list[str]]:
    """
    Read source files, extract facts, return (markdown_section, change_summary).
    """
    agent_src  = _read("agent.py")
    wiggum_src = _read("wiggum.py")
    plan_src   = _read("planner.py")
    orch_src   = _read("orchestrator.py")
    mem_src    = _read("memory.py")
    inf_src    = _read("inference.py")

    today = date.today().isoformat()

    # --- Models by stage ---
    producer_model   = _extract_const(agent_src,  "MODEL")
    wiggum_producer  = _extract_const(wiggum_src, "PRODUCER_MODEL")
    wiggum_evaluator = _extract_const(wiggum_src, "EVALUATOR_MODEL")
    planner_model    = _extract_const(plan_src,   "PLANNER_MODEL")
    assembly_model   = _extract_const(orch_src,   "ASSEMBLY_MODEL")

    model_table = (
        "| Stage | Model | Override Env Var |\n"
        "|-------|-------|------------------|\n"
        f"| Producer (synthesis) | `{producer_model}` | `HARNESS_PRODUCER_MODEL` |\n"
        f"| Wiggum producer (revision) | `{wiggum_producer}` | `WIGGUM_PRODUCER_MODEL` |\n"
        f"| Wiggum evaluator | `{wiggum_evaluator}` | `WIGGUM_EVALUATOR_MODEL` |\n"
        f"| Planner | `{planner_model}` | — |\n"
        f"| Orchestrator assembly | `{assembly_model}` | — |\n"
    )

    # --- Key constants ---
    max_search   = _extract_const(agent_src,  "MAX_SEARCH_ROUNDS")
    nov_thresh   = _extract_const(agent_src,  "NOVELTY_THRESHOLD")
    nov_eps      = _extract_const(agent_src,  "NOVELTY_EPSILON")
    pass_thresh  = _extract_const(wiggum_src, "PASS_THRESHOLD")
    max_rounds   = _extract_const(wiggum_src, "MAX_ROUNDS")
    max_obs      = _extract_const(mem_src,    "MAX_CONTEXT_OBSERVATIONS")
    sem_cands    = _extract_const(mem_src,    "SEMANTIC_CANDIDATES")
    sub_workers  = _extract_const(orch_src,   "SUBTASK_MAX_WORKERS")
    sub_retries  = _extract_const(orch_src,   "SUBTASK_MAX_RETRIES")

    const_table = (
        "| Constant | Value | File | Effect |\n"
        "|----------|-------|------|--------|\n"
        f"| `MAX_SEARCH_ROUNDS` | {max_search} | agent.py | Hard cap on research iterations |\n"
        f"| `NOVELTY_THRESHOLD` | {nov_thresh} | agent.py | Stop if new results score below this (0–10) |\n"
        f"| `NOVELTY_EPSILON` | {nov_eps} | agent.py | Pass-through rate for sub-threshold rounds |\n"
        f"| `PASS_THRESHOLD` | {pass_thresh} | wiggum.py | Score required to exit wiggum loop |\n"
        f"| `MAX_ROUNDS` | {max_rounds} | wiggum.py | Max wiggum revision rounds |\n"
        f"| `MAX_CONTEXT_OBSERVATIONS` | {max_obs} | memory.py | Observations injected per run |\n"
        f"| `SEMANTIC_CANDIDATES` | {sem_cands} | memory.py | Over-fetch count before re-ranking |\n"
        f"| `SUBTASK_MAX_WORKERS` | {sub_workers} | orchestrator.py | Parallel subtask threads |\n"
        f"| `SUBTASK_MAX_RETRIES` | {sub_retries} | orchestrator.py | Retries per failed subtask |\n"
    )

    # --- Wiggum dimension weights ---
    dim_rows = _extract_dim_weights(wiggum_src)
    if dim_rows:
        dim_table = (
            "| Dimension | Weight | What it measures |\n"
            "|-----------|--------|------------------|\n"
        )
        for name, weight, desc in sorted(dim_rows, key=lambda x: -float(x[1])):
            dim_table += f"| `{name}` | {weight} | {desc[:80]} |\n"
    else:
        dim_table = "_Could not extract dimension weights._\n"

    # --- Memory ranking formula ---
    rank_line = "rank = 0.7 × semantic_similarity + 0.3 × quality_score"
    rl_m = re.search(r'rank\s*=\s*0\.[0-9]+\s*\*\s*sim\s*\+\s*0\.[0-9]+\s*\*\s*qual', mem_src)
    if rl_m:
        rank_line = rl_m.group(0).replace("*", "×").replace("sim", "semantic_similarity").replace("qual", "quality_score")
    qual_floor_m = re.search(r'raw_score\s*<\s*([\d.]+)', mem_src)
    qual_floor = qual_floor_m.group(1) if qual_floor_m else "7.0"

    # --- Model map (vLLM) ---
    model_map_rows = _extract_model_map(inf_src)
    if model_map_rows:
        mm_table = (
            "| Ollama tag | vLLM / HF model ID |\n"
            "|------------|--------------------|\n"
        )
        for tag, hf in model_map_rows:
            mm_table += f"| `{tag}` | `{hf}` |\n"
    else:
        mm_table = "_Could not extract model map._\n"

    # --- SYNTH_INSTRUCTION ---
    synth_instr = _extract_synth_instruction(agent_src)

    # --- Assemble section ---
    section = f"""{MARKER_START}
## Implementation Reference

*Auto-generated by `/sync-wiki` on {today}. Do not edit — re-run `/sync-wiki` to update.*

### Models by Stage

{model_table}
### Key Constants

{const_table}
### Wiggum Evaluation Weights

Composite score formula: `0.20×relevance + 0.25×completeness + 0.30×depth + 0.15×specificity + 0.10×structure`

{dim_table}
### Memory Retrieval Ranking

`{rank_line}`

- Observations scoring below `{qual_floor}` are half-weighted in quality component
- Results deduplicated by title — only the highest-ranked observation per unique title is kept
- `SEMANTIC_CANDIDATES = {sem_cands}` fetched from ChromaDB, re-ranked, top `{max_obs}` injected

### Synthesis Instruction (SYNTH_INSTRUCTION)

> {synth_instr}

### Model Map (Ollama → vLLM)

Used when `INFERENCE_BACKEND=vllm`. Built-in defaults (overridden by `VLLM_MODEL_MAP` env var):

{mm_table}
{MARKER_END}"""

    changes = [
        f"producer={producer_model}",
        f"evaluator={wiggum_evaluator}",
        f"planner={planner_model}",
        f"pass_threshold={pass_thresh}",
        f"max_search_rounds={max_search}",
        f"max_context_observations={max_obs}",
        f"quality_floor={qual_floor}",
        f"dim_weights extracted ({len(dim_rows)} dims)",
        f"model_map entries: {len(model_map_rows)}",
    ]
    return section, changes


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def sync() -> str:
    """
    Build the implementation reference section and inject it into wiki/pipeline.md.
    Returns a summary string suitable for use as synthesis context.
    """
    if not WIKI_TARGET.exists():
        return f"[sync-wiki] ERROR: {WIKI_TARGET} not found"

    section, changes = build_section()

    original = WIKI_TARGET.read_text(encoding="utf-8")

    # Replace existing block if present, otherwise append
    if MARKER_START in original and MARKER_END in original:
        updated = re.sub(
            re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END),
            section,
            original,
            flags=re.DOTALL,
        )
        action = "updated"
    else:
        updated = original.rstrip() + "\n\n" + section + "\n"
        action = "appended"

    WIKI_TARGET.write_text(updated, encoding="utf-8")

    summary_lines = [
        f"# /sync-wiki completed — {action} Implementation Reference in wiki/pipeline.md",
        "",
        f"**Date:** {date.today().isoformat()}",
        f"**Target:** `{WIKI_TARGET}`",
        "",
        "## Facts extracted",
        "",
    ] + [f"- {c}" for c in changes] + [
        "",
        "## What was written",
        "",
        "- **Models by stage table**: producer, evaluator, planner, assembly models with env var overrides",
        "- **Key constants table**: search rounds, novelty threshold/epsilon, wiggum pass threshold and max rounds, memory observation count, subtask parallelism",
        "- **Wiggum dimension weights**: all 5 scoring dimensions with weights and descriptions",
        "- **Memory ranking formula**: exact blending formula + quality floor + deduplication logic",
        "- **SYNTH_INSTRUCTION**: active synthesis prompt text",
        "- **Model map**: Ollama tag → vLLM/HF model ID mapping",
    ]

    return "\n".join(summary_lines)


# ---------------------------------------------------------------------------
# Gap-targeted extraction
# ---------------------------------------------------------------------------

GAP_MARKER_START = "<!-- sync-wiki-gaps:start -->"
GAP_MARKER_END   = "<!-- sync-wiki-gaps:end -->"

# Each entry: list of trigger substrings (case-insensitive) → extraction spec
# extract: ("string_const", name) | ("function", name, max_lines) | ("heredoc", name)
GAP_EXTRACTIONS = [
    {
        "triggers": ["prompted", "plan prompt", "plan format", "plan structure",
                     "planner makes decisions", "task classification", "how classified",
                     "complexity analysis", "plan is validated"],
        "label": "Planning prompts (planner.py)",
        "entries": [
            ("planner.py", "heredoc", "PRIOR_KNOWLEDGE_PROMPT", 20,
             "Prior knowledge pass — asks model what it already knows before any search"),
            ("planner.py", "heredoc", "PLAN_PROMPT", 20,
             "Main planning prompt — produces task_type, complexity, queries"),
        ],
    },
    {
        "triggers": ["evaluation criteria", "how revision", "revision logic",
                     "how the evaluator", "evaluation loop", "revision process",
                     "specific evaluation", "how suggestions are generated"],
        "label": "Evaluation prompt (wiggum.py)",
        "entries": [
            ("wiggum.py", "string_const", "EVAL_PROMPT", 40,
             "Full wiggum evaluation prompt — defines scoring dimensions and format"),
        ],
    },
    {
        "triggers": ["synthesis prompt", "how LLM is instructed", "producer model integrates",
                     "how synthesize", "formatting rules", "how the producer model enforces",
                     "expected output format"],
        "label": "Synthesis prompt construction (agent.py)",
        "entries": [
            ("agent.py", "function", "synthesize", 25,
             "synthesize() — builds prompt from task + research + contexts, calls producer"),
        ],
    },
    {
        "triggers": ["conflict", "novelty", "search filtering", "search results filtered",
                     "how search quality", "how results are filtered", "relevance"],
        "label": "Novelty scoring (memory.py)",
        "entries": [
            ("memory.py", "function", "assess_novelty", 20,
             "assess_novelty() — scores new search results 0-10 against accumulated knowledge"),
        ],
    },
    {
        "triggers": ["chromadb", "embedding", "collection", "chroma parameter",
                     "fine-tuned", "semantic similarity threshold"],
        "label": "ChromaDB / embedding setup (memory.py)",
        "entries": [
            ("memory.py", "function", "_get_chroma_ef", 15,
             "_get_chroma_ef() — embedding function used for all ChromaDB queries"),
            ("memory.py", "function", "_get_chroma", 20,
             "_get_chroma() — collection initialisation and auto-migration"),
        ],
    },
    {
        "triggers": ["compression model", "how compressed", "compress", "key information is retained",
                     "compression model is selected"],
        "label": "Memory compression (memory.py)",
        "entries": [
            ("memory.py", "function", "compress_and_store", 30,
             "compress_and_store() — LLM compresses run into title/narrative/facts, writes SQLite+ChromaDB"),
        ],
    },
    {
        "triggers": ["gather_research", "research loop", "saturation loop", "how research is gathered",
                     "search rounds", "quality floor", "fallback search"],
        "label": "Research gathering loop (agent.py)",
        "entries": [
            ("agent.py", "function", "gather_research", 35,
             "gather_research() — saturation loop: search → novelty gate → compress → repeat"),
        ],
    },
    {
        "triggers": ["planner generates queries", "determines task type", "task classification",
                     "how the plan", "how queries are determined", "rule-based", "natural language processing",
                     "make plan", "make_plan", "complexity score", "plan queries"],
        "label": "Planner — make_plan() (planner.py)",
        "entries": [
            ("planner.py", "function", "make_plan", 35,
             "make_plan() — LLM call that classifies task type, complexity, and generates search queries"),
        ],
    },
    {
        "triggers": ["auto-activate", "auto activate", "skill activation", "determines which skills",
                     "heuristic", "how skills are activated", "complexity score calculation",
                     "keywords or complexity", "auto_activate"],
        "label": "Skill auto-activation (agent.py)",
        "entries": [
            ("agent.py", "function", "auto_activate", 30,
             "auto_activate() — rule-based: maps task keywords and plan signals to skill names"),
        ],
    },
]


def _extract_heredoc(src: str, name: str, max_lines: int) -> str:
    """Extract a triple-quoted or backslash-terminated heredoc constant."""
    # Triple-quoted
    m = re.search(rf'{re.escape(name)}\s*=\s*"""\s*\n(.*?)"""', src, re.DOTALL)
    if m:
        lines = m.group(1).splitlines()
        excerpt = "\n".join(lines[:max_lines])
        if len(lines) > max_lines:
            excerpt += f"\n… ({len(lines) - max_lines} more lines)"
        return excerpt
    # Backslash-terminated ("""\... """)
    m2 = re.search(rf'{re.escape(name)}\s*=\s*"""\\\s*\n(.*?)"""', src, re.DOTALL)
    if m2:
        lines = m2.group(1).splitlines()
        excerpt = "\n".join(lines[:max_lines])
        if len(lines) > max_lines:
            excerpt += f"\n… ({len(lines) - max_lines} more lines)"
        return excerpt
    return f"(could not extract {name})"


def _extract_string_const_block(src: str, name: str, max_lines: int) -> str:
    """Extract a multi-line string constant (triple-quoted)."""
    return _extract_heredoc(src, name, max_lines)


def _extract_function_body(src: str, name: str, max_lines: int) -> str:
    """Extract the first max_lines of a function body."""
    m = re.search(rf'^(def {re.escape(name)}\(.*?)(?=\ndef |\nclass |\Z)', src,
                  re.MULTILINE | re.DOTALL)
    if not m:
        return f"(could not find def {name})"
    lines = m.group(1).splitlines()
    excerpt = "\n".join(lines[:max_lines])
    if len(lines) > max_lines:
        excerpt += f"\n    … ({len(lines) - max_lines} more lines)"
    return excerpt


def _run_extraction(file: str, kind: str, name: str, max_lines: int) -> str:
    src = _read(file)
    if kind == "heredoc":
        return _extract_heredoc(src, name, max_lines)
    if kind == "string_const":
        return _extract_string_const_block(src, name, max_lines)
    if kind == "function":
        return _extract_function_body(src, name, max_lines)
    return f"(unknown extraction kind: {kind})"


def sync_gaps(issues: list[str]) -> str:
    """
    Given a list of wiggum issue strings, identify which gap patterns are triggered,
    extract the relevant source code sections, and write them into wiki/pipeline.md
    under a <!-- sync-wiki-gaps --> block.

    Returns a summary of what was added.
    """
    if not WIKI_TARGET.exists():
        return "[sync-wiki:gaps] ERROR: wiki/pipeline.md not found"

    issues_lower = " ".join(issues).lower()

    matched: list[dict] = []
    for spec in GAP_EXTRACTIONS:
        if any(str(t) in issues_lower for t in spec["triggers"]):
            matched.append(spec)

    if not matched:
        return "[sync-wiki:gaps] no matching gap patterns — wiki unchanged"

    today = date.today().isoformat()
    parts = [
        f"{GAP_MARKER_START}",
        "## Gap-Targeted Extractions",
        "",
        f"*Auto-generated by wiggum gap analysis on {today}. Re-generated each FAIL cycle.*",
        "",
    ]

    added_labels = []
    for spec in matched:
        parts.append(f"### {spec['label']}")
        parts.append("")
        for _e in spec["entries"]:
            file, kind, name, max_lines, desc = str(_e[0]), str(_e[1]), str(_e[2]), int(_e[3]), str(_e[4])
            excerpt = _run_extraction(file, kind, name, max_lines)
            parts.append(f"**`{name}`** — {desc}")
            parts.append("")
            parts.append("```python")
            parts.append(excerpt)
            parts.append("```")
            parts.append("")
        added_labels.append(str(spec["label"]))

    parts.append(GAP_MARKER_END)
    gap_section = "\n".join(parts)

    original = WIKI_TARGET.read_text(encoding="utf-8")
    if GAP_MARKER_START in original and GAP_MARKER_END in original:
        updated = re.sub(
            re.escape(GAP_MARKER_START) + r".*?" + re.escape(GAP_MARKER_END),
            gap_section,
            original,
            flags=re.DOTALL,
        )
        action = "updated"
    else:
        updated = original.rstrip() + "\n\n" + gap_section + "\n"
        action = "appended"

    WIKI_TARGET.write_text(updated, encoding="utf-8")

    summary = (
        f"[sync-wiki:gaps] {action} — {len(matched)} gap section(s) written: "
        + ", ".join(added_labels)
    )
    print(f"  {summary}")
    return summary


# ---------------------------------------------------------------------------
# Selective context injection for /contextualize
# ---------------------------------------------------------------------------

def get_relevant_wiki_context(max_chars: int = 8000) -> str:
    """
    Return a targeted slice of pipeline.md for /contextualize injection:
      1. Human-written body (pipeline diagram + architectural overview, capped at
         BODY_MAX chars) — provides accurate function names and stage descriptions.
      2. Implementation Reference marker block — constants, models, weights.
      3. Gap-Targeted Extractions marker block — source code for flagged gaps.

    Total is capped at max_chars to prevent truncation.
    Returns empty string if pipeline.md doesn't exist.
    """
    BODY_MAX = 3000

    if not WIKI_TARGET.exists():
        return ""

    text = WIKI_TARGET.read_text(encoding="utf-8")
    parts = []

    # 1. Human-written body: strip frontmatter, take content before first marker block
    body = text
    if body.startswith("---"):
        end_fm = body.find("---", 3)
        if end_fm != -1:
            body = body[end_fm + 3:].strip()
    # Trim at first auto-generated marker so we don't double-include it
    for marker in (MARKER_START, GAP_MARKER_START):
        idx = body.find(marker)
        if idx != -1:
            body = body[:idx].strip()
    if body:
        excerpt = body[:BODY_MAX]
        if len(body) > BODY_MAX:
            excerpt += f"\n… ({len(body) - BODY_MAX} more chars)"
        parts.append(excerpt)

    # 2. Implementation Reference block (constants, models, dim weights)
    impl_m = re.search(
        re.escape(MARKER_START) + r"(.*?)" + re.escape(MARKER_END),
        text, re.DOTALL
    )
    if impl_m:
        parts.append(impl_m.group(0).strip())

    # 3. Gap-Targeted Extractions (source code for flagged gaps)
    gap_m = re.search(
        re.escape(GAP_MARKER_START) + r"(.*?)" + re.escape(GAP_MARKER_END),
        text, re.DOTALL
    )
    if gap_m:
        parts.append(gap_m.group(0).strip())

    if not parts:
        return ""

    combined = "\n\n".join(parts)
    if len(combined) > max_chars:
        combined = combined[:max_chars] + f"\n… (truncated at {max_chars} chars)"
    return combined


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    result = sync()
    sys.stdout.buffer.write((result + "\n").encode("utf-8", errors="replace"))

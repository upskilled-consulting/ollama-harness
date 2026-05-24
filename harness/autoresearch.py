"""
autoresearch.py — autonomous harness improvement loop.

Applies Karpathy's autoresearch pattern to the synthesis instruction in agent.py.

Loop (runs indefinitely until killed):
  1. Read current SYNTH_INSTRUCTION from agent.py
  2. Gather context: experiment history + evaluator feedback from last run
  3. Ask Qwen3-Coder:30b to propose a new instruction (one specific change)
  4. Apply the change to agent.py
  5. git commit
  6. Run eval_suite --score --tasks <EVAL_TASKS> → composite float
  7. If score improved by > DELTA_THRESHOLD: keep (advance), update baseline
     Else: git checkout -- agent.py (discard), log as discard
  8. Log to autoresearch.tsv
  9. GOTO 1

Mutable scope: SYNTH_INSTRUCTION, SYNTH_INSTRUCTION_COUNT, and SYNTH_INSTRUCTION_PROSE in agent.py only.
Fixed metric:  eval_suite composite (wiggum r1 score + criteria rate).
Immutable:     eval_suite task definitions, wiggum evaluator, PASS_THRESHOLD.

Usage:
    conda activate ollama-pi
    python autoresearch.py                  # use defaults
    python autoresearch.py --tasks T_A,T_B  # fast: 2 tasks per experiment (~25 min/loop)
    python autoresearch.py --delta 0.2      # require larger improvement to keep

Environment:
    conda activate ollama-pi
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from harness.inference import OllamaLike as _OllamaLike

_KEEP_ALIVE = int(os.environ.get("OLLAMA_KEEP_ALIVE", -1))
ollama = _OllamaLike(keep_alive=_KEEP_ALIVE)


try:
    from ddgs import DDGS
    _ddgs = DDGS()
    DDGS_AVAILABLE = True
except Exception:
    DDGS_AVAILABLE = False

try:
    from markitdown import MarkItDown
    _md = MarkItDown(enable_plugins=False)
    MARKITDOWN_AVAILABLE = True
except ImportError:
    MARKITDOWN_AVAILABLE = False

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PROPOSER_MODEL      = os.environ.get("PROPOSER_MODEL", "Qwen3-Coder:30b")  # override: PROPOSER_MODEL=kimi-k2.5:cloud
EVAL_TASKS          = ["T_B", "T_D", "T_E"]  # T_B (best_practices) + T_D (enumerated) + T_E (open)
DELTA_THRESHOLD     = 0.1                  # minimum score improvement to keep a change
TSV_PATH            = "autoresearch.tsv"
AGENT_PATH          = "harness/agent.py"
RUNS_JSONL          = "data/runs.jsonl"
RESEARCH_ENABLED    = True                 # gather web context before each proposal
RESEARCH_MAX_CHARS  = 4000                 # max chars of research context fed to proposer

# Use the same Python interpreter that launched autoresearch.py — ensures the
# correct conda environment (with ddgs, ollama, etc.) is used for eval subprocesses.
PYTHON          = sys.executable

# Sentinel markers in agent.py (do not change without updating agent.py too)
BEGIN_MARKER       = "# AUTORESEARCH:SYNTH_INSTRUCTION:BEGIN"
END_MARKER         = "# AUTORESEARCH:SYNTH_INSTRUCTION:END"
BEGIN_MARKER_COUNT = "# AUTORESEARCH:SYNTH_INSTRUCTION_COUNT:BEGIN"
END_MARKER_COUNT   = "# AUTORESEARCH:SYNTH_INSTRUCTION_COUNT:END"
BEGIN_MARKER_PROSE = "# AUTORESEARCH:SYNTH_INSTRUCTION_PROSE:BEGIN"
END_MARKER_PROSE   = "# AUTORESEARCH:SYNTH_INSTRUCTION_PROSE:END"


# ---------------------------------------------------------------------------
# Instruction read / write
# ---------------------------------------------------------------------------

def _extract_between(text: str, begin: str, end: str) -> str:
    """Extract text between two sentinel lines (exclusive)."""
    lines = text.splitlines()
    in_block = False
    block = []
    for line in lines:
        if line.strip() == begin:
            in_block = True
            continue
        if line.strip() == end:
            break
        if in_block:
            block.append(line)
    return "\n".join(block)


def _replace_between(text: str, begin: str, end: str, new_block: str) -> str:
    """Replace lines between two sentinel lines with new_block."""
    lines = text.splitlines(keepends=True)
    out = []
    in_block = False
    for line in lines:
        if line.strip() == begin:
            out.append(line)
            in_block = True
            out.append(new_block + "\n")
            continue
        if line.strip() == end:
            in_block = False
            out.append(line)
            continue
        if not in_block:
            out.append(line)
    return "".join(out)


def _parse_instruction_value(block: str) -> str:
    """Extract the string value from a SYNTH_INSTRUCTION = (...) block.
    Handles implicit string concatenation (adjacent quoted literals).
    """
    fragments = re.findall(r'"((?:[^"\\]|\\.)*)"', block)
    return "".join(fragments)  # fragments already include trailing spaces


def _build_instruction_block(var_name: str, value: str) -> str:
    """Build a SYNTH_INSTRUCTION = (...) block from a plain string value."""
    # Collapse to single line, then escape for a Python string literal
    single_line = " ".join(value.splitlines()).strip()
    escaped = single_line.replace('\\', '\\\\').replace('"', '\\"')
    return f'{var_name} = (\n    "{escaped}"\n)'


def read_instructions() -> dict:
    """Read current SYNTH_INSTRUCTION, SYNTH_INSTRUCTION_COUNT, and SYNTH_INSTRUCTION_PROSE from agent.py."""
    with open(AGENT_PATH, encoding="utf-8") as f:
        text = f.read()
    synth_block       = _extract_between(text, BEGIN_MARKER,       END_MARKER).strip()
    synth_count_block = _extract_between(text, BEGIN_MARKER_COUNT,  END_MARKER_COUNT).strip()
    synth_prose_block = _extract_between(text, BEGIN_MARKER_PROSE,  END_MARKER_PROSE).strip()
    return {
        "synth":       _parse_instruction_value(synth_block),
        "synth_count": _parse_instruction_value(synth_count_block),
        "synth_prose": _parse_instruction_value(synth_prose_block),
    }


def write_instructions(synth: str, synth_count: str, synth_prose: str = ""):
    """Write SYNTH_INSTRUCTION, SYNTH_INSTRUCTION_COUNT, and (optionally) SYNTH_INSTRUCTION_PROSE into agent.py."""
    with open(AGENT_PATH, encoding="utf-8") as f:
        text = f.read()
    text = _replace_between(
        text, BEGIN_MARKER, END_MARKER,
        _build_instruction_block("SYNTH_INSTRUCTION", synth),
    )
    text = _replace_between(
        text, BEGIN_MARKER_COUNT, END_MARKER_COUNT,
        _build_instruction_block("SYNTH_INSTRUCTION_COUNT", synth_count),
    )
    if synth_prose:
        text = _replace_between(
            text, BEGIN_MARKER_PROSE, END_MARKER_PROSE,
            _build_instruction_block("SYNTH_INSTRUCTION_PROSE", synth_prose),
        )
    with open(AGENT_PATH, "w", encoding="utf-8") as f:
        f.write(text)


# ---------------------------------------------------------------------------
# TSV logging
# ---------------------------------------------------------------------------

TSV_HEADER = "experiment\tscore\tbaseline\tdelta\tstatus\ttasks\tdescription\n"

def init_tsv():
    if not os.path.exists(TSV_PATH):
        with open(TSV_PATH, "w", encoding="utf-8") as f:
            f.write(TSV_HEADER)
    else:
        # Migrate old TSV (no tasks column) to new format in-place
        with open(TSV_PATH, encoding="utf-8") as f:
            lines = f.readlines()
        if lines and "tasks" not in lines[0]:
            new_lines = [TSV_HEADER]
            for line in lines[1:]:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 6:
                    # old: exp score baseline delta status description
                    new_lines.append("\t".join(parts[:5]) + "\t\t" + parts[5] + "\n")
                else:
                    new_lines.append(line)
            with open(TSV_PATH, "w", encoding="utf-8") as f:
                f.writelines(new_lines)


def log_experiment(experiment: int, score: float, baseline: float, status: str, description: str, task_ids: list[str] | None = None):
    delta = round(score - baseline, 3)
    sign = "+" if delta >= 0 else ""
    tasks_str = "+".join(task_ids) if task_ids else ""
    with open(TSV_PATH, "a", encoding="utf-8") as f:
        f.write(f"{experiment}\t{score:.3f}\t{baseline:.3f}\t{sign}{delta:.3f}\t{status}\t{tasks_str}\t{description}\n")
    print(f"  [tsv] exp {experiment}: score={score:.3f} baseline={baseline:.3f} "
          f"delta={sign}{delta:.3f} status={status}")


def read_history() -> str:
    """Return TSV contents as a string for the proposer prompt."""
    if not os.path.exists(TSV_PATH):
        return "(no experiments yet)"
    with open(TSV_PATH, encoding="utf-8") as f:
        return f.read().strip()


def read_baseline_for_tasks(task_ids: list[str]) -> float | None:
    """Return the best score from keep/baseline rows that match this exact task set.
    Returns None if no matching rows exist."""
    task_key = "+".join(sorted(task_ids))
    if not os.path.exists(TSV_PATH):
        return None
    best: float | None = None
    with open(TSV_PATH, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 6:
                continue
            status = parts[4].strip()
            row_tasks = parts[5].strip() if len(parts) > 5 else ""
            if status not in ("keep", "baseline"):
                continue
            row_key = "+".join(sorted(row_tasks.split("+"))) if row_tasks else ""
            if row_key != task_key:
                continue
            try:
                s = float(parts[1])
                if best is None or s > best:
                    best = s
            except ValueError:
                pass
    return best


# ---------------------------------------------------------------------------
# Evaluator feedback extraction
# ---------------------------------------------------------------------------

def get_recent_eval_feedback(task_ids: list[str], n_before: int) -> str:
    """
    Read runs.jsonl entries added since n_before and extract evaluator feedback
    for runs matching the eval task fingerprints.
    """
    FINGERPRINTS = {
        "T_A": "top 5 context engineering",
        "T_B": "cost envelope management",
        "T_C": "3 most common failure modes",
        "T_D": "top 3 context window management",
        "T_E": "prompt injection defense",
    }
    try:
        with open(RUNS_JSONL, encoding="utf-8") as f:
            all_runs = [json.loads(l) for l in f if l.strip()]
    except FileNotFoundError:
        return "(no runs.jsonl)"

    new_runs = all_runs[n_before:]
    feedback_lines = []
    for run in new_runs:
        task_str = run.get("task", "").lower()
        matched_id = None
        for tid in task_ids:
            if FINGERPRINTS.get(tid, "").lower() in task_str:
                matched_id = tid
                break
        if not matched_id:
            continue
        eval_log = run.get("wiggum_eval_log", [])
        for entry in eval_log:
            score = entry.get("score", "?")
            dims = entry.get("dims", {})
            issues = entry.get("issues", [])
            feedback = entry.get("feedback", "")
            dim_str = " ".join(f"{k[:3]}={v}" for k, v in dims.items())
            feedback_lines.append(f"[{matched_id} round {entry.get('round',1)} score={score} {dim_str}]")
            for issue in issues:
                feedback_lines.append(f"  issue: {issue}")
            if feedback:
                feedback_lines.append(f"  feedback: {feedback[:300]}")

    return "\n".join(feedback_lines) if feedback_lines else "(no eval feedback found)"


def get_run_count() -> int:
    try:
        with open(RUNS_JSONL, encoding="utf-8") as f:
            return sum(1 for l in f if l.strip())
    except FileNotFoundError:
        return 0


# ---------------------------------------------------------------------------
# Pre-proposal research
# ---------------------------------------------------------------------------

_RESEARCH_QUERIES = [
    "effective LLM synthesis prompt engineering depth specificity",
    "prompt instruction techniques chain-of-thought output quality improvement",
]
_RESEARCH_URL_COUNT = 2  # MarkItDown pages to fetch per session


def _web_search_brief(query: str, max_results: int = 5) -> str:
    """Run a DuckDuckGo search and return a compact text snippet."""
    if not DDGS_AVAILABLE:
        return ""
    try:
        results = list(_ddgs.text(query, max_results=max_results))
        lines = []
        for r in results:
            title = r.get("title", "")
            body = r.get("body", "")[:200]
            href = r.get("href", "")
            lines.append(f"- {title}: {body} ({href})")
        return "\n".join(lines)
    except Exception:
        return ""


def _fetch_page(url: str, max_chars: int = 2000) -> str:
    """Fetch a URL via MarkItDown and return truncated markdown text."""
    if not MARKITDOWN_AVAILABLE or not url.startswith("http"):
        return ""
    try:
        import os
        import sys
        with open(os.devnull, "w") as devnull:
            old_stderr = sys.stderr
            sys.stderr = devnull
            try:
                result = _md.convert(url)
            finally:
                sys.stderr = old_stderr
        text = (result.text_content or "").strip()
        if len(text) > max_chars:
            text = text[:max_chars] + "\n[truncated]"
        return text
    except Exception:
        return ""


def gather_proposal_context() -> str:
    """
    Search the web for prompt engineering research and fetch top pages via MarkItDown.
    Returns a compact research brief to enrich the proposer's context.
    Skips gracefully if ddgs or markitdown are unavailable.
    """
    if not RESEARCH_ENABLED or not DDGS_AVAILABLE:
        return ""

    print("  [research] gathering proposal context...")
    sections = []
    fetched_urls: list[str] = []

    for query in _RESEARCH_QUERIES:
        snippet = _web_search_brief(query)
        if snippet:
            sections.append(f"Search: {query}\n{snippet}")
        # Collect URLs for page fetching
        if MARKITDOWN_AVAILABLE and len(fetched_urls) < _RESEARCH_URL_COUNT:
            try:
                results = list(_ddgs.text(query, max_results=3))
                for r in results:
                    url = r.get("href", "")
                    if url.startswith("http") and url not in fetched_urls:
                        fetched_urls.append(url)
                        break
            except Exception:
                pass

    # Fetch full pages for top URLs
    for url in fetched_urls[:_RESEARCH_URL_COUNT]:
        print(f"  [research] fetching {url[:70]}...")
        page = _fetch_page(url, max_chars=1500)
        if page:
            sections.append(f"Full page ({url}):\n{page}")

    brief = "\n\n---\n\n".join(sections)
    if len(brief) > RESEARCH_MAX_CHARS:
        brief = brief[:RESEARCH_MAX_CHARS] + "\n[truncated]"

    print(f"  [research] {len(brief)} chars of context gathered")
    return brief


# ---------------------------------------------------------------------------
# Proposer
# ---------------------------------------------------------------------------

PROPOSE_PROMPT = """You are improving the synthesis instruction for a local LLM research agent.

The agent researches topics via web search and synthesizes findings into markdown documents.
The evaluator (Qwen3-Coder:30b) scores outputs on 6 dimensions (weights in parens):
  - relevance (0.20)
  - completeness (0.20)
  - depth (0.25)       ← highest weight; scored low when items lack concrete implementation steps
  - grounded (0.15)    ← are claims traceable to real systems, named APIs, or published data?
  - specificity (0.10) ← scored low when claims are generic rather than actionable
  - structure (0.10)
  Composite = 0.20*rel + 0.20*cmp + 0.25*dep + 0.15*grounded + 0.10*spc + 0.10*str
  PASS threshold = 9.0  (a dep=7 makes 9.0 mathematically unreachable — dep must reach 9)

There are THREE synthesis instructions:
  1. SYNTH_INSTRUCTION — for technical tasks (code, tools, APIs, software)
  2. SYNTH_INSTRUCTION_COUNT — for technical tasks with a count constraint ("top 5", "3 ways")
  3. SYNTH_INSTRUCTION_PROSE — for non-technical tasks (best practices, concepts, strategies)
     This one uses What/Why/How structure and avoids code blocks.
     Scored on the same 5 dimensions, especially "grounded" (cite sources, concrete details).

Each instruction is the final sentence(s) appended to its synthesis prompt. It must:
  - Tell the model to output ONLY markdown starting with #
  - Not mention file paths
  - Be clear and direct

Current SYNTH_INSTRUCTION:
{synth}

Current SYNTH_INSTRUCTION_COUNT (used when task has a count constraint like "top 5"):
{synth_count}

Current SYNTH_INSTRUCTION_PROSE (used for non-technical / best-practices tasks):
{synth_prose}

ALREADY IN THE INSTRUCTION — do not re-propose any of these, they are already present:
{already_present}

Experiment history (tab-separated: experiment, score, baseline, delta, status, description):
{history}

PREVIOUSLY TRIED AND FAILED — do not repeat any of these approaches:
{discarded_list}

Latest evaluator feedback from the most recent eval run:
{eval_feedback}

External research context (prompt engineering literature and best practices):
{research_context}

Your task: propose ONE specific change to ONE of the three synthesis instructions that might
improve the composite eval score. If evaluator feedback mentions "grounded", "sources", or
"depth" on a prose/best-practices task, prioritize changing SYNTH_INSTRUCTION_PROSE.
The change must be genuinely NEW — not a variation of anything already present or previously discarded.

HARD-BANNED — tried 15+ times across experiments, ALWAYS score worse or equal to baseline:
  - Requiring named examples, case studies, or published references for each practice
  - Requiring explicit source citations or external links
  - Requiring concrete implementation snippets or code examples (in PROSE instruction)
  - Adding a "practitioner deploying tomorrow" persona
  - Adding confidence ratings or hedging language per claim
  - ANY variation of "problem → practice → caveat" 3-part structure (tried 24 times, exps 29–52)
      This includes: "state the problem it solves", "when NOT to use", "when it does not apply",
      "problem statement + approach + trade-off", "decision-rule framing", "conditional rule" openings
  - Ranking practices by ROI / labeling "highest ROI" / requiring ROI ordering (tried 8+ times, no gain)
  - ANY comparison framing: "compare X vs Y", "zero-shot vs chain-of-thought", "few-shot vs zero-shot",
      "approach A versus approach B", "contrast two techniques" (tried 55 times, exps 53–107, all discards)
      This includes: any "compare/contrast" instruction, any "X vs Y" structure, any dual-approach analysis
  Do NOT propose any of these even if the evaluator feedback seems to ask for them.

Unexplored angles — pick one that genuinely differs from everything above:
  - Changing the NUMBER of practices required (try 5-6, or just 2, vs. the current implicit count)
  - Removing structural constraints entirely: let the model choose its own format for this task
  - Constraining OUTPUT LENGTH: require a specific word count range (e.g. 200-300 words total)
  - Changing the VOICE: require second-person ("you should") vs. declarative ("the model should")
  - Changing the FRAMING: reframe from "best practices" to "common failure modes and their fixes"
  - Adding a SCOPE constraint: limit to a specific context (e.g. "for tasks under 5 minutes", "for RAG pipelines")
  - Single-technique DEEP DIVE: pick ONE practice and require exhaustive treatment (when to use, pitfalls, tuning)
  - NARRATIVE format: require the output as a cohesive paragraph narrative, not a list
  - FAQ format: require Q&A pairs instead of a list ("Q: When should I use X? A: ...")
  - AUDIENCE shift: reframe for a non-technical stakeholder (explain tradeoffs without jargon)
  - NEGATIVE space: require the model to focus on what NOT to do and why (anti-patterns only)

Rules:
  - Output complete replacement strings — not patches
  - All three instructions must still say "output ONLY the markdown starting with #"
  - Make one focused change to one instruction; don't try to fix everything at once
  - CRITICAL: each instruction is a SHORT directive (1-4 sentences, under 600 chars). Do NOT output an example document, markdown content, or code — only the instruction text that tells the model how to write its output.

Output ONLY valid JSON (no preamble, no markdown fences):
{{
  "synth": "complete replacement for SYNTH_INSTRUCTION (the Python string value, not the assignment)",
  "synth_count": "complete replacement for SYNTH_INSTRUCTION_COUNT",
  "synth_prose": "complete replacement for SYNTH_INSTRUCTION_PROSE",
  "description": "one line: what changed and why (mention which instruction was changed)"
}}"""


def _extract_already_present(synth: str) -> str:
    """Extract key requirements already in the instruction as a bullet list."""
    keywords = [
        ("What/Why/How structure", r"\bwhat\b.*\bwhy\b.*\bhow\b"),
        ("numbered steps", r"numbered steps"),
        ("inline code blocks", r"inline code blocks"),
        ("specific tool names/versions", r"tool names|versions"),
        ("working code examples / executable snippets", r"code (snippet|example)|executable"),
        ("production-ready library mentions", r"production.ready|LangChain|HuggingFace|Prometheus"),
        ("implementation notes for edge cases", r"edge cases?|chunk overlap|anomaly detection"),
        ("trade-off discussion", r"trade.off"),
        ("real-world examples", r"real.world"),
    ]
    found = []
    import re as _re
    for label, pattern in keywords:
        if _re.search(pattern, synth, _re.IGNORECASE):
            found.append(f"- {label}")
    return "\n".join(found) if found else "(none detected)"


def _extract_discarded(history: str) -> str:
    """Extract descriptions of discarded experiments as a bullet list."""
    lines = []
    for row in history.splitlines():
        parts = row.split("\t")
        # TSV columns: experiment, score, baseline, delta, status, tasks, description
        if len(parts) >= 5 and parts[4].strip().lower() == "discard":
            score = parts[1].strip() if len(parts) > 1 else "?"
            desc = parts[6].strip() if len(parts) > 6 else ""
            if desc:
                lines.append(f"- [score={score}] {desc}")
    return "\n".join(lines) if lines else "(none yet)"


def propose_instructions(current: dict, history: str, eval_feedback: str, research_context: str = "") -> dict | None:
    """Ask proposer model to suggest new synthesis instructions. Returns dict or None on failure."""
    prompt = PROPOSE_PROMPT.format(
        synth=current["synth"],
        synth_count=current["synth_count"],
        synth_prose=current.get("synth_prose", ""),
        already_present=_extract_already_present(current["synth"] + " " + current.get("synth_prose", "")),
        discarded_list=_extract_discarded(history),
        history=history,
        eval_feedback=eval_feedback,
        research_context=research_context or "(none gathered)",
    )
    print("  [propose] asking proposer for new instruction...")
    try:
        response = ollama.chat(
            model=PROPOSER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.3},
        )
    except Exception as e:
        print(f"  [propose] ollama error: {e}")
        return None

    raw = response["message"]["content"].strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```\s*$", "", raw, flags=re.MULTILINE)
    # Strip <think>...</think> if present
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        print(f"  [propose] parse error, raw: {raw[:300]}")
        return None

    for key in ("synth", "synth_count", "synth_prose", "description"):
        if key not in result:
            print(f"  [propose] missing key '{key}' in response")
            return None

    # Sanity check: reject if proposer hallucinated a document as the instruction
    MAX_INSTRUCTION_CHARS = 1200
    for key in ("synth", "synth_count", "synth_prose"):
        val = result[key]
        if len(val) > MAX_INSTRUCTION_CHARS:
            print(f"  [propose] rejected: {key} too long ({len(val)} chars > {MAX_INSTRUCTION_CHARS}) — proposer likely hallucinated a document")
            return None
        if val.count("\n") > 3:
            print(f"  [propose] rejected: {key} contains {val.count(chr(10))} newlines — proposer likely hallucinated a document")
            return None

    return result


# ---------------------------------------------------------------------------
# Eval
# ---------------------------------------------------------------------------

def run_eval(task_ids: list[str]) -> float:
    """Run eval_suite --score --tasks <tasks> and return composite float."""
    tasks_arg = ",".join(task_ids)
    print(f"  [eval] running eval_suite on {tasks_arg}...")
    # Use a bounded keep_alive (120s) instead of -1 so models unload after eval
    # completes and don't occupy Ollama slots when the proposer runs next iteration.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "WIGGUM_MAX_ROUNDS": "1", "OLLAMA_KEEP_ALIVE": "120", "WIGGUM_PANEL": "1", "RESEARCH_CACHE": "1"}
    result = subprocess.run(
        [PYTHON, "-m", "harness.eval.eval_suite", "--score", "--tasks", tasks_arg],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=str(Path(__file__).parent.parent),
    )
    if result.returncode != 0:
        print(f"  [eval] returncode: {result.returncode}")
        if result.stderr.strip():
            print(f"  [eval] stderr: {result.stderr[:2000]}")
    stdout = result.stdout.strip()
    try:
        score = float(stdout.split("\n")[-1].strip())
        print(f"  [eval] composite score: {score:.3f}")
        return score
    except (ValueError, IndexError):
        print(f"  [eval] parse error, stdout: {stdout[:400]!r}")
        return 0.0


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def git_commit(message: str):
    subprocess.run(["git", "add", AGENT_PATH], check=True)
    subprocess.run(["git", "commit", "-m", message], check=True)


def git_discard():
    """Restore agent.py to last committed state."""
    subprocess.run(["git", "checkout", "--", AGENT_PATH], check=True)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

PLATEAU_DISCARDS = 3    # consecutive discards before auto-explore kicks in
PLATEAU_DELTA    = 0.05  # |delta| below this counts as "stuck at plateau"


def _should_explore(mode: str, consecutive_discards: int, last_deltas: list[float]) -> bool:
    """Return True if the loop should re-gather research context before the next proposal."""
    if mode == "explore":
        return True
    if mode == "exploit":
        return False
    # auto: explore after PLATEAU_DISCARDS consecutive discards regardless of delta size.
    # Large negative swings are also a sign of a stuck proposer — not just near-zero ones.
    return consecutive_discards >= PLATEAU_DISCARDS


def main():
    global PROPOSER_MODEL
    # Parse args
    args = sys.argv[1:]
    task_ids = EVAL_TASKS[:]
    if "--tasks" in args:
        idx = args.index("--tasks")
        if idx + 1 < len(args):
            task_ids = [t.strip() for t in args[idx + 1].split(",")]
    delta_threshold = DELTA_THRESHOLD
    if "--delta" in args:
        idx = args.index("--delta")
        if idx + 1 < len(args):
            delta_threshold = float(args[idx + 1])
    if "--proposer" in args:
        idx = args.index("--proposer")
        if idx + 1 < len(args):
            PROPOSER_MODEL = args[idx + 1]
    reset_baseline = "--reset-baseline" in args
    mode = "auto"
    if "--mode" in args:
        idx = args.index("--mode")
        if idx + 1 < len(args):
            mode = args[idx + 1].lower()
    if mode not in ("explore", "exploit", "auto"):
        print(f"[warn] unknown --mode '{mode}', defaulting to 'auto'")
        mode = "auto"

    print("\n" + "=" * 60)
    print(" autoresearch — autonomous synthesis instruction improvement")
    print(f" proposer:    {PROPOSER_MODEL}")
    print(f" eval tasks:  {task_ids}")
    print(f" delta thr:   {delta_threshold}")
    print(f" mode:        {mode}  (explore|exploit|auto)")
    if mode == "auto":
        print(f"   auto-explore after {PLATEAU_DISCARDS} consecutive discards with |delta| < {PLATEAU_DELTA}")
    print("=" * 60 + "\n")

    init_tsv()

    # Establish baseline scoped to the current task set
    task_baseline = read_baseline_for_tasks(task_ids)

    if reset_baseline or task_baseline is None:
        reason = "--reset-baseline requested" if reset_baseline else f"no history for tasks {task_ids}"
        print(f"[baseline] {reason} — running fresh baseline eval...")
        baseline_score = run_eval(task_ids)
        log_experiment(0, baseline_score, baseline_score, "baseline", "initial baseline", task_ids)
        print(f"[baseline] score: {baseline_score:.3f}\n")
    else:
        baseline_score = task_baseline
        print(f"[resume] best score for tasks {task_ids}: {baseline_score:.3f}\n")

    history    = read_history()
    experiment = sum(1 for l in history.splitlines() if l and not l.startswith("experiment")) + 1

    # Seed fresh_feedback from most recent eval runs already in runs.jsonl
    n_seed = get_run_count()
    fresh_feedback = get_recent_eval_feedback(task_ids, max(0, n_seed - len(task_ids) * 2))
    if not fresh_feedback or fresh_feedback == "(no eval feedback found)":
        fresh_feedback = "(no prior eval feedback — first experiment)"

    # Research context: seeded now, refreshed conditionally per mode logic
    research_context = gather_proposal_context()

    consecutive_discards = 0
    last_deltas: list[float] = []

    # LOOP FOREVER — generate → verify → revise
    while True:
        # Mode decision: should we re-gather research before this proposal?
        if _should_explore(mode, consecutive_discards, last_deltas):
            print(f"  [mode] {'forced explore' if mode == 'explore' else 'auto-explore: plateau detected'} — re-gathering research context")
            research_context = gather_proposal_context()
            consecutive_discards = 0  # reset plateau counter after explore

        print(f"\n{'=' * 60}")
        print(f" Experiment {experiment}  |  mode={mode}  |  consecutive_discards={consecutive_discards}")
        print(f" Baseline: {baseline_score:.3f}")
        print(f"{'=' * 60}")

        current = read_instructions()
        history = read_history()

        # 1. GENERATE — propose based on the signal from the LAST eval run
        proposal = propose_instructions(current, history, fresh_feedback, research_context)
        if proposal is None:
            print("  [warn] proposer failed — skipping experiment")
            time.sleep(5)
            continue

        description = proposal["description"]
        print(f"  [proposal] {description}")
        print(f"  [proposal] synth:\n    {proposal['synth']}")
        if proposal.get("synth_prose"):
            print(f"  [proposal] synth_prose:\n    {proposal['synth_prose']}")

        # 2. APPLY
        write_instructions(
            synth=proposal["synth"],
            synth_count=proposal["synth_count"],
            synth_prose=proposal.get("synth_prose", ""),
        )

        commit_msg = f"autoresearch exp {experiment}: {description}"
        try:
            git_commit(commit_msg)
        except subprocess.CalledProcessError as e:
            print(f"  [warn] git commit failed: {e} — continuing anyway")

        # 3. VERIFY
        n_before_eval = get_run_count()
        score = run_eval(task_ids)

        # Capture THIS eval's feedback immediately — it feeds the next proposal
        fresh_feedback = get_recent_eval_feedback(task_ids, n_before_eval)
        if not fresh_feedback or fresh_feedback == "(no eval feedback found)":
            fresh_feedback = "(no eval feedback from this run)"

        # 4. KEEP or DISCARD
        delta = score - baseline_score
        last_deltas.append(delta)

        if delta > delta_threshold:
            status = "keep"
            baseline_score = score
            consecutive_discards = 0
            print(f"  [KEEP] {score:.3f} (+{delta:.3f}) — new baseline: {baseline_score:.3f}")
            # On keep: refresh research only if in explore or auto mode
            if mode != "exploit":
                research_context = gather_proposal_context()
        else:
            status = "discard"
            consecutive_discards += 1
            print(f"  [DISCARD] {score:.3f} (delta={delta:+.3f} <= threshold {delta_threshold})  "
                  f"[{consecutive_discards} consecutive]")
            try:
                subprocess.run(["git", "reset", "HEAD~1", "--soft"], check=True)
                subprocess.run(["git", "checkout", "--", AGENT_PATH], check=True)
            except subprocess.CalledProcessError as e:
                print(f"  [warn] git discard failed: {e}")

        log_experiment(experiment, score, baseline_score, status, description, task_ids)
        experiment += 1
        print(f"\n  [loop] experiment {experiment - 1} done. Starting {experiment}...")


if __name__ == "__main__":
    main()

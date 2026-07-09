"""
wiggum.py — verification loop for agent outputs

Flow per round:
  1. Normalize output to markdown via markitdown
  2. If HTML, render with playwright and extract clean text
  3. Evaluate normalized content against task criteria using an ollama evaluator model
  4. PASS: done. FAIL: revise with producer model, write, loop back.

Max 3 rounds — rounds 1-2 capture ~75% of reachable improvement (Yang et al., EMNLP 2025).

Usage (standalone):
    python -m harness.wiggum "<task>" <output_path>

Usage (as module):
    from harness.wiggum import loop
    result = loop(task, output_path, producer_model="pi-qwen")

Environment:
    conda activate ollama-pi
"""

import datetime
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from typing import Any

from harness.inference import OllamaLike as _OllamaLike, list_endpoints as _list_endpoints
from harness.summarizer import summarize_for_eval, summarize_for_revision


@contextmanager
def _nullspan():
    """No-op context manager used when no parent_trace is available."""
    yield

_KEEP_ALIVE = int(os.environ.get("OLLAMA_KEEP_ALIVE", -1))
ollama = _OllamaLike(keep_alive=_KEEP_ALIVE)


def _emit(event_type: str, data: dict) -> None:
    print(f"[EVENT]{json.dumps({'type': event_type, 'data': data})}", flush=True)


try:
    from markitdown import MarkItDown
    MARKITDOWN_AVAILABLE = True
except ImportError:
    MARKITDOWN_AVAILABLE = False

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

PRODUCER_MODEL = (os.environ.get("WIGGUM_PRODUCER_MODEL")
                  or os.environ.get("HARNESS_PRODUCER_MODEL", "pi-qwen-32b"))
EVALUATOR_MODEL = (os.environ.get("WIGGUM_EVALUATOR_MODEL")
                   or os.environ.get("HARNESS_EVALUATOR_MODEL")
                   or os.environ.get("HARNESS_PRODUCER_MODEL", "atla/selene-mini"))
from harness.config import settings as _settings
MAX_ROUNDS     = _settings.wiggum_max_rounds
PASS_THRESHOLD = _settings.pass_threshold

# Evaluator pool for rotation — comma-separated model names in HARNESS_EVALUATOR_POOL.
# When set, each run draws one evaluator deterministically from the pool (hash of seed).
# Falls back to EVALUATOR_MODEL when pool is empty.
_EVALUATOR_POOL: list[str] = [
    m.strip() for m in os.environ.get("HARNESS_EVALUATOR_POOL", "").split(",")
    if m.strip()
]


def select_evaluator(seed: str = "") -> str:
    """Return an evaluator model name, rotating through HARNESS_EVALUATOR_POOL by hash."""
    if not _EVALUATOR_POOL:
        return EVALUATOR_MODEL
    import hashlib
    h = hashlib.md5((seed or os.urandom(4).hex()).encode()).hexdigest()
    idx = int(h, 16) % len(_EVALUATOR_POOL)
    chosen = _EVALUATOR_POOL[idx]
    print(f"  [wiggum] evaluator rotation → {chosen} ({idx + 1}/{len(_EVALUATOR_POOL)})", flush=True)
    return chosen

# ---------------------------------------------------------------------------
# Hallucination detector
# ---------------------------------------------------------------------------

_KNOWN_OBJECTS = frozenset({
    'model', 'tokenizer', 'optimizer', 'scheduler', 'trainer',
    'np', 'pd', 'plt', 'ax', 'fig', 'torch', 'tf', 'nn',
    'logger', 'logging', 'os', 'sys', 'json', 're', 'time',
    'datetime', 'client', 'session', 'cursor', 'conn', 'db',
    'app', 'router', 'request', 'response', 'df',
})

# Match standalone method calls: obj.long_method_name(  (no assignment before the dot)
_STUB_CALL = re.compile(r'^([a-z_]\w*)\.([a-z_]{12,})\(')


def _count_stub_blocks(content: str) -> int:
    """
    Count code blocks containing likely-fabricated API stubs.

    Signature: object not in known-real namespaces, 2+ standalone method calls
    with names ≥12 chars (real APIs rarely describe their action in full sentences).
    Returns penalty 0–2 (capped so one bad block doesn't crater the score).
    """
    blocks = re.findall(r'```(?:\w*)\n(.*?)```', content, re.DOTALL)
    count = 0
    for block in blocks:
        lines = [l.strip() for l in block.splitlines()
                 if l.strip() and not l.strip().startswith('#')]
        suspicious = 0
        for line in lines:
            m = _STUB_CALL.match(line)
            if m:
                obj = m.group(1)
                if obj not in _KNOWN_OBJECTS and '=' not in line.split('(')[0]:
                    suspicious += 1
        if suspicious >= 2:
            count += 1
    return min(count, 2)

# WIGGUM_PANEL=1 enables the TinyTroupe multi-persona panel after each evaluate() call.
# Panel issues are merged into the revision prompt for richer feedback.
_PANEL_ENABLED = os.environ.get("WIGGUM_PANEL", "0").strip() == "1"


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize(path: str) -> str:
    """Convert any file format to plain markdown text for evaluation."""
    expanded = os.path.expanduser(path)

    if not os.path.exists(expanded):
        return f"[error] file not found: {expanded}"

    ext = os.path.splitext(expanded)[1].lower()

    # HTML: render with playwright for clean text extraction
    if ext in (".html", ".htm") and PLAYWRIGHT_AVAILABLE:
        print("  [normalize] rendering HTML with playwright")
        return _playwright_extract(expanded)

    # PDF, DOCX, etc: convert via markitdown
    if MARKITDOWN_AVAILABLE and ext in (".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm"):
        print(f"  [normalize] converting {ext} via markitdown")
        md = MarkItDown()
        result = md.convert(expanded)
        return result.text_content

    # Markdown or plain text: read directly
    with open(expanded, encoding="utf-8") as f:
        return f.read()


def _playwright_extract(html_path: str) -> str:
    """Render HTML file in headless Chromium and return visible text."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f"file:///{html_path.replace(os.sep, '/')}")
        text = page.inner_text("body")
        browser.close()
    return text


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

_EVAL_DIMS = ["relevance", "completeness", "depth", "grounded", "specificity", "structure"]
_DIM_WEIGHTS = {"relevance": 0.20, "completeness": 0.20, "depth": 0.25,
                "grounded": 0.15, "specificity": 0.10, "structure": 0.10}


def _extract_eval_from_prose(text: str) -> dict | None:
    """
    Fallback parser: extract dimension scores from prose when the model ignores
    the JSON instruction (e.g. selene-mini returning markdown bullets).
    Looks for patterns like 'relevance: 8', '* Score: 8/10', '**Depth**: 7/10'.
    Returns a result dict if all six dimensions found, else None.
    """
    scores = {}
    for dim in _EVAL_DIMS:
        # Match patterns: "Relevance: 8", "* Score: 8/10", "relevance=8", "**Relevance**: 8/10"
        m = re.search(
            rf'(?i)\b{dim}\b[^\n]{{0,60}}?(\d{{1,2}})(?:\s*/\s*10)?',
            text,
        )
        if m:
            val = int(m.group(1))
            if 0 <= val <= 10:
                scores[dim] = val
    if len(scores) < len(_EVAL_DIMS):
        return None
    composite = round(sum(scores[d] * _DIM_WEIGHTS[d] for d in _EVAL_DIMS), 1)
    passed = composite >= 8.0
    # Extract issues/feedback as the full prose (truncated)
    feedback = text.strip()[:800]
    return {
        **scores,
        "score": composite,
        "passed": passed,
        "issues": ["(parsed from prose — evaluator ignored JSON format)"],
        "feedback": feedback,
    }


EVAL_PROMPT = """You are a strict evaluator. Score this output across five dimensions, then compute a weighted composite.

Today's date: {today}
Temporal reference guide — use these exact years for relative terms in both the task and output:
  "this year"   = {this_year}   (the current calendar year)
  "last year"   = {last_year}   (the year before the current year)
  "recent"      = {last_year}–{this_year}

Knowledge-cutoff rule: your training data may not include works, events, or releases from {last_year} onward. When scoring completeness, evaluate whether the output covers the expected TOPIC AREAS and depth — do NOT penalize for omitting specific named papers, products, or events that you cannot independently verify exist in {last_year}. If the output's year references conflict with the temporal guide above, flag the year error in issues but score completeness on coverage, not on named items you happen to know from earlier years.

Task:
{task}

Output:
{content}

Score each dimension 0-10 as an integer:
- relevance (weight 0.20): Does the output address the correct topic and complete the task as specified?
- completeness (weight 0.20): Are all required items or practices present, with nothing important missing?
- depth (weight 0.25): Does each item have a concrete example or implementation note specific enough to act on?
- grounded (weight 0.15): Are specific claims traceable to real systems, documented APIs, or published benchmarks? Penalize invented method names and code stubs that don't correspond to any real library.
- specificity (weight 0.10): Are claims precise and actionable, or vague and generic?
- structure (weight 0.10): Is the document clearly organized and readable?

Dimension score guide (apply to each dimension independently):
- 9-10: exceptional — no meaningful gaps; content a domain expert would be satisfied with
- 7-8: good — addresses the dimension but has at least one concrete gap you can name
- 5-6: surface-level — present but shallow, generic, or missing key parts
- 3-4: weak — significant problems; a practitioner could not act on this
- 1-2: failing — this dimension is essentially absent

Depth calibration anchors (most important dimension — read carefully):
- depth=3: paragraph per item with no example, no mechanism, no numbers — pure definition
- depth=5: each item has 1-2 sentences of explanation but no worked example, no specific threshold, no named tool or technique
- depth=6: some items have a partial example (e.g. names a tool but does not show how to use it; states a principle but gives no concrete scenario)
- depth=7: most items have a concrete example OR a specific implementation note, but at least one major item is still surface-level
- depth=8: every item has a concrete example AND a mechanism (why it works, what can go wrong, what to watch for); a practitioner could act on any section
- depth=9: every item has a worked example with specific parameters, thresholds, or decisions; an expert would find nothing to add
- depth=10: reserved for genuinely exceptional depth — essentially never

Grounded calibration anchors:
- grounded=9-10: every specific claim names a real system, documented API, or published outcome a practitioner could verify
- grounded=7-8: most claims grounded; 1-2 plausible but unverifiable specifics
- grounded=5-6: mix of real and invented specifics; at least one code block with method calls that don't correspond to a documented API
- grounded=3-4: most specifics generic or hallucinated; code blocks use invented method names that describe what the function should do rather than a real call
- grounded=1-2: almost all specifics fabricated; output reads as plausible-sounding fiction

Other calibration anchors:
- A document that covers the topic broadly but omits 2+ major subtopics an expert would expect: completeness=6
- Claims with no source, number, or named system to back them up: specificity=5
- Do not score 9+ on any dimension unless you cannot identify a single concrete improvement

Task-type criteria:
{task_criteria}

Compute composite = round(0.20*relevance + 0.20*completeness + 0.25*depth + 0.15*grounded + 0.10*specificity + 0.10*structure, 1)

Respond with valid JSON only — no preamble, no explanation:
{{
  "relevance": integer 0-10,
  "completeness": integer 0-10,
  "depth": integer 0-10,
  "grounded": integer 0-10,
  "specificity": integer 0-10,
  "structure": integer 0-10,
  "score": composite as a number with one decimal place,
  "passed": true if composite >= 8.0 else false,
  "issues": ["issue naming section and what is missing"],
  "feedback": "one paragraph of specific, actionable feedback for the producer",
  "tac_hours": decimal hours a skilled researcher/engineer would need to produce a PERFECT version of this task from scratch — use task complexity, not the quality of the output above; this is the reference human ceiling. Scale: 0.25=trivial lookup, 1=standard research question, 3=synthesis across many sources, 8=comprehensive technical guide with working examples, 24=novel research requiring primary data collection
}}

Universal rules:
- A bullet list of one-liners with no implementation detail: depth <= 5.
- issues must name the specific section and what is missing (e.g. "Section 2 has no implementation note")
- feedback must tell the producer exactly what to add or change, not just that improvement is possible
- Do not give 10 on any dimension unless it is genuinely exceptional — find at least one thing that could be improved
- For every dimension you scored 8 or below, include at least one specific issue describing exactly what would raise the score
- Be a strict grader. When in doubt, score lower rather than higher.
- Do NOT cite specific papers or products as "missing" from the output unless they are explicitly named in the task — your training data may not represent {last_year} accurately.
- Language consistency: if any portion of the output is not in English (e.g. Chinese, French, Arabic characters appear), cap structure at 3 and add an issue flagging the language switch. The document must be entirely in English."""


# Task-type-specific criteria injected into EVAL_PROMPT
TASK_CRITERIA = {
    "enumerated": (
        "This is an enumerated list task (e.g. 'top N' or 'N most common').\n"
        "- The output must contain exactly the requested number of items. More or fewer is an automatic score cap of 5 and passed=false.\n"
        "- Each item must have a distinct name, a concrete example of it in practice, and a specific implementation note.\n"
        "- Items that restate the same concept in different words count as duplicates — flag them."
    ),
    "best_practices": (
        "This is a best practices task (open-ended, no count constraint).\n"
        "- Evaluate completeness: the practices should cover multiple distinct dimensions of the topic, not cluster around one angle.\n"
        "- Each practice must be actionable — it should tell a practitioner exactly what to do, not just describe a concept.\n"
        "- Flag any major practices that a domain expert would expect to see but are absent.\n"
        "- More practices is not better if they are shallow — depth over breadth."
    ),
    "research": (
        "This is a research synthesis task — NOT a software engineering or coding task.\n"
        "DO NOT penalize for missing 'implementation notes', 'code examples', or 'named tools/APIs' — "
        "those criteria do not apply here.\n\n"
        "Reinterpret the depth and grounded dimensions as follows for this task type:\n"
        "- depth: Does each section provide specific supporting evidence — data points, statistics, "
        "named regions/sectors/entities, direct quotes from sources, or mechanisms that explain "
        "the 'why'? A section that names a region but gives no figures, dates, or causal explanation "
        "is depth=6. A section with specific numbers, named actors, and causal reasoning is depth=8.\n"
        "- grounded: Are empirical claims traceable to named real-world sources — specific reports, "
        "datasets, agencies, or publications a reader could look up? Penalize claims that assert "
        "facts without naming any source. Do NOT require code citations or API references.\n\n"
        "Other criteria:\n"
        "- The output should synthesize findings across sources, not just list facts — explain why "
        "each point matters and what it implies.\n"
        "- Flag claims that introduce information not supported by any source named in the output "
        "(e.g. a global comparison added without citation).\n"
        "- Flag missing nuance or important caveats that affect how the findings should be interpreted."
    ),
    "coding": (
        "This is a software engineering / coding task — the deliverable is WORKING CODE.\n"
        "- The output MUST contain actual code that implements the request, not a prose description "
        "of what the code would do. A description without runnable code is a hard cap of 4 and passed=false.\n"
        "- completeness: every explicit requirement in the task (each feature, parameter, edge case, and "
        "any requested test) must be implemented. Name each missing requirement in issues.\n"
        "- depth: the code must handle the non-trivial parts the task calls out (concurrency, retries, "
        "error paths, resource cleanup), not just the happy path. Stubs or 'TODO' for required logic = depth<=4.\n"
        "- grounded: code must use real, documented APIs of the named libraries/language correctly. "
        "Penalize invented method names, wrong signatures, or calls that would not run. Source/citation "
        "criteria DO NOT apply — do not penalize for missing references.\n"
        "- Reward correctness and runnability over verbosity; a concise correct solution beats a long broken one."
    ),
    "comparison": (
        "This is a comparison task — the output must actually COMPARE the items, not describe each in isolation.\n"
        "- completeness: every item the task names must be covered, AND the axes of comparison the task asks "
        "for (performance, cost, trade-offs, when-to-use) must each be addressed across all items.\n"
        "- depth: reward concrete differentiators — specific numbers, thresholds, or scenarios where one option "
        "wins over another. A side-by-side that never states a trade-off or a 'choose X when…' is depth<=5.\n"
        "- grounded: claims of superiority must be backed by a specific mechanism, benchmark, or named property, "
        "not vague assertion. Do not require academic citations; do require the reasoning be checkable.\n"
        "- A decision/recommendation (which to pick, and under what conditions) should be present and justified."
    ),
    "analysis": (
        "This is an analysis task — explain WHY, with specifics, not just describe WHAT.\n"
        "- depth: each claim should carry a mechanism or causal explanation plus concrete evidence — numbers, "
        "named entities, dates, or worked reasoning. Description without causal 'why' is depth<=5.\n"
        "- grounded: empirical claims should trace to specific data, named systems, or documented behavior. "
        "Penalize hand-wavy assertions; do not require formal citations for reasoning that is self-evidently derived.\n"
        "- completeness: the analysis should address the dimensions an expert would expect for this topic and "
        "surface important caveats or failure modes, not only the obvious angle.\n"
        "- Reward synthesis (connecting factors into a coherent account) over a flat list of observations."
    ),
    "planning": (
        "This is a planning / design task — the output must be an ACTIONABLE plan, not a description of the problem.\n"
        "- completeness: cover the concrete elements the task asks for (components, steps, configs, sequencing); "
        "name any required element that is missing.\n"
        "- depth: steps must be specific enough to act on — named tools, concrete settings/commands, ordering, "
        "and what to do at decision points. Generic advice ('monitor performance') with no mechanism is depth<=5.\n"
        "- grounded: recommended tools/approaches must be real and used correctly; penalize invented tools or "
        "configs that would not work. Source citations are not required.\n"
        "- Reward a plan a competent practitioner could execute without having to fill in the hard parts themselves."
    ),
    "osint": (
        "This is an OSINT / open-source intelligence task.\n"
        "- Information scarcity is a valid finding — if the subject has a minimal public footprint, "
        "the correct output states this clearly with evidence, rather than inventing verification steps or fabricating specifics.\n"
        "- Penalize fabricated search steps, invented profiles, or unverifiable claims about the subject. "
        "Do NOT penalize for lacking 'concrete LinkedIn examples' when the subject has no public profile — "
        "that absence IS the finding.\n"
        "- Reward accurate disambiguation (correctly distinguishing two people with similar names is high-value work).\n"
        "- Depth means covering all available passive data sources exhaustively, not inventing depth through speculation.\n"
        "- Grounded means every claim traces to a named public source (RDAP, crt.sh, Wayback, LinkedIn, etc.) — "
        "not to steps the investigator should take in the future."
    ),
}


def detect_task_type(task: str) -> str:
    """Classify the task for criteria selection.

    Detection is a best-effort FALLBACK. Callers that know the type (e.g. a
    task-suite record's `task_type`) should pass it to evaluate() directly —
    that path is exact and bypasses these heuristics.

    Conservative on purpose: only `coding` is added beyond the original buckets,
    because grading code under the research rubric (which demands source
    citations and rejects implementation detail) catastrophically tanks correct
    code. The softer prose types (comparison/analysis/planning) have criteria in
    TASK_CRITERIA but are NOT auto-detected — their verbs ("compare", "analyze",
    "design") appear in ordinary research prompts too, so regex routing there
    caused more misclassification than it fixed. Use explicit task_type for them.

    Order: instructional ('how to'/'guide') and enumerated ('top N') are matched
    BEFORE coding so "how to implement X" stays a guide, while a bare
    "implement X" request is correctly routed to coding."""
    if re.search(r'\bosint\b|\bopen.source intelligence\b|\bwhois\b|\bdomain investigation\b'
                 r'|\bip investigation\b|\bthreat intel\b|\bpassive recon\b'
                 r'|\bbackground.check\b|\bpublic.record', task, re.IGNORECASE):
        return "osint"
    if re.search(r'\btop\s+\d+\b|\b\d+\s+most\b|\b\d+\s+(?:best|key|common|main)\b', task, re.IGNORECASE):
        return "enumerated"
    if re.search(r'\bbest practices?\b|\bhow to\b|\bstrategies? for\b|\bguide\b|\btips?\b', task, re.IGNORECASE):
        return "best_practices"
    if re.search(r'\bimplement\b|\bwrite (?:a |an )?(?:function|class|script|program|module|test)\b'
                 r'|\bin python\b|\bin (?:rust|go|java|c\+\+|typescript|javascript)\b'
                 r'|\brefactor\b|\bfix the bug\b|\bconnection pool\b|\brate limiter\b', task, re.IGNORECASE):
        return "coding"
    return "research"


def _pick_llamacpp_fallback(exclude: str = "") -> str | None:
    """Return a llamacpp-backed model tag for eval fallback when the primary evaluator is unavailable."""
    endpoints = _list_endpoints()
    # Prefer known-good eval-capable models in size order
    for preferred in ("qwen3-14b", "qwen3-8b", "qwen3-7b"):
        if preferred in endpoints and preferred != exclude:
            ep = endpoints[preferred]
            if ep.get("backend", "") in ("llamacpp", "openai"):
                return preferred
    # Generic fallback: any llamacpp endpoint that isn't the excluded model
    for tag, ep in endpoints.items():
        if ep.get("backend") == "llamacpp" and tag != exclude:
            return tag
    return None


def evaluate(task: str, content: str, prior_issues: list[str] = None, _trace=None,
             _msg_trace=None, task_type: str = None) -> dict:
    """Call the evaluator model. Returns parsed result dict.

    task_type: pass explicitly when the caller knows it (e.g. a task-suite
    record's `task_type`); otherwise it is detected from the task text. An
    unknown/unmapped type safely falls back to the research rubric."""
    if task_type is None:
        task_type = detect_task_type(task)
    print(f"  [evaluate] task_type={task_type}  scoring output...")

    # Code-bearing tasks: do NOT prose-summarize — that strips the actual code,
    # which IS the deliverable, leaving the judge to grade a description. Keep the
    # source verbatim and rely on head+tail truncation below to fit the budget.
    if task_type == "coding":
        eval_content = content
    else:
        eval_content = summarize_for_eval(content, task, _msg_trace or _trace)

    # Hard cap so the prompt fits the evaluator's per-slot context. Budget is
    # num_ctx tokens: rubric ~900 + JSON output ~1024 + this content. We reserve
    # ~2000 tokens for rubric+output and give the rest (~3 chars/token) to content.
    # num_ctx defaults to 4096 (matches an 8B server at --ctx-size 16384 --parallel
    # 4 -> 4096/slot). Raise HARNESS_EVAL_NUM_CTX only if the eval server's per-slot
    # context is larger (e.g. --parallel 2 -> 8192/slot); a value the server can't
    # honor truncates server-side. A bigger budget lets the judge see long code in
    # full instead of with an elided middle.
    _EVAL_NUM_CTX = int(os.environ.get("HARNESS_EVAL_NUM_CTX", "4096"))
    # 4000 chars is the validated safe budget at the 4096 default; grow only the
    # extra context (~3 chars/token) so default behavior is unchanged and a raised
    # num_ctx buys proportionally more visible content.
    _EVAL_CONTENT_CAP = 4000 + max(0, _EVAL_NUM_CTX - 4096) * 3
    # Truncate head+tail rather than head-only: the tail carries conclusions and —
    # for coding tasks — the required test, which a head-only cut silently drops
    # (scoring completeness as if the test were missing). Keep 65% head / 35% tail.
    if len(eval_content) > _EVAL_CONTENT_CAP:
        _keep_head = int(_EVAL_CONTENT_CAP * 0.65)
        _keep_tail = _EVAL_CONTENT_CAP - _keep_head
        eval_content = (eval_content[:_keep_head]
                        + "\n…[middle truncated for eval]…\n"
                        + eval_content[-_keep_tail:])
    _today     = datetime.date.today()
    _this_year = _today.year
    prompt = EVAL_PROMPT.format(
        today=_today.isoformat(),
        this_year=_this_year,
        last_year=_this_year - 1,
        task=task,
        content=eval_content,
        task_criteria=TASK_CRITERIA.get(task_type, TASK_CRITERIA["research"]),
    )

    result = None
    raw = ""
    _conn_failed = False
    for _eval_attempt in range(2):
        _eval_model = EVALUATOR_MODEL
        if _eval_attempt == 1 and _conn_failed:
            fallback = _pick_llamacpp_fallback(exclude=PRODUCER_MODEL)
            if fallback and fallback != EVALUATOR_MODEL:
                _eval_model = fallback
                print(f"  [evaluate] primary evaluator unavailable — switching to llamacpp fallback: {_eval_model}")
        try:
            response = ollama.chat(
                model=_eval_model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.0, "num_predict": 1024, "num_ctx": _EVAL_NUM_CTX},
                format="json",
            )
        except Exception as _conn_err:
            print(f"  [warn] evaluator connection error (attempt {_eval_attempt+1}): {_conn_err!s:.120}")
            _conn_failed = True
            if _eval_attempt == 0:
                time.sleep(8)
            continue

        if _trace is not None:
            _trace.log_usage(response, stage="wiggum_eval")

        # Capture thinking content if the evaluator model supports it
        thinking = getattr(response.message, "thinking", None) or ""
        if thinking:
            _emit("thinking", {"stage": "eval", "text": thinking[:8000], "chars": len(thinking)})

        raw = response["message"]["content"].strip()

        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        # Strip <think>...</think> blocks some models prepend
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

        _turn_trace = _msg_trace or _trace
        if _turn_trace is not None:
            _turn_trace.log_llm_turn("wiggum_eval", prompt, raw, thinking=thinking)

        try:
            result = json.loads(raw)
            break
        except json.JSONDecodeError:
            print(f"  [warn] evaluator returned non-JSON (attempt {_eval_attempt+1}): {raw[:200]}")
            prose_result = _extract_eval_from_prose(raw)
            if prose_result:
                print(f"  [warn] prose fallback succeeded: score={prose_result['score']}")
                result = prose_result
                break
            if _eval_attempt == 0:
                print("  [warn] retrying evaluation...")
                time.sleep(3)

    if result is None:
        return {"passed": False, "score": 0.0, "issues": ["evaluator parse error"],
                "feedback": raw, "_eval_failed": True}

    # Recompute composite from dimension scores in Python — don't trust model arithmetic
    dims = {
        "relevance":    (result.get("relevance", 0),    0.20),
        "completeness": (result.get("completeness", 0), 0.20),
        "depth":        (result.get("depth", 0),        0.25),
        "grounded":     (result.get("grounded", 0),     0.15),
        "specificity":  (result.get("specificity", 0),  0.10),
        "structure":    (result.get("structure", 0),    0.10),
    }

    # Hallucination penalty: dock depth for fabricated code stubs
    stub_count = _count_stub_blocks(eval_content)
    if stub_count:
        raw_depth = dims["depth"][0]
        docked = max(0, raw_depth - stub_count)
        dims["depth"] = (docked, dims["depth"][1])
        print(f"  [hallucination] {stub_count} fabricated stub block(s) — depth docked {raw_depth}→{docked}")

    composite = round(sum(score * weight for score, weight in dims.values()), 1)
    result["score"] = composite
    result["dims"] = {k: v[0] for k, v in dims.items()}

    # Enforce threshold
    result["passed"] = composite >= PASS_THRESHOLD

    # Extract tac_hours — clamp to sane range [0.1, 200]
    try:
        tac = float(result.get("tac_hours", 0) or 0)
        result["tac_hours"] = round(max(0.1, min(tac, 200.0)), 2) if tac > 0 else None
    except (TypeError, ValueError):
        result["tac_hours"] = None

    # Attach thinking content if present (non-empty only)
    if thinking:
        result["thinking"] = thinking

    return result


# ---------------------------------------------------------------------------
# Revision
# ---------------------------------------------------------------------------

REVISE_PROMPT = """You produced the following output for this task:

Task: {task}

Your output:
{content}

The evaluator found these issues:
{issues}

Evaluator feedback:
{feedback}

{style_reminder}Produce a corrected version. Output ONLY the revised markdown starting with # — no preamble, no commentary."""


def _revise_style_reminder() -> str:
    """Return a style reminder paragraph if HARNESS_SYNTH_INSTRUCTION is active."""
    instr = os.environ.get("HARNESS_SYNTH_INSTRUCTION", "").strip()
    if not instr:
        return ""
    return f"Original output instructions (maintain these constraints while fixing issues):\n{instr}\n\n"


def revise(task: str, content: str, eval_result: dict, _trace=None, _msg_trace=None) -> str:
    """Ask the producer model to revise the output given evaluator feedback."""
    print("  [revise] asking producer to fix issues...")

    issues_list = eval_result.get("issues", [])
    issues_text = "\n".join(f"- {i}" for i in issues_list)
    revision_content = summarize_for_revision(content, task, issues_list, _msg_trace or _trace)
    # Hard cap: even if summarizer fails and returns full content, cap the revision
    # prompt to ~2 000 tokens so the producer's KV cache stays bounded.
    # num_ctx: 16384 is silently dropped by _chat_vllm (not translated to OpenAI API),
    # so the actual limit is whatever llama-server was started with. Keep input small.
    _REVISE_CONTENT_CAP = int(os.environ.get("WIGGUM_REVISE_CONTENT_CAP", 8000))
    if len(revision_content) > _REVISE_CONTENT_CAP:
        revision_content = revision_content[:_REVISE_CONTENT_CAP] + "\n…[truncated for revision]…"
        print(f"  [revise] content hard-capped at {_REVISE_CONTENT_CAP} chars")
    prompt = REVISE_PROMPT.format(
        task=task,
        content=revision_content,
        issues=issues_text,
        feedback=eval_result.get("feedback", ""),
        style_reminder=_revise_style_reminder(),
    )

    response = ollama.chat(
        model=PRODUCER_MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.1, "think": False, "num_predict": 4096, "num_ctx": 12288},
    )
    if _trace is not None:
        _trace.log_usage(response, stage="wiggum_revise")
    _turn_trace = _msg_trace or _trace
    if _turn_trace is not None:
        _turn_trace.log_llm_turn("wiggum_revise", prompt, response["message"]["content"].strip())

    return response["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def loop(task: str, output_path: str, producer_model: str = PRODUCER_MODEL, evaluator_model: str = EVALUATOR_MODEL, parent_trace=None) -> dict:
    """
    Run the Wiggum verification loop on an existing output file.

    Returns a trace dict with round-by-round results, final status, and token stats.
    Respects WIGGUM_MAX_ROUNDS env var to cap rounds (e.g. set to 1 for autoresearch eval).
    """
    from harness.logger import RunTrace as _RunTrace

    global PRODUCER_MODEL, EVALUATOR_MODEL
    PRODUCER_MODEL = producer_model
    EVALUATOR_MODEL = evaluator_model

    expanded = os.path.expanduser(output_path)
    task_type = detect_task_type(task)

    # Allow env override of max rounds (autoresearch sets WIGGUM_MAX_ROUNDS=1 to save time)
    max_rounds = MAX_ROUNDS
    env_cap = os.environ.get("WIGGUM_MAX_ROUNDS")
    if env_cap is not None:
        try:
            max_rounds = max(1, int(env_cap))
        except ValueError:
            pass

    # Lightweight local trace just for token accumulation — not written to disk
    _local_trace = _RunTrace(task=task, producer_model=producer_model, evaluator_model=evaluator_model)

    trace: dict[str, Any] = {"task": task, "task_type": task_type, "output_path": expanded, "rounds": [], "final": None}

    print("\n[wiggum] starting verification loop")
    print(f"  file:  {expanded}")
    print(f"  task_type: {task_type}")
    print(f"  model: evaluator={evaluator_model} producer={producer_model}")
    print(f"  max rounds: {max_rounds}\n")

    best_score = 0.0
    best_content = ""
    best_round = 0

    # Attempt to unload the producer from VRAM before evaluation.
    # Only meaningful for ollama backend (keep_alive=0 is forwarded); vLLM ignores it
    # and will OOM on any request — skip entirely to avoid noisy failed retries.
    if _list_endpoints().get(producer_model, {}).get("backend") != "vllm":
        try:
            ollama.chat(model=producer_model,
                        messages=[{"role": "user", "content": "x"}],
                        options={"num_predict": 1},
                        keep_alive=0)
            print("  [wiggum] producer unload requested (effective for ollama backend)")
        except Exception:
            pass

    for round_num in range(1, max_rounds + 1):
        print(f"--- round {round_num} ---")

        # 1. Normalize
        with (parent_trace.span("normalize") if parent_trace else _nullspan()):
            content = normalize(expanded)

        # 2. Evaluate
        with (parent_trace.span("wiggum_eval", round=round_num) if parent_trace else _nullspan()):
            result = evaluate(task, content, _trace=_local_trace, _msg_trace=parent_trace)
        score = result.get("score", 0.0)
        passed = result.get("passed", False)
        issues = [i for i in result.get("issues", []) if i and str(i).strip().lower() not in ("none", "n/a", "")]
        feedback = result.get("feedback", "")

        # Track best-scoring round so we can restore it if later rounds regress
        if score > best_score:
            best_score = score
            best_content = content
            best_round = round_num

        # 2b. Optional panel — augments issues with multi-persona perspectives
        panel_reviews = []
        if _PANEL_ENABLED:
            from harness.panel import panel_issues, run_panel
            print("\n  [panel] running 3-persona evaluation panel...")
            with (parent_trace.span("panel") if parent_trace else _nullspan()):
                panel_reviews = run_panel(task, content, evaluator_model, trace=parent_trace)
            panel_issue_list = panel_issues(panel_reviews)
            if panel_issue_list:
                # Merge panel issues: deduplicate against wiggum issues
                existing = {i.lower() for i in issues}
                new_panel_issues = [i for i in panel_issue_list if i.lower() not in existing]
                issues = issues + new_panel_issues
                print(f"  [panel] added {len(new_panel_issues)} new issue(s) from panel")
        dims = result.get("dims", {})

        abbrev = {"relevance": "rel", "completeness": "cmp", "depth": "dep", "specificity": "spc", "structure": "str"}
        dim_str = "  ".join(f"{abbrev.get(k, k)}={v}" for k, v in dims.items()) if dims else ""
        print(f"  score: {score}/10  passed: {passed}  [{dim_str}]")
        if issues:
            for issue in issues:
                print(f"    - {issue}")

        round_record = {
            "round":    round_num,
            "score":    score,
            "dims":     dims,
            "passed":   passed,
            "issues":   issues,
            "feedback": feedback,
            "content":  content[:8_000],   # capture synthesis text for DPO pairs
        }
        if result.get("tac_hours") is not None:
            round_record["tac_hours"] = result["tac_hours"]
        if result.get("thinking"):
            round_record["thinking"] = result["thinking"]
        if panel_reviews:
            round_record["panel_reviews"] = panel_reviews
        trace["rounds"].append(round_record)
        _emit("wiggum", {"round": round_num, "score": score, "passed": passed, "dims": dims})

        if passed:
            print(f"\n[wiggum] PASS on round {round_num} (score {score}/10)")
            trace["final"] = "PASS"
            _attach_token_stats(trace, _local_trace)
            return trace

        # Cycling detection: if score + all dimension scores are identical to the
        # previous round, the producer isn't making measurable progress — return
        # best round immediately rather than burning another revision call.
        if round_num >= 2:
            prev = trace["rounds"][-2]
            if score == prev["score"] and dims == prev.get("dims", {}):
                print(f"  [cycling] score and dims unchanged from round {round_num - 1} — stopping early")
                if best_round < round_num:
                    print(f"\n[wiggum] restoring round {best_round} output (score {best_score:.1f})")
                    with open(expanded, "w", encoding="utf-8") as f:
                        f.write(best_content)
                print(f"\n[wiggum] FAIL — cycling detected after round {round_num}")
                trace["final"] = "FAIL"
                _attach_token_stats(trace, _local_trace)
                return trace

        if round_num == max_rounds:
            # Restore the best-scoring round's content if later rounds regressed
            if best_round < round_num:
                cmp = ">" if best_score > score else "="
                print(f"\n[wiggum] restoring round {best_round} output (score {best_score:.1f} {cmp} round {round_num} score {score:.1f})")
                with open(expanded, "w", encoding="utf-8") as f:
                    f.write(best_content)
            print("\n[wiggum] FAIL — max rounds reached without passing")
            trace["final"] = "FAIL"
            _attach_token_stats(trace, _local_trace)
            return trace

        # Skip revision when the evaluator itself failed (connection/OOM) rather than giving
        # a genuine low score — revising based on "evaluator parse error" produces noise, and
        # reloading the producer while the evaluator is still in VRAM worsens the OOM situation.
        if result.get("_eval_failed"):
            print("  [wiggum] skipping revision — evaluator connection failed, will retry eval")
            time.sleep(5)
            continue

        # 3. Revise — unload evaluator first to free VRAM before reloading the producer.
        # keep_alive=0 works for ollama and llamacpp backends; vLLM ignores it and OOMs
        # on any request — skip entirely for vLLM-backed evaluators.
        if _list_endpoints().get(evaluator_model, {}).get("backend") != "vllm":
            try:
                ollama.chat(model=evaluator_model,
                            messages=[{"role": "user", "content": "x"}],
                            options={"num_predict": 1},
                            keep_alive=0)
                print("  [wiggum] evaluator unloaded before revision")
            except Exception:
                pass

        with (parent_trace.span("wiggum_revise", round=round_num) if parent_trace else _nullspan()):
            revised_content = revise(task, content, result, _trace=_local_trace, _msg_trace=parent_trace)

        if not revised_content.strip():
            print("  [warn] producer returned empty revision, stopping loop")
            trace["final"] = "FAIL"
            return trace

        # Strip fences/epilogues before writing
        try:
            from harness.agent import clean_synthesis_output
            revised_content = clean_synthesis_output(revised_content)
        except Exception:
            revised_content = revised_content.strip()

        # Write revised content back to disk (re-validate path before each write)
        from harness.security import check_output_path
        ok, reason = check_output_path(expanded)
        if not ok:
            print(f"  [security] revision write blocked: {reason}")
            trace["final"] = "ERROR"
            return trace
        with open(expanded, "w", encoding="utf-8") as f:
            f.write(revised_content)
        print(f"  [write] revision saved to {expanded}")

    trace["final"] = "FAIL"
    _attach_token_stats(trace, _local_trace)
    return trace


def _attach_token_stats(trace: dict, local_trace):
    """Copy accumulated token stats from local_trace into the wiggum trace dict."""
    trace["input_tokens"]    = local_trace.data["input_tokens"]
    trace["output_tokens"]   = local_trace.data["output_tokens"]
    trace["tokens_by_stage"] = local_trace.data["tokens_by_stage"]
    # Bubble up TAC from the best-scoring round (most reliable estimate)
    tac_by_round = [(r["score"], r.get("tac_hours")) for r in trace.get("rounds", []) if r.get("tac_hours")]
    if tac_by_round:
        trace["tac_hours"] = max(tac_by_round, key=lambda x: x[0])[1]


# ---------------------------------------------------------------------------
# Annotation evaluation loop (/annotate /wiggum)
# ---------------------------------------------------------------------------

EVAL_PROMPT_PICO = """You are evaluating a PICO biomedical annotation against the original paper content.

The PICO framework produces a structured annotation with EXACTLY these six bold section headers:
  **Population** | **Intervention** | **Comparison** | **Outcome** | **Study Type** | **Evidence Grade**

Each section should have 1-2 sentences of prose grounded in the paper.

Paper content (ground truth):
{paper_context}

PICO annotation to evaluate:
{content}

Score across four dimensions (0-10 integer each):
- section_accuracy (weight 0.35): Does each section correctly capture the right PICO element? Key distinctions: Population = who (n, health status, species); Intervention = compound+dose+duration; Comparison = control condition; Outcome = measured endpoint and effect direction/magnitude; Study Type = design category; Evidence Grade = High/Moderate/Low/Very Low based on design.
- coverage (weight 0.25): Are all 6 sections present with substantive prose? Penalty for missing sections or "Not reported" where data exists in the paper.
- faithfulness (weight 0.25): Is the prose grounded in the paper content — no hallucinated doses, fabricated effect sizes, or invented controls?
- structure (weight 0.15): Does the output start with a # heading and use exactly the 6 bold headers in order?

Dimension score guide (be strict):
- 10:  perfect — all 6 sections present, correctly characterized, grounded in the paper
- 8-9: near-perfect — one minor characterization issue; all 6 sections present
- 6-7: acceptable — one clear section mismatch or one missing/empty section
- 4-5: weak — two or more mismatches or multiple missing sections
- 1-3: failing — most sections wrong, missing, or not grounded in the paper

Compute composite = round(0.35*section_accuracy + 0.25*coverage + 0.25*faithfulness + 0.15*structure, 1)

Respond with valid JSON only — no preamble, no explanation:
{{
  "section_accuracy": integer 0-10,
  "coverage": integer 0-10,
  "faithfulness": integer 0-10,
  "structure": integer 0-10,
  "score": composite as a number with one decimal place,
  "issues": ["brief note on biggest problem, or empty list if perfect"]
}}"""

EVAL_PROMPT_FINANCE = """You are evaluating a finance/quant strategy annotation against the original paper content.

The framework produces a structured annotation with EXACTLY these eight bold section headers:
  **Strategy** | **Signal** | **Asset Class** | **Backtest** | **Performance** | **Limitations** | **Implementation** | **Outlook**

Each section should have 1-2 sentences of prose grounded in the paper.

Paper content (ground truth):
{paper_context}

Finance annotation to evaluate:
{content}

Score across four dimensions (0-10 integer each):
- section_accuracy (weight 0.35): Does each section correctly capture the right element? Key distinctions: Strategy = core approach; Signal = specific predictive factor/indicator; Backtest = sample period and OOS methodology; Performance = Sharpe/return/drawdown metrics; Limitations = data snooping, costs, capacity; Outlook = alpha decay and regime risk.
- coverage (weight 0.25): Are all 8 sections present with substantive prose? Penalty for missing sections or "Not reported" where data exists.
- faithfulness (weight 0.25): Is the prose grounded in the paper — no invented Sharpe ratios, fabricated returns, or hallucinated backtests?
- structure (weight 0.15): Does the output start with a # heading and use exactly the 8 bold headers in order?

Compute composite = round(0.35*section_accuracy + 0.25*coverage + 0.25*faithfulness + 0.15*structure, 1)

Respond with valid JSON only:
{{
  "section_accuracy": integer 0-10,
  "coverage": integer 0-10,
  "faithfulness": integer 0-10,
  "structure": integer 0-10,
  "score": composite as a number with one decimal place,
  "issues": ["brief note on biggest problem, or empty list if perfect"]
}}"""

EVAL_PROMPT_ANNOTATE = """You are evaluating a Nanda Annotated Abstract against the original paper content.

The Nanda framework produces a structured abstract with EXACTLY these eight bold section headers:
  **Topic** | **Motivation** | **Contribution** | **Detail / Nuance** | **Evidence / Contribution 2** | **Weaker result** | **Narrow impact** | **Broad impact**

Each section should have 1-2 sentences of prose synthesized from the paper.

Paper content (ground truth):
{paper_context}

Annotated abstract to evaluate:
{content}

Score across four dimensions (0-10 integer each):
- section_accuracy (weight 0.35): Does each section's prose correctly capture the right rhetorical move? Key distinctions: Topic = subject area (not the contribution); Motivation = gap/need; Contribution = what was built/proved; Evidence = benchmark results; Broad impact = open-source/community-wide effects.
- coverage (weight 0.25): Are all 8 sections present with substantive prose? Penalty for missing sections or empty/placeholder content.
- faithfulness (weight 0.25): Is the prose grounded in the paper content — no hallucinated results, fabricated benchmarks, or invented claims?
- structure (weight 0.15): Does the output start with a # heading and use exactly the 8 bold headers in order?

Dimension score guide (be strict):
- 10:  perfect — all 8 sections present, correctly characterized, grounded in the paper
- 8-9: near-perfect — one minor section characterization issue; all 8 sections present
- 6-7: acceptable — one clear section mismatch or one missing/empty section
- 4-5: weak — two or more section mismatches or multiple missing sections
- 1-3: failing — most sections wrong, missing, or not grounded in the paper

Compute composite = round(0.35*section_accuracy + 0.25*coverage + 0.25*faithfulness + 0.15*structure, 1)

Respond with valid JSON only — no preamble, no explanation:
{{
  "section_accuracy": integer 0-10,
  "coverage": integer 0-10,
  "faithfulness": integer 0-10,
  "structure": integer 0-10,
  "score": composite as a number with one decimal place,
  "passed": true if composite >= 9.0 else false,
  "issues": ["specific issue: which section, what is wrong or missing"],
  "feedback": "one paragraph of specific, actionable corrections for the annotator"
}}"""

REVISE_PROMPT_ANNOTATE = """You are a research-paper analyst producing a Nanda Annotated Abstract.

The Nanda framework requires EXACTLY these eight bold section headers in this order:
**Topic**
**Motivation**
**Contribution**
**Detail / Nuance**
**Evidence / Contribution 2**
**Weaker result**
**Narrow impact**
**Broad impact**

After each header, write 1-2 sentences of plain prose synthesized from the paper. Use only information from the provided text. If a section is not clearly evidenced, write a brief inference grounded in what IS present.

Paper content (ground truth):
{paper_context}

Your previous annotation:
{content}

The evaluator found these issues:
{issues}

Evaluator feedback:
{feedback}

Produce a corrected annotation. Start with:
# Annotated Abstract: <paper title>

Then output all eight headers with revised prose. Output NOTHING before **Topic** and NOTHING after the **Broad impact** prose."""


ANNOTATE_EVALUATOR_MODEL = os.environ.get("WIGGUM_ANNOTATE_EVALUATOR_MODEL", PRODUCER_MODEL)


def loop_annotate(
    task: str,
    output_path: str,
    paper_context: str,
    producer_model: str = PRODUCER_MODEL,
    evaluator_model: str = ANNOTATE_EVALUATOR_MODEL,
    domain: str = "cs",
    parent_trace=None,
) -> dict:
    """
    Wiggum evaluation+revision loop for /annotate /wiggum outputs.

    Uses annotation-specific eval/revise prompts with the original paper content
    as ground truth. The evaluator checks label accuracy, coverage, and faithfulness
    rather than the standard depth/specificity/relevance dimensions.

    Returns a trace dict with round-by-round results and final status.
    """
    from harness.logger import RunTrace as _RunTrace

    global PRODUCER_MODEL, EVALUATOR_MODEL
    PRODUCER_MODEL = producer_model
    EVALUATOR_MODEL = evaluator_model

    expanded = os.path.expanduser(output_path)

    max_rounds = MAX_ROUNDS
    env_cap = os.environ.get("WIGGUM_MAX_ROUNDS")
    if env_cap is not None:
        try:
            max_rounds = max(1, int(env_cap))
        except ValueError:
            pass

    _local_trace = _RunTrace(task=task, producer_model=producer_model, evaluator_model=evaluator_model)
    trace: dict[str, Any] = {"task": task, "task_type": "annotate", "output_path": expanded, "rounds": [], "final": None}

    # Clean garbled PDF text (single-char-per-line runs from MarkItDown pdfminer)
    try:
        from harness.skills import _clean_pdf_text
        paper_context = _clean_pdf_text(paper_context)
    except Exception:
        pass

    print("\n[wiggum:annotate] starting annotation evaluation loop")
    print(f"  file:  {expanded}")
    print(f"  model: evaluator={evaluator_model}  producer={producer_model}")
    print(f"  max rounds: {max_rounds}\n")

    best_score = 0.0
    best_content = ""
    best_round = 0

    for round_num in range(1, max_rounds + 1):
        print(f"--- round {round_num} ---")

        # 1. Read current annotation from disk
        with (parent_trace.span("normalize") if parent_trace else _nullspan()):
            content = normalize(expanded)

        # 2. Evaluate against paper content
        print("  [evaluate] task_type=annotate  scoring annotation...")
        _ann_eval_template = (EVAL_PROMPT_PICO    if domain == "health"
                              else EVAL_PROMPT_FINANCE if domain == "finance"
                              else EVAL_PROMPT_ANNOTATE)
        eval_prompt = _ann_eval_template.format(
            paper_context=paper_context[:4000],
            content=summarize_for_eval(content, task),
        )
        response = ollama.chat(
            model=evaluator_model,
            messages=[{"role": "user", "content": eval_prompt}],
            options={"temperature": 0.0, "think": False, "num_ctx": 16384, "num_predict": 512},
            format="json",
        )
        _local_trace.log_usage(response, stage="wiggum_eval")

        raw = response["message"]["content"].strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        _local_trace.log_llm_turn("wiggum_eval", eval_prompt, raw)

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            print(f"  [warn] evaluator returned non-JSON: {raw[:200]}")
            result = {"passed": False, "score": 0.0, "issues": ["evaluator parse error"], "feedback": raw}

        # Recompute composite in Python — don't trust model arithmetic
        ann_dims = {
            "section_accuracy": (result.get("section_accuracy", 0), 0.35),
            "coverage":         (result.get("coverage", 0),         0.25),
            "faithfulness":     (result.get("faithfulness", 0),     0.25),
            "structure":        (result.get("structure", 0),        0.15),
        }
        composite = round(sum(score * weight for score, weight in ann_dims.values()), 1)
        result["score"] = composite
        result["dims"]  = {k: v[0] for k, v in ann_dims.items()}
        result["passed"] = composite >= PASS_THRESHOLD

        score   = result["score"]
        passed  = result["passed"]
        issues  = [i for i in result.get("issues", []) if i and str(i).strip().lower() not in ("none", "n/a", "")]
        feedback = result.get("feedback", "")

        if score > best_score:
            best_score = score
            best_content = content
            best_round = round_num

        abbrev  = {"section_accuracy": "sec", "coverage": "cov", "faithfulness": "fth", "structure": "str"}
        dim_str = "  ".join(f"{abbrev.get(k, k)}={v[0]}" for k, v in ann_dims.items())
        print(f"  score: {score}/10  passed: {passed}  [{dim_str}]")
        if issues:
            for issue in issues:
                print(f"    - {issue}")

        round_record = {
            "round":    round_num,
            "score":    score,
            "dims":     result["dims"],
            "passed":   passed,
            "issues":   issues,
            "feedback": feedback,
            "content":  content[:8_000],   # capture synthesis text for DPO pairs
        }
        trace["rounds"].append(round_record)

        if passed:
            print(f"\n[wiggum:annotate] PASS on round {round_num} (score {score}/10)")
            trace["final"] = "PASS"
            _attach_token_stats(trace, _local_trace)
            return trace

        # Cycling detection: identical score + dims → producer is stuck, stop early
        if round_num >= 2:
            prev = trace["rounds"][-2]
            if score == prev["score"] and result["dims"] == prev.get("dims", {}):
                print(f"  [cycling] score and dims unchanged from round {round_num - 1} — stopping early")
                if best_round < round_num:
                    print(f"\n[wiggum:annotate] restoring round {best_round} output (score {best_score:.1f})")
                    with open(expanded, "w", encoding="utf-8") as f:
                        f.write(best_content)
                print(f"\n[wiggum:annotate] FAIL — cycling detected after round {round_num}")
                trace["final"] = "FAIL"
                _attach_token_stats(trace, _local_trace)
                return trace

        if round_num == max_rounds:
            if best_round < round_num:
                print(f"\n[wiggum:annotate] restoring round {best_round} output (score {best_score:.1f} > round {round_num} score {score:.1f})")
                with open(expanded, "w", encoding="utf-8") as f:
                    f.write(best_content)
            print("\n[wiggum:annotate] FAIL — max rounds reached without passing")
            trace["final"] = "FAIL"
            _attach_token_stats(trace, _local_trace)
            return trace

        # 3. Revise — re-annotate using paper context + evaluator feedback
        print("  [revise] re-annotating with evaluator corrections...")
        issues_text  = "\n".join(f"- {i}" for i in issues)
        revise_prompt = REVISE_PROMPT_ANNOTATE.format(
            paper_context=paper_context[:4000],
            content=content,
            issues=issues_text,
            feedback=feedback,
        )
        rev_response = ollama.chat(
            model=producer_model,
            messages=[{"role": "user", "content": revise_prompt}],
            options={"temperature": 0.1, "think": False, "num_predict": 8192, "num_ctx": 16384},
        )
        _local_trace.log_usage(rev_response, stage="wiggum_revise")
        _local_trace.log_llm_turn("wiggum_revise", revise_prompt, rev_response["message"]["content"].strip())
        revised = rev_response["message"]["content"].strip()

        if not revised.strip():
            print("  [warn] producer returned empty revision, stopping")
            trace["final"] = "FAIL"
            _attach_token_stats(trace, _local_trace)
            return trace

        try:
            from harness.agent import clean_synthesis_output
            revised = clean_synthesis_output(revised)
        except Exception:
            pass

        from harness.security import check_output_path
        ok, reason = check_output_path(expanded)
        if not ok:
            print(f"  [security] revision write blocked: {reason}")
            trace["final"] = "ERROR"
            _attach_token_stats(trace, _local_trace)
            return trace

        with open(expanded, "w", encoding="utf-8") as f:
            f.write(revised)
        print(f"  [write] revised annotation saved to {expanded}")

    trace["final"] = "FAIL"
    _attach_token_stats(trace, _local_trace)
    return trace


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def print_trace(trace: dict):
    print("\n==============================")
    print(" Wiggum Loop Trace")
    print("==============================")
    for r in trace["rounds"]:
        print(f"  Round {r['round']}: score={r['score']}/10 passed={r['passed']}")
    print(f"  Final: {trace['final']}")
    print("==============================\n")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print('usage: python -m harness.wiggum "<task>" <output_path>')
        sys.exit(1)

    task_arg = sys.argv[1]
    path_arg = sys.argv[2]

    result = loop(task_arg, path_arg)
    print_trace(result)
    sys.exit(0 if result["final"] == "PASS" else 1)

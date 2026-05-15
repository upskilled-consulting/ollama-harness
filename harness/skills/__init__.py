"""
skills/__init__.py — skill registry and invocation layer for the harness agent.

Skills extend the agent pipeline at defined hook points:

  pre_research   — modify search behaviour (e.g. force deep search)
  pre_synthesis  — inject additional instructions into the synthesis prompt
  post_synthesis — transform or augment the synthesized output
  post_wiggum    — run additional evaluation after the verification loop

Invocation — explicit slash commands in the task string:
    python agent.py "/annotate /cite Search for RAG papers and save to output.md"

Invocation — automatic, via per-skill trigger predicates:
    Planner complexity="high"   → panel auto-activates
    Task mentions "paper"       → annotate auto-activates
    Task mentions "exhaustive"  → deep auto-activates

Skills are loaded lazily — importing skills.py does not import kg_gen, panel, etc.
"""

import os
import re
from datetime import UTC, datetime as _datetime

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
# Each entry:
#   description  — shown in /skills listing
#   hook         — pipeline stage: pre_research | pre_synthesis | post_synthesis | post_wiggum
#   prompt       — text injected into synthesis prompt (pre_synthesis only); None otherwise
#   auto         — callable(task: str, plan) -> bool; None = explicit-only
# ---------------------------------------------------------------------------

REGISTRY: dict[str, dict] = {

    "annotate": {
        "description": "Standalone: read a paper (local or URL) and output a Nanda Annotated Abstract",
        "hook":        "standalone",
        "prompt":      None,
        "auto":        None,   # explicit only — /annotate bypasses the whole pipeline
    },

    "knowledge-graph": {
        "description": "Generate a D3.js knowledge graph from the synthesized content",
        "hook":        "post_synthesis",
        "prompt":      None,
        "auto": lambda task, plan: bool(re.search(
            r"knowledge[\s-]graph|\bkg\b|visuali[sz]e", task, re.IGNORECASE
        )),
    },

    "panel": {
        "description": "Run the 3-persona evaluation panel (Domain Practitioner, Critical Reviewer, Informed Newcomer)",
        "hook":        "post_wiggum",
        "prompt":      None,
        "auto": lambda task, plan: plan.complexity == "high",
    },

    "deep": {
        "description": "Force MAX_SEARCH_ROUNDS, disable novelty saturation gate",
        "hook":        "pre_research",
        "prompt":      None,
        "auto": lambda task, plan: bool(re.search(
            r"\bcomprehensive\b|\bthorough\b|\bexhaustive\b|\bin.depth\b|\bdeep.dive\b",
            task, re.IGNORECASE
        )),
    },

    "cite": {
        "description": "Require source attribution and citations for each claim",
        "hook":        "pre_synthesis",
        "prompt": (
            "For each significant claim, technique, or recommendation, include a source reference "
            "in parentheses (e.g. the URL or publication name from the research context). "
            "If a claim cannot be attributed to the provided sources, flag it explicitly as inferred."
        ),
        "auto": None,   # explicit only — too broad to auto-trigger
    },

    "date": {
        "description": "Inject today's date into the synthesis prompt so the model knows the current date",
        "hook":        "pre_synthesis",
        "prompt":      lambda: f"Today's date is {_datetime.now(UTC).strftime('%Y-%m-%d')} — use this when referencing the current date or year in your output.",
        "auto": lambda task, plan: bool(re.search(
            r"\bto[\s-]date\b|\bso[\s-]far\b|\bthis[\s-]year\b|\bcurrent(?:ly)?\b"
            r"|\blatest\b|\brecent(?:ly)?\b|\btoday\b|\bright[\s-]now\b|\bas[\s-]of\b"
            r"|\b(?:in\s+)?20\d\d\b",
            task, re.IGNORECASE
        )),
    },

    "time": {
        "description": "Inject the current UTC timestamp into the synthesis prompt",
        "hook":        "pre_synthesis",
        "prompt":      lambda: f"Current UTC timestamp: {_datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')} — use this when referencing the current time in your output.",
        "auto":        None,
    },

    "annotated-abstract": {
        "description": "Alias for /annotate",
        "hook":        "standalone",
        "prompt":      None,   # resolved to "annotate" at parse time
        "auto":        None,
    },

    "wiggum": {
        "description": "Run the wiggum evaluation+revision loop on the output (combine with /annotate for annotation eval)",
        "hook":        "modifier",
        "prompt":      None,
        "auto":        None,   # explicit only — always opt-in
    },

    "email": {
        "description": (
            "Generate personalized email JSON drafts, saved to email_drafts/ by default. "
            "Two modes:\n"
            "  Single: /email <Name> <email@x.com> <file/url/text> <goal>\n"
            "  Batch:  /email <contacts.csv> <goal>\n"
            "Source can be a URL, local file (pdf/txt/md/docx/html/pptx), or inline text. "
            "Batch mode reads CSV columns: name, affiliation, emails/email, "
            "topic_keywords, summary, markdown, content_url."
        ),
        "hook":        "standalone",
        "prompt":      None,
        "auto":        None,   # explicit only
    },

    "github": {
        "description": (
            "GitHub operations via gh CLI: push, pr create/list/view/merge/review, "
            "issue create/list/view, repo view/clone, status"
        ),
        "hook":        "standalone",
        "prompt":      None,
        "auto":        None,   # explicit only — always opt-in
    },

    "review": {
        "description": (
            "Review staged/unstaged/last/all diff against Karpathy rubric: "
            "no magic, no speculative abstractions, no dead code, functions do one thing"
        ),
        "hook":        "standalone",
        "prompt":      None,
        "auto":        None,   # explicit only
    },

    "lit-review": {
        "description": (
            "Literature review pipeline: fetch arXiv papers, enrich with citation graph "
            "(Semantic Scholar), curate, annotate+wiggum, cluster, synthesize, render via Jinja2 template"
        ),
        "hook":        "standalone",
        "prompt":      None,
        "auto":        None,   # explicit only
    },

    "recall": {
        "description": (
            "Standalone: semantic search over agent memory. "
            "Usage: /recall <query> [--n N] [--facts] [--scores]"
        ),
        "hook":        "standalone",
        "prompt":      None,
        "auto":        None,   # explicit only
    },

    "queue": {
        "description": (
            "Standalone: add one or more tasks to the server run queue. "
            "Usage: /queue <task1> ;; <task2> ;; ... — tasks execute sequentially"
        ),
        "hook":        "standalone",
        "prompt":      None,
        "auto":        None,   # explicit only
    },

    "orientation": {
        "description": (
            "Standalone: build a full situational awareness document for the agent — "
            "directory tree (with mtime/size), .env config, recent runs, active experiments, "
            "git log, GPU state, and wiki self-knowledge. Compresses with the LLM if the "
            "document exceeds the context budget. Use when the agent needs to understand "
            "its own environment before tackling an unfamiliar task."
        ),
        "hook":        "standalone",
        "prompt":      None,
        "auto":        None,
    },

    "introspect": {
        "description": (
            "Standalone: answer questions about the agent from memory + context/ files; "
            "no web search. Use for self-referential tasks like 'describe your skillset'."
        ),
        "hook":        "standalone",
        "prompt":      None,
        "auto":        None,   # explicit only — user must deliberately invoke self-reflection
    },

    "contextualize": {
        "description": (
            "Pre-research: inject agent self-knowledge (context/ files) into any "
            "self-referential task; skips web search when context files are present."
        ),
        "hook":        "pre_research",
        "prompt":      None,
        "auto": lambda task, plan: bool(re.search(
            r"\byour(?:self)?\b"
            r"|\bwhat (?:can|are) you\b"
            r"|\bdescribe (?:you\b|the agent\b|the harness\b)"
            r"|\babout (?:you\b|the agent\b|the harness\b)"
            r"|\bagent['\u2019s]?\s+(?:capabilities?|skills?|functions?|role)\b"
            r"|\bthe harness\b",
            task, re.IGNORECASE,
        )),
    },

    "sync-wiki": {
        "description": (
            "Extract implementation facts from source code (models, constants, prompts, "
            "weights) and write a structured Implementation Reference section into "
            "wiki/pipeline.md. Deterministic — no web search, no LLM extraction."
        ),
        "hook":   "standalone",
        "prompt": None,
        "auto":   None,   # explicit only — user must invoke /sync-wiki
    },

    "playwright": {
        "description": (
            "LLM-guided browser navigation using Playwright (headed Chromium). "
            "Navigates to a website, intelligently traverses pages to find a target "
            "(via site search, link-following, or direct goto), then extracts and "
            "synthesizes the content. Use for JS-rendered pages, multi-hop navigation, "
            "or any site where fetch_url_content() fails. "
            "Invocation: /playwright go to <site>, <goal>"
        ),
        "hook":   "standalone",
        "prompt": None,
        "auto":   None,   # explicit only — triggered by /playwright token or voice intent
    },

    "sitemap": {
        "description": (
            "Discover all pages on a domain using the fastest available method: "
            "robots.txt → sitemap.xml → DDGS site: search → BFS crawl. "
            "Optionally ranks pages by a goal string and writes a markdown report. "
            "Invocation: /sitemap <url> [optional goal]"
        ),
        "hook":   "standalone",
        "prompt": None,
        "auto":   None,
    },

    "crawl": {
        "description": "Alias for /sitemap. Invocation: /crawl <url> [optional goal]",
        "hook":   "standalone",
        "prompt": None,
        "auto":   None,
    },

    "re-orient": {
        "description": (
            "Fast project state snapshot combining the cached /orientation doc with live "
            "GitHub data (recent commits, merged PRs, open PRs, open issues, CI runs). "
            "Runs in seconds — no agent subprocess, no wiggum loop. "
            "Optionally steered by a focus question. "
            "Invocation: /re-orient [optional question or focus]"
        ),
        "hook":   "standalone",
        "prompt": None,
        "auto":   None,
    },

    "forge:plugin": {
        "description": (
            "Generate a new plugin — skills, commands, and manifest — from a natural-language description. "
            "Writes files to plugins/<name>/ and hot-loads immediately. "
            "Invocation: /forge:plugin <description>"
        ),
        "hook":   "standalone",
        "prompt": None,
        "auto":   None,
    },

    "forge:list": {
        "description": (
            "List all installed plugins, their commands, and skill files. "
            "Invocation: /forge:list"
        ),
        "hook":   "standalone",
        "prompt": None,
        "auto":   None,
    },

    "debug": {
        "description": (
            "Diagnose recent ERROR or FAIL runs and propose a specific fix. "
            "Reads run records, wiggum eval logs, trace event sequences, and relevant source. "
            "Handles both code crashes (ERROR) and quality failures (FAIL score). "
            "Invocation: /debug [task_type | model | ERROR | FAIL]  — defaults to last failure"
        ),
        "hook":   "standalone",
        "prompt": None,
        "auto":   None,
    },

    "suggest": {
        "description": (
            "Synthesise one concrete next task from current project state: recent runs, "
            "git log, orientation cache, and autoresearch progress. "
            "Returns a single recommendation with rationale and a ready-to-run command. "
            "Reads cached /orientation data — run /orientation first if cache is stale. "
            "Invocation: /suggest"
        ),
        "hook":   "standalone",
        "prompt": None,
        "auto":   None,
    },

    "troubleshoot": {
        "description": (
            "Higher-order skill combining /debug and /suggest in a single LLM call. "
            "Loads recent ERROR/FAIL run records, wiggum eval logs, trace events, and relevant source "
            "alongside orientation cache, git log, and autoresearch state, then synthesises a "
            "four-part response: Issue / Root cause / Fix / Next task after fix. "
            "Falls back to suggest-only mode when no active failures are found. "
            "Optional filter: /troubleshoot [task_type | model | ERROR | FAIL] — defaults to last 2 failures. "
            "Invocation: /troubleshoot [filter]"
        ),
        "hook":   "standalone",
        "prompt": None,
        "auto":   None,
    },

    "transcribe": {
        "description": (
            "Transcribe a local audio file using OpenAI Whisper. "
            "Searches common locations (Desktop, Downloads, Documents, Music, Videos) "
            "if the file is not found at the given path. "
            "Output saved to a user-specified .md file or auto-named <stem>-transcript.md "
            "in the working directory. "
            "Invocation: /transcribe <filename> [to <output.md>]"
        ),
        "hook":   "standalone",
        "prompt": None,
        "auto":   None,
    },

    "design": {
        "description": (
            "Extract a structured design system from a URL: colors, typography, spacing, "
            "components, and complete CSS. Uses Playwright + vision model for screenshot analysis. "
            "Invocation: /design <url> [save to design.md]"
        ),
        "hook":   "standalone",
        "prompt": None,
        "auto":   None,
    },

    "build-page": {
        "description": (
            "Generate a self-contained HTML page from a design system .md and a folder of content .md files. "
            "With --refine N, opens the result in Chrome and iteratively refines against the original screenshots. "
            "Invocation: /build-page <design.md> from <content_dir/> [save to index.html] [--refine N]"
        ),
        "hook":   "standalone",
        "prompt": None,
        "auto":   None,
    },

    "site": {
        "description": (
            "Full pipeline: extract design system from URL, then generate HTML from content folder. "
            "Combines /design + /build-page in one command. "
            "Invocation: /site <url> from <content_dir/> [save to index.html] [--refine N]"
        ),
        "hook":   "standalone",
        "prompt": None,
        "auto":   None,
    },

    "deck": {
        "description": (
            "Generate a themed .pptx slide deck. "
            "Extracts a design system from a URL or .md file, loads content from a URL, "
            "folder of .md files, or PDF (local or URL), and renders slides with python-pptx. "
            "Invocation: /deck --design <url|design.md> --content <url|dir|pdf> [--out <file.pptx>] [--title \"Title\"]"
        ),
        "hook":   "standalone",
        "prompt": None,
        "auto":   None,
    },

    "test-harness": {
        "description": (
            "Run the harness test suite and save output to agent-workspace/test-results/latest.txt. "
            "Default: fast suite (skips the ~14-min Ollama integration test). "
            "Invocation: /test-harness [--full] [-k <keyword>]"
        ),
        "hook":   "standalone",
        "prompt": None,
        "auto":   None,   # explicit only
    },

    "onboarding": {
        "description": (
            "First-run personalization: guided interview → data/user_profile.md + .harness-user.toml + memory seed. "
            "3 fixed rounds (role, use cases, output prefs) + up to 3 free-form. "
            "Auto-triggers when .harness-user.toml is absent. Re-run is additive (merges, not overwrites). "
            "Invocation: /onboarding"
        ),
        "hook":   "standalone",
        "prompt": None,
        "auto":   None,
    },

    "grill-me": {
        "description": (
            "Saturation-driven user interview. Asks targeted questions, gates on novelty, "
            "and synthesizes answers into a structured knowledge brief (data/briefs/). "
            "Flags: --thorough (disable gate, run all rounds), --for <skill> (tailor to output). "
            "Invocation: /grill-me [goal] [--thorough] [--for deck|research|email]"
        ),
        "hook":   "standalone",
        "prompt": None,
        "auto":   None,
    },

    "scratchpad": {
        "description": (
            "Pre-synthesis: run Python code to compute exact values before writing. "
            "Forces the tool loop on for any task type. Use when the output requires "
            "concrete, deterministic values (counts, stats, API results, calculations) "
            "rather than LLM estimates. Results saved to agent-workspace/scratch/ for "
            "downstream retrieval. "
            "Invocation: /scratchpad <task>"
        ),
        "hook": "pre_synthesis",
        "prompt": (
            "IMPORTANT: This task requires concrete, deterministic values. "
            "Do NOT estimate or approximate any numbers — use only exact values "
            "from the Code execution results block above. "
            "If a value was computed and saved via save_result(), treat it as ground truth. "
            "Reference computed values directly (e.g. 'exactly 42 runs matched' not 'approximately 40'). "
            "If a required value was not computed, state that explicitly rather than guessing."
        ),
        "auto": None,  # explicit only — user opts in when they need deterministic values
    },

}

# ---------------------------------------------------------------------------
# Context file loader — used by /introspect and /contextualize
# ---------------------------------------------------------------------------

def load_context_files() -> str:
    """
    Load wiki pages tagged with 'introspect: true' in their YAML frontmatter.
    These are the canonical self-knowledge pages for /introspect and /contextualize.

    Falls back to context/ directory if wiki/ has no tagged pages (migration safety net).
    Skips index.md and log.md (index and journal — not self-knowledge).
    """
    from pathlib import Path

    _SKIP = {"index.md", "log.md"}

    def _tagged_pages(directory: Path) -> list[str]:
        parts = []
        for f in sorted(directory.glob("*.md")):
            if f.name in _SKIP:
                continue
            try:
                text = f.read_text(encoding="utf-8")
                # Parse YAML frontmatter between leading --- delimiters
                if text.startswith("---"):
                    end = text.find("---", 3)
                    if end != -1 and "introspect: true" in text[3:end]:
                        body = text[end + 3:].strip()
                        parts.append(f"## {f.stem}\n\n{body}")
            except Exception:
                pass
        return parts

    wiki_dir = Path(__file__).parent / "wiki"
    parts = _tagged_pages(wiki_dir) if wiki_dir.exists() else []

    # Fallback to legacy context/ if wiki has no tagged pages yet
    if not parts:
        ctx_dir = Path(__file__).parent / "context"
        if ctx_dir.exists():
            for f in sorted(ctx_dir.glob("*.md")):
                try:
                    parts.append(f"## {f.stem}\n\n{f.read_text(encoding='utf-8')}")
                except Exception:
                    pass

    return "\n\n" + ("\n\n" + "=" * 60 + "\n\n").join(parts)


# Aliases — resolved during parse
_ALIASES = {"annotated-abstract": "annotate"}


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_skills(task: str) -> tuple[str, list[str]]:
    """
    Extract /skill_name tokens from the task string.
    Returns (clean_task, deduplicated_list_of_skill_names).
    Tokens not in REGISTRY are left in the task string unchanged.
    """
    parts      = task.split()
    skill_names: list[str] = []
    clean: list[str] = []

    _drop_next_windows_fragment = False
    for part in parts:
        # Git Bash (MSYS2) converts /skillname → C:/Program Files/Git/skillname.
        # The path splits across two tokens: "C:/Program" and "Files/Git/skillname".
        # Drop the leading Windows drive fragment when we know the next token held the skill.
        if _drop_next_windows_fragment:
            _drop_next_windows_fragment = False
            continue

        if part.startswith("/"):
            raw  = part[1:]
            name = _ALIASES.get(raw, raw)
            if name in REGISTRY:
                if name not in skill_names:
                    skill_names.append(name)
                continue   # strip from task
        elif "/" in part or "\\" in part:
            # Could be a MSYS2-mangled skill token (e.g. "Files/Git/recall")
            stem = part.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
            name = _ALIASES.get(stem, stem)
            if name in REGISTRY:
                if name not in skill_names:
                    skill_names.append(name)
                # Also drop the preceding "C:/Program"-style fragment we already appended
                if clean and clean[-1].startswith(("C:/", "C:\\", "D:/")):
                    clean.pop()
                continue   # strip mangled token from task
        clean.append(part)

    return " ".join(clean), skill_names


def auto_activate(task: str, plan) -> list[str]:
    """
    Return skill names whose auto-trigger fires for this task + plan.
    Safe — never raises; trigger errors are silently skipped.
    """
    active = []
    for name, skill in REGISTRY.items():
        if name in _ALIASES.values() and name != name:   # skip alias targets
            continue
        trigger = skill.get("auto")
        if not trigger:
            continue
        try:
            if trigger(task, plan):
                active.append(name)
        except Exception:
            pass
    return active


def merge_skills(explicit: list[str], auto: list[str]) -> list[str]:
    """Deduplicate, preserving explicit-first order."""
    seen   = set(explicit)
    merged = list(explicit)
    for s in auto:
        if s not in seen:
            seen.add(s)
            merged.append(s)
    return merged


# ---------------------------------------------------------------------------
# Hook helpers
# ---------------------------------------------------------------------------

def get_prompt_injections(active_skills: list[str], hook: str) -> str:
    """
    Concatenate prompt injections for all active skills at the given hook.
    Returns an empty string if none match.
    Prompt values may be a static string or a zero-argument callable returning a string.
    """
    parts = []
    for name in active_skills:
        skill = REGISTRY.get(name, {})
        if skill.get("hook") == hook and skill.get("prompt"):
            p = skill["prompt"]
            parts.append(p() if callable(p) else p)
    return "\n\n".join(parts)


def skills_at_hook(active_skills: list[str], hook: str) -> list[str]:
    """Return the subset of active_skills that fire at the given hook."""
    return [n for n in active_skills if REGISTRY.get(n, {}).get("hook") == hook]


# ---------------------------------------------------------------------------
# Post-synthesis handler
# ---------------------------------------------------------------------------

def run_post_synthesis(
    active_skills: list[str],
    content:       str,
    task:          str,
    output_path:   str,
    producer_model: str,
) -> dict:
    """
    Run all post_synthesis skill handlers.
    Returns a dict of results keyed by skill name (e.g. {"knowledge-graph": "/path/to/graph.html"}).
    """
    results = {}
    for name in skills_at_hook(active_skills, "post_synthesis"):
        if name == "knowledge-graph":
            results["knowledge-graph"] = _handle_kg(content, task, output_path, producer_model)
    return results


def _handle_kg(content: str, task: str, output_path: str, producer_model: str) -> str | None:
    """Generate a D3.js knowledge graph from synthesized content."""
    try:
        from datetime import datetime
        from pathlib import Path

        from harness.skills.kg_gen import generate_kg, render_html

        article = content[:4000]
        graph_data = generate_kg(article, producer_model, num_nodes=12, max_edge_density=3)

        ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir   = Path(output_path).parent if output_path else Path("graphs")
        kg_path   = out_dir / f"kg_{ts}.html"

        render_html(graph_data, kg_path, title=task[:60], model=producer_model, article_snippet=article)
        print(f"  [skill:knowledge-graph] graph → {kg_path.resolve()}")
        return str(kg_path.resolve())
    except Exception as e:
        print(f"  [skill:knowledge-graph] failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Standalone skill handler — /annotate
# ---------------------------------------------------------------------------

# The 8 rhetorical moves in Nanda's Annotated Abstract framework
_ANNOTATE_LABELS = [
    "Topic",
    "Motivation",
    "Contribution",
    "Detail/Nuance",
    "Evidence/Contribution 2",
    "Weaker result",
    "Narrow impact",
    "Broad impact",
]

_ANNOTATE_SYSTEM = (
    "You are a research-paper analyst. Given paper content, produce an annotated abstract "
    "using the Nanda framework with EXACTLY these eight bold section headers, in this order:\n\n"
    "**Topic**\n"
    "**Motivation**\n"
    "**Contribution**\n"
    "**Detail / Nuance**\n"
    "**Evidence / Contribution 2**\n"
    "**Weaker result**\n"
    "**Narrow impact**\n"
    "**Broad impact**\n\n"
    "Rules:\n"
    "- Each header must appear on its own line, bold, exactly as shown above.\n"
    "- After each header write 1-2 sentences of plain prose synthesized from the paper. Be concise.\n"
    "- Use only information from the provided text. Do not invent results.\n"
    "- If a section is not clearly evidenced, write a brief inference grounded in what IS present.\n"
    "- Output NOTHING before **Topic** and NOTHING after the **Broad impact** prose.\n\n"
    "Section definitions:\n"
    "  Topic                    — what subject area / problem this paper addresses\n"
    "  Motivation               — why this problem matters; the gap or need being addressed\n"
    "  Contribution             — the main new artifact, method, or claim ('We introduce/propose X')\n"
    "  Detail / Nuance          — key technical specifics of how the contribution works\n"
    "  Evidence / Contribution 2 — benchmark results or empirical evidence; secondary findings\n"
    "  Weaker result            — limitations, conditions where the approach underperforms, or open problems\n"
    "  Narrow impact            — specific, bounded applications or immediate takeaways\n"
    "  Broad impact             — wider implications for the field or community (e.g. open-source release)\n"
)

_ANNOTATE_PROMPT = (
    "Here is the paper content. Produce the annotated abstract.\n\n"
    "Start your output with:\n"
    "# Annotated Abstract: <paper title>\n\n"
    "Then output each of the eight section headers followed immediately by 1-2 sentences.\n\n"
    "PAPER CONTENT:\n"
)


_ANNOTATE_SECTION_PATTERNS = [
    ("Abstract",     r"(?i)^#+\s*abstract|^abstract\s*:",          2_000),
    ("Conclusion",   r"(?i)^#+\s*conclusions?",                     2_500),
    ("Introduction", r"(?i)^#+\s*\d*\.?\s*introduction",           2_500),
    ("Results",      r"(?i)^#+\s*\d*\.?\s*(results?|experiments?|evaluation)", 2_500),
    ("Discussion",   r"(?i)^#+\s*\d*\.?\s*discussion",              1_500),
]
_ANNOTATE_CHAR_BUDGET = 10_000

_ANNOTATE_LABELS = [
    "**Topic**",
    "**Motivation**",
    "**Contribution**",
    "**Detail / Nuance**",
    "**Evidence / Contribution 2**",
    "**Weaker result**",
    "**Narrow impact**",
    "**Broad impact**",
]


def _extract_sections(text: str) -> str:
    """
    Extract key sections (Abstract, Conclusion, Introduction, Results, Discussion)
    in priority order within a char budget. Falls back to truncated full text if
    no section headings are found (e.g. arxiv abstract-only pages).
    """
    lines = text.splitlines()
    heading_re = re.compile(r"^#+\s")

    section_starts = []
    for label, pattern, max_chars in _ANNOTATE_SECTION_PATTERNS:
        for idx, line in enumerate(lines):
            if re.match(pattern, line.strip()):
                section_starts.append((label, idx, max_chars))
                break

    if not section_starts:
        # No headings — likely an abstract-only page. Return as-is.
        return text[:_ANNOTATE_CHAR_BUDGET]

    extracted = {}
    for label, start_idx, max_chars in section_starts:
        chunk_lines: list[str] = []
        for line in lines[start_idx:]:
            if chunk_lines and heading_re.match(line):
                break
            chunk_lines.append(line)
        extracted[label] = "\n".join(chunk_lines)[:max_chars]

    priority = ["Abstract", "Conclusion", "Introduction", "Results", "Discussion"]
    parts = []
    remaining = _ANNOTATE_CHAR_BUDGET
    for label in priority:
        if label not in extracted or remaining <= 0:
            continue
        chunk = extracted[label][:remaining]
        parts.append(f"=== {label} ===\n{chunk}")
        remaining -= len(chunk)

    if not parts:
        return text[:_ANNOTATE_CHAR_BUDGET]

    return "\n\n".join(parts)


def _is_valid_annotation(text: str) -> bool:
    """Return True if annotation has a heading and at least 6 of 8 Nanda sections."""
    if not re.search(r"^#\s", text, re.MULTILINE):
        return False
    hits = sum(1 for lbl in _ANNOTATE_LABELS if lbl in text)
    return hits >= 6


def _clean_pdf_text(text: str) -> str:
    """
    Clean garbled PDF extraction output.

    MarkItDown's pdfminer backend sometimes produces single-character-per-line
    output for PDFs with unusual font encoding (common in arXiv papers).
    This collapses those runs back into readable text before feeding to the model.
    """
    lines = text.split("\n")
    cleaned = []
    i = 0
    while i < len(lines):
        # Detect a run of >=5 single-char (or 2-char) lines — garbled PDF artifact
        run_start = i
        while i < len(lines) and len(lines[i].strip()) <= 2:
            i += 1
        run_len = i - run_start
        if run_len >= 5:
            # Collapse: join non-blank single chars, skip pure whitespace lines
            joined = "".join(l.strip() for l in lines[run_start:i] if l.strip())
            if joined:
                cleaned.append(joined)
        else:
            cleaned.extend(lines[run_start:i])
            if i < len(lines):
                cleaned.append(lines[i])
                i += 1
    return "\n".join(cleaned)


def run_annotate_standalone(
    paper_context: str,
    producer_model: str,
    max_retries: int = 3,
    _trace=None,          # optional RunTrace — captures token usage per attempt
) -> str:
    """
    Standalone /annotate handler.

    Reads the paper content (already fetched by agent.py — local PDF or URL),
    extracts key sections (Abstract, Conclusion, Introduction, Results),
    and returns a Nanda-annotated abstract with retry logic.

    Bypasses the normal research → synthesize → wiggum pipeline entirely.
    """
    from harness.inference import chat as _llm_chat

    keep_alive = int(os.environ.get("OLLAMA_KEEP_ALIVE", -1))

    if not paper_context.strip():
        return ""

    cleaned_context = _clean_pdf_text(paper_context)
    context = _extract_sections(cleaned_context)
    print(f"  [annotate] paper context: {len(paper_context)} chars raw → {len(context)} chars extracted")

    # Append /no_think for Qwen3 models — more reliable than the think:false option
    model_lower = producer_model.lower()
    system = _ANNOTATE_SYSTEM
    if "qwen3" in model_lower:
        system = system + "\n/no_think"

    prompt = system + "\n\n" + _ANNOTATE_PROMPT + context

    for attempt in range(1, max_retries + 1):
        resp = _llm_chat(
            model=producer_model,
            messages=[{"role": "user", "content": prompt}],
            options={"num_predict": 2048, "num_ctx": 8192},
            keep_alive=keep_alive,
        )
        if _trace is not None:
            _trace.log_usage(resp, stage="annotate")
        result = resp["message"]["content"].strip()
        # Strip Qwen3 chain-of-thought blocks if present
        result = re.sub(r"<think>.*?</think>", "", result, flags=re.DOTALL).strip()
        # Strip Qwen2.5 end-of-turn tokens and anything after
        result = re.split(r"<\|im_end\|>|<\|endoftext\|>", result)[0].strip()

        # Strip preamble before the annotation heading or first section
        preamble_m = re.search(r"(#\s*Annotated Abstract|\*\*Topic\*\*)", result)
        if preamble_m:
            result = result[preamble_m.start():].strip()

        # Truncate after the Broad impact paragraph.
        # Strategy: take at most 600 chars of content after the header line,
        # then cut at the last sentence-ending punctuation in that window.
        # This avoids dependence on blank lines or stop markers the model may not emit.
        broad_idx = result.find("**Broad impact**")
        if broad_idx != -1:
            header_end = result.find("\n", broad_idx)
            if header_end != -1:
                content_start = header_end + 1
                window = result[content_start : content_start + 600]
                last_sent = max(window.rfind("."), window.rfind("!"), window.rfind("?"))
                if last_sent != -1:
                    result = result[: content_start + last_sent + 1].strip()

        if _is_valid_annotation(result):
            return result

        print(f"  [annotate] attempt {attempt}/{max_retries} — invalid output, retrying...")

    return result  # return last attempt even if invalid; wiggum will catch it


# ---------------------------------------------------------------------------
# CLI — list available skills
# ---------------------------------------------------------------------------

def _print_registry():
    print("\nAvailable skills (prefix task with /name to activate):\n")
    for name, skill in REGISTRY.items():
        if name in _ALIASES:
            continue
        hook  = skill["hook"]
        desc  = skill["description"]
        auto  = "auto" if skill.get("auto") else "explicit"
        print(f"  /{name:<22} [{hook:<15}] [{auto}]  {desc}")
    print()


if __name__ == "__main__":
    _print_registry()

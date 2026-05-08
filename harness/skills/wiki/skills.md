---
title: Skill Catalog
introspect: true
---

# Skill Catalog

All skills are invoked by prefixing a `/skill-name` token in the task string. Tokens are stripped before routing; remaining text becomes the task. Multiple skills can be combined: `/cite /deep research prompt caching...`

## Hook types

| Hook | When it fires |
|------|--------------|
| `standalone` | Bypasses the research→synthesis→wiggum pipeline entirely |
| `pre_research` | Runs before web search; can modify or replace the search phase |
| `pre_synthesis` | Injects a prompt block into the synthesis call |
| `post_synthesis` | Transforms or augments the synthesized output |
| `post_wiggum` | Runs additional evaluation after the verification loop |
| `modifier` | Changes pipeline behaviour without occupying a stage |

---

## Research & Analysis

### `/annotate` — standalone, explicit
Read a paper (local path or URL) and produce a Nanda Annotated Abstract with exactly eight sections: Topic, Motivation, Contribution, Detail/Nuance, Evidence/Contribution 2, Weaker result, Narrow impact, Broad impact. Uses the wiggum evaluator after annotation. Alias: `/annotated-abstract`.

### `/lit-review` — standalone, explicit
Full literature review pipeline: fetch arXiv papers → enrich with Semantic Scholar citation graph → curate → annotate+wiggum → cluster → synthesize → render via Jinja2 template. Produces a structured `.md` review document.

### `/deep` — pre_research, auto-triggers on: "comprehensive", "thorough", "exhaustive", "in-depth", "deep dive"
Forces MAX_SEARCH_ROUNDS and disables the novelty saturation gate so search continues until fully saturated, not just until diminishing returns.

### `/cite` — pre_synthesis, explicit
Injects a citation requirement into synthesis: every significant claim must include a source reference (URL or publication name). Unattributable claims must be flagged as inferred.

### `/scratchpad` — pre_synthesis, explicit
Forces the tool loop on. The model writes and executes Python code before synthesis to compute exact values (counts, stats, API results, calculations). Synthesis is then constrained to use only these computed values — no LLM estimates. Results are saved to `agent-workspace/scratch/` for downstream retrieval.

### `/knowledge-graph` (`/kg`) — post_synthesis, auto-triggers on: "knowledge graph", "kg", "visualize/visualise"
Generates an interactive D3.js knowledge graph from synthesized content (12 nodes, variable edge density). Output: `graphs/kg_<timestamp>.html` alongside the primary output.

---

## Browser & Navigation

### `/playwright` (`/browser`) — standalone, explicit
LLM-guided browser navigation using headless Chromium. Navigates to a website, traverses pages intelligently (site search → link-following → direct goto) to find a target, then extracts and synthesizes the content. Use for JS-rendered pages, multi-hop navigation, or when `fetch_url_content()` fails.
Invocation: `/playwright go to <site>, <goal>`

### `/sitemap` (`/crawl`) — standalone, explicit
Discovers all pages on a domain using the fastest available method: `robots.txt` → `sitemap.xml` → DDGS `site:` search → BFS crawl. Optionally ranks pages by a goal string and writes a markdown report.
Invocation: `/sitemap <url> [optional goal]`

---

## Site Generation

### `/design` — standalone, explicit
Extracts a structured design system from a live URL: colors, typography, spacing, components, and complete CSS. Uses Playwright + vision model for screenshot analysis.
Invocation: `/design <url> [save to design.md]`

### `/build-page` — standalone, explicit
Generates a self-contained HTML page from a design system `.md` file and a folder of content `.md` files. With `--refine N`, opens the result in Chrome and iteratively refines against the original screenshots.
Invocation: `/build-page <design.md> from <content_dir/> [save to index.html] [--refine N]`

### `/site` — standalone, explicit
Full pipeline combining `/design` + `/build-page` in one command.
Invocation: `/site <url> from <content_dir/> [save to index.html] [--refine N]`

### `/deck` — standalone, explicit
Generates a themed `.pptx` slide deck. Extracts a design system from a URL or `.md` file, loads content from a URL, folder of `.md` files, or PDF (local or URL), and renders slides with `python-pptx`.
Invocation: `/deck --design <url|design.md> --content <url|dir|pdf> [--out <file.pptx>] [--title "Title"]`

---

## Memory & Project Intelligence

### `/recall` — standalone, explicit
Semantic search over agent memory (ChromaDB). Surfaces observations relevant to a query.
Invocation: `/recall <query> [--n N] [--facts] [--scores]`

### `/orientation` — standalone, explicit
Builds a full situational awareness document: directory tree (with mtime/size), `.env` config, recent runs, active experiments, git log, GPU state, and wiki self-knowledge. Compresses with the LLM if the document exceeds the context budget. Run this before tackling unfamiliar tasks.

### `/re-orient` — standalone, explicit
Fast project state snapshot combining the cached `/orientation` doc with live GitHub data (recent commits, merged PRs, open PRs, open issues, CI runs). Runs in seconds — no agent subprocess.
Invocation: `/re-orient [optional focus question]`

### `/introspect` — standalone, explicit
Answers questions about the agent from memory + wiki context files. No web search. Use for self-referential tasks ("describe your skillset", "what can you do?"). Loads `wiki/*.md` pages tagged `introspect: true` plus a live capability doc generated from the skill registry.

### `/contextualize` — pre_research, auto-triggers on: self-referential phrasing
Injects agent self-knowledge (wiki/context files) into any self-referential task. Skips web search when context files are present. Auto-triggers on phrases like "yourself", "what can you do", "describe the agent", "agent's capabilities".

### `/suggest` — standalone, explicit
Synthesises one concrete next task from current project state: recent runs, git log, orientation cache, and autoresearch progress. Returns a single recommendation with rationale and a ready-to-run command. Run `/orientation` first if cache is stale.

### `/debug` — standalone, explicit
Diagnoses recent ERROR or FAIL runs and proposes a specific fix. Reads run records, wiggum eval logs, trace event sequences, and relevant source. Handles both code crashes (ERROR) and quality failures (FAIL score).
Invocation: `/debug [task_type | model | ERROR | FAIL]` — defaults to last failure

### `/troubleshoot` — standalone, explicit
Higher-order skill combining `/debug` + `/suggest` in a single LLM call. Produces a four-part response: Issue / Root cause / Fix / Next task after fix. Falls back to suggest-only when no active failures are found.
Invocation: `/troubleshoot [filter]`

---

## Collaboration & Media

### `/email` — standalone, explicit
Generates personalized email JSON drafts, saved to `email_drafts/`.
- Single: `/email <Name> <email@x.com> <file/url/text> <goal>`
- Batch: `/email <contacts.csv> <goal>` — CSV columns: name, affiliation, emails/email, topic_keywords, summary, markdown, content_url

### `/github` — standalone, explicit
GitHub operations via `gh` CLI: push, PR create/list/view/merge/review, issue create/list/view, repo view/clone, status.

### `/review` — standalone, explicit
Reviews staged/unstaged/last/all diffs against the Karpathy rubric: no magic, no speculative abstractions, no dead code, functions do one thing.

### `/sync-wiki` — standalone, explicit
Extracts implementation facts from source code (models, constants, prompts, weights) and writes a structured Implementation Reference section into `wiki/pipeline.md`. Deterministic — no web search, no LLM extraction.

### `/transcribe` — standalone, explicit
Transcribes a local audio file using OpenAI Whisper. Searches Desktop, Downloads, Documents, Music, Videos if the file is not found at the given path. Output: `<stem>-transcript.md` or a user-specified `.md` file.
Invocation: `/transcribe <filename> [to <output.md>]`

### `/queue` — standalone, explicit
Adds one or more tasks to the server run queue. Tasks execute sequentially.
Invocation: `/queue <task1> ;; <task2> ;; ...`

---

## Plugin Framework

### `/forge:plugin` — standalone, explicit
Generates a new plugin (skills, commands, manifest) from a natural-language description. Writes files to `plugins/<name>/` and hot-loads immediately.
Invocation: `/forge:plugin <description>`

### `/forge:list` — standalone, explicit
Lists all installed plugins, their commands, and skill files.

---

## Modifier skills

### `/wiggum` — modifier, explicit
Forces the wiggum evaluation+revision loop on tasks that normally skip it (e.g. combined with `/annotate`). Explicit opt-in only.

### `/panel` — post_wiggum, auto-triggers when plan.complexity == "high"
Runs a 3-persona evaluation panel (Domain Practitioner, Critical Reviewer, Informed Newcomer) after wiggum. Panel issues are merged into the revision prompt. Enable globally via `WIGGUM_PANEL=1`.

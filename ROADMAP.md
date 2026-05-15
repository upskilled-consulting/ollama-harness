# Roadmap — ollama-harness

## North Star

A locally-running swarm of specialized agents that iteratively improves its own harness, models, and capabilities — without human intervention beyond goal-setting and checkpoint approval. The loop closes continuously: run → preference data → fine-tune → hot-swap → benchmark → promote or revert. Human checkpoints at goal-setting and promotion; everything between is autonomous.

This is achievable on a single RTX 5000 Ada (63.8GB VRAM). The scaffolding — orchestrator, vLLM backend, evaluator separation, RLHF feedback, semantic memory, fine-tuning pipeline, and skills registry — is largely built. What remains is closing the manual hand-offs and building toward autonomous swarm operation.

---

## What's been accomplished

### Infrastructure
- FastAPI backend with WebSocket live run updates (`/ws/runs`)
- React/TypeScript dashboard (Vite, Tanstack Query) — full rewrite from Flask/Jinja
- `harness/` as a proper installable Python package with `oh` CLI entry point
- vLLM inference backend (`INFERENCE_BACKEND=vllm`) with multi-endpoint routing
- ChromaDB semantic memory with quality-weighted retrieval
- Structured logging — every run appends a full trace to `data/runs.jsonl`
- Wiggum multi-round evaluation loop with best-round restoration and cycling detection
- Parallel orchestration via `ThreadPoolExecutor` + subprocess isolation
- MCP server with security hardening (task length cap, UNC block, injection scan, semaphore, API key)
- DPO/GRPO/SFT RL dataset pipeline — exported from `runs.jsonl` to HF-ready formats
- Nanda annotator fine-tuning pipeline (`finetune_annotate.py`) with v2 dataset
- PyPI package setup (`pyproject.toml` with metadata, build-system, entry points) — wheel smoke-tested ✓
- Ruff + mypy + TypeScript type-checking all clean in CI
- Leverage metric (`score × lines / runtime_hours`, tac_hours override) logged on every run ✓
- Fan-out planned queries in `gather_research()` — parallel `ThreadPoolExecutor` prefetch ✓
- Oversearch detector — domain diversity tracking, terminates after 2 consecutive zero-net-new-domain rounds ✓
- Test suite — 28 tests across logger, agent, and API endpoint modules ✓
- Search result cache (`search_cache.py`) — SQLite TTL cache for DDGS results and research contexts ✓
- Chunked URL retrieval (`chunker.py`) — 512-token overlapping segments, semantic top-K retrieval via nomic-embed-text ✓
- OCR cascade (`ocr.py`) — PyMuPDF → llama-server GLM-OCR → llama3.2-vision fallback ✓
- Perfetto trace instrumentation — Chrome Trace Event JSON per run, loadable at ui.perfetto.dev ✓
- Curator (`curator.py`) — 5-persona LLM paper scoring with veto floor; filters annotation corpus ✓
- Git state auto-commit (`GIT_STATE=1`) — `RunTrace.finish()` stages `runs.jsonl` + output file and commits on every PASS ✓
- Synthesis instruction fix — `SYNTH_INSTRUCTION*` constants are task-agnostic; sentinel comments (`AUTORESEARCH:SYNTH_INSTRUCTION:*`) allow autoresearch to rewrite them ✓
- Paginated runs API — `GET /api/runs/paged` with 30s in-memory cache; `GET /api/data` uncapped ✓
- GitHub commit detail API — `GET /api/github/commits/{sha}/detail` (message, stat, file list, 16KB-capped diff); `github_repo` parallelized via `asyncio.gather` ✓

### Dashboard views
- **Home** — KPI cards (total runs, pass rate, avg score, token spend) + activity feed; uncapped (all runs, not just last 100)
- **Runs** — merged Runs + Explorer: compact run list + DAG inspector (pipeline graph, per-stage tokens, output preview, Wiggum scores + dim bars, evaluator feedback, RLHF panel, leverage chip); server-side pagination (25/page, total count); DAG zoom controls (+/− buttons, 0.25×–2.0× scale)
- **Submit** — fire a task from the browser; live pulse dot while in flight, `ResultCard` on completion ✓
- **Sessions** — grouped by `session_id`, per-session pass rate / wall time / token spend ✓
- **Analytics** — time-series charts: run volume, pass rate by day, score distribution, token trend ✓
- **Artifacts** — browse output files with markdown preview and download ✓
- **Fine-tune** — training metrics charts (loss, accuracy, lr) + RL dataset browser (preference pairs, reward feedback, GRPO rollouts, DPO with evaluator feedback)
- **GitHub** — repo health (branch, dirty count, ahead/behind); GitHub-style commit activity heatmap (52×7 grid, 5-level intensity); clickable day cells → commit popup; commit clickable → detail drawer with full diff, stat, and changed-files list; PRs, issues, CI runs panels; parallelized repo endpoint ✓
- **MCP** — registered tool inspector: tool cards with name, description, required/optional param badges ✓
- **Sidebar terminal** — `oh >` REPL with input history, live run-status badges (button in sidebar nav)
- **Sidebar voice** — voice input panel (button in sidebar nav)

### Skills
| Skill | Status |
|-------|--------|
| `research <topic>` | ✓ multi-round web search + synthesis |
| `/lit-review <topic>` | ✓ fetch → annotate → cluster → synthesize |
| `/annotate <url\|path>` | ✓ Nanda 8-move annotated abstract |
| `/browser <url> <goal>` | ✓ LLM-guided Playwright navigation |
| `/design <url>` | ✓ design system token extraction |
| `/build-page` | ✓ decomposed 3-pass HTML generation |
| `/site <url> from <dir>` | ✓ design + page build in one command |
| `/deck --design --content` | ✓ themed .pptx from any source |
| `/transcribe <url\|path>` | ✓ YouTube/local audio via whisper.cpp |
| `/recall <topic>` | ✓ semantic memory search |
| `/introspect` | ✓ live capabilities doc from skill registry |
| `/email <contact> <goal>` | ✓ Gmail draft + send |
| `/orientation` | ✓ project state summary |
| `/debug [filter]` | ✓ FAIL/ERROR run diagnosis |
| `/sync-wiki` | ✓ deterministic wiki sync |
| `/panel` | ✓ 3-persona wiggum review panel |
| `/curate` | ✓ 5-persona LLM paper scoring + veto-floor corpus filter |
| `/grill-me [domain]` | ✓ saturation-driven user interview; brief → `data/briefs/` |
| `/onboarding` | ✓ first-run personalization; profile + TOML config + memory seed |

---

## 0.1.0 — PyPI release blockers ✓ COMPLETE

All items resolved. Wheel smoke-tested: `oh --help`, `/introspect`, Jinja templates load
from installed path. Dashboard bundled via `start.py → npm run build`.

---

## 0.2.0 — Dashboard completeness ✓ COMPLETE

All views wired and shipping:
- Sessions — grouped by `session_id`, per-session pass rate / wall time / tokens
- Artifacts — file browser with markdown preview
- Analytics — time-series charts (run volume, pass rate, score distribution, token trend)
- Submit — live pulse dot while in flight; `ResultCard` with score, duration, output preview
- MCP inspector — real tool cards from `GET /api/mcp/tools`, param badges, call log

Remaining open: ~~Submit live output streaming~~ — implemented (see 0.3.0 below).

---

## 0.3.0 — Self-improvement loop

### ✓ Leverage as RLHF reward signal
Computed and logged on every run in `RunTrace.finish()`. Proxy formula:
`leverage = wiggum_score × output_lines / (runtime_hours)`. Overridden by exact
`tac_hours × quality_norm / runtime_s` formula when `tac_hours` is set. Exposed as
`leverage` chip in Runs list and summary card. Secondary DPO reward signal available.

### ✓ Fan-out planned queries
`gather_research()` pre-fetches all `planned_queries` in parallel via
`ThreadPoolExecutor(max_workers=5)` before the loop starts. Loop reads pre-fetched
results; falls back to direct `web_search_raw` if prefetch raised. Eliminates sequential
blocking on the minimum-window rounds.

### ✓ Oversearch detector
Domain diversity tracking per round: `net_new_domains = round_domains - seen_domains`.
After `SEARCHES_PER_TASK` (2) minimum rounds, fires if 2 consecutive rounds add zero
net-new domains. Disabled by `force_deep=True`. Estimated 20-40% token reduction on
well-sourced tasks.

### ✓ Autoresearch stall replan
Stall replan injection into `PROPOSE_PROMPT` after 4+ consecutive discarded experiments.
Already in place.

### ✓ `/plan` interactive approval (Submit view only)
Agent pauses after `make_plan()` when `use_plan=True` in the task request. A
`threading.Event` gate blocks `gather_research()` until the user approves via
`POST /api/tasks/{id}/approve-plan`. The Submit view renders an `ApprovePlanCard`
with an editable query textarea; approving POSTs the (possibly edited) queries and
unblocks the agent. 10-minute timeout auto-approves with original queries.

**Scope note:** approval is only surfaced in the Submit view (the one path where
`use_plan` can be set). The Runs view and floating terminal do not show approval UI —
tasks submitted there without the Submit form will auto-approve after timeout. Extending
approval to those surfaces is deferred; see 0.4.0 below.

### ✓ Search result cache
`search_cache.py` — SQLite-backed, keyed on normalized query fingerprint, 24h TTL.
Wired into `web_search_raw()` as transparent cache; separate `get_research`/`put_research`
for full research-context cache (opt-in via `RESEARCH_CACHE=1`). Eliminates DDGS
rate-limit risk; removes ~30s latency per autoresearch iteration on repeat eval tasks.

### ✓ Chunked URL retrieval
`chunker.py` — replaces hard-truncation at 8000 chars with 512-token overlapping segments
embedded via `nomic-embed-text`; retrieves top-K chunks most similar to the task string.
Provenance metadata attached per chunk. Falls back to head-truncation if embed model unavailable.

### Nanda annotator integration
After fine-tune v2 completes:
1. Convert to GGUF: `convert_hf_to_gguf.py finetune_output/merged`
2. Register: `ollama create nanda-annotator -f Modelfile`
3. Benchmark: `/annotate /wiggum --producer nanda-annotator` on held-out papers vs base

### DPO training loop closure
`build_dpo_dataset.py` exports cross-run preference pairs. When N ≥ 50 pairs:
`trl dpo --model <sft-checkpoint> --dataset hf_datasets/dpo.jsonl`
Re-import via Ollama Modelfile and benchmark against base producer.

### ✓ Submit: live output streaming
`POST /api/tasks` returns an `item_id`. The Submit view opens an SSE connection to
`/api/tasks/{item_id}/stream` and renders structured `[EVENT]` lines as typed cards
(plan, search, synth, wiggum) with a raw log `<pre>` for unstructured output. Plan
approval gate (`use_plan=true`) blocks execution until the user edits and approves
queries via `ApprovePlanCard`.

---

## 0.3.5 — Multi-agent patterns

Four patterns ordered by orchestration complexity. Start with Pattern 1 (already in place);
each step up requires a more capable orchestrating model.

### ✓ Pattern 2 — Fan-out web search
`gather_research()` pre-fetches planned queries in parallel. Implemented in 0.3.0.

### ✓ Pattern 2 — Fan-out annotation loop
`step_annotate` uses `ThreadPoolExecutor(max_workers=parallel)` (default `parallel=2`).
Threading lock guards `RunTrace` token rollup; paper order preserved via indexed futures.
`DEFAULT_ANNOTATE_PARALLEL = 2` — raise to match `llama-server --parallel N`.

### `/grill-me` — Saturation-driven user interview

Mirrors `gather_research()` exactly — same loop shape, same novelty gate, same oversearch
analog — but the information source is the user instead of the web. Each round the agent
generates one targeted question, reads the user's answer as its "search result", compresses
it into `knowledge_state`, and evaluates novelty. When answers stop adding new information,
the loop terminates and the knowledge state is synthesized into a structured brief.

**Core loop:**
```
for round_num in range(1, MAX_INTERVIEW_ROUNDS + 1):
    question = plan_question(goal, knowledge_state, round_num)
    answer   = ask_user(question)           # input() in terminal; SSE card in dashboard
    novelty  = assess_novelty([answer], knowledge_state)
    if round_num > MIN_INTERVIEW_ROUNDS and novelty < NOVELTY_THRESHOLD:
        break
    knowledge_state = compress_knowledge(knowledge_state, [answer])
```

**New helper — `plan_question(goal, knowledge_state, round_num)`:**
Analogous to `plan_query()`. Generates one targeted follow-up question based on what
the agent already knows and what gaps remain. Prompt instructs the model to cover
`who / what / why / constraints / success criteria` in the early rounds, then
drill into specifics once context is established.

**User-fatigue detector (oversearch analog):**
If 2+ consecutive rounds produce answers below a word-count floor (e.g., < 15 words)
the agent infers the user has nothing more to add and terminates early — identical logic
to the domain-diversity termination in `gather_research()`.

**Parameters:**
| | |
|---|---|
| `MIN_INTERVIEW_ROUNDS` | 3 — covers who/what/why before novelty gating activates |
| `MAX_INTERVIEW_ROUNDS` | 8 — hard cap; respects user time |
| `--thorough` | disables novelty gate, runs all rounds (analogous to `force_deep`) |
| `--for <skill>` | tailors question framing to target output: `deck`, `research`, `email` |

**Output:** structured knowledge brief (markdown):
```
## Context
## Goals
## Constraints & non-goals
## Open questions (unresolved after interview)
## Suggested next steps
```

The brief is written to `data/briefs/<slug>.md` and printed to stdout. Can pipe directly:
`/grill-me --for deck` → brief → `/deck --content brief.md`.

**Dashboard path:**
Each question is pushed as an SSE event (`type: "grill_question"`). The Submit view renders
a question card with a text input; submitting fires `POST /api/runs/{run_id}/grill-answer`
which unblocks the agent loop for the next round. Progress bar shows round N of MAX.

**Integration:**
Any skill can call `grill_me_preflight(task, trace)` to run a short interview before
executing — e.g., `/deck` runs a 3-round preflight when the task string is short/ambiguous,
ensuring the slide structure reflects actual intent rather than the agent's best guess.

### `/onboarding` — First-run personalization

`/grill-me` applied to a specific goal: learning who the user is before they've run a
single task. Called automatically on the first invocation of `oh` when no user profile
exists, or explicitly any time to refresh configuration.

**What makes it distinct from a bare `/grill-me` run:**

1. **Fixed question scaffold** — the first 3 rounds always cover the same ground regardless
   of novelty: role and domain, primary use cases, output format preferences. This ensures a
   minimum viable profile even if answers are terse. Free-form novelty-gated rounds follow.

2. **Writes persistent config, not just a brief** — after the interview, synthesizes answers
   into two artifacts:
   - `data/user_profile.md` — human-readable, version-controlled, editable
   - `.harness-user.toml` — machine-readable config consumed by the harness at startup:
     ```toml
     [user]
     role          = "ML researcher"
     domain        = "LLM fine-tuning, RLHF, local inference"
     preferred_model  = "pi-qwen-32b"
     preferred_format = "markdown with H2 sections"
     verbosity     = "concise"

     [routing]
     research_tasks = "pi-qwen-32b"
     coding_tasks   = "qwen2.5-coder-14b"
     ```

3. **Seeds semantic memory** — user-provided domain terms, prior project names, preferred
   vocabulary, and stated expertise are embedded via `nomic-embed-text` and written to
   ChromaDB's `user_context` collection. Subsequent `/recall` and synthesis prompts
   include top-K user-context chunks alongside task-specific memory — so the model
   already "knows" the user's stack, terminology, and constraints before the first task runs.

4. **Auto-triggers on first use** — detected by absence of `.harness-user.toml`. The
   terminal prints a one-line prompt before launching the interview:
   ```
   oh > No user profile found. Running /onboarding (takes ~2 min). Skip with --no-onboard.
   ```

5. **Re-run is additive, not destructive** — subsequent `/onboarding` runs diff the new
   answers against the existing profile and merge changes rather than overwriting, preserving
   manual edits to `.harness-user.toml`.

**Tactful by design:** question count is capped at 6 regardless of `MAX_INTERVIEW_ROUNDS`.
The user is new to the system — the goal is a warm start, not a thorough audit. Depth comes
later from accumulated run telemetry.

**After onboarding completes**, runs `/orientation` to show the user what was configured and
suggest a first task based on their stated use case. Closes the loop: the harness knows who
it's talking to before the first real `oh <task>` is ever typed.

### Pattern 3 — Agent pool for orchestrator subtasks
`orchestrator.py` spawns subtasks via `ThreadPoolExecutor` already, but subtasks are
fire-and-forget with no inter-agent messaging. Upgrade to Pattern 3: give each subtask
agent a `send_message(to="parent")` tool so it can report intermediate results, request
clarification, or surface blockers before finishing.

### ✓ Git as state layer
Auto-commit after each PASS run so `runs.jsonl` and output files become a replayable,
diffable experiment history — not just an append-only log. Opt-in via `GIT_STATE=1`.

Concretely: in `RunTrace.finish("PASS")`, after writing to `runs.jsonl`, stage and commit:
```python
subprocess.run(["git", "add", str(RUNS_FILE), str(output_path)])
subprocess.run(["git", "commit", "-m", f"run: {run_id} {task[:60]}"])
```
This unlocks:
- `git diff <run_a> <run_b>` to compare two lit-review outputs or synthesis passes
- `git bisect` to locate when a quality regression was introduced
- `git log --oneline data/lit_reviews/` as a structured experiment ledger

Deliberately scoped to data files only (`data/`, output `.md`s). Harness source stays
on its own commit cadence — the two histories don't mix.

### Pattern 4 — Teams (Stage 4 prerequisite)
Full peer-to-peer agent messaging. Prerequisite for the autonomous swarm — the
Proposer/Executor/Critic loop requires agents to coordinate directly without a central
bottleneck. Blocked on: cycle detection, shared file conflict resolution, distributed
trace reconstruction across agent conversation histories.

### ✓ PlannedSubtask typed objects (DAG prerequisite)
`plan.subtasks` is currently `list[str]`. Convert to a structured dataclass before
implementing DAG execution — strings can't encode dependency order or execution mode:

```python
@dataclass
class PlannedSubtask:
    desc: str
    depends_on: list[int] = field(default_factory=list)  # indices into subtasks list
    mode: str = "research"                                 # "research" | "code" | "critique"
    priority: int = 0
```

Call sites: `planner._parse_plan()`, `orchestrator._assign_paths()`,
`orchestrator._run_subtasks_parallel()`, `logger.log_plan_record()`. Downstream code
that iterates `plan.subtasks` treating each as a string needs a one-line update
(`sub.desc` instead of `sub`). Parse `depends_on` from the planner JSON output so the
model can declare ordering constraints; orchestrator respects them when scheduling.
Without this, DAG execution in 0.4.x is building on strings.

### ✓ Policy-driven orchestration (replace always-parallel fan-out)
`orchestrator.py` currently runs `_run_subtasks_parallel()` whenever `plan.subtasks`
is non-empty, regardless of whether subtasks are independent. Add `orchestration_style`
and `allow_parallelism` to `Plan` so the planner makes the call:

```python
# Plan dataclass additions
orchestration_style: str = "single_agent"   # "single_agent" | "sequential" | "parallel" | "dag"
allow_parallelism: bool = False
```

Planner prompt gains two new output fields:
```json
{"orchestration_style": "parallel", "allow_parallelism": true}
```

Orchestrator reads `plan.orchestration_style` and branches:
- `single_agent` → delegate to `agent.run()` (existing path)
- `sequential` → `_run_subtasks_sequential()` (new, preserves order, blocks on each)
- `parallel` → `_run_subtasks_parallel()` (existing, gated on `allow_parallelism`)
- `dag` → deferred to 0.4.x after `PlannedSubtask.depends_on` is wired

This also removes the need for a standalone `PolicySelector` module: policy lives
in the Plan, produced by the same LLM call that already has task + memory context.
A rule-based scoring layer on arbitrary weights adds no value until calibrated from
telemetry; use the planner's contextual judgment instead.

---

## 0.3.6 — Observability, tooling, and critic infrastructure

Items recovered from pre-refactor roadmap that are open and not yet ported.

### ✓ Logger policy fields (telemetry → policy feedback loop)
`RunTrace.data` currently records what happened (tokens, scores, output size) but not
which orchestration policy was chosen. Add these fields so run outcomes can be correlated
with the decisions that produced them:

```python
# RunTrace.__init__ additions
"orchestration_style": None,    # from Plan.orchestration_style
"allow_parallelism": None,      # from Plan.allow_parallelism
"subtask_results": [],          # [{"desc", "ok", "attempts", "elapsed_s"}] per subtask
"tool_failures": [],            # [{"tool", "query", "error"}]
"validation_passed": None,      # True/False after wiggum
"policy_confidence": None,      # planner-reported confidence when added
```

`orchestrator.py` populates these before calling `trace.finish()`. Without this,
`runs.jsonl` can't answer "did parallel execution outperform sequential on high-complexity
tasks?" — the signal needed for a self-calibrating policy selector in Stage 4.

### ✓ Embed routing fix
`_embed_vllm()` currently picks `next(iter(_MODEL_MAP.values()))` as the embedding model,
which resolves to whatever chat model is first in the map (`pi-qwen3.6`). Chat models
reject embedding requests. Fix: add a dedicated env var:

```bash
HARNESS_EMBED_MODEL=nomic-ai/nomic-embed-text-v1.5  # vLLM-served embed model
```

`_embed_vllm()` reads `os.environ.get("HARNESS_EMBED_MODEL")` and falls back to
`_embed_local()` if unset, rather than guessing from the chat model map. The local
`sentence-transformers` path already works correctly and is the right default.

### Unified structured event protocol (`[EVENT]` format)
All pipeline stages print `[EVENT]<json>` to stdout. The SSE stream already delivers
these to the dashboard. Currently the dashboard renders raw stdout; structured events
enable per-stage progress cards, live plan display, and training metrics without polling.

Event taxonomy:
```json
{"type": "plan",   "data": {"queries": [...], "gaps": [...], "complexity": "high"}}
{"type": "memory", "data": {"hits": 3, "titles": ["prior run title", ...]}}
{"type": "search", "data": {"query": "...", "round": 1, "hits": 3}}
{"type": "synth",  "data": {"stage": "start", "tokens_in": 4200}}
{"type": "wiggum", "data": {"round": 1, "score": 7.4, "dims": {...}}}
{"type": "metric", "data": {"step": 14, "loss": 1.35, "epoch": 0.13}}
{"type": "span",   "data": {"name": "forward_pass", "duration_ms": 1240}}
{"type": "log",    "data": {"text": "raw stdout line"}}
```

Non-`[EVENT]` lines fall through as `log` — backward compatible. Build order:
1. ✓ `memory` event emitted from `agent.py` after ChromaDB retrieval (hits + titles)
2. ✓ `plan` + `search` + `synth` + `wiggum` events live; rendered as typed cards in Submit view
3. Emit `plan` + `search` + `wiggum` events from `agent.py` and `wiggum.py` — small, immediate
2. Add `DashboardCallback` (`trl.TrainerCallback`) to `finetune_annotate.py` — emits `metric`
   events per step + appends to `finetune_metrics.jsonl`; `GET /api/finetune/metrics` serves it
3. Dashboard: parse `[EVENT]` prefix → plan card above log stream; Training tab with live loss
4. `FinetuneTracer` — `torch.cuda.Event` GPU-accurate spans; writes `traces/finetune_<ts>.json`

Ties Submit streaming, `/plan` card, and live training metrics into one coherent protocol.

### Agentic cost estimator (COCOMO II analog)
Pre-task estimate of LLM calls, tokens, wall time, and wiggum rounds — calibrated from
`runs.jsonl` actuals. Emits alongside the `plan` event so the user knows before committing
whether a task is a 2-minute or 45-minute run.

```python
CostEstimate(
    estimated_llm_calls      = N,
    estimated_tokens         = K,
    estimated_wiggum_rounds  = 1-3,
    estimated_wall_time_s    = T,
    complexity               = "low" | "medium" | "high",
    risk_flags               = ["count_constraint", "novel_task_type", ...],
    confidence               = 0.0-1.0,
)
```

COCOMO II → harness unit mapping: SLOC → task complexity + expected output size;
Precedentedness → memory hit rate; Architecture/Risk → plan complexity + subtask count;
Team cohesion → evaluator/producer score variance; Process maturity → wiggum round
distribution. Trains on `runs.jsonl` after 50+ runs; self-calibrating. Variance between
estimated and actual logged per run for retrospective drift analysis.

Plugs into: `/plan` card (show before any search runs); swarm scheduler (allocate model
tier by estimated cost); roadmap prioritization (rank open items by effort/value ratio).

### Harness ontology layer (`code-review-graph`)
Tree-sitter AST parsing → function call graph → community detection → SQLite graph.
Incremental updates in <2s per save. Enables:
- **Blast-radius context for Proposer/Critic** — "changing `synthesize()` touches 6 downstream callers" — 8× fewer tokens than full-file reads per published benchmarks
- **`/plan` blast-radius preview** — before executing a plan step, query which harness functions are affected
- **Dead code detection** — orphaned skills, stale stage hooks, unused utilities
- **Wiki auto-generation** — `code-review-graph wiki` produces markdown from code communities via Ollama → feeds harness memory
- **Structural graph diffs across worktrees** — each Proposer worktree builds its own graph; Critic compares edge sets

```bash
pip install "code-review-graph[communities,wiki]"
code-review-graph build    # initial parse
code-review-graph watch    # incremental on save/commit
```

Build after Stage 4 Proposer prototype exists — most valuable once agents need structured
context about what they can mutate and what the downstream impact is.

### ✓ Evaluator rotation
`HARNESS_EVALUATOR_POOL` (comma-separated list) + `select_evaluator(seed)` in `wiggum.py`.
Hash-based deterministic selection per run; falls back to `EVALUATOR_MODEL` when pool is
empty. Guards against producer == evaluator collision. Enabled via:
```bash
HARNESS_EVALUATOR_POOL=qwen3-14b,gemma4-27b
```
Gemma 4 26B (MoE, 3.8B active params) is the recommended second evaluator: different
architecture family (Google vs Alibaba), 256K context, configurable thinking mode.
Test: set pool to both models and confirm divergent wiggum scores → add as 4th panel persona.

### Plan approval — surface extensions
**✓ Global gate banner** — `GET /api/tasks/gates` returns all pending gates (`_plan_pending`
dict in `tasks.py`). `useGates()` polls every 2s. `GateBanner` in `App.tsx` renders a
fixed overlay (top-right, z=200) with one `ApprovePlanCard` per pending gate — visible
from any dashboard view regardless of which tab is active.

**Remaining (deferred):**

*Active-run card in Runs view* — when a run has a pending gate, the Runs view could
render an inline `ApprovePlanCard` without needing a full EventSource subscription.

*Floating terminal* — the `oh >` REPL could open the EventSource stream, watch for
`plan_gate` events, and render a blocking `input()` prompt — mirroring the terminal path.

Both are purely additive UI. Implement whichever gets asked for first.

---

## 0.3.7 — Memory observability, RLHF pruning, and ontology ✓ COMPLETE

The semantic memory system (`observations` table + ChromaDB collection) currently has
no user-facing window and no quality signal. Memories accumulate indefinitely; bad ones
lower retrieval quality without any mechanism for correction. This milestone adds:
a provenance layer so every memory can be traced to the run that produced it; an RLHF
signal (thumbs up/down) that soft-weights retrieval without deletion; a full Memory
panel in the dashboard; and a nascent ontology visualization using the embeddings already
in ChromaDB.

### Layer 0 — Schema migration

The `observations` SQLite table gains three new columns:

```sql
ALTER TABLE observations ADD COLUMN run_id     TEXT;    -- FK → runs.jsonl run_id
ALTER TABLE observations ADD COLUMN quality    INTEGER DEFAULT 0;  -- -1 / 0 / +1
ALTER TABLE observations ADD COLUMN tags       TEXT;    -- JSON array of strings
```

`run_id` closes the provenance gap: every memory created from a run can be traced back
to the originating `run_id` and from there to the full run trace, output artifact, and
wiggum eval. `quality` stores the cumulative RLHF signal from user thumbs votes.
`tags` seeds the ontology layer (user-editable, agent-suggested via embedding clusters).

**Write path:** `memory.py`'s `store_observation()` accepts an optional `run_id` kwarg;
`agent.py` passes `trace.run_id` at the call site. Migration is additive — existing
rows default to `run_id=NULL, quality=0, tags='[]'`.

**Read path:** `retrieve_observations()` receives an additional `quality_floor` param
(default `−1` — include all); retrieval SQL adds `AND quality >= quality_floor` so
consistently downvoted memories can be suppressed without deletion by raising the floor.
ChromaDB `where` filter mirrors this: `{"$and": [{"quality": {"$gte": quality_floor}}]}`.

### Layer 1 — Backend API (5 endpoints)

```
GET    /api/memories                 list, filter by task_type / tags / quality / search
GET    /api/memories/{id}            full detail: title, narrative, facts, tags, provenance
PATCH  /api/memories/{id}            update title, tags, quality; supports partial updates
DELETE /api/memories/{id}            hard delete after confirm dialog (soft-delete preferred)
POST   /api/memories/{id}/feedback   body: {"rating": 1|-1, "comment": "..."}
                                     → adjusts quality column ± 1, clamps to [-3, 3]
```

`GET /api/memories` response shape:
```json
{
  "memories": [
    {
      "id": 42,
      "run_id": "abc123",
      "timestamp": "2026-05-14T03:21:00Z",
      "task": "survey RLHF papers",
      "task_type": "research",
      "title": "PPO vs DPO tradeoffs",
      "quality": 1,
      "tags": ["rlhf", "alignment"],
      "facts_count": 4,
      "final_score": 8.2
    }
  ],
  "total": 147,
  "page": 1
}
```

`GET /api/memories/{id}` includes `provenance`:
```json
{
  "provenance": {
    "run_id": "abc123",
    "task": "survey RLHF papers",
    "final": "PASS",
    "wiggum_scores": [6.1, 7.8, 8.2],
    "timestamp": "2026-05-14T03:21:00Z",
    "output_path": "data/lit_reviews/rlhf_survey.md"
  }
}
```

The `feedback` endpoint does not delete. Deletion is a separate explicit user action
with a confirm dialog. This preserves the audit trail even for bad memories — the
quality score is the soft signal; hard delete is the user's last resort.

### Layer 2 — Memory panel (dashboard)

**Entry point:** brain SVG icon in the sidebar nav (between GitHub and MCP). Routes
to `/memories`.

**List view (left pane):**
- Paginated list of memories (25/page), sorted by recency by default
- Search bar — free-text search against title + narrative (hits ChromaDB's `query_texts`)
- Filter chips: `task_type`, `tags`, `quality` (⊕ = 1, ○ = 0, ⊖ = −1), `final` (PASS/FAIL)
- Each row: title, task_type badge, quality icon (thumb up/down/neutral), date, score chip
- Clicking a row opens the detail panel (right pane)

**Detail panel (right pane):**
- Header: title (editable inline), quality bar (−3 to +3 thermometer)
- RLHF controls: 👍 / 👎 buttons → `POST /api/memories/{id}/feedback`; shows current
  quality score and vote count
- Narrative block (markdown-rendered)
- Facts list (bulleted, from JSON array)
- Tags: editable chip list; typing in the box adds a tag; `PATCH /api/memories/{id}`
- **Provenance trace:** collapsible section showing:
  - `run_id` linked to the Runs view (filters to that run)
  - task string, timestamp, final verdict
  - wiggum score sparkline
  - link to output artifact if `output_path` is set
- **Changelog:** list of quality adjustments with timestamp and direction (auto-appended
  on every feedback POST; stored in a `memory_feedback_log` table — `memory_id, rating,
  comment, created_at`)
- Delete button → confirm dialog: "This will permanently remove this memory from
  retrieval. Consider lowering quality instead. Delete permanently?" → `DELETE /api/memories/{id}`

**Empty state:** no memories matching filters → "No memories yet. Memories are created
automatically after PASS runs." with a link to Submit.

### Layer 3 — Ontology visualization

Builds on the ChromaDB embeddings already computed for retrieval. No new embedding
pipeline needed.

**Algorithm:**
1. `GET /api/memories/graph` — Python side fetches all memory embeddings from ChromaDB,
   runs UMAP (2D, `n_neighbors=15, min_dist=0.1`), then lightweight community detection
   (HDBSCAN or k-means k=8) to assign cluster labels
2. Response: `{nodes: [{id, title, x, y, cluster, quality}], edges: [{source, target, weight}]}`
   Edges computed by cosine similarity > 0.75 threshold
3. Dashboard: D3 force-directed graph with cluster color coding; nodes sized by quality
   (higher quality = larger); hover shows title; click opens detail panel
4. Cluster labels: auto-generated by asking the producer model "given these memory titles:
   [...], name this cluster in 2-3 words" — cached in `memory_clusters` table

**Scope note:** This is a visualization layer on top of existing embeddings. No new
model training, no knowledge graph database. The ChromaDB collection already has the
vectors — UMAP + D3 is the only new code. Build UMAP as a lazy endpoint: computed
on first request, cached for 1h (`memory_graph_cache.json`), invalidated on any
`store_observation()` or `feedback` write.

### RLHF-based soft pruning

Retrieval quality degrades when low-quality memories compete with high-quality ones
at equal weight. Two mechanisms close this:

**1. Quality-weighted retrieval score:**
After ChromaDB returns the top-K candidates by cosine similarity, rerank by:
```python
adjusted_score = cosine_similarity * max(0.2, 1 + (quality * 0.15))
```
`quality=+3` → 1.45× boost; `quality=-3` → 0.2× floor (not zero — still visible to the
quality inspector in the panel). The floor prevents good memories from being permanently
buried by a bad vote cluster. Reranked top-K is what the agent actually sees.

**2. Auto-suggest prune candidates:**
`GET /api/memories/prune-candidates` — returns memories with `quality ≤ -2` and
`final_score < 6` on the originating run. Memory panel renders these in a separate
"Review needed" tab with batch thumbs-down confirmation. This is the human-in-the-loop
step before any bulk delete; the agent never auto-deletes.

### Sequencing

1. **Schema migration** ✓ — idempotent `ALTER TABLE` in `_init_db()`; safe on existing installs (1960 rows migrated). `run_id` threaded through `compress_and_store()` from `trace.data`.
2. **Backend API** ✓ — 7 endpoints (list, detail, update, delete, feedback, prune-candidates, graph) + `memory_feedback_log` table. Quality adjustment clamps to `[-3, 3]`. Quality-weighted reranking: `adjusted = blend * max(0.2, 1 + quality * 0.15)`.
3. **Memory panel list + detail** ✓ — brain icon in sidebar; list with search (FTS5 → LIKE fallback), quality filter chips, pagination; detail with inline title edit, 👍/👎 RLHF, tag editor, provenance block, confirm-delete.
4. **Ontology graph** ✓ — `GET /api/memories/graph` runs UMAP 2D + k-means clustering on ChromaDB embeddings; SVG renderer with scroll-to-zoom, drag-to-pan, hover preview, click-to-open detail. Gracefully degrades when `umap-learn` is missing or fewer than 5 memories exist.

**Also shipped in this milestone:**
- **Security panel** (lock icon) — `GET /api/security/events` + `/summary`; search/filter/severity chips; sticky detail pane; `_log_event()` wired into all 5 security layers with diagnostic print on success and failure.
- **System panel** (gear icon) — governance file viewer/editor (AGENTS.md, ROADMAP.md, wiki files, user profile, `.harness-user.toml`); live config inspector (safe env vars, runtime settings, synth instructions); skills registry table with hook filter chips.
- **Test suite expansion** — `test_wiggum.py` (45 tests: dim weights, composite formula, stub detector, prose parser, task type, evaluator rotation) and `test_memory.py` (56 tests: schema migration, CRUD, quality clamping, feedback log, list filtering/pagination, prune candidates). Total: 419 tests.
- **CI hardening** — dashboard `tsc + vite build` job; `pip-audit` dependency CVE scan; `--cov-fail-under=20` coverage floor; publish-from-main guard via `git merge-base`; tests run before PyPI publish.

---

## 0.4.0 — Personal TTS model

Fine-tune `microsoft/speecht5_tts` on local voice recordings to produce a personalized
speech model that feeds back into the harness voice interface.

### Data pipeline ✓
Timestamped transcripts (`data/transcripts/*-transcript.md`) are paired with matching WAVs
(`notes/*.wav`). `my_utils.py` parses each transcript line into a manifest row with
`audio_filepath`, `start`, `end`, `duration`, and `text`. Segments are filtered by duration
(1.5–10s) and word count (≥4 words), and short-circuit endings (`"...and"`, `"...of"`, etc.)
are dropped. `reading_scripts.md` contains prepared passages to record as additional op-notes.
Current dataset: ~20 clean utterances. Target before next training pass: 200+.

### Speaker embeddings ✓
512-dim x-vector embeddings via `speechbrain==0.5.15` + `spkrec-xvect-voxceleb`. Each
segment is sliced to its exact timestamp window and resampled to 16kHz before embedding.
Inference averages embeddings across all training clips for a stable identity vector.
Note: `speechbrain>=1.0` has a broken lazy-importer that cascades on missing optional deps
(`k2`, `flair`) — pin to `0.5.15`.

### Training ✓
`Seq2SeqTrainer` on `SpeechT5ForTextToSpeech`, 500 steps, batch 2 + gradient accumulation 4,
`lr=1e-5`, fp16. Final checkpoint at `speecht5_nicho/checkpoint-500/`, training loss 0.467.
Notebooks: `notebooks/tts_training.ipynb`, `notebooks/tts_inference.ipynb`.

### Integration target
Swap the voice FAB's synthesis backend from an external API to the local fine-tuned checkpoint.
The `/transcribe` skill already handles audio input; TTS closes the other direction.

### Iterative improvement
Record the passages in `reading_scripts.md`, rebuild the manifest, and run a continued
training pass on top of `checkpoint-500` (not from base). Target: 200+ utterances before
the second pass, 500+ before evaluating voice character transfer. Wiggum-style eval for
voice: MOS proxy via preference comparison against the base SpeechT5 output.

---

## Stage 4 — Autonomous swarm

### Harness governance layer (constitution / ethos / cadence)
As the swarm gains multiple autonomous agents, behavioral constraints need to live in
shared documents rather than per-agent system prompts. Three non-anthropomorphic files,
injected into every agent's bootstrap context:

| File | Purpose |
|------|---------|
| `constitution.md` | Hard constraints all agents must respect: what they can't do, what requires human checkpoint, output format minimums, security rules |
| `ethos.md` | Evaluation standards and decision norms: quality floors, search discipline, when to stop and escalate, how to handle conflicting sources |
| `cadence.md` | The operational loop: gather → annotate → synthesize → eval → checkpoint. Each agent's recurring cycle, what state must be checkpointed, what triggers the next phase |

Mirrors OpenClaw's bootstrap injection pattern: stable content (constitution, ethos)
sits above the prompt cache boundary so vLLM prefix caching can reuse it across turns.
`cadence.md` is the technical analogue of `heartbeat.md` — cycle rhythm without
organism metaphor.

**Iterative improvement path:** after each autoresearch session, Wiggum's failure
patterns (e.g. "specificity_score < 6 in 40% of runs") can be distilled into a
proposed `constitution.md` diff by a meta-agent. Human approves or rejects the diff
before it merges. This is the "democratic constitution" pattern — grounded in eval
signal rather than agent opinion.

### Prompt cache boundary design
Before the vLLM move, design the system prompt so stable content sits above the cache
cut and volatile content below it. Concretely:

- **Above the boundary (stable):** `constitution.md`, `ethos.md`, `cadence.md`,
  skill list, tool descriptions, workspace path
- **Below the boundary (volatile):** current task, memory hits, session state,
  live tool results, plan events

With Qwen3.6-35B's SWA this is irrelevant — it re-processes the full prompt per
request regardless. But designing for the boundary now means the vLLM migration
is a configuration change, not a prompt rewrite. Target: stable prefix ≥ 80% of
total prompt tokens on repeat task types.

### Sub-agent minimal context mode
Worker agents (orchestrator subtasks, Executor instances) don't need the full
coordinator context: no memory recall, no self-update guidance, no evaluation
rubric, no session history. Add a `--minimal-context` flag to `harness.agent` that
strips the system prompt to task + tools + `constitution.md` only. Reduces per-subtask
token cost proportionally to how much coordinator context the worker would otherwise
receive — typically 30–50% of the full prompt on research tasks.

Mirrors OpenClaw's `promptMode=minimal`: sub-agents get `AGENTS.md` + `TOOLS.md`
equivalents only. Apply in `orchestrator._run_one_subtask()` by passing
`--minimal-context` in the subprocess command.

### Policy selector with telemetry calibration
A rule-based `PolicySelector` with fixed weights is editorial guesswork until
calibrated from data. After Stage 4 Proposer/Executor/Critic is running and
`runs.jsonl` has 50+ orchestrated runs with policy fields logged (see 0.3.6):

1. Extract `(orchestration_style, allow_parallelism, complexity, task_type) →
   (final, wiggum_scores[-1], leverage, wall_time_s)` from `runs.jsonl`
2. Fit a lightweight model (logistic regression or gradient-boosted tree) on the
   extracted features — no LLM needed, just tabular prediction
3. Replace planner's flat JSON orchestration fields with a call to the fitted
   selector at planning time
4. Re-fit after each N=25 new orchestrated runs; version the weights in git so
   regressions are diffable

This is how policy selection becomes genuinely adaptive rather than opinion-driven.
The telemetry loop closed in 0.3.6 is the prerequisite.

### Proposer → Executor → Critic loop
Close the manual hand-offs in the autoresearch loop:
- **Proposer** generates harness mutations (synthesis instruction, rubric params, search config, model routing)
- **Executor** runs eval tasks in parallel via `ThreadPoolExecutor` + subprocess isolation (already in place)
- **Critic** scores via typed event telemetry from `runs.jsonl` — not just a scalar, but reasoning about *why* a mutation worked using plan events, search rounds, and dim-level wiggum scores

Human checkpoint: goal-setting and checkpoint promotion only.

### Git worktrees as Proposer isolation substrate
Each Proposer mutation runs in its own `git worktree` — isolated filesystem, own branch,
no interference with live harness runs on `main`. Promoter merges with `--ff-only`;
reverts are `git worktree remove --force`. Zero new infrastructure — just `git worktree add`.

Coordination objects live inside each worktree as a directory convention — no VFS
infrastructure needed on a single machine:

```
worktrees/<branch>/
  tasks/      ← agent claims work by writing a file here (task_id.json)
  leases/     ← task_id.lock with {agent_id, claimed_at} — coordinator expires stale locks
  artifacts/  ← outputs staged here; never written directly to shared data/
  events/     ← append-only per-run event log for this agent
```

Workers only write inside their branch tree. Coordinator reads `leases/` to detect
abandonment and re-queue. Promotion is `git merge --ff-only`; cleanup is
`git worktree remove --force`. This gives VFS-style coordination semantics (isolated
write namespace, shared read, staged commits) without FUSE, Lustre, or any kernel driver.

**Multi-machine scaling note:** when the swarm grows beyond a single GPU host, this
convention needs a shared namespace across nodes. Ordered preference by complexity:
1. NFS mount of `data/` — simplest, sufficient for 2–4 machines
2. FUSE-based coordinator-mediated writes (WinFsp/Dokany on Windows) — adds policy
3. Distributed filesystem — only if running dozens of nodes

Don't pull in distributed filesystem infrastructure for single-machine operation;
the directory convention above is the right implementation at current scale.

### vLLM hot-swap for promoted checkpoints
When a fine-tuned checkpoint is promoted:
- `POST /v1/load_lora_adapter` via vLLM's LoRA serving API
- No server restart, no Ollama pull
- Enables A/B serving: base + adapter simultaneously for the Critic to compare

### A2A protocol foundation

The harness's producer→evaluator→wiggum loop is already an A2A pattern — agents
negotiating over shared task state across multiple turns. The gap is that it's
in-process rather than networked.

#### Multi-agent file architecture

Each specialized agent lives in its own file (`researcher_agent.py`, `coder_agent.py`,
`critic_agent.py`, …) with distinct system instructions, skill registries, and model
routing. This is a natural extension of the existing `agent.py` structure — no new
abstractions needed, just multiple instances of the same scaffold configured differently.

The key design constraint: **agents must not import from each other**. All coordination
happens over the wire. A `researcher_agent.py` that deep-imports from `coder_agent.py`
defeats isolation and reintroduces the in-process coupling A2A is meant to eliminate.

#### Wire protocol

Each agent exposes two A2A-standard HTTP endpoints:

```
GET  /.well-known/agent.json   → Agent Card (capabilities, skills, model, version)
POST /                         → Task endpoint (receives A2A Task object, returns result)
```

The Agent Card is a JSON document declaring what the agent can do:
```json
{
  "name":        "researcher",
  "description": "Multi-round web research, lit-review, and synthesis",
  "skills":      ["research", "lit-review", "annotate", "recall"],
  "model":       "pi-qwen-32b",
  "endpoint":    "http://localhost:7861"
}
```

The orchestrating `agent.py` (or a dedicated coordinator) discovers peers at startup by
reading a `agents.toml` registry, fetches their cards, and routes subtasks to them via
standard A2A `Task` objects over `httpx`.

#### Routing in the planner

The planner's `make_plan()` step gains a `delegate_to` field per query:
```python
# planner output (extended)
{"query": "survey RLHF papers", "delegate_to": "researcher"}
{"query": "write tokenizer utility", "delegate_to": "coder"}
```

`gather_research()` checks `delegate_to`: local skill → existing path; named agent →
`httpx.post(peer_url, json=a2a_task)`. The rest of the pipeline (compression, wiggum,
leverage) is unchanged — the delegated result arrives as a normal search result.

#### Tradeoffs vs. current in-process model

| | In-process (current) | A2A (networked) |
|---|---|---|
| Latency | ~0ms | HTTP round-trip per delegation |
| Isolation | None — shared `_queue`, `_TaskTee`, `_plan_gates` | Full process isolation |
| Model per agent | Shared backend | Each agent can run a different model |
| Distributed | Single machine | Multi-machine / multi-GPU |
| Third-party agents | No | Any A2A-compliant agent can plug in |
| State sharing | Direct memory | Must pass context explicitly in task payload |

The in-process shared state that gets severed: `_TaskTee` log tee, `_queue` list,
`_plan_gates` threading events. Each agent's task log becomes its own SSE stream;
the orchestrator correlates them by `run_id` in `runs.jsonl`.

#### Implementation path

1. **`a2a_server.py`** — thin wrapper that mounts the existing FastAPI `router` plus a
   `/agent.json` card endpoint. Any `*_agent.py` imports it to become an A2A peer:
   ```python
   from harness.a2a_server import serve
   serve(agent_card=MY_CARD, port=7861)
   ```

2. **`agents.toml`** — registry of known peers:
   ```toml
   [[agents]]
   name     = "researcher"
   endpoint = "http://localhost:7861"

   [[agents]]
   name     = "coder"
   endpoint = "http://localhost:7862"
   ```

3. **Planner routing** — add `delegate_to` to `make_plan()` prompt and parse it in
   `gather_research()`. Two-line change: check `delegate_to`, call `httpx.post` if set.

4. **Log correlation** — orchestrator attaches `parent_run_id` to each delegated task;
   delegated agents include it in their `runs.jsonl` entries. Dashboard groups by
   `parent_run_id` for a unified run tree view.

Existing skill/queue/log machinery is untouched. The near-term goal is exposing the
harness as an A2A peer so external orchestrators can delegate to it; the long-term goal
is the full swarm where every agent is an A2A node.

Each individual skill continues to use MCP for tool calls (web search, browser, file I/O) —
MCP and A2A are complementary layers: MCP for tools, A2A for agent-to-agent delegation.

### Docker sandbox for run_python
When `run_python` scope expands beyond model-generated code to untrusted sources
(web search results, user scripts), replace the AST blocklist with true process
isolation via Docker throwaway containers. Not urgent until productionization.

For subagent sandboxes specifically, the target shape is:
```bash
docker run --rm --gpus all \
  --network harness-net \          # isolated bridge, no host access
  --mount type=bind,src=./worktrees/<branch>,dst=/workspace \
  harness-agent:latest \
  python -m harness.agent --minimal-context "<task>"
```
NVIDIA Container Toolkit (already needed for WSL2/vLLM) handles GPU passthrough;
the worktree mount provides the isolation substrate from 0.3.5.

**OpenShell watch item:** NVIDIA's [OpenShell](https://github.com/NVIDIA/OpenShell) (alpha)
provides declarative YAML egress policy, credential injection, and inference routing for
sandboxed agents. Currently optimized for external coding agents (Claude Code, Codex) rather
than self-hosted harness subprocesses — the inference routing duplicates what `HARNESS_ENDPOINTS`
already does. Revisit if Stage 4 expands to include external coding agents as swarm participants,
at which point credential isolation and per-sandbox egress policy become genuinely valuable.

---

## Guiding principles (inherited and confirmed)

1. **Build for deletion.** Every workaround exists because models can't yet handle it natively. Design so the workaround is trivially removable when the model improves.
2. **Verify externally at every stage boundary.** The model's self-report is not verification.
3. **Add observability before adding features.** Structured traces before new tools. Logging is not optional.
4. **Evaluator and producer must be different models.** Same-model evaluation is circular.
5. **The harness is the product.** The model is a commodity input. Reliability lives in the harness.
6. **Every manual hand-off is a loop that hasn't closed yet.** Each one is a target for automation.
7. **Telemetry is what separates a critic from a scorer.** Typed event traces tell you *why* — the self-improvement loop stalls without this signal.

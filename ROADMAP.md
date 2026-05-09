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

### Dashboard views
- **Home** — KPI cards (total runs, pass rate, avg score, token spend) + activity feed
- **Runs** — merged Runs + Explorer: compact run list + DAG inspector (pipeline graph, per-stage tokens, output preview, Wiggum scores + dim bars, evaluator feedback, RLHF panel, leverage chip)
- **Submit** — fire a task from the browser; live pulse dot while in flight, `ResultCard` on completion ✓
- **Sessions** — grouped by `session_id`, per-session pass rate / wall time / token spend ✓
- **Analytics** — time-series charts: run volume, pass rate by day, score distribution, token trend ✓
- **Artifacts** — browse output files with markdown preview and download ✓
- **Fine-tune** — training metrics charts (loss, accuracy, lr) + RL dataset browser (preference pairs, reward feedback, GRPO rollouts, DPO with evaluator feedback)
- **MCP** — registered tool inspector: tool cards with name, description, required/optional param badges ✓
- **Floating terminal** — `oh >` REPL with input history, live run-status badges
- **Voice FAB** — voice input panel

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
| `/grill-me [domain]` | → 0.3.5 saturation-driven user interview |
| `/onboarding` | → 0.3.5 first-run personalization via /grill-me |

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

Remaining open: **Submit live output streaming** (SSE per-run stdout → structured rendering)
— not yet implemented; deferred to 0.3.0.

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

### `/plan` interactive approval
Show gap analysis and proposed search queries before any search runs. Terminal path:
`input()` prompt with editable query list. Dashboard path: SSE plan event → editable
plan card with Approve button → `POST /api/runs/{run_id}/approve-plan` → agent continues.

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

### Submit: live output streaming
`POST /api/tasks` queues a run and returns a `run_id`. The Submit view should then
open an SSE connection to `/api/runs/{run_id}/stream` and render the agent's stdout
(plan events, search rounds, wiggum scores) in real time — identical to the terminal
but with structured rendering for `[EVENT]` lines.

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

### Git as state layer
Auto-commit after each PASS run so `runs.jsonl` and output files become a replayable,
diffable experiment history — not just an append-only log.

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

---

## 0.3.6 — Observability, tooling, and critic infrastructure

Items recovered from pre-refactor roadmap that are open and not yet ported.

### Unified structured event protocol (`[EVENT]` format)
All pipeline stages print `[EVENT]<json>` to stdout. The SSE stream already delivers
these to the dashboard. Currently the dashboard renders raw stdout; structured events
enable per-stage progress cards, live plan display, and training metrics without polling.

Event taxonomy:
```json
{"type": "plan",   "data": {"queries": [...], "gaps": [...], "complexity": "high"}}
{"type": "search", "data": {"query": "...", "round": 1, "hits": 3}}
{"type": "synth",  "data": {"stage": "start", "tokens_in": 4200}}
{"type": "wiggum", "data": {"round": 1, "score": 7.4, "dims": {...}}}
{"type": "metric", "data": {"step": 14, "loss": 1.35, "epoch": 0.13}}
{"type": "span",   "data": {"name": "forward_pass", "duration_ms": 1240}}
{"type": "log",    "data": {"text": "raw stdout line"}}
```

Non-`[EVENT]` lines fall through as `log` — backward compatible. Build order:
1. Emit `plan` + `search` + `wiggum` events from `agent.py` and `wiggum.py` — small, immediate
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

### Evaluator rotation (Gemma 4 26B)
`Qwen3-Coder:30b` is the sole evaluator across wiggum and panel. Single-evaluator
autoresearch risks optimizing against one model's scoring bias invisibly.

Gemma 4 26B (MoE, 3.8B active params at inference) is the right candidate: different
architecture family (Google vs Alibaba), fits alongside pi-qwen-32b without full VRAM swap,
256K context, native function calling, configurable thinking mode.

Test protocol: `EVALUATOR_MODEL=gemma4:26b python eval_suite.py --tasks T_D,T_E --score`.
If scores diverge significantly → rotate evaluators across autoresearch sessions or add
Gemma 4 as a 4th panel persona. If scores converge → rubric is robust.

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

### vLLM hot-swap for promoted checkpoints
When a fine-tuned checkpoint is promoted:
- `POST /v1/load_lora_adapter` via vLLM's LoRA serving API
- No server restart, no Ollama pull
- Enables A/B serving: base + adapter simultaneously for the Critic to compare

### A2A protocol foundation
The harness's producer→evaluator→wiggum loop is already an A2A pattern — agents
negotiating over shared task state across multiple turns. The gap is that it's
in-process rather than networked.

Near-term: expose the harness as an A2A peer agent via an Agent Card so external
orchestrators can delegate research, lit-review, and evaluation tasks to it.
Each individual skill continues to use MCP for tool calls (web search, browser, file I/O).

### Docker sandbox for run_python
When `run_python` scope expands beyond model-generated code to untrusted sources
(web search results, user scripts), replace the AST blocklist with true process
isolation via Docker throwaway containers. Not urgent until productionization.

---

## Guiding principles (inherited and confirmed)

1. **Build for deletion.** Every workaround exists because models can't yet handle it natively. Design so the workaround is trivially removable when the model improves.
2. **Verify externally at every stage boundary.** The model's self-report is not verification.
3. **Add observability before adding features.** Structured traces before new tools. Logging is not optional.
4. **Evaluator and producer must be different models.** Same-model evaluation is circular.
5. **The harness is the product.** The model is a commodity input. Reliability lives in the harness.
6. **Every manual hand-off is a loop that hasn't closed yet.** Each one is a target for automation.
7. **Telemetry is what separates a critic from a scorer.** Typed event traces tell you *why* — the self-improvement loop stalls without this signal.

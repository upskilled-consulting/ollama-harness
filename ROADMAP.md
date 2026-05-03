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
- PyPI package setup (`pyproject.toml` with metadata, build-system, entry points)
- Ruff + mypy + TypeScript type-checking all clean in CI

### Dashboard views
- **Home** — KPI cards (total runs, pass rate, avg score, token spend) + activity feed
- **Runs** — merged Runs + Explorer: compact run list + DAG inspector (pipeline graph, per-stage tokens, output preview, Wiggum scores + dim bars, evaluator feedback, RLHF panel)
- **Submit** — fire a task from the browser; result appears live in Runs
- **Fine-tune** — training metrics charts (loss, accuracy, lr) + RL dataset browser (preference pairs, reward feedback, GRPO rollouts, DPO with evaluator feedback)
- **MCP** — registered MCP tool server inspector
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

---

## 0.1.0 — PyPI release blockers

These must be resolved before `python -m build && twine upload dist/*`.

### P0: Commit deck skill implementation
`harness/skills/deck/builder.py`, `content.py`, `skill.py`, `theme.py` are untracked.
The `/deck` skill is documented and referenced in `__init__.py` but absent from the package.

### P0: Add package_data for templates and assets
Jinja2 templates (`*.j2`) and `kg_template.html.j2` are not Python files and won't be
included in the wheel without explicit `package_data` in `pyproject.toml`:

```toml
[tool.setuptools.package-data]
"harness.skills" = ["*.j2", "templates/*.j2"]
```

### P0: Document or bundle the dashboard
Users who `pip install ollama-harness` and run `oh` or `python start.py` need either:
- A pre-built `dashboard/dist/` committed to the repo and served by the FastAPI static mount, **or**
- A clear prerequisite note in the README: "Node.js ≥ 18 required; `start.py` builds the dashboard automatically on first run."

`start.py` already calls `npm run build` before launching — document this explicitly.

### P1: Gitignore lit-review cache
`harness/skills/.lit_review_cache/` contains hundreds of per-paper JSON files that
should not be in the repo. Add to `.gitignore`.

### P1: Smoke test the wheel
```bash
python -m build
pip install dist/ollama_harness-0.1.0-py3-none-any.whl --force-reinstall
oh --help
oh /introspect
```
Confirm entry points resolve and Jinja templates load from the installed package path.

---

## 0.2.0 — Dashboard completeness

### Sessions view
Currently a placeholder. Wire to `GET /api/sessions` — group runs by `session_id`,
show per-session stats (total runs, pass rate, wall time, token spend).

### Artifacts view
Currently a placeholder. Wire to `GET /api/artifacts` — browse output files written
by runs, with download and preview (markdown rendered via `MdView`).

### Analytics charts
Currently a placeholder. Time-series charts (run volume, pass rate by day, token spend
trend, score distribution histogram) from `runs.jsonl` aggregated server-side.

### Submit: live output streaming
`POST /api/tasks` queues a run and returns a `run_id`. The Submit view should then
open an SSE connection to `/api/runs/{run_id}/stream` and render the agent's stdout
(plan events, search rounds, wiggum scores) in real time — identical to the terminal
but with structured rendering for `[EVENT]` lines.

### MCP inspector
The MCP view needs real content: list registered servers, show available tools per server,
allow test invocations, display recent MCP call logs from `runs.jsonl` tool_calls.

---

## 0.3.0 — Self-improvement loop

### `/plan` interactive approval
Show gap analysis and proposed search queries before any search runs. Terminal path:
`input()` prompt with editable query list. Dashboard path: SSE plan event → editable
plan card with Approve button → `POST /api/runs/{run_id}/approve-plan` → agent continues.

### Autoresearch stall replan
If 4+ consecutive autoresearch experiments are discarded, inject into `PROPOSE_PROMPT`:
"The last 4 variations were all discarded — propose a fundamentally different framing."
Mirrors MagenticOne's replan trigger. Low effort, high impact on proposer local minima.

### Search result cache
SQLite-backed cache keyed on normalized query fingerprint (24h TTL). Wire into
`web_search_raw()` — transparent to the pipeline. Eliminates DDGS rate-limit risk
and removes ~30s latency per autoresearch iteration on repeat eval tasks.

### Chunked URL retrieval
Replace hard-truncation at `URL_ENRICH_MAX_CHARS = 8000` with semantic chunking:
512-token overlapping segments → embed via `nomic-embed-text` → retrieve top-K
chunks most similar to the task string. Depends on `sqlite-vec` (already in deps).

### Nanda annotator integration
After fine-tune v2 completes:
1. Convert to GGUF: `convert_hf_to_gguf.py finetune_output/merged`
2. Register: `ollama create nanda-annotator -f Modelfile`
3. Benchmark: `/annotate /wiggum --producer nanda-annotator` on held-out papers vs base

### DPO training loop closure
`build_dpo_dataset.py` exports cross-run preference pairs. When N ≥ 50 pairs:
`trl dpo --model <sft-checkpoint> --dataset hf_datasets/dpo.jsonl`
Re-import via Ollama Modelfile and benchmark against base producer.

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

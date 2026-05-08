---
title: Agent Pipeline
introspect: true
---

# Agent Pipeline

## Research pipeline (default for most tasks)

```
Task input
  → Planner          (queries, complexity, task_type)
  → pre_research skills  (deep, contextualize)
  → Gather research  (multi-round web search, compression, dedup)
  → pre_synthesis skills  (cite, scratchpad)
  → Synthesize       (producer model, single LLM call)
  → post_synthesis skills  (knowledge-graph)
  → Wiggum loop      (evaluate → revise, up to 3 rounds)
  → post_wiggum skills  (panel)
  → Write output     (markdown file)
```

Standalone skills bypass this entire pipeline.

## Pipeline stages and their token budget

Each stage produces input tokens (prompt) + output tokens (response). The `tokens_by_stage` field in every run record tracks: `input`, `output`, `calls`, `total_ms`, `eval_ms`, `prompt_ms`, `thinking_chars` per stage.

| Stage key | What it is |
|-----------|-----------|
| `planner` | Task decomposition into search queries + complexity estimate |
| `search_query` | Per-search query generation and reformulation |
| `compress_knowledge` | LLM compression of raw search results before synthesis |
| `synth` | Main synthesis call (largest single input) |
| `synth_count` | Count-check retry if output count doesn't match task |
| `tool_loop` | Python tool execution calls within synthesis |
| `wiggum_eval` | Evaluation call per wiggum round |
| `wiggum_revise` | Revision call per wiggum round |
| `memory` | Memory retrieval query |
| `introspect` | Self-knowledge synthesis call |
| `orientation` | Environment awareness synthesis call |
| `annotate` | Paper annotation call |
| `other` | Miscellaneous calls not mapped to a named stage |

## Planner output

The planner produces:
- `search_queries` — list of web search queries
- `complexity` — `"low"`, `"medium"`, or `"high"` (triggers panel at high)
- `task_type` — classifies the task for wiggum task-criteria injection
- `known_facts` — facts derivable without search
- `knowledge_gaps` — what web search must resolve

## Memory integration

Agent memory is a ChromaDB vector store (`data/chroma_memory/`). At the start of each research run, the planner query is used to retrieve semantically relevant observations from prior runs. Retrieved observations are injected into the synthesis prompt as a `memory_block`. `/recall` performs direct semantic search without starting a full pipeline.

## Search and deduplication

Web search uses DuckDuckGo (`duckduckgo-search`). Each round generates new queries, fetches results, and accumulates a knowledge base. A novelty gate tracks already-seen content hashes; search stops early when diminishing returns are detected (configurable by `/deep` to disable). Results are compressed with the LLM if the total context exceeds `KNOWLEDGE_MAX_CHARS`.

## Context files for self-knowledge

The `/introspect` and `/contextualize` skills load `harness/skills/wiki/*.md` files that have `introspect: true` in their YAML frontmatter. Files named `index.md` and `log.md` are skipped. If no tagged wiki pages exist, falls back to `harness/skills/context/*.md` (legacy).

## Trajectory tracing

Every pipeline step is recorded in `trajectory` in the run record: `{seq, stage, thinking, tool, query, result_chars}`. This powers the Pipeline DAG view in the dashboard. Chrome Trace JSON files (loadable in `ui.perfetto.dev`) are written to `data/traces/` per run.

## Run record fields (key subset)

| Field | Description |
|-------|-------------|
| `run_id` | Unique run identifier |
| `task` | Original task string (after skill tokens stripped) |
| `task_type` | Classified task type |
| `producer_model` | Model used for synthesis |
| `evaluator_model` | Model used for wiggum evaluation |
| `input_tokens` / `output_tokens` | Total across all LLM calls |
| `tokens_by_stage` | Per-stage token breakdown (see above) |
| `wiggum_scores` | List of composite scores, one per round |
| `wiggum_dims` | Per-dimension scores per round |
| `wiggum_eval_log` | Full eval text, thinking, issues, feedback per round |
| `final` | `PASS`, `FAIL`, or `ERROR` |
| `trajectory` | Ordered list of pipeline steps |
| `memory_hits` | Number of memory observations retrieved |
| `tool_calls` | List of `{name, query, result_chars}` |
| `leverage` | `(tac_hours × quality_norm) / (runtime_s + cost_s)` |

## Environment variables

| Variable | Effect |
|----------|--------|
| `HARNESS_PRODUCER_MODEL` | Default producer model |
| `HARNESS_EVALUATOR_MODEL` | Default evaluator model |
| `OLLAMA_KEEP_ALIVE` | Pin model keep-alive in seconds (`-1` = forever) |
| `WIGGUM_PANEL` | Set to `1` to enable 3-persona panel after eval |
| `HARNESS_HEADED` | Set to `1` to show browser window |
| `HARNESS_KEEP_BROWSER` | Set to `1` to leave browser open |
| `HARNESS_REUSE_BROWSER` | Set to `1` to reconnect to existing session |
| `CLAUDE_WEBHOOK_URL` | POST a compact run summary here on completion |
| `HARNESS_HOURLY_RATE` | Hourly rate for leverage calculation (default: 75.0) |
| `HARNESS_SESSION_ID` | Override session grouping |
| `HARNESS_PROJECT_ID` | Override project grouping |
| `HARNESS_EXPERIMENT_ID` | Tag run to an experiment |
| `HARNESS_TREATMENT_LEVEL` | A/B treatment label for this run |

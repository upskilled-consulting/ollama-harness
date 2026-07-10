# ollama-harness

Local-first agentic research pipeline. An LLM talks to the web, your filesystem, a browser, and itself — search, synthesize, evaluate, revise, remember. No cloud API required.

```bash
pip install ollama-harness
oh                        # interactive REPL
oh research "RL from human feedback"
oh /lit-review "RAG reranking" save to review.md
oh /design https://stripe.com save to stripe-design.md
```

---

## What it does

A single `oh` command drives an agentic loop:

1. **Plan** — identify what's known, what's missing, what queries to run
2. **Research** — multi-round web search with novelty gating and URL enrichment
3. **Synthesize** — produce a structured markdown document from the merged context
4. **Evaluate** — Wiggum scores output across 6 dimensions (relevance, completeness, depth, groundedness, specificity, structure)
5. **Revise** — if below threshold, the producer rewrites from evaluator feedback
6. **Remember** — compress the run, store in ChromaDB, inject relevant observations into future runs

Skills extend the loop with specialised agents: browser navigation, literature review, YouTube transcription, design-system extraction, and multi-file HTML page generation.

---

## Install

```bash
pip install ollama-harness
```

Or from source with [uv](https://github.com/astral-sh/uv):

```bash
git clone https://github.com/upskilled-consulting/ollama-harness
cd ollama-harness
uv sync
uv sync --extra gpu   # CUDA torch
uv pip install -e .   # register the `oh` entry point
```

### Prerequisites

| Dependency | Purpose | Notes |
|---|---|---|
| [Ollama](https://ollama.com) | LLM inference (default) | `ollama serve` must be running |
| [llama.cpp server](https://github.com/ggerganov/llama.cpp) | Alternative inference backend | Configure via `HARNESS_ENDPOINTS` |
| [vLLM](https://github.com/vllm-project/vllm) | High-throughput inference backend (Linux/WSL2) | Set `INFERENCE_BACKEND=vllm` + `VLLM_BASE_URL` |
| [Node.js ≥ 18](https://nodejs.org) | Dashboard UI | `start.py` builds it automatically; manual: `cd dashboard && npm install && npm run build` |
| [Playwright](https://playwright.dev) | Browser skills | `playwright install chromium` |
| [whisper.cpp](https://github.com/ggerganov/whisper.cpp) | Audio transcription | Build binary, place at `whisper.cpp/` |

---

## Quick start

```bash
# Interactive REPL
oh

# One-shot task (no quotes needed)
oh research the latest work on speculative decoding

# Literature review
oh /lit-review "LLM calibration and uncertainty" save to calibration-review.md

# Browser navigation
oh /browser https://arxiv.org "find the most cited paper on RLHF this year"

# Transcribe a YouTube video
oh /transcribe https://youtube.com/watch?v=...

# Extract a design system from a live site
oh /design https://example.com save to design.md

# Generate a themed HTML page from .md content files
oh /build-page design.md from content/ save to index.html

# Full design-extract + page-build in one command
oh /site https://example.com from content/ save to index.html

# Generate a themed .pptx deck from a PDF paper
oh /deck --design https://example.com --content paper.pdf --out slides.pptx

# Deck from a URL content source with an existing design system
oh /deck --design brand.md --content https://example.com/article --out deck.pptx

# Deck from a folder of .md files styled to match a live site
oh /deck --design https://example.com --content ~/notes/ --title "Q2 Review" --out deck.pptx
```

---

## Skills reference

| Command | Description |
|---|---|
| `research <topic>` | Multi-round web search + synthesis |
| `summarize <url\|path>` | Fetch and compress a URL or local file |
| `/lit-review <topic>` | Fetch papers, annotate, synthesize into review |
| `/annotate <url\|path>` | Annotate a paper or document (wiggum eval) |
| `/browser <url> <goal>` | LLM-guided web navigation + content extraction |
| `/sitemap <url> [goal]` | Crawl a domain, rank pages by goal |
| `/design <url>` | Extract design system tokens from a live URL |
| `/build-page <design.md> from <dir/>` | Generate themed HTML page from .md content files |
| `/site <url> from <dir/>` | Design extraction + page build in one command |
| `/deck --design <url\|md> --content <url\|dir\|pdf>` | Generate a themed .pptx slide deck |
| `/transcribe <url\|path>` | Transcribe YouTube video or local audio |
| `/recall <topic>` | Surface relevant observations from memory |
| `/introspect` | Generate a live capabilities doc from the skill registry |
| `/orientation` | Summarise project state + recent activity |
| `/re-orient` | Rebuild orientation cache from GitHub state |
| `/suggest` | Recommend next research tasks |
| `/debug [filter]` | Diagnose recent FAIL/ERROR runs |
| `/email <contact> <goal>` | Draft and send emails via Gmail |
| `/sync-wiki` | Sync lit-review corpus to GitHub wiki |
| `/panel` | Enable 3-persona wiggum review panel |

### Flags

| Flag | Effect |
|---|---|
| `--no-wiggum` | Skip quality evaluation loop |
| `--headed` | Show browser window (browser/design tasks) |
| `--keep-browser` | Leave browser open after task |
| `--reuse-browser` | Reconnect to existing Chrome session |

---

## Configuration

Copy `.env.example` to `.env` and edit:

```bash
cp .env.example .env
```

Key variables:

```bash
# Model endpoints — llamacpp / vllm / openai-compatible
HARNESS_ENDPOINTS='{"qwen3-8b": {"url": "http://localhost:8082/v1", "model_id": "qwen3-8b", "backend": "llamacpp"}, "qwen3.6-35b": {"url": "http://localhost:8083/v1", "model_id": "Qwen3.6-35B-A3B-UD-IQ3_S.gguf", "backend": "llamacpp"}}'
HARNESS_PRODUCER_MODEL=qwen3.6-35b

# Pure Ollama (default — no HARNESS_ENDPOINTS needed)
# Just run: ollama pull qwen3:8b

# vLLM backend (Linux/WSL2 only)
INFERENCE_BACKEND=vllm
VLLM_BASE_URL=http://localhost:8000/v1
VLLM_API_KEY=token-abc123
# Required when INFERENCE_BACKEND=vllm — must match the embedding model served by vLLM:
HARNESS_EMBED_MODEL=nomic-ai/nomic-embed-text-v1.5

# Semantic Scholar API key (optional — increases rate limit)
S2_API_KEY=your_key_here

# Gmail (for /email skill)
SENDER_NAME=Your Name
SENDER_EMAIL=you@example.com
```

### Multi-endpoint routing

`HARNESS_ENDPOINTS` maps a short tag to `{url, model_id, backend}`. Supported backends: `llamacpp`, `vllm`, `openai`. Models not listed fall through to Ollama. This lets you run a fast small model (8B) alongside a large one (35B) on separate ports and route to the right one per task.

---

## Deck generation

`/deck` extracts a design system from any URL (or reads an existing `.md` design file), loads content from a URL, folder of `.md` files, or PDF (local or remote), and renders a fully themed `.pptx` using python-pptx.

```bash
oh /deck --design https://stripe.com --content research.pdf --out deck.pptx
oh /deck --design brand.md --content ~/notes/ --title "Q2 Review" --out deck.pptx
oh /deck --design https://notion.so --content https://example.com/paper.pdf
```

Content sources are auto-detected:

| Source | Handling |
|---|---|
| `https://...` (web page) | Playwright scrape → structured markdown |
| `https://....pdf` | MarkItDown converts directly from URL |
| `/path/to/file.pdf` | MarkItDown converts local PDF |
| `/path/to/folder/` | All `.md` / `.txt` files in directory |
| `/path/to/file.md` | Single markdown file |

Slide types are inferred from markdown structure: `#` → title slide, `##` → section divider, bullet lists → content slides (auto-split at 6 bullets), `> blockquote` → callout, markdown tables → table slides.

---

## Page generation

`/build-page` uses a three-pass decomposed strategy that handles any number of content files without context overflow:

1. **Analysis** — LLM reads title + abstract of every file, clusters by topic, assigns display roles (`featured` / `card` / `compact`)
2. **Shell** — generates HTML structure (nav, hero, cluster sections) with `<!-- SECTION:filename.md -->` placeholders
3. **Sections** — one LLM call per file, role-aware card HTML injected into the shell

Result: a complete, themed, clustered page regardless of how many files are in the content directory.

---

## Self-improvement loop (autoresearch)

`autoresearch.py` is a standalone optimizer that runs outside the main `oh` pipeline. It proposes changes to `SYNTH_INSTRUCTION` in `agent.py`, runs the eval suite, and keeps changes that improve the composite score.

```bash
# Run against all three eval tasks, one eval sample per experiment
python harness/autoresearch.py --eval-n 1 --tasks T_B --mode auto

# Override inference routing (required when .env points at servers that aren't running)
$env:HARNESS_ENDPOINTS = ""
$env:INFERENCE_BACKEND = "ollama"
python harness/autoresearch.py --eval-n 1 --mode auto
```

| Flag | Effect |
|------|--------|
| `--eval-n N` | Samples per eval run (default: 3; use 1 for fast iteration) |
| `--tasks T_B,T_D` | Comma-separated eval task IDs (default: T_B,T_D,T_E) |
| `--mode auto` | `auto` (re-gathers research after plateau), `explore` (always), `exploit` (never) |
| `--delta FLOAT` | Minimum score improvement to keep a change (default: 0.1) |

Key environment variables for autoresearch:

| Variable | Effect |
|----------|--------|
| `PROPOSER_MODEL` | Model for instruction proposals (default: `Qwen3-Coder:30b`) |
| `KIMI_MODEL` | Cloud model consulted when loop gets stuck (default: `kimi-k2.5:cloud`) |
| `KIMI_STUCK_THRESHOLD` | Consecutive discards before Kimi consult fires (default: `6`) |
| `MINIBATCH_FLOOR` | Score floor for quick-screen before full eval (default: `6.5`) |
| `EPOCH_SIZE` | Experiments per slow-update epoch (default: `10`) |
| `VALIDATION_SEED_COUNT` | Re-run seeds required before accepting a proposal (default: `2`) |

Progress is logged to `autoresearch.tsv` (one row per experiment). The best accepted instruction is written to `skills/synthesis.md` and loaded by `agent.py` at startup.

---

## Supply chain transparency

[`AIBOM.md`](./AIBOM.md) enumerates all AI model artifacts — local GGUF models, custom Ollama Modelfiles with system-prompt overlays, and cloud endpoints — that the harness invokes at runtime. It complements [`SBOM.md`](./SBOM.md) (the software bill of materials, also generatable via `cyclonedx-py`) by capturing dependencies that don't appear in `pyproject.toml` or `uv.lock`.

Update `AIBOM.md` whenever a model is pulled or a Modelfile system prompt changes.

---

## Dashboard

A React/TypeScript UI (Vite + Tanstack Query) provides live visibility into every run.

| View | Description |
|---|---|
| **Dashboard** | KPI cards (total runs, pass rate, avg score, token spend) + recent activity feed |
| **Runs** | Master-detail split: compact run list on the left, full DAG inspector on the right. Click any run to see the pipeline graph, per-stage token counts, output preview, Wiggum scores with dimension bars, evaluator feedback, and an RLHF thumbs-up/down panel per node. |
| **Submit** | Fire a task directly from the browser; result appears live in Runs. |
| **Analytics** | Time-series charts for run volume, pass rate, and token usage. |
| **Sessions** | Group runs by session for multi-turn task tracking. |
| **Artifacts** | Browse output files written by runs. |
| **Fine-tune** | Training metrics (loss, accuracy curves) and RL dataset browser — preference pairs, reward feedback, GRPO rollouts, and DPO examples with Wiggum evaluator annotations. |
| **Autoresearch** | Real-time supervision of the autoresearch optimizer — experiment table (status badge, score, Δ, consecutive discards, Kimi-fire indicator), score sparkline, KPI summary, and a detail panel showing the full proposed synth instructions. Polls every 5 s. |
| **MCP** | Inspect registered MCP tool servers. |
| **Memory** | Semantic observation store browser — search/filter 1960+ memories, 👍/👎 RLHF quality signals (clamp −3 to +3), provenance trace to originating run, tag editor, prune-candidate review queue, and UMAP ontology graph (`pip install umap-learn scikit-learn`). |
| **Security** | Real-time audit log for all blocked/detected security events — injection attempts, path sandbox violations, Python code blocks, CDP navigation. Search, filter by severity/type/layer, click to expand full event detail. |
| **System** | Governance file viewer/editor (AGENTS.md, ROADMAP.md, wiki pages, user profile, `.harness-user.toml`), live active-config inspector (safe env vars + runtime settings + synth instructions), and skills registry table with hook-type filter chips. |

Two floating panels provide quick access from any view:

- **Terminal** — a harness shell with `cd` navigation, command history (↑/↓), `clear`/`help`, and live run-status badges for any submitted task.
- **Voice** — hands-free task submission via microphone.

---

## Starting the full stack

```bash
python start.py          # starts inference servers, FastAPI, React dashboard
```

Or individually:

```bash
uvicorn harness.api.main:app --reload    # API server (port 8000)
cd dashboard && npm run dev              # React dashboard (port 5173)
```

---

## whisper.cpp setup

The `/transcribe` skill uses the whisper.cpp binary for fast CPU/CUDA inference:

```bash
git clone https://github.com/ggerganov/whisper.cpp whisper.cpp
cd whisper.cpp
cmake -B build -DGGML_CUDA=ON
cmake --build build --config Release
./build/bin/whisper-cli --download-model base.en
```

Place the built directory at `whisper.cpp/` in the repo root.

---

## Development

```bash
uv sync --extra dev
pytest tests/
ruff check harness/
```

---

## License

MIT

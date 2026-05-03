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
| **MCP** | Inspect registered MCP tool servers. |

Two floating action buttons in the lower-right corner provide quick access without cluttering the sidebar:

- **Terminal** — a harness shell with `cd` navigation, command history (↑/↓), `clear`/`help`, and live run-status badges for any submitted task.
- **Voice** — the voice input panel for hands-free task submission.

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

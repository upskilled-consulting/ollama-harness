---
title: CLI Reference
introspect: true
---

# CLI Reference

The harness is invoked via the `oh` command (entrypoint: `harness.cli:main`).

## Usage modes

```
oh                        Interactive REPL (prompt_toolkit with history at ~/.op_history)
oh <task>                 Run a single task — no quotes needed
oh -h / --help            Show help
oh --serve [port]         Start the FastAPI server (default port from settings)
```

## Flags

| Flag | Effect |
|------|--------|
| `--no-wiggum` | Skip the quality evaluation+revision loop |
| `--headed` | Show the browser window for Playwright tasks (sets `HARNESS_HEADED=1`) |
| `--keep-browser` | Leave the browser open after the task (sets `HARNESS_KEEP_BROWSER=1`) |
| `--reuse-browser` | Reconnect to an existing Chromium session (sets `HARNESS_REUSE_BROWSER=1`) |
| `-h / --help` | Show the help panel |
| `exit / quit / q / :q` | Exit the REPL |

Flags can be mixed freely with task text: `oh --no-wiggum /cite research prompt caching`

## Task routing

Input is classified as a task (routes to full agent pipeline) when any of these are true:
- Starts with `/` (skill prefix)
- 5 or more words
- First word is a task verb (see below)
- Contains `https://`, a file extension (`.md`, `.py`, `.txt`), or `"save to"`

Otherwise the input is handled as lightweight chat (single-turn LLM call, no pipeline).

## Task verbs (auto-detected as tasks)

`research` `summarize` `summarise` `find` `fetch` `explain` `compare` `analyze` `analyse` `review` `generate` `write` `create` `build` `list` `show` `get` `search` `look` `check` `translate` `convert` `extract` `annotate` `transcribe` `survey` `evaluate` `run` `save`

## Common invocation patterns

```bash
# Research
oh research best practices for RAG pipeline design, save to ~/Desktop/out.md
oh /deep /cite research transformer attention mechanisms, save to attention.md

# Browser
oh /browser go to docs.anthropic.com and find the pricing page
oh /sitemap stripe.com find integration guides

# Papers
oh /annotate https://arxiv.org/abs/2305.10403
oh /lit-review retrieval-augmented generation

# Site generation
oh /design https://stripe.com save to stripe-design.md
oh /build-page stripe-design.md from ~/Desktop/content/ save to index.html
oh /site https://vercel.com from ~/Desktop/content/

# Deck
oh /deck --design https://notion.so --content ~/Desktop/notes/ --out slides.pptx --title "Q2 Review"

# Memory & project
oh /recall prompt injection detection
oh /orientation
oh /re-orient what changed in the last week?
oh /suggest
oh /debug
oh /troubleshoot ERROR

# Collaboration
oh /email "Dr. Smith" smith@uni.edu ~/Desktop/paper.pdf "invite to collaborate"
oh /email contacts.csv "follow up on our research proposal"
oh /github pr create
oh /review

# Media
oh /transcribe interview.mp3 to transcript.md
oh /queue "research topic A" ;; "research topic B" ;; "research topic C"
```

## Plugin commands

Plugins installed to `plugins/<name>/` are loaded at startup. Their commands appear in `/help` under PLUGINS and are invoked with `/<plugin-command>`. List installed plugins with `/forge:list`. Generate a new plugin with `/forge:plugin <description>`.

## Dashboard / API server

```bash
oh --serve           # starts FastAPI on configured host:port
harness              # same (alternative entrypoint)
```

API docs: `http://localhost:<port>/docs`

Key endpoints:
- `GET /api/data` — dashboard KPI payload
- `GET /api/runs` — active + recent runs
- `GET /api/runs/all` — full run list
- `GET /api/runs/{run_id}/content` — run output text
- `GET /api/runs/{run_id}/messages?stage=<stage>` — logged LLM turns per stage
- `GET /api/analytics` — daily aggregates, score distribution, task types
- `GET /api/sessions` — session history
- `GET /api/artifacts` — artifact registry
- `WS /ws/runs` — live run stream

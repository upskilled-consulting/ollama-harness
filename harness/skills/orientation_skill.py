"""
orientation_skill.py — /orientation skill.

Gathers situational awareness for the agent:
  - Directory tree with mtime + size (filtered)
  - .env config (keys only, no secret values)
  - Recent runs summary
  - Active experiments
  - Git log (last 10 commits)
  - GPU / system state
  - Wiki self-knowledge (introspect-tagged pages)
  - Memory observations

If the assembled document exceeds CHAR_LIMIT, prose sections are compressed
via the compress model before being returned.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

_BASE = Path(__file__).parent

# Char limit before the summarizer kicks in
CHAR_LIMIT = 14_000

# Directories/patterns to exclude from the tree walk
_TREE_EXCLUDE = {
    ".git", "__pycache__", "llama.cpp", "node_modules",
    ".mypy_cache", ".pytest_cache", "traces", "dist", "build",
}
_TREE_SKIP_EXT = {".pyc", ".pyo", ".egg-info"}


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------

def _tree() -> str:
    lines = ["## Directory tree\n"]
    for root, dirs, files in os.walk(_BASE):
        dirs[:] = sorted(d for d in dirs if d not in _TREE_EXCLUDE and not d.startswith("."))
        depth = len(Path(root).relative_to(_BASE).parts)
        indent = "  " * depth
        folder = Path(root).name if depth else "."
        lines.append(f"{indent}{folder}/")
        for fname in sorted(files):
            if Path(fname).suffix in _TREE_SKIP_EXT:
                continue
            fpath = Path(root) / fname
            try:
                stat = fpath.stat()
                mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC).strftime("%Y-%m-%d")
                size_kb = stat.st_size // 1024
                lines.append(f"{'  '*(depth+1)}{fname}  ({size_kb}KB, {mtime})")
            except OSError:
                lines.append(f"{'  '*(depth+1)}{fname}")
    return "\n".join(lines)


def _env_config() -> str:
    env_path = _BASE / ".env"
    if not env_path.exists():
        return "## .env config\n(not found)"
    lines = ["## .env config (keys shown; secret values redacted)\n"]
    _SECRET = {"token", "key", "password", "secret", "email"}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            k = k.strip()
            if any(s in k.lower() for s in _SECRET) and v.strip():
                lines.append(f"{k}=<redacted>")
            else:
                lines.append(line)
    return "\n".join(lines)


def _recent_runs(n: int = 8) -> str:
    runs_path = _BASE / "runs.jsonl"
    if not runs_path.exists():
        return "## Recent runs\n(none)"
    runs = []
    with open(runs_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    runs.append(json.loads(line))
                except Exception:
                    pass
    if not runs:
        return "## Recent runs\n(none)"
    recent = runs[-n:]
    lines = [f"## Recent runs (last {len(recent)})\n"]
    for r in recent:
        ts = (r.get("timestamp") or "")[:16].replace("T", " ")
        final = r.get("final", "?")
        score = (r.get("wiggum_scores") or [None])[0]
        score_str = f"  score={score}" if score is not None else ""
        model = r.get("producer_model", "")
        task = (r.get("task") or "")[:70]
        lines.append(f"- [{ts}] {final}{score_str}  model={model}  task={task}")
    return "\n".join(lines)


def _active_experiments() -> str:
    exp_dir = _BASE / "experiments"
    if not exp_dir.exists():
        return "## Active experiments\n(none)"
    lines = ["## Experiments\n"]
    for spec_path in sorted(exp_dir.glob("*/spec.json")):
        try:
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            run_log = spec_path.parent / "run_log.jsonl"
            n_done = 0
            if run_log.exists():
                with open(run_log, encoding="utf-8") as f:
                    n_done = sum(1 for l in f if l.strip())
            report = spec_path.parent / "report.md"
            verdict = ""
            if report.exists():
                first_line = report.read_text(encoding="utf-8").split("\n")[0]
                verdict = f"  → {first_line.strip()}"
            lines.append(
                f"- **{spec['title']}**  runs={n_done}  "
                f"factor={spec.get('factor',{}).get('name','')}  "
                f"levels={spec.get('factor',{}).get('levels',[])} {verdict}"
            )
        except Exception:
            pass
    return "\n".join(lines) if len(lines) > 1 else "## Experiments\n(none)"


def _git_log() -> str:
    try:
        out = subprocess.check_output(
            ["git", "log", "--oneline", "-10"],
            cwd=_BASE, stderr=subprocess.DEVNULL, text=True,
        )
        return f"## Git log (last 10)\n\n{out.strip()}"
    except Exception:
        return "## Git log\n(unavailable)"


def _gpu_state() -> str:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
        lines = ["## GPU state\n"]
        for row in out.splitlines():
            name, used, total, util = [x.strip() for x in row.split(",")]
            lines.append(f"- {name}  VRAM {used}/{total} MiB  util={util}%")
        return "\n".join(lines)
    except Exception:
        return ""


def _wiki_context() -> str:
    try:
        from harness.skills import load_context_files
        ctx = load_context_files()
        return f"## Self-knowledge (wiki)\n\n{ctx}" if ctx else ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Assembly + optional compression
# ---------------------------------------------------------------------------

def _compress(text: str, model: str) -> str:
    try:
        from harness import inference
        active = inference.get_active_vllm_model()
        if active:
            model = active
        resp = inference.chat(
            model=model,
            messages=[{
                "role": "user",
                "content": (
                    "Summarize the following project orientation document for an AI agent. "
                    "Preserve: all file paths, model names, experiment names, config keys, "
                    "git hashes, and run statistics. Condense prose descriptions. "
                    "Keep the section headers. Target ~6000 chars.\n\n"
                    f"{text}"
                ),
            }],
            options={"temperature": 0.1, "num_predict": 3000},
        )
        return resp.message.content.strip()
    except Exception as e:
        print(f"  [orientation] compression failed ({e}), using truncated raw")
        return text[:CHAR_LIMIT]


def build_orientation(
    producer_model: str,
    memory_ctx: str = "",
    compress_model: str | None = None,
) -> str:
    sections = [
        _env_config(),
        _recent_runs(),
        _active_experiments(),
        _git_log(),
        _gpu_state(),
        _wiki_context(),
        _tree(),
    ]
    if memory_ctx:
        sections.append(f"## Memory observations\n\n{memory_ctx}")

    doc = "\n\n".join(s for s in sections if s)

    if len(doc) > CHAR_LIMIT:
        print(f"  [orientation] document is {len(doc)} chars — compressing...")
        doc = _compress(doc, compress_model or producer_model)
        print(f"  [orientation] compressed to {len(doc)} chars")
    else:
        print(f"  [orientation] document is {len(doc)} chars (no compression needed)")

    return doc

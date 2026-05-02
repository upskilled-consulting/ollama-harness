"""
review_skill.py — /review standalone skill.

Reviews staged (or unpushed) changes against a code quality rubric inspired by
Karpathy's "no magic, explicit, no speculative abstractions" guidelines.

What it checks:
  - No speculative abstractions (helpers/classes built for one-time use)
  - No magic / implicit behaviour (auto-wiring, hidden side-effects)
  - No unnecessary complexity (over-engineered for the task)
  - No dead code / unused parameters left in
  - No backwards-compatibility shims that aren't needed
  - Functions do one thing
  - Error handling only at real system boundaries

Scope options (parsed from task string):
  staged   — git diff --cached  (default if nothing staged, falls back to HEAD~1)
  unstaged — git diff
  last     — git diff HEAD~1..HEAD (last commit)
  all      — git diff origin/main...HEAD

Usage (via agent.py):
    python agent.py "/review"
    python agent.py "/review last"
    python agent.py "/review all"
    python agent.py "/review output/review.md"
"""

import os
import re
import subprocess
from pathlib import Path

from harness.inference import chat as _llm_chat

HERE          = Path(__file__).parent
_KEEP_ALIVE   = int(os.environ.get("OLLAMA_KEEP_ALIVE", -1))
_DEFAULT_MODEL = os.environ.get("REVIEW_MODEL", os.environ.get("PRODUCER_MODEL", "Qwen3-Coder:30b"))

_MAX_DIFF_CHARS = 8000   # keep prompt manageable for small models

# ---------------------------------------------------------------------------
# Rubric
# ---------------------------------------------------------------------------

_REVIEW_SYSTEM = """\
You are a senior software engineer reviewing a git diff for code quality issues.
Apply the following rubric strictly. Only flag real problems — do not invent issues.

You are looking for four specific anti-patterns ONLY. Do not invent issues outside these four.

ANTI-PATTERN 1 — DEAD CODE
A symbol (function, variable, import) is added or kept in the diff AND is never referenced anywhere in the same diff.

IMPORTANT EXCEPTION — do NOT flag dead code if ANY of these are true:
  a) The symbol appears as a value in a dict literal: `{"key": symbol}` — that IS a reference.
  b) The symbol appears in a list literal: `[symbol, ...]` — that IS a reference.
  c) The symbol is a function added to a dispatch/registry dict on any subsequent line of the diff.

Flag as: WARN FILE:LINE — Dead code: X is defined but never used

ANTI-PATTERN 2 — BARE EXCEPT
A try/except block uses `except:` or `except Exception:` with an empty body or only `pass`.
Flag as: WARN FILE:LINE — Bare except swallows errors silently

ANTI-PATTERN 3 — BACKWARDS-COMPAT SHIM
A symbol is renamed and the old name is re-exported as an alias with a comment like "# deprecated" or "# TODO remove".
Flag as: WARN FILE:LINE — Backwards-compat alias for X — remove it or the caller

ANTI-PATTERN 4 — UNREACHABLE BRANCH
An if/else branch whose condition is always True or always False given the surrounding code.
Flag as: WARN FILE:LINE — Unreachable branch: condition is always X

If none of the four anti-patterns appear in the diff, output ONLY:
  SUMMARY: 0 warnings — looks good

If anti-patterns are found, list each as a WARN line, then:
  SUMMARY: N warnings

Output ONLY these lines. No explanations, no other commentary.\
"""


# ---------------------------------------------------------------------------
# Shell helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str]) -> tuple[int, str, str]:
    result = subprocess.run(
        cmd,
        cwd=str(HERE),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _get_diff(scope: str) -> tuple[str, str]:
    """
    Returns (diff_text, scope_label).
    scope: "staged" | "unstaged" | "last" | "all"
    """
    if scope == "unstaged":
        _, diff, _ = _run(["git", "diff"])
        return diff, "unstaged changes"

    if scope == "last":
        _, diff, _ = _run(["git", "diff", "HEAD~1..HEAD"])
        return diff, "last commit"

    if scope == "all":
        _, diff, _ = _run(["git", "diff", "origin/main...HEAD"])
        return diff, "all unpushed commits"

    # Default: staged; fall back to HEAD~1 if nothing staged
    _, staged, _ = _run(["git", "diff", "--cached"])
    if staged.strip():
        return staged, "staged changes"
    _, diff, _ = _run(["git", "diff", "HEAD~1..HEAD"])
    return diff, "last commit (nothing staged)"


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _llm(diff: str, model: str) -> tuple[str, int, int, str]:
    """Returns (review_text, tokens_in, tokens_out, thinking_text)."""
    user_msg = f"Review this git diff:\n\n```diff\n{diff[:_MAX_DIFF_CHARS]}\n```"
    if len(diff) > _MAX_DIFF_CHARS:
        user_msg += f"\n\n[diff truncated — {len(diff):,} chars total, showing first {_MAX_DIFF_CHARS:,}]"

    resp = _llm_chat(
        model=model,
        messages=[
            {"role": "system", "content": _REVIEW_SYSTEM},
            {"role": "user",   "content": user_msg},
        ],
        options={"temperature": 0.1},
        keep_alive=_KEEP_ALIVE,
    )
    msg     = resp["message"]
    text    = msg.get("content", "").strip()
    # Strip any markdown fences the model wraps around its output
    text    = re.sub(r"^```[a-z]*\n?", "", text).rstrip("`").strip()
    # Capture reasoning trace if the model emitted one (Qwen3, deepseek-r1, etc.)
    thinking = (msg.get("thinking") or "").strip()
    in_tok  = resp.get("prompt_eval_count", 0) or 0
    out_tok = resp.get("eval_count", 0) or 0
    return text, in_tok, out_tok, thinking


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_review_standalone(task: str, model: str = _DEFAULT_MODEL) -> dict:
    """
    Parse scope from task string, get diff, run LLM review.

    Returns a result dict:
      text          — full formatted review markdown
      scope         — staged | unstaged | last | all
      diff_chars    — size of diff reviewed
      warnings      — list of WARN lines extracted from output
      warnings_count — int
      summary       — the SUMMARY: line
      thinking      — reasoning trace text if model emitted one (else "")
      tokens_in     — int
      tokens_out    — int
    """
    tokens = task.lower().split()

    # Scope detection
    if "unstaged" in tokens:
        scope = "unstaged"
    elif "last" in tokens:
        scope = "last"
    elif "all" in tokens:
        scope = "all"
    else:
        scope = "staged"

    diff, label = _get_diff(scope)

    if not diff.strip():
        msg = f"[review] Nothing to review ({label} — diff is empty)."
        print(msg)
        return {"text": msg, "scope": scope, "diff_chars": 0, "warnings": [],
                "warnings_count": 0, "summary": "", "thinking": "", "tokens_in": 0, "tokens_out": 0}

    print(f"[review] Reviewing {label} ({len(diff):,} chars diff)...")
    review, in_tok, out_tok, thinking = _llm(diff, model)

    # Parse structured fields from review text
    warn_lines = [l.strip() for l in review.splitlines() if l.strip().startswith("WARN")]
    summary_m  = re.search(r"^SUMMARY:.+$", review, re.MULTILINE)
    summary    = summary_m.group(0) if summary_m else ""

    # Build output markdown
    lines = [
        f"# Code Review — {label}",
        "",
        review,
        "",
        f"*Model: {model}  |  tokens in: {in_tok:,}  out: {out_tok:,}*",
    ]
    output = "\n".join(lines)

    print("\n" + review + "\n")
    print(f"[review] tokens — in: {in_tok:,}  out: {out_tok:,}")
    if thinking:
        print(f"[review] thinking: {len(thinking)} chars")

    return {
        "text":           output,
        "scope":          scope,
        "diff_chars":     len(diff),
        "warnings":       warn_lines,
        "warnings_count": len(warn_lines),
        "summary":        summary,
        "thinking":       thinking,
        "tokens_in":      in_tok,
        "tokens_out":     out_tok,
    }


# ---------------------------------------------------------------------------
# CLI (standalone test)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    run_review_standalone(task)

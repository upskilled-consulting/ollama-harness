"""
harness/summarizer.py — conditional content summarization for wiggum and agent pipeline.

Fires only when content exceeds a character threshold; passes through unchanged
otherwise. Uses a fast model (SUMMARIZER_MODEL, default glm4:9b) to avoid
adding latency on short documents.

Two modes:
  summarize_for_eval()     — section-preserving summary for the evaluator;
                             ensures all H2 sections are visible even in long docs.
  summarize_for_revision() — surgical: keeps sections mentioned in issues verbatim,
                             condenses the rest so the revision prompt fits in context.

Thresholds:
  EVAL_THRESHOLD    = 32000 chars
  REVISE_THRESHOLD  = 5000  chars
"""

from __future__ import annotations

import os
import re

from harness.inference import OllamaLike as _OllamaLike

_KEEP_ALIVE = int(os.environ.get("OLLAMA_KEEP_ALIVE", -1))
_chat = _OllamaLike(keep_alive=_KEEP_ALIVE).chat

SUMMARIZER_MODEL  = os.environ.get("SUMMARIZER_MODEL",
                       os.environ.get("COMPRESS_MODEL", "qwen3-8b"))
EVAL_THRESHOLD    = int(os.environ.get("SUMMARIZER_EVAL_THRESHOLD",   32000))
REVISE_THRESHOLD  = int(os.environ.get("SUMMARIZER_REVISE_THRESHOLD",   5000))


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_EVAL_SUMMARY_PROMPT = """\
You are summarizing a research document so an evaluator can assess it.
The evaluator checks: relevance, completeness, depth, specificity, and structure.

Task this document addresses:
{task}

Document:
{content}

Produce a faithful summary that preserves:
- Every H2 section heading (## Section Name)
- The key claim and one concrete example or implementation detail per section
- Any specific names, thresholds, library names, or tool names mentioned

Format: keep the ## headings, write 3-5 sentences per section.
Do not add anything not present in the original. Do not evaluate — only summarize.
Target length: under 4000 characters."""


_REVISE_SUMMARY_PROMPT = """\
You are compressing a document before it is revised. Certain sections need full
attention (listed as issues). Preserve those sections verbatim. For all other
sections, write a 2-3 sentence condensed version that preserves the key claim
and any specific details (names, numbers, code snippets).

Task:
{task}

Sections requiring full preservation (keep these EXACTLY as written):
{issue_sections}

Document:
{content}

Output the condensed document. Keep ## headings. Do not add commentary."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_section_headings(content: str) -> list[str]:
    """Return all H2 section names from a markdown document."""
    return re.findall(r"^##\s+(.+)", content, re.MULTILINE)


def _sections_matching_issues(content: str, issues: list[str]) -> set[str]:
    """
    Return the set of H2 section headings mentioned in any issue string.
    Issues typically look like: "Section 4 (Multi-Agent Resource Efficiency) ..."
    """
    headings = _extract_section_headings(content)
    mentioned = set()
    for issue in issues:
        issue_lower = issue.lower()
        for heading in headings:
            heading_words = set(re.findall(r"\w{4,}", heading.lower()))
            if heading_words and any(w in issue_lower for w in heading_words):
                mentioned.add(heading)
    return mentioned


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def summarize_for_eval(content: str, task: str, trace=None) -> str:
    """
    Return content suitable for the evaluator.

    If len(content) <= EVAL_THRESHOLD: returns content unchanged.
    Otherwise: calls SUMMARIZER_MODEL to produce a section-preserving summary,
    then appends the raw tail of the document (last 500 chars).
    """
    if len(content) <= EVAL_THRESHOLD:
        return content

    print(f"  [summarizer] eval: {len(content)} chars > {EVAL_THRESHOLD} — summarizing for evaluator")
    prompt = _EVAL_SUMMARY_PROMPT.format(task=task, content=content)

    try:
        response = _chat(
            model=SUMMARIZER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1, "num_predict": 1200, "think": False},
        )
        if trace is not None:
            trace.log_usage(response, stage="summarize_eval")
        summary = response["message"]["content"].strip()
    except Exception as e:
        print(f"  [summarizer] eval failed ({e}) — falling back to head+tail excerpt")
        head = content[:4500]
        tail = content[-500:] if len(content) > 5000 else ""
        return (head + ("\n\n[...]\n\n" + tail if tail else "")).strip()

    tail = content[-300:] if len(content) > EVAL_THRESHOLD + 300 else ""
    if tail and tail not in summary:
        summary = summary + "\n\n[document tail]\n" + tail

    print(f"  [summarizer] eval: {len(content)} -> {len(summary)} chars")
    return summary


def summarize_for_revision(content: str, task: str, issues: list[str], trace=None) -> str:
    """
    Return content suitable for the revision prompt.

    If len(content) <= REVISE_THRESHOLD: returns content unchanged.
    Otherwise: keeps sections mentioned in issues verbatim, condenses the rest.
    """
    if len(content) <= REVISE_THRESHOLD:
        return content

    print(f"  [summarizer] revise: {len(content)} chars > {REVISE_THRESHOLD} — summarizing for revision")
    issue_sections = _sections_matching_issues(content, issues)
    issue_sections_str = "\n".join(f"- {s}" for s in issue_sections) if issue_sections else "(none identified — preserve all sections)"

    prompt = _REVISE_SUMMARY_PROMPT.format(
        task=task,
        issue_sections=issue_sections_str,
        content=content,
    )

    try:
        response = _chat(
            model=SUMMARIZER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1, "num_predict": 2000, "think": False},
        )
        if trace is not None:
            trace.log_usage(response, stage="summarize_revise")
        compressed = response["message"]["content"].strip()
        print(f"  [summarizer] revise: {len(content)} -> {len(compressed)} chars  "
              f"(preserved sections: {issue_sections or 'all'})")
        return compressed
    except Exception as e:
        print(f"  [summarizer] revise failed ({e}) — using original content")
        return content

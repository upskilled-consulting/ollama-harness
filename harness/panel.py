"""
harness/panel.py — Multi-persona evaluation panel via Ollama.

Three reviewers evaluate a document from distinct angles:
  1. Domain Practitioner  — technical depth, accuracy, actionability
  2. Critical Reviewer    — coverage gaps, missing context, unsupported claims
  3. Informed Newcomer    — clarity, accessibility, whether a newcomer could act on it

Each reviewer returns: {"persona", "score", "issues", "strengths", "raw"}
Panel results augment wiggum's issues[] before revision and are logged to
runs.jsonl for downstream distillation / preference learning.

Enabled in wiggum via WIGGUM_PANEL=1 environment variable.

Usage (standalone):
    python -m harness.panel "<task>" path/to/output.md [model]
"""

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager

from harness.inference import OllamaLike as _OllamaLike


@contextmanager
def _nullctx():
    yield

_KEEP_ALIVE = int(os.environ.get("OLLAMA_KEEP_ALIVE", -1))
_chat = _OllamaLike(keep_alive=_KEEP_ALIVE).chat


# ---------------------------------------------------------------------------
# Persona definitions
# ---------------------------------------------------------------------------

PANEL_PERSONAS = [
    {
        "name": "Domain Practitioner",
        "system": (
            "You are a senior software engineer with 10+ years building production systems. "
            "You evaluate whether technical content is actionable and production-ready. "
            "You look for concrete implementation details, not just conceptual descriptions. "
            "You flag when examples are toy-level rather than production-grade. "
            "You are rigorous and skeptical of vague claims. "
            "You always ask: could a practitioner act on this today?"
        ),
        "focus": "technical depth, accuracy, and practical actionability",
    },
    {
        "name": "Critical Reviewer",
        "system": (
            "You are a technical editor who reviews documentation for completeness and intellectual rigor. "
            "You systematically identify gaps — what an expert would expect to see but is missing. "
            "You flag unsupported claims, missing caveats, and one-sided coverage. "
            "You read for what is absent, not just what is present. "
            "You check whether multiple angles of a topic are covered, not just the easiest ones."
        ),
        "focus": "coverage gaps, missing context, and unsupported claims",
    },
    {
        "name": "Informed Newcomer",
        "system": (
            "You are a developer with general programming knowledge learning this specific topic for the first time. "
            "You test whether a document is comprehensible to someone without prior domain knowledge. "
            "You flag jargon that is not explained and concepts assumed without introduction. "
            "You ask: could I act on this after reading it? "
            "You flag any step that requires knowledge the document does not provide."
        ),
        "focus": "clarity, accessibility, and whether a newcomer could follow and act on this",
    },
]

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

PANEL_PROMPT = """\
Task this document was written for:
{task}

Document:
{content}

Review this document from your perspective, focusing on: {focus}

Be specific — name sections and exact issues. Be concise.

Respond with valid JSON only, no preamble:
{{
  "score": integer 0-10,
  "issues": ["specific issue naming the section and exactly what is missing or wrong"],
  "strengths": ["specific thing done well"]
}}"""


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def _parse_response(raw: str, persona_name: str) -> dict:
    """Extract score/issues/strengths from raw model output."""
    try:
        clean = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        clean = re.sub(r"\s*```$", "", clean)
        clean = re.sub(r"<think>.*?</think>", "", clean, flags=re.DOTALL).strip()
        data = json.loads(clean)
        return {
            "persona":   persona_name,
            "score":     int(data.get("score", 5)),
            "issues":    [i for i in data.get("issues", []) if i],
            "strengths": [s for s in data.get("strengths", []) if s],
            "raw":       raw,
        }
    except (json.JSONDecodeError, ValueError):
        pass

    issues  = re.findall(r"(?:issue|problem|missing|gap|unclear)[:\s-]+(.+)", raw, re.IGNORECASE)
    strengths = re.findall(r"(?:strength|good|well|positive)[:\s-]+(.+)", raw, re.IGNORECASE)
    score_m = re.search(r"\b(\d(?:\.\d)?)\s*(?:/\s*10|out of 10)\b", raw)
    return {
        "persona":   persona_name,
        "score":     int(float(score_m.group(1))) if score_m else 5,
        "issues":    issues[:5],
        "strengths": strengths[:3],
        "raw":       raw,
    }


def run_panel(task: str, content: str, model: str, trace=None) -> list[dict]:
    """
    Run the three-persona evaluation panel on a document in parallel.

    Returns a list of review dicts, one per persona (order matches PANEL_PERSONAS):
        [{"persona", "score", "issues", "strengths", "raw"}, ...]

    If trace (a RunTrace) is provided, each persona records its own span — they will
    appear as separate lanes in the Perfetto timeline, confirming actual parallelism.
    """
    content_excerpt = content[:5000]

    def _run_persona(persona):
        name = persona["name"]
        if trace is not None:
            trace.name_thread(f"panel/{name}")
        print(f"  [panel] {name}...")
        try:
            prompt = PANEL_PROMPT.format(
                task=task,
                content=content_excerpt,
                focus=persona["focus"],
            )
            ctx = trace.span(f"panel/{name}") if trace is not None else _nullctx()
            with ctx:
                response = _chat(
                    model=model,
                    messages=[
                        {"role": "system", "content": persona["system"]},
                        {"role": "user",   "content": prompt},
                    ],
                    options={"temperature": 0.3},
                )
            raw = response["message"]["content"].strip()
            review = _parse_response(raw, name)
            print(f"    [{name}] score={review['score']}/10  issues={len(review['issues'])}")
            return review
        except Exception as e:
            print(f"  [panel] {name} failed ({e}) — skipping")
            return None

    reviews = []
    with ThreadPoolExecutor(max_workers=len(PANEL_PERSONAS)) as pool:
        futures = {pool.submit(_run_persona, p): p["name"] for p in PANEL_PERSONAS}
        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
                if result is not None:
                    reviews.append(result)
            except Exception as e:
                print(f"  [panel] {name} failed ({e}) — skipping")

    order = {p["name"]: i for i, p in enumerate(PANEL_PERSONAS)}
    reviews.sort(key=lambda r: order.get(r["persona"], 99))
    return reviews


def panel_issues(reviews: list[dict]) -> list[str]:
    """Flatten panel reviews into a deduplicated issues list prefixed by persona name."""
    seen = set()
    issues = []
    for r in reviews:
        for issue in r.get("issues", []):
            key = issue.lower().strip()
            if key not in seen:
                seen.add(key)
                issues.append(f"[{r['persona']}] {issue}")
    return issues


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print('usage: python -m harness.panel "<task>" path/to/output.md [model]')
        sys.exit(1)

    _task    = sys.argv[1]
    _path    = sys.argv[2]
    _model   = sys.argv[3] if len(sys.argv) > 3 else "Qwen3-Coder:30b"

    with open(_path, encoding="utf-8") as _f:
        _content = _f.read()

    print(f"\n[panel] running 3-persona evaluation panel (model={_model})\n")
    _reviews = run_panel(_task, _content, _model)

    for r in _reviews:
        print(f"\n--- {r['persona']} (score={r['score']}/10) ---")
        for i in r.get("issues", []):
            print(f"  issue: {i}")
        for s in r.get("strengths", []):
            print(f"  strength: {s}")

    print("\n[panel] merged issues:")
    for i in panel_issues(_reviews):
        print(f"  - {i}")

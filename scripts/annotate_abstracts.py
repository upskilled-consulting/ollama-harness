"""
annotate_abstracts.py — Annotated Abstract generator using the Nanda framework.

Reads a CSV of research papers (with a markdown_content column) and produces an
annotated abstract for each paper using 8 rhetorical moves:

    Topic · Motivation · Contribution · Detail/Nuance ·
    Evidence/Contribution 2 · Weaker result · Narrow impact · Broad impact

Context engineering: extracts Abstract, Conclusion, Introduction, Results, and
Discussion sections within a char budget rather than blindly feeding full text.
Falls back to head+tail truncation if the paper has no markdown headings.

Usage:
    python annotate_abstracts.py papers.csv
    python annotate_abstracts.py papers.csv --model Qwen3-Coder:30b --out annotated/
    python annotate_abstracts.py papers.csv --reprocess   # redo failed/incomplete

Environment:
    conda activate ollama-pi
"""

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import argparse
import os
import os as _os
import re
import sys as _sys
import time

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import pandas as pd

from harness.inference import OllamaLike as _OllamaLike
from harness.logger import RunTrace

# ---------------------------------------------------------------------------
# Ollama shim — keeps model hot between calls
# ---------------------------------------------------------------------------

_KEEP_ALIVE = int(os.environ.get("OLLAMA_KEEP_ALIVE", -1))
_chat = _OllamaLike(keep_alive=_KEEP_ALIVE).chat


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "qwen2.5:7b"
CHAR_BUDGET   = 12_000   # ~3k tokens — sufficient for structured sections
MAX_RETRIES   = 3
NUM_PREDICT   = 6144     # generous; Qwen3 CoT can consume 1-2k tokens before output
OUT_DIR       = "annotated-abstracts"

REQUIRED_SECTIONS = [
    "**Topic**",
    "**Motivation**",
    "**Contribution**",
    "**Detail / Nuance**",
    "**Evidence / Contribution 2**",
    "**Weaker result**",
    "**Narrow impact**",
    "**Broad impact**",
]

# Section extraction patterns — priority order, (label, heading_regex, max_chars)
SECTION_PATTERNS = [
    ("Abstract",     r"(?i)^#+\s*abstract",                            2_000),
    ("Conclusion",   r"(?i)^#+\s*conclusions?",                        2_500),
    ("Introduction", r"(?i)^#+\s*\d*\.?\s*introduction",               2_500),
    ("Results",      r"(?i)^#+\s*\d*\.?\s*(results?|experiments?|evaluation)", 2_500),
    ("Discussion",   r"(?i)^#+\s*\d*\.?\s*discussion",                 1_500),
]

SYSTEM_PROMPT = """\
You are a research-paper analyst. Given selected sections from a research paper,
produce an annotated abstract with EXACTLY these eight bold headers, in this order:

**Topic**
**Motivation**
**Contribution**
**Detail / Nuance**
**Evidence / Contribution 2**
**Weaker result**
**Narrow impact**
**Broad impact**

Rules:
- Each header must appear on its own line, bold, exactly as shown above.
- After each header write 1-2 sentences of plain prose. Be concise — one sentence is fine.
  No bullets, no sub-lists.
- Use only information from the provided text. Do not invent results.
- If a section is not clearly evidenced in the text, write a brief inference
  clearly grounded in what IS present.
- Output NOTHING before **Topic** and NOTHING after the **Broad impact** prose."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:80]


def extract_title(markdown: str) -> str:
    for line in markdown.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:120]
    return "Untitled"


def extract_sections(markdown: str) -> str:
    """
    Extract key sections in priority order within CHAR_BUDGET.
    Falls back to head+tail window if no headings are found.
    """
    lines       = markdown.splitlines()
    heading_re  = re.compile(r"^#+\s")

    # Find the first matching heading for each section type
    section_starts = []
    for label, pattern, max_chars in SECTION_PATTERNS:
        for idx, line in enumerate(lines):
            if re.match(pattern, line.strip()):
                section_starts.append((label, idx, max_chars))
                break

    if not section_starts:
        head = markdown[:6_000]
        tail = markdown[-4_000:] if len(markdown) > 10_000 else ""
        parts = [f"=== Start of paper ===\n{head}"]
        if tail:
            parts.append(f"=== End of paper ===\n{tail}")
        return "\n\n".join(parts)

    # Extract each section up to the next heading or max_chars
    extracted = {}
    for label, start_idx, max_chars in section_starts:
        chunk_lines = []
        for line in lines[start_idx:]:
            if chunk_lines and heading_re.match(line):
                break
            chunk_lines.append(line)
        extracted[label] = "\n".join(chunk_lines)[:max_chars]

    # Assemble in priority order within budget
    priority       = ["Abstract", "Conclusion", "Introduction", "Results", "Discussion"]
    assembled      = []
    remaining      = CHAR_BUDGET
    for label in priority:
        if label not in extracted or remaining <= 0:
            continue
        chunk = extracted[label][:remaining]
        assembled.append(f"=== {label} ===\n{chunk}")
        remaining -= len(chunk)

    if not assembled:
        head = markdown[:6_000]
        tail = markdown[-4_000:] if len(markdown) > 10_000 else ""
        parts = [f"=== Start of paper ===\n{head}"]
        if tail:
            parts.append(f"=== End of paper ===\n{tail}")
        return "\n\n".join(parts)

    return "\n\n".join(assembled)


def is_valid(text: str) -> bool:
    return all(sec in text for sec in REQUIRED_SECTIONS)


# ---------------------------------------------------------------------------
# Core annotation
# ---------------------------------------------------------------------------

def annotate(context: str, model: str, _trace=None) -> str | None:
    """
    Call the model to produce an annotated abstract for the given paper sections.
    Returns the annotation string, or None after MAX_RETRIES failures.
    _trace: optional RunTrace — captures token usage per attempt.
    """
    # /no_think suppresses Qwen3 chain-of-thought, preserving token budget for output
    system = SYSTEM_PROMPT
    if re.search(r"qwen3", model, re.IGNORECASE):
        system += "\n/no_think"

    user_msg = (
        "Here are the key sections from a research paper. "
        "Please produce the annotated abstract.\n\n"
        f"<paper_sections>\n{context}\n</paper_sections>"
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = _chat(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user_msg},
                ],
                options={"temperature": 0.1, "num_predict": NUM_PREDICT},
            )
            if _trace is not None:
                _trace.log_usage(response, stage="annotate")
            result = response["message"]["content"].strip()
            # Strip Qwen3 <think>...</think> blocks if present
            result = re.sub(r"<think>.*?</think>", "", result, flags=re.DOTALL).strip()
            if is_valid(result):
                return result
            print(f"    [retry {attempt}/{MAX_RETRIES}] missing required sections")
        except Exception as e:
            print(f"    [retry {attempt}/{MAX_RETRIES}] error: {e}")
            time.sleep(2)

    return None


def annotate_text(markdown: str, model: str = DEFAULT_MODEL) -> str | None:
    """
    Annotate a single paper given its full markdown text.
    Convenience function for use as a module.
    """
    context = extract_sections(markdown)
    return annotate(context, model)


# ---------------------------------------------------------------------------
# CLI — batch CSV processing
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate annotated abstracts from a CSV of research papers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("csv",                  help="CSV file with pdf_filename and markdown_content columns")
    parser.add_argument("--model",   "-m",      default=DEFAULT_MODEL,
                        help=f"Ollama model (default: {DEFAULT_MODEL})")
    parser.add_argument("--out",     "-o",      default=OUT_DIR,
                        help=f"Output directory (default: {OUT_DIR})")
    parser.add_argument("--reprocess",          action="store_true",
                        help="Redo entries that already exist but have invalid structure")
    args = parser.parse_args()

    df = pd.read_csv(args.csv)
    os.makedirs(args.out, exist_ok=True)
    total = len(df)

    print(f"Model: {args.model}  |  Papers: {total}  |  Budget: {CHAR_BUDGET:,} chars/paper")
    print("-" * 60)

    done = failed = skipped = 0

    for i, (_, row) in enumerate(df.iterrows(), 1):
        pdf_filename     = str(row.get("pdf_filename", f"paper-{i}")).strip()
        markdown_content = str(row.get("markdown_content", "")).strip()

        if not markdown_content:
            print(f"  [{i}/{total}] [skip] {pdf_filename} — no content")
            skipped += 1
            continue

        slug      = slugify(os.path.splitext(pdf_filename)[0])
        out_dir   = os.path.join(args.out, slug)
        out_path  = os.path.join(out_dir, "annotated-abstract.md")

        if os.path.exists(out_path):
            with open(out_path, encoding="utf-8") as f:
                existing = f.read()
            if is_valid(existing) and not args.reprocess:
                print(f"  [{i}/{total}] [skip] {pdf_filename} — already done")
                skipped += 1
                continue
            if not is_valid(existing):
                print(f"  [{i}/{total}] [reprocess] {pdf_filename} — incomplete structure")
            else:
                print(f"  [{i}/{total}] [reprocess] {pdf_filename} — --reprocess flag")

        title   = extract_title(markdown_content)
        context = extract_sections(markdown_content)
        print(f"  [{i}/{total}] {pdf_filename}: {title[:55]} ({len(context):,} chars)")

        trace = RunTrace(
            task=f"/annotate {pdf_filename}",
            producer_model=args.model,
            evaluator_model="n/a",
        )
        trace.data["task_type"] = "annotate"

        annotated = annotate(context, args.model, _trace=trace)

        if annotated is None:
            print(f"  [{i}/{total}] [FAILED] {pdf_filename} — no valid output after {MAX_RETRIES} tries")
            failed += 1
            trace.finish("FAIL")
            continue

        os.makedirs(out_dir, exist_ok=True)
        full_output = (
            f"# {title}\n\n"
            f"**Source:** {pdf_filename}  \n"
            f"**Model:** {args.model}  \n"
            "\n---\n\n"
            "## Annotated Abstract\n\n"
            f"{annotated}\n"
        )
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(full_output)

        trace.data["output_path"]  = os.path.abspath(out_path)
        trace.data["output_bytes"] = len(full_output.encode())
        trace.data["output_lines"] = full_output.count("\n") + 1
        trace.finish("PASS")

        print(f"  [{i}/{total}] [done] → {out_path}")
        done += 1

    print(f"\nDone: {done}  Failed: {failed}  Skipped: {skipped}")


if __name__ == "__main__":
    main()

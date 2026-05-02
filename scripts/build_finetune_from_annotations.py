"""
build_finetune_from_annotations.py

Converts annotated paper CSVs (produced by run_annotations.py) into a
fine-tuning JSONL dataset compatible with finetune_annotate.py.

Sources (merged, deduplicated by arxiv_id):
  1. annotated-abstracts.csv     — human-curated gold annotations (121 rows)
  2. arxiv_*_annotated.csv       — agent-produced annotations from run_annotations.py
  3. Abstracts sourced from the corresponding arxiv_*.md markdown files

Output:
  finetune_dataset_v2.jsonl      — merged, deduped, ready for SFTTrainer

Usage:
    python build_finetune_from_annotations.py
    python build_finetune_from_annotations.py --out finetune_dataset_v2.jsonl --min-sections 6
"""

import re
import csv
import json
import argparse
from pathlib import Path

HERE = Path(__file__).parent.parent  # repo root

# ── Column name normalisation ────────────────────────────────────────────────
# Both CSVs use the same 8 Nanda section column names.
SECTION_COLS = [
    "topic",
    "motivation",
    "contribution",
    "detail_nuance",
    "evidence_contribution_2",
    "weaker_result",
    "narrow_impact",
    "broad_impact",
]

SECTION_HEADERS = [
    "**Topic**",
    "**Motivation**",
    "**Contribution**",
    "**Detail / Nuance**",
    "**Evidence / Contribution 2**",
    "**Weaker result**",
    "**Narrow impact**",
    "**Broad impact**",
]

SYSTEM_PROMPT = """\
You are a research-paper analyst. Given a paper abstract, produce an annotated abstract \
using the Nanda framework with EXACTLY these eight bold section headers, in this order:

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
- After each header write 1-2 sentences of plain prose synthesized from the paper. Be concise.
- Use only information from the provided text. Do not invent results.
- If a section is not clearly evidenced, write a brief inference grounded in what IS present.
- Output NOTHING before **Topic** and NOTHING after the **Broad impact** prose.

Section definitions:
  Topic                    — what subject area / problem this paper addresses
  Motivation               — why this problem matters; the gap or need being addressed
  Contribution             — the main new artifact, method, or claim ('We introduce/propose X')
  Detail / Nuance          — key technical specifics of how the contribution works
  Evidence / Contribution 2 — benchmark results or empirical evidence; secondary findings
  Weaker result            — limitations, conditions where the approach underperforms, or open problems
  Narrow impact            — specific, bounded applications or immediate takeaways
  Broad impact             — wider implications for the field or community (e.g. open-source release)\
"""


# ── Markdown parser ──────────────────────────────────────────────────────────

def parse_markdown_papers(md_path: Path) -> dict[str, dict]:
    """
    Parse an arxiv markdown file into {arxiv_id: {title, abstract}}.
    Handles both 2402.11651v2 and 2402-11651v2 ID formats.
    """
    text  = md_path.read_text(encoding="utf-8", errors="replace")
    # Split on H2 headings (paper titles)
    chunks = re.split(r"\n(?=## )", text)

    papers = {}
    for chunk in chunks:
        if not chunk.startswith("## "):
            continue
        lines = chunk.strip().splitlines()
        title = lines[0][3:].strip()  # strip "## "

        # Extract arxiv_id from the Abstract link
        id_m = re.search(r"\[Abstract\]\(https://arxiv\.org/abs/([^\)]+)\)", chunk)
        if not id_m:
            continue
        raw_id   = id_m.group(1)                       # e.g. 2402.11651v2
        arxiv_id = raw_id.replace(".", "-", 1)         # normalise to 2402-11651v2
        # also keep dot form for lookup flexibility
        dot_id   = raw_id

        # Extract abstract — text after "**Abstract:**" until next "**" or end
        abs_m = re.search(r"\*\*Abstract:\*\*\s*\n(.*?)(?=\n---|\Z)", chunk, re.DOTALL)
        abstract = re.sub(r"\s+", " ", abs_m.group(1)).strip() if abs_m else ""
        if not abstract:
            continue

        entry = {"title": title, "abstract": abstract}
        papers[arxiv_id] = entry
        papers[dot_id]   = entry   # register both forms

    print(f"  [md] {md_path.name}: {len(papers)//2} papers parsed")
    return papers


# ── CSV loaders ───────────────────────────────────────────────────────────────

def load_annotated_csv(csv_path: Path) -> list[dict]:
    """Load an annotated CSV and return list of row dicts."""
    rows = []
    with open(csv_path, encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    print(f"  [csv] {csv_path.name}: {len(rows)} rows")
    return rows


def normalise_id(raw: str) -> str:
    """Normalise arxiv ID to dot form (2402.11651v2)."""
    # Strip version suffix for matching, keep it otherwise
    raw = raw.strip()
    # Convert dash form 2402-11651v2 → 2402.11651v2
    m = re.match(r"^(\d{4})-(\d+)(v\d+)?$", raw)
    if m:
        return f"{m.group(1)}.{m.group(2)}{m.group(3) or ''}"
    return raw


def format_annotation(row: dict, title: str) -> str:
    """Reconstruct the 8-section annotation string from CSV columns."""
    parts = [f"# Annotated Abstract: {title}\n"]
    for header, col in zip(SECTION_HEADERS, SECTION_COLS):
        text = (row.get(col) or "").strip()
        if text:
            parts.append(f"{header}\n{text}")
    return "\n\n".join(parts)


def row_is_valid(row: dict, min_sections: int) -> bool:
    """Return True if at least min_sections Nanda columns are non-empty."""
    filled = sum(1 for c in SECTION_COLS if (row.get(c) or "").strip())
    return filled >= min_sections


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out",          default="data/finetune_dataset_v2.jsonl")
    parser.add_argument("--min-sections", type=int, default=6,
                        help="Minimum filled Nanda sections to include a row (default 6)")
    args = parser.parse_args()

    out_path = HERE / args.out

    # 1. Parse all arxiv markdown files for abstracts
    md_files = sorted(HERE.glob("arxiv_*.md"))
    print(f"\nParsing {len(md_files)} markdown file(s)...")
    paper_meta: dict[str, dict] = {}
    for md in md_files:
        paper_meta.update(parse_markdown_papers(md))

    seen_ids:  set[str] = set()
    examples:  list[dict] = []
    skipped_no_abstract = 0
    skipped_invalid     = 0

    # 2a. Seed with existing finetune_dataset.jsonl (already has abstracts fetched)
    existing_jsonl = HERE / "data" / "finetune_dataset.jsonl"
    if existing_jsonl.exists():
        print(f"\nSeeding from existing {existing_jsonl.name}...")
        for line in existing_jsonl.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            ex = json.loads(line)
            aid = normalise_id(ex.get("arxiv_id", ""))
            if aid and aid not in seen_ids:
                seen_ids.add(aid)
                seen_ids.add(aid.replace(".", "-", 1))
                examples.append(ex)
        print(f"  seeded {len(examples)} examples from existing dataset")

    # 2b. Load all annotation CSVs (prefer *_curated.csv over *_annotated.csv if available)
    # curator.py writes *_curated.csv as a filtered subset — use it when present so
    # the training dataset only includes persona-approved papers.
    annotated = sorted(HERE.glob("arxiv_*_annotated.csv"))
    csv_files = []
    for ann in annotated:
        curated = ann.with_name(ann.stem.replace("_annotated", "_curated") + ".csv")
        csv_files.append(curated if curated.exists() else ann)
    csv_files = [f for f in csv_files if f.exists()]
    using_curated = sum(1 for f in csv_files if "_curated" in f.name)
    print(f"\nLoading {len(csv_files)} annotation CSV(s)  ({using_curated} curated, {len(csv_files)-using_curated} raw)...")

    for csv_path in csv_files:
        rows = load_annotated_csv(csv_path)
        for row in rows:
            # Normalise the arxiv ID
            raw_id   = row.get("filename") or row.get("arxiv_id") or ""
            arxiv_id = normalise_id(raw_id)
            dash_id  = arxiv_id.replace(".", "-", 1)

            # Dedup
            if arxiv_id in seen_ids or dash_id in seen_ids:
                continue

            # Validate annotation quality
            if not row_is_valid(row, args.min_sections):
                skipped_invalid += 1
                continue

            # Look up abstract
            meta = paper_meta.get(arxiv_id) or paper_meta.get(dash_id)
            if not meta:
                skipped_no_abstract += 1
                continue

            seen_ids.add(arxiv_id)
            seen_ids.add(dash_id)

            assistant = format_annotation(row, meta["title"])
            examples.append({
                "system":    SYSTEM_PROMPT,
                "user":      f"Paper abstract:\n\n{meta['abstract']}",
                "assistant": assistant,
                "arxiv_id":  arxiv_id,
            })

    # 3. Write JSONL
    print(f"\nWriting {len(examples)} examples to {out_path.name}...")
    print(f"  Skipped — no abstract match : {skipped_no_abstract}")
    print(f"  Skipped — too few sections  : {skipped_invalid}")

    with open(out_path, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    print(f"\nDone. {len(examples)} training examples saved to {out_path}")
    print(f"\nTo train:")
    print(f"  python finetune_annotate.py --skip-fetch --dataset {out_path.name}")


if __name__ == "__main__":
    main()

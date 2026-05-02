"""
run_annotations.py — Parse arxiv markdown files and produce Nanda annotation CSVs.

Usage:
    python run_annotations.py arxiv_agentic_papers.md
    python run_annotations.py arxiv_agentic_papers.md arxiv_agentic_harness_engineering_papers.md
    python run_annotations.py arxiv_agentic_papers.md --model pi-qwen-32b --dry-run
    python run_annotations.py arxiv_agentic_papers.md --skip-existing
"""

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import argparse
import csv
import re
import time
from pathlib import Path

HERE = Path(__file__).parent

# CSV columns matching annotated-abstracts.csv
ANNOTATION_COLS = [
    "filename",
    "topic",
    "motivation",
    "contribution",
    "detail_nuance",
    "evidence_contribution_2",
    "weaker_result",
    "narrow_impact",
    "broad_impact",
]

# Maps bold header text -> CSV column name
_SECTION_MAP = {
    "**Topic**":                    "topic",
    "**Motivation**":               "motivation",
    "**Contribution**":             "contribution",
    "**Detail / Nuance**":          "detail_nuance",
    "**Evidence / Contribution 2**": "evidence_contribution_2",
    "**Weaker result**":            "weaker_result",
    "**Narrow impact**":            "narrow_impact",
    "**Broad impact**":             "broad_impact",
}

_SECTION_HEADERS = list(_SECTION_MAP.keys())


# ---------------------------------------------------------------------------
# Step 1 — parse markdown
# ---------------------------------------------------------------------------

def parse_arxiv_md(path: Path) -> list[dict]:
    """
    Parse an arxiv markdown file into a list of paper dicts:
      {arxiv_id, title, abstract, published, abstract_url, pdf_url}

    Expected block structure (separated by ---):
      ## Paper Title
      **Authors:** ...
      **Published:** 2024-02-18T17:10:07Z
      **Categories:** ...
      **Links:** [Abstract](https://arxiv.org/abs/2402.11651v2) | [PDF](url)
      **Abstract:**
      Full abstract text here.
    """
    text   = path.read_text(encoding="utf-8")
    blocks = re.split(r"\n---\n", text)
    papers = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        # Title — first ## heading
        title_m = re.search(r"^##\s+(.+)$", block, re.MULTILINE)
        if not title_m:
            continue
        title = title_m.group(1).strip()

        # Published date
        pub_m = re.search(r"\*\*Published:\*\*\s*(\S+)", block)
        published = pub_m.group(1) if pub_m else ""

        # Abstract and PDF URLs
        abs_url_m = re.search(r"\[Abstract\]\((https://arxiv\.org/abs/([^\)]+))\)", block)
        pdf_url_m = re.search(r"\[PDF\]\((https://arxiv\.org/pdf/([^\)]+))\)", block)
        if not abs_url_m:
            continue

        abstract_url = abs_url_m.group(1)
        arxiv_id     = abs_url_m.group(2)
        pdf_url      = pdf_url_m.group(1) if pdf_url_m else abstract_url.replace("/abs/", "/pdf/")

        # Abstract text — everything after **Abstract:**
        abs_m = re.search(r"\*\*Abstract:\*\*\s*\n(.*)", block, re.DOTALL)
        if not abs_m:
            continue
        abstract = abs_m.group(1).strip()

        papers.append({
            "arxiv_id":     arxiv_id,
            "title":        title,
            "abstract":     abstract,
            "published":    published,
            "abstract_url": abstract_url,
            "pdf_url":      pdf_url,
        })

    return papers


# ---------------------------------------------------------------------------
# Step 2 — parse annotation output into CSV columns
# ---------------------------------------------------------------------------

def parse_annotation(text: str) -> dict | None:
    """
    Parse 8-section generative annotation into a column dict.
    Returns None if fewer than 6 sections are found.
    """
    # Split on bold section headers
    parts   = re.split(r"(\*\*[^*]+\*\*)", text)
    result  = {}
    current = None

    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part in _SECTION_MAP:
            current = _SECTION_MAP[part]
            result[current] = ""
        elif current is not None:
            result[current] = part.strip()

    if len(result) < 6:
        return None

    # Fill any missing columns with empty string
    for col in ANNOTATION_COLS[1:]:
        result.setdefault(col, "")

    return result


# ---------------------------------------------------------------------------
# Step 3 — annotate papers and write CSV
# ---------------------------------------------------------------------------

def annotate_papers(
    papers:       list[dict],
    output_csv:   Path,
    model:        str,
    skip_existing: bool,
    dry_run:      bool,
    sleep_s:      float,
):
    from skills import run_annotate_standalone

    from harness.logger import RunTrace

    # Load existing arxiv_ids if skip_existing
    existing = set()
    if skip_existing and output_csv.exists():
        import csv as _csv
        with open(output_csv, newline="", encoding="utf-8") as f:
            for row in _csv.DictReader(f):
                existing.add(row.get("filename", ""))
        print(f"  Skipping {len(existing)} already-annotated papers")

    # Open CSV for append (or create with header)
    write_header = not output_csv.exists()
    out_f = open(output_csv, "a", newline="", encoding="utf-8") if not dry_run else None
    writer = csv.DictWriter(out_f, fieldnames=ANNOTATION_COLS) if out_f else None
    if write_header and writer:
        writer.writeheader()

    annotated = 0
    skipped   = 0
    failed    = 0

    try:
        for paper in papers:
            arxiv_id = paper["arxiv_id"]

            if arxiv_id in existing:
                skipped += 1
                continue

            print(f"\n[annotate] {arxiv_id}: {paper['title'][:60]}")

            if dry_run:
                print(f"  [dry-run] would annotate with {model}")
                continue

            # Build context: title + abstract (same as what the model sees)
            context = f"# {paper['title']}\n\n{paper['abstract']}"

            task_str = f"/annotate {paper.get('abstract_url', arxiv_id)}"
            trace = RunTrace(task=task_str, producer_model=model, evaluator_model="n/a")
            trace.data["task_type"] = "annotate"

            annotation_text = run_annotate_standalone(
                paper_context=context,
                producer_model=model,
                max_retries=3,
                _trace=trace,
            )

            row = parse_annotation(annotation_text)
            if row is None:
                print(f"  [warn] {arxiv_id}: annotation invalid, skipping")
                failed += 1
                trace.finish("FAIL")
                continue

            row["filename"] = arxiv_id
            writer.writerow(row)
            out_f.flush()
            annotated += 1
            trace.data["output_bytes"] = len(annotation_text.encode())
            trace.data["output_lines"] = annotation_text.count("\n") + 1
            trace.finish("PASS")

            if sleep_s > 0:
                time.sleep(sleep_s)

    finally:
        if out_f:
            out_f.close()

    print(f"\nDone: {annotated} annotated, {skipped} skipped, {failed} failed -> {output_csv}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs",       nargs="+",           help="Markdown file(s) to process")
    parser.add_argument("--model",      default="pi-qwen-32b", help="Ollama model for annotation")
    parser.add_argument("--output-dir", default=str(HERE),   help="Directory for output CSVs")
    parser.add_argument("--skip-existing", action="store_true", help="Skip papers already in output CSV")
    parser.add_argument("--dry-run",    action="store_true",  help="Parse only, don't annotate")
    parser.add_argument("--sleep",      type=float, default=0.5, help="Seconds between annotations")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)

    for md_path_str in args.inputs:
        md_path = Path(md_path_str)
        if not md_path.exists():
            print(f"[error] file not found: {md_path}")
            continue

        papers = parse_arxiv_md(md_path)
        print(f"\nParsed {len(papers)} papers from {md_path.name}")

        if not papers:
            continue

        output_csv = output_dir / (md_path.stem + "_annotated.csv")

        annotate_papers(
            papers=papers,
            output_csv=output_csv,
            model=args.model,
            skip_existing=args.skip_existing,
            dry_run=args.dry_run,
            sleep_s=args.sleep,
        )


if __name__ == "__main__":
    main()

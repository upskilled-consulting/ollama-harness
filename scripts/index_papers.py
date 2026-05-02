"""
index_papers.py — Import annotated paper corpus into the agent memory store.

Reads all *_annotated.csv files (gold + agent-produced) and indexes each paper
as a memory observation so that get_context() retrieves relevant prior papers
before web search fires.

Each paper is stored with:
  task      = "paper: {arxiv_id}"
  task_type = "paper"
  title     = paper title (from arxiv MD files or arxiv_id fallback)
  narrative = Topic + Motivation + Contribution (first 3 Nanda sections)
  facts     = [Contribution, Evidence/Contribution 2, Broad impact]

Idempotent — re-running skips already-indexed papers.

Usage:
    python index_papers.py                # index all annotation CSVs
    python index_papers.py --dry-run      # count only, no writes
    python index_papers.py --stats        # show current paper count in memory
"""

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import argparse
import csv
import re
from pathlib import Path

HERE = Path(__file__).parent.parent  # repo root

ANNOTATION_CSVS = [
    HERE / "data" / "annotated-abstracts.csv",
    *(HERE / "data").glob("arxiv_*_annotated.csv"),
]

ARXIV_MD_FILES = list(HERE.glob("arxiv_*.md"))

# Nanda column → role mapping
_NARRATIVE_COLS = ["topic", "motivation", "contribution"]
_FACT_COLS = [
    ("contribution",          "Contribution"),
    ("evidence_contribution_2", "Evidence"),
    ("broad_impact",          "Broad impact"),
]


# ---------------------------------------------------------------------------
# Step 1 — build arxiv_id → title map from markdown files
# ---------------------------------------------------------------------------

def _parse_titles_from_md(md_path: Path) -> dict[str, str]:
    """Return {arxiv_id: title} from an arxiv markdown file."""
    text   = md_path.read_text(encoding="utf-8")
    blocks = re.split(r"\n---\n", text)
    result = {}
    for block in blocks:
        title_m   = re.search(r"^##\s+(.+)$", block, re.MULTILINE)
        abs_url_m = re.search(r"\[Abstract\]\(https://arxiv\.org/abs/([^\)]+)\)", block)
        if title_m and abs_url_m:
            result[abs_url_m.group(1)] = title_m.group(1).strip()
    return result


def build_title_map() -> dict[str, str]:
    titles = {}
    for md in ARXIV_MD_FILES:
        titles.update(_parse_titles_from_md(md))
    return titles


# ---------------------------------------------------------------------------
# Step 2 — load + deduplicate annotation rows across all CSVs
# ---------------------------------------------------------------------------

def load_annotations() -> dict[str, dict]:
    """Return {arxiv_id: row_dict}, preferring gold CSV rows over agent rows."""
    papers: dict[str, dict] = {}

    # Process gold CSV first so agent rows don't overwrite it
    ordered = []
    gold = HERE / "data" / "annotated-abstracts.csv"
    if gold.exists():
        ordered.append(gold)
    for p in ANNOTATION_CSVS:
        if p != gold and p.exists():
            ordered.append(p)

    for csv_path in ordered:
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                arxiv_id = row.get("filename", "").strip()
                if not arxiv_id or arxiv_id in papers:
                    continue
                papers[arxiv_id] = row

    return papers


# ---------------------------------------------------------------------------
# Step 3 — build observation fields from annotation row
# ---------------------------------------------------------------------------

def _truncate(text: str, n: int) -> str:
    text = (text or "").strip()
    return text[:n] + "…" if len(text) > n else text


def build_observation(arxiv_id: str, row: dict, title_map: dict) -> dict:
    title = title_map.get(arxiv_id) or f"arxiv:{arxiv_id}"

    # Narrative: Topic → Motivation → Contribution (capped at 600 chars total)
    parts = []
    for col in _NARRATIVE_COLS:
        val = (row.get(col) or "").strip()
        if val:
            parts.append(val)
    narrative = " ".join(parts)[:600]

    # Facts: labelled key claims
    facts = []
    for col, label in _FACT_COLS:
        val = (row.get(col) or "").strip()
        if val:
            facts.append(f"{label}: {_truncate(val, 180)}")

    return {
        "task":      f"paper: {arxiv_id}",
        "task_type": "paper",
        "title":     _truncate(title, 80),
        "narrative": narrative,
        "facts":     facts,
        "timestamp": "2026-01-01T00:00:00+00:00",  # fixed past date so paper obs sort before run obs
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Count only, no writes")
    parser.add_argument("--stats",   action="store_true", help="Show paper count in memory and exit")
    args = parser.parse_args()

    from harness.memory import MemoryStore
    store = MemoryStore()

    if args.stats:
        with store._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            papers = conn.execute(
                "SELECT COUNT(*) FROM observations WHERE task_type = 'paper'"
            ).fetchone()[0]
            runs = total - papers
        print(f"Memory: {total} total observations  ({papers} papers, {runs} runs)")
        return

    print("Building title map from arxiv markdown files...")
    title_map = build_title_map()
    print(f"  {len(title_map)} titles found")

    print("Loading annotation CSVs...")
    papers = load_annotations()
    print(f"  {len(papers)} unique papers across {len([p for p in ANNOTATION_CSVS if p.exists()])} CSV(s)")

    if args.dry_run:
        print(f"\n[dry-run] would index up to {len(papers)} papers — no writes performed")
        return

    indexed = 0
    skipped = 0

    for arxiv_id, row in papers.items():
        obs = build_observation(arxiv_id, row, title_map)
        rowid = store.store_direct(**obs)
        if rowid == -1:
            skipped += 1
        else:
            indexed += 1
            if indexed % 50 == 0:
                print(f"  indexed {indexed}...")

    print(f"\nDone: {indexed} papers indexed, {skipped} already present")

    # Final stats
    with store._connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        paper_count = conn.execute(
            "SELECT COUNT(*) FROM observations WHERE task_type = 'paper'"
        ).fetchone()[0]
    print(f"Memory now contains {total} observations ({paper_count} papers)")


if __name__ == "__main__":
    main()

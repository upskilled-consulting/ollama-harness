"""
harvest_lit_reviews.py — retroactively store existing lit-review .md files
into the memory system (SQLite + ChromaDB).

Usage:
    python harvest_lit_reviews.py                    # all files in data/lit_reviews/
    python harvest_lit_reviews.py path/to/file.md   # specific file(s)
    python harvest_lit_reviews.py --dry-run          # show what would be harvested
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.config import LIT_REVIEWS_DIR
from harness.memory import MemoryStore


def harvest(path: Path, memory: MemoryStore, dry_run: bool = False) -> bool:
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        print(f"  [skip] {path.name} — empty")
        return False

    # Extract query from first heading or filename
    first_line = content.splitlines()[0].lstrip("# ").strip()
    task = f"/lit-review {first_line}" if first_line else f"/lit-review {path.stem}"

    size_kb = len(content) // 1024
    print(f"  {path.name}  ({size_kb}KB)  ->  task: {task[:70]}")

    if dry_run:
        return True

    try:
        obs = memory.compress_and_store(
            task=task,
            task_type="lit-review",
            tool_calls=[],
            output_content=content,
            output_lines=content.count("\n"),
            output_bytes=len(content.encode()),
            output_path=str(path),
            wiggum_scores=[],
            final="PASS",
            wiggum_issues=[],
        )
        print(f"    stored: {obs['title']!r}")
        return True
    except Exception as e:
        print(f"    [error] {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Harvest lit-review .md files into memory")
    parser.add_argument("files", nargs="*", help="Specific .md files to harvest (default: all in data/lit_reviews/)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be harvested without writing")
    args = parser.parse_args()

    if args.files:
        paths = [Path(f) for f in args.files]
    else:
        paths = sorted(LIT_REVIEWS_DIR.glob("*.md"))

    if not paths:
        print(f"No .md files found in {LIT_REVIEWS_DIR}")
        sys.exit(0)

    print(f"{'[dry-run] ' if args.dry_run else ''}Harvesting {len(paths)} file(s) into memory...\n")
    memory = MemoryStore()

    ok = fail = skip = 0
    for p in paths:
        if not p.exists():
            print(f"  [skip] {p} — not found")
            skip += 1
            continue
        if harvest(p, memory, dry_run=args.dry_run):
            ok += 1
        else:
            fail += 1

    print(f"\nDone: {ok} stored, {fail} failed, {skip} skipped")


if __name__ == "__main__":
    main()

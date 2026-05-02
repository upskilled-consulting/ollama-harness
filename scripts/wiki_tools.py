"""
wiki_tools.py — Python-deterministic wiki maintenance for harness-engineering.

Usage:
    python wiki_tools.py index          # rebuild wiki/index.md from page frontmatter
    python wiki_tools.py log "msg"      # append timestamped entry to wiki/log.md
    python wiki_tools.py lint           # check for orphans, missing frontmatter, broken links
"""

import argparse
import os
import re
import sys
from datetime import date
from pathlib import Path

WIKI_DIR = Path(__file__).parent / "wiki"
INDEX_PATH = WIKI_DIR / "index.md"
LOG_PATH = WIKI_DIR / "log.md"


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

def parse_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter fields as strings. Returns {} if none."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()
    return fm


def get_wiki_pages() -> list[Path]:
    """Return all .md files in wiki/ except index.md and log.md."""
    skip = {INDEX_PATH.name, LOG_PATH.name}
    return sorted(p for p in WIKI_DIR.glob("*.md") if p.name not in skip)


# ---------------------------------------------------------------------------
# Index rebuild
# ---------------------------------------------------------------------------

INDEX_HEADER = """# Wiki Index

Machine-maintained. Run `python wiki_tools.py index` to rebuild.

| Page | Summary | Updated | Tags |
|------|---------|---------|------|
"""


def cmd_index():
    pages = get_wiki_pages()
    rows = []
    for p in pages:
        text = p.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        title = fm.get("title", p.stem)
        updated = fm.get("updated", "—")
        tags = fm.get("tags", "").strip("[]")
        # First non-frontmatter, non-header line as summary
        body_lines = re.sub(r"^---.*?---\s*\n", "", text, flags=re.DOTALL).splitlines()
        summary = ""
        for line in body_lines:
            line = line.strip()
            if line and not line.startswith("#"):
                summary = line[:100]
                break
        rows.append(f"| [{title}]({p.name}) | {summary} | {updated} | {tags} |")

    content = INDEX_HEADER + "\n".join(rows) + "\n"
    INDEX_PATH.write_text(content, encoding="utf-8")
    print(f"[index] wrote {len(rows)} entries to {INDEX_PATH}")


# ---------------------------------------------------------------------------
# Log append
# ---------------------------------------------------------------------------

def cmd_log(message: str):
    today = date.today().isoformat()
    entry = f"\n## [{today}] {message}\n"
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(entry)
    print(f"[log] appended: [{today}] {message}")


# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------

def cmd_lint():
    pages = get_wiki_pages()
    issues = []

    page_names = {p.name for p in pages}

    for p in pages:
        text = p.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)

        # Missing frontmatter fields
        for field in ("title", "updated", "tags"):
            if field not in fm:
                issues.append(f"[missing-{field}] {p.name}")

        # Find all internal wiki links [[page]] or [text](page.md)
        links = re.findall(r"\[.*?\]\((\S+?\.md)\)", text)
        for link in links:
            if link not in page_names and link not in {INDEX_PATH.name, LOG_PATH.name}:
                issues.append(f"[broken-link] {p.name} -> {link}")

    # Orphan check: pages with no inbound links from other pages
    page_texts = {p: p.read_text(encoding="utf-8") for p in pages}
    for p in pages:
        linked_from = any(p.name in text for other, text in page_texts.items() if other != p)
        if not linked_from:
            issues.append(f"[orphan] {p.name} — no inbound links from other wiki pages")

    if issues:
        print(f"[lint] {len(issues)} issue(s):")
        for issue in issues:
            print(f"  {issue}")
    else:
        print("[lint] wiki is clean")

    return issues


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Wiki maintenance tools")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("index", help="Rebuild wiki/index.md")

    log_p = sub.add_parser("log", help="Append entry to wiki/log.md")
    log_p.add_argument("message", help='Log message, e.g. "ingest | experiment-05.md"')

    sub.add_parser("lint", help="Check wiki health")

    args = parser.parse_args()

    if args.cmd == "index":
        cmd_index()
    elif args.cmd == "log":
        cmd_log(args.message)
    elif args.cmd == "lint":
        issues = cmd_lint()
        sys.exit(1 if issues else 0)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

"""
arxiv_fetch.py — Fetch papers from the arXiv API and save to CSV.

Produces the same column schema as arxiv_agentic_papers.csv so output
feeds directly into run_annotations.py and annotate_abstracts.py.

Columns: title, authors, published, updated, summary, arxiv_url, pdf_url,
         arxiv_id, categories

Usage:
    python arxiv_fetch.py "agentic LLM harness"
    python arxiv_fetch.py "RAG retrieval augmented" --max 500 --out rag_papers.csv
    python arxiv_fetch.py "prompt injection" --after 2024-01-01
    python arxiv_fetch.py "context window" --after 2024-06-01 --before 2025-01-01
    python arxiv_fetch.py "multi-agent" --append existing.csv
    python arxiv_fetch.py "transformer attention" --stats existing.csv

Options:
    --max N          Total papers to fetch (default: 300)
    --batch N        Papers per API request, max 300 (default: 100)
    --after DATE     Only keep papers published on or after DATE (YYYY-MM-DD)
    --before DATE    Only keep papers published before DATE (YYYY-MM-DD)
    --out FILE       Output CSV path (default: derived from query slug)
    --append FILE    Append to an existing CSV, skipping already-present arxiv_ids
    --stats FILE     Print stats about an existing CSV and exit
    --field FIELD    arXiv search field: all, ti (title), abs, cat (default: all)
    --sort           Sort by submittedDate descending (newest first)
    --sleep N        Seconds between batches (default: 3 — be polite to arXiv)
"""

import argparse
import csv
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

try:
    import feedparser
except ImportError:
    print("[arxiv_fetch] feedparser not installed: pip install feedparser")
    sys.exit(1)

BASE_URL     = "http://export.arxiv.org/api/query?"
DEFAULT_MAX  = 300
DEFAULT_BATCH = 100
DEFAULT_SLEEP = 3.0

COLUMNS = ["title", "authors", "published", "updated", "summary",
           "arxiv_url", "pdf_url", "arxiv_id", "categories"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40]


def _parse_date(s: str) -> datetime:
    """Parse YYYY-MM-DD into a UTC-aware datetime."""
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _entry_date(entry) -> datetime | None:
    """Parse feedparser entry's published field to UTC datetime."""
    published = getattr(entry, "published", None)
    if not published:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(published, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
    return None


def _entry_to_row(entry) -> dict:
    authors    = ", ".join(getattr(a, "name", "") for a in getattr(entry, "authors", []))
    pdf_url    = None
    for link in getattr(entry, "links", []):
        if getattr(link, "type", "") == "application/pdf":
            pdf_url = link.href
    categories = ", ".join(
        getattr(t, "term", "") for t in getattr(entry, "tags", [])
    )
    arxiv_id = entry.id.split("/")[-1] if hasattr(entry, "id") else ""
    # Normalise pdf_url — feedparser sometimes gives abstract link
    if not pdf_url:
        pdf_url = entry.link.replace("/abs/", "/pdf/") if hasattr(entry, "link") else ""

    return {
        "title":      getattr(entry, "title", "").strip().replace("\n", " "),
        "authors":    authors,
        "published":  getattr(entry, "published", ""),
        "updated":    getattr(entry, "updated", ""),
        "summary":    getattr(entry, "summary", "").strip().replace("\n", " "),
        "arxiv_url":  getattr(entry, "link", ""),
        "pdf_url":    pdf_url or "",
        "arxiv_id":   arxiv_id,
        "categories": categories,
    }


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch(
    query:     str,
    max_results: int   = DEFAULT_MAX,
    batch_size:  int   = DEFAULT_BATCH,
    field:       str   = "all",
    sort_by:     bool  = False,
    after:       datetime | None = None,
    before:      datetime | None = None,
    sleep_s:     float = DEFAULT_SLEEP,
    existing_ids: set[str] | None = None,
) -> list[dict]:
    """
    Fetch papers from arXiv and return list of row dicts.
    Applies date filters and deduplication against existing_ids.
    """
    encoded = urllib.parse.quote(query)
    search_field = field if field in ("all", "ti", "abs", "cat", "au") else "all"

    sort_clause = "&sortBy=submittedDate&sortOrder=descending" if sort_by else ""

    rows = []
    seen_ids: set[str] = set(existing_ids or [])
    skipped_date = 0
    skipped_dup  = 0

    for start in range(0, max_results, batch_size):
        this_batch = min(batch_size, max_results - start)
        url = (
            f"{BASE_URL}"
            f"search_query={search_field}:{encoded}"
            f"&start={start}"
            f"&max_results={this_batch}"
            f"{sort_clause}"
        )
        print(f"[arxiv] fetching {start}–{start + this_batch}...  ", end="", flush=True)

        feed = feedparser.parse(url)
        entries = feed.entries

        if not entries:
            print("no results.")
            break

        batch_added = 0
        for entry in entries:
            row = _entry_to_row(entry)
            aid = row["arxiv_id"]

            # Dedup
            if aid in seen_ids:
                skipped_dup += 1
                continue

            # Date filter
            if after or before:
                dt = _entry_date(entry)
                if dt:
                    if after and dt < after:
                        skipped_date += 1
                        continue
                    if before and dt >= before:
                        skipped_date += 1
                        continue

            seen_ids.add(aid)
            rows.append(row)
            batch_added += 1

        print(f"+{batch_added} (total {len(rows)})")

        if len(entries) < this_batch:
            break   # arXiv returned fewer than requested — no more results

        if start + this_batch < max_results:
            time.sleep(sleep_s)

    if skipped_dup:
        print(f"[arxiv] skipped {skipped_dup} duplicates")
    if skipped_date:
        print(f"[arxiv] skipped {skipped_date} outside date range")

    return rows


# ---------------------------------------------------------------------------
# CSV I/O
# ---------------------------------------------------------------------------

def load_existing(path: Path) -> tuple[list[dict], set[str]]:
    """Load existing CSV, return (rows, set of arxiv_ids)."""
    rows = []
    ids  = set()
    if not path.exists():
        return rows, ids
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
            ids.add(row.get("arxiv_id", ""))
    return rows, ids


def save_csv(rows: list[dict], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[arxiv] wrote {len(rows)} rows -> {path}")


def print_stats(path: Path) -> None:
    rows, _ = load_existing(path)
    if not rows:
        print(f"[arxiv] {path} is empty or missing.")
        return

    dates = [r["published"][:10] for r in rows if r.get("published")]
    dates.sort()
    cats: dict[str, int] = {}
    for r in rows:
        for c in r.get("categories", "").split(", "):
            c = c.strip()
            if c:
                cats[c] = cats.get(c, 0) + 1
    top_cats = sorted(cats.items(), key=lambda x: -x[1])[:10]

    print(f"\n{path}")
    print(f"  Papers:     {len(rows)}")
    print(f"  Date range: {dates[0] if dates else '?'} to {dates[-1] if dates else '?'}")
    print(f"  Top categories:")
    for cat, n in top_cats:
        print(f"    {cat:<20} {n}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Fetch arXiv papers to CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("query",          nargs="?",   help="Search query (omit with --stats)")
    ap.add_argument("--max",          type=int,    default=DEFAULT_MAX,   help=f"Max papers (default {DEFAULT_MAX})")
    ap.add_argument("--batch",        type=int,    default=DEFAULT_BATCH, help=f"Batch size (default {DEFAULT_BATCH})")
    ap.add_argument("--after",        default=None, help="Only papers published on/after YYYY-MM-DD")
    ap.add_argument("--before",       default=None, help="Only papers published before YYYY-MM-DD")
    ap.add_argument("--out",          default=None, help="Output CSV path")
    ap.add_argument("--append",       default=None, help="Append to existing CSV (skip duplicates)")
    ap.add_argument("--stats",        default=None, help="Print stats for a CSV and exit")
    ap.add_argument("--field",        default="all", choices=["all", "ti", "abs", "cat", "au"],
                    help="arXiv search field (default: all)")
    ap.add_argument("--sort",         action="store_true", help="Sort by submittedDate descending")
    ap.add_argument("--sleep",        type=float, default=DEFAULT_SLEEP, help=f"Seconds between batches (default {DEFAULT_SLEEP})")
    args = ap.parse_args()

    # Stats-only mode
    if args.stats:
        print_stats(Path(args.stats))
        return

    if not args.query:
        ap.print_help()
        sys.exit(1)

    # Date parsing
    after  = _parse_date(args.after)  if args.after  else None
    before = _parse_date(args.before) if args.before else None

    # Determine output path
    if args.append:
        out_path = Path(args.append)
        existing_rows, existing_ids = load_existing(out_path)
        print(f"[arxiv] appending to {out_path} ({len(existing_rows)} existing rows, {len(existing_ids)} unique ids)")
    else:
        out_path = Path(args.out) if args.out else Path(f"arxiv_{_slugify(args.query)}.csv")
        existing_rows, existing_ids = [], set()

    print(f"[arxiv] query: {args.field}:{args.query!r}")
    print(f"[arxiv] max={args.max}  batch={args.batch}  sort={'date-desc' if args.sort else 'relevance'}")
    if after:
        print(f"[arxiv] after:  {after.date()}")
    if before:
        print(f"[arxiv] before: {before.date()}")

    new_rows = fetch(
        query=args.query,
        max_results=args.max,
        batch_size=args.batch,
        field=args.field,
        sort_by=args.sort,
        after=after,
        before=before,
        sleep_s=args.sleep,
        existing_ids=existing_ids,
    )

    all_rows = existing_rows + new_rows
    save_csv(all_rows, out_path)
    print(f"[arxiv] done — {len(new_rows)} new, {len(all_rows)} total")


if __name__ == "__main__":
    main()

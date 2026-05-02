"""
harness/semantic_scholar.py — Enrich arXiv paper CSVs with citation graph data
                               from the Semantic Scholar Graph API (free, no auth).

Core functions
--------------
fetch_references(arxiv_id)
    What this paper cites. Returns list of ref dicts with arXiv IDs resolved
    where Semantic Scholar has them.

build_citation_graph(papers)
    Takes your corpus (list of dicts with 'arxiv_id'). Fetches all references,
    returns a GraphResult with:
      adjacency       {arxiv_id: [cited_arxiv_ids]}  within-corpus edges only
      hub_scores      {arxiv_id: int}                in-corpus citation count
      gap_candidates  [dict]                         cited externally, not in corpus
      all_refs        {arxiv_id: [ref_dict]}         full reference list per paper

Caching
-------
Responses are cached in semantic_scholar_cache.db (SQLite, 30-day TTL).
Re-running on the same corpus costs 0 API calls.

Rate limiting
-------------
Without an API key: ~1 req/s. Set S2_API_KEY env var for 10 req/s.

CLI
---
    python -m harness.semantic_scholar arxiv_agentic_papers.csv
    python -m harness.semantic_scholar arxiv_agentic_papers.csv --refs-out refs.json
    python -m harness.semantic_scholar --cache-stats
"""

import argparse
import csv
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from harness.config import SEMANTIC_SCHOLAR_CACHE_DB

CACHE_PATH = SEMANTIC_SCHOLAR_CACHE_DB
CACHE_TTL  = 30 * 24 * 3600   # 30 days

S2_BASE    = "https://api.semanticscholar.org/graph/v1/paper"
S2_FIELDS  = "references.externalIds,references.title,references.year,references.authors,externalIds,title,year"

COLUMNS_EXTRA = ["hub_score", "ref_count", "in_corpus_citations"]


# ---------------------------------------------------------------------------
# SQLite cache
# ---------------------------------------------------------------------------

def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(CACHE_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS s2_cache (
            arxiv_id  TEXT PRIMARY KEY,
            data      TEXT NOT NULL,
            fetched   INTEGER NOT NULL
        )
    """)
    conn.commit()
    return conn


def _cache_get(arxiv_id: str) -> dict | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT data, fetched FROM s2_cache WHERE arxiv_id = ?", (arxiv_id,)
        ).fetchone()
    if not row:
        return None
    data_str, fetched = row
    if time.time() - fetched > CACHE_TTL:
        return None
    return json.loads(data_str)


def _cache_set(arxiv_id: str, data: dict) -> None:
    with _db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO s2_cache (arxiv_id, data, fetched) VALUES (?, ?, ?)",
            (arxiv_id, json.dumps(data), int(time.time())),
        )
        conn.commit()


def cache_stats() -> dict:
    with _db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM s2_cache").fetchone()[0]
        expired = conn.execute(
            "SELECT COUNT(*) FROM s2_cache WHERE fetched < ?",
            (int(time.time()) - CACHE_TTL,),
        ).fetchone()[0]
    return {"total": total, "live": total - expired, "expired": expired}


# ---------------------------------------------------------------------------
# S2 API call
# ---------------------------------------------------------------------------

_BACKOFF = [10, 30, 60]   # seconds to wait on successive 429s

def _fetch_s2_raw(arxiv_id: str, sleep_s: float = 1.0) -> dict | None:
    """
    Hit the S2 API for a single paper. Returns raw response dict or None on
    failure. Does NOT consult cache — use fetch_references() for cached access.
    """
    base_id = arxiv_id.split("v")[0]
    url = f"{S2_BASE}/arXiv:{base_id}?fields={S2_FIELDS}"

    headers = {"User-Agent": "harness-engineering/1.0 (research; contact via github)"}
    api_key = os.environ.get("S2_API_KEY", "")
    if api_key:
        headers["x-api-key"] = api_key

    for attempt, backoff in enumerate([0] + _BACKOFF):
        if backoff:
            print(f"  [s2] rate limited — sleeping {backoff}s (attempt {attempt}/{len(_BACKOFF)})")
            time.sleep(backoff)
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            time.sleep(sleep_s)
            return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {}
            if e.code == 429:
                continue
            print(f"  [s2] HTTP {e.code} for {arxiv_id}")
            return None
        except Exception as e:
            print(f"  [s2] error for {arxiv_id}: {e}")
            return None

    print(f"  [s2] gave up on {arxiv_id} after {len(_BACKOFF)} retries — skipping")
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_references(arxiv_id: str, sleep_s: float = 1.0) -> list[dict]:
    """
    Return the papers cited by arxiv_id. Each entry:
      {
        "title":    str,
        "year":     int | None,
        "authors":  str,        # comma-joined
        "arxiv_id": str | None, # resolved arXiv ID if S2 has it
        "s2_id":    str,        # Semantic Scholar paperId
      }
    Returns [] if the paper is not in S2 or has no references.
    """
    cached = _cache_get(arxiv_id)
    if cached is None:
        cached = _fetch_s2_raw(arxiv_id, sleep_s) or {}
        _cache_set(arxiv_id, cached)

    refs = []
    for r in cached.get("references", []):
        ext   = r.get("externalIds") or {}
        title = r.get("title") or ""
        year  = r.get("year")
        authors = ", ".join(
            a.get("name", "") for a in (r.get("authors") or [])
        )
        refs.append({
            "title":    title,
            "year":     year,
            "authors":  authors,
            "arxiv_id": ext.get("ArXiv"),
            "s2_id":    r.get("paperId", ""),
        })
    return refs


# ---------------------------------------------------------------------------
# Citation graph
# ---------------------------------------------------------------------------

@dataclass
class GraphResult:
    adjacency:      dict = field(default_factory=dict)
    hub_scores:     dict = field(default_factory=dict)
    gap_candidates: list = field(default_factory=list)
    all_refs:       dict = field(default_factory=dict)
    unresolved:     dict = field(default_factory=dict)
    stats:          dict = field(default_factory=dict)


def build_citation_graph(
    papers:   list[dict],
    sleep_s:  float = 1.0,
    verbose:  bool  = True,
    top_gaps: int   = 50,
) -> GraphResult:
    """
    Fetch references for every paper in `papers` and build the citation graph.

    papers: list of dicts with at minimum an 'arxiv_id' key.
    Returns a GraphResult.
    """
    corpus_ids = {p["arxiv_id"].split("v")[0] for p in papers if p.get("arxiv_id")}

    adjacency:   dict[str, list[str]] = {}
    all_refs:    dict[str, list[dict]] = {}
    unresolved:  dict[str, list[dict]] = {}
    external_citations: Counter = Counter()

    cache_hits        = 0
    api_calls         = 0
    consecutive_fails = 0
    MAX_CONSECUTIVE   = 2

    for i, paper in enumerate(papers):
        aid = (paper.get("arxiv_id") or "").split("v")[0]
        if not aid:
            continue

        was_cached  = _cache_get(aid) is not None
        raw_skipped = False

        if not was_cached:
            raw = _fetch_s2_raw(aid, sleep_s=sleep_s)
            if raw is None:
                consecutive_fails += 1
                raw_skipped = True
                if consecutive_fails >= MAX_CONSECUTIVE:
                    print(f"  [s2] {consecutive_fails} consecutive failures — aborting enrichment, continuing without S2")
                    break
            else:
                _cache_set(aid, raw)
                consecutive_fails = 0

        refs = fetch_references(aid, sleep_s=0) if not raw_skipped else []

        if was_cached:
            cache_hits += 1
            consecutive_fails = 0
        elif not raw_skipped:
            api_calls += 1

        if verbose:
            status = "(cached)" if was_cached else ("(skipped)" if raw_skipped else "(api)")
            print(f"  [{i+1}/{len(papers)}] {aid:<20} {len(refs):>3} refs  {status}")

        all_refs[aid]   = refs
        unresolved[aid] = [r for r in refs if not r["arxiv_id"]]

        corpus_cited = []
        for r in refs:
            ref_aid = (r["arxiv_id"] or "").split("v")[0]
            if ref_aid and ref_aid in corpus_ids:
                corpus_cited.append(ref_aid)
            elif r["arxiv_id"]:
                external_citations[r["arxiv_id"].split("v")[0]] += 1
        adjacency[aid] = corpus_cited

    hub_scores: dict[str, int] = Counter()
    for cited_list in adjacency.values():
        for cited in cited_list:
            hub_scores[cited] += 1

    gap_candidates = []
    for ext_id, count in external_citations.most_common(top_gaps):
        if ext_id not in corpus_ids:
            gap_candidates.append({
                "arxiv_id":       ext_id,
                "cited_by_count": count,
                "arxiv_url":      f"https://arxiv.org/abs/{ext_id}",
            })

    result = GraphResult(
        adjacency=adjacency,
        hub_scores=dict(hub_scores),
        gap_candidates=gap_candidates,
        all_refs=all_refs,
        unresolved=unresolved,
        stats={
            "corpus_size": len(corpus_ids),
            "api_calls":   api_calls,
            "cache_hits":  cache_hits,
            "total_edges": sum(len(v) for v in adjacency.values()),
            "external_refs": sum(len(v) for v in all_refs.values()),
        },
    )
    return result


# ---------------------------------------------------------------------------
# CSV enrichment
# ---------------------------------------------------------------------------

def enrich_csv(in_path: Path, out_path: Path, graph: GraphResult) -> None:
    """Add hub_score, ref_count, in_corpus_citations columns to the CSV."""
    rows = []
    with open(in_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        existing_cols = reader.fieldnames or []
        for row in reader:
            rows.append(row)

    new_cols = [c for c in COLUMNS_EXTRA if c not in existing_cols]
    all_cols = list(existing_cols) + new_cols

    for row in rows:
        aid = (row.get("arxiv_id") or "").split("v")[0]
        row["hub_score"]           = graph.hub_scores.get(aid, 0)
        row["ref_count"]           = len(graph.all_refs.get(aid, []))
        row["in_corpus_citations"] = ",".join(graph.adjacency.get(aid, []))

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_cols)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[s2] enriched CSV -> {out_path}")


# ---------------------------------------------------------------------------
# Gap resolution: fetch arXiv metadata for gap candidates
# ---------------------------------------------------------------------------

def fetch_gap_arxiv_rows(gap_candidates: list[dict], max_n: int) -> list[dict]:
    """Fetch arXiv metadata for top-N gap candidates so they can be appended to the corpus CSV."""
    try:
        import feedparser
    except ImportError:
        print("[s2] feedparser not installed — cannot fetch gap metadata")
        return []

    rows = []
    for g in gap_candidates[:max_n]:
        aid = g["arxiv_id"]
        url = f"http://export.arxiv.org/api/query?id_list={aid}&max_results=1"
        feed = feedparser.parse(url)
        if not feed.entries:
            continue
        entry = feed.entries[0]
        authors = ", ".join(getattr(a, "name", "") for a in getattr(entry, "authors", []))
        pdf_url = None
        for link in getattr(entry, "links", []):
            if getattr(link, "type", "") == "application/pdf":
                pdf_url = link.href
        categories = ", ".join(
            getattr(t, "term", "") for t in getattr(entry, "tags", [])
        )
        rows.append({
            "title":      getattr(entry, "title", "").strip().replace("\n", " "),
            "authors":    authors,
            "published":  getattr(entry, "published", ""),
            "updated":    getattr(entry, "updated", ""),
            "summary":    getattr(entry, "summary", "").strip().replace("\n", " "),
            "arxiv_url":  getattr(entry, "link", ""),
            "pdf_url":    pdf_url or "",
            "arxiv_id":   aid,
            "categories": categories,
        })
        time.sleep(1)
    return rows


# ---------------------------------------------------------------------------
# Pretty-print helpers
# ---------------------------------------------------------------------------

def print_hubs(papers: list[dict], hub_scores: dict, top_n: int = 15) -> None:
    id_to_title = {
        p.get("arxiv_id", "").split("v")[0]: p.get("title", "")
        for p in papers
    }
    ranked = sorted(hub_scores.items(), key=lambda x: -x[1])[:top_n]
    print(f"\n{'Hub papers (in-corpus citation count)':}")
    print(f"  {'#':<4} {'Citations':<12} {'arXiv ID':<18} {'Title'}")
    print(f"  {'-'*80}")
    for i, (aid, score) in enumerate(ranked, 1):
        title = id_to_title.get(aid, "?")[:55]
        print(f"  {i:<4} {score:<12} {aid:<18} {title}")


def print_gaps(gap_candidates: list[dict], top_n: int = 20) -> None:
    print(f"\n{'Gap candidates (cited by corpus, not annotated)':}")
    print(f"  {'#':<4} {'Cited by':<12} {'arXiv ID':<18} {'URL'}")
    print(f"  {'-'*70}")
    for i, g in enumerate(gap_candidates[:top_n], 1):
        print(f"  {i:<4} {g['cited_by_count']:<12} {g['arxiv_id']:<18} {g['arxiv_url']}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Enrich arXiv CSV with Semantic Scholar citation data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("csv",          nargs="?",  help="Input CSV (arxiv_agentic_papers.csv schema)")
    ap.add_argument("--out",        default=None, help="Output enriched CSV (default: input_enriched.csv)")
    ap.add_argument("--refs-out",   default=None, help="Write full reference graph to JSON file")
    ap.add_argument("--gaps",       type=int, default=20, help="Show top N gap candidates (default 20)")
    ap.add_argument("--fetch-gaps", type=int, default=0,
                    help="Resolve top N gaps and append to --append CSV")
    ap.add_argument("--append",     default=None, help="CSV to append fetched gap rows to")
    ap.add_argument("--sleep",      type=float, default=1.0,
                    help="Seconds between API calls (default 1.0)")
    ap.add_argument("--cache-stats", action="store_true", help="Show cache stats and exit")
    ap.add_argument("--top-hubs",   type=int, default=15, help="Show top N hub papers (default 15)")
    args = ap.parse_args()

    if args.cache_stats:
        stats = cache_stats()
        print(f"Semantic Scholar cache: {CACHE_PATH}")
        print(f"  Total entries: {stats['total']}")
        print(f"  Live (< 30d):  {stats['live']}")
        print(f"  Expired:       {stats['expired']}")
        return

    if not args.csv:
        ap.print_help()
        sys.exit(1)

    in_path = Path(args.csv)
    if not in_path.exists():
        print(f"[s2] file not found: {in_path}")
        sys.exit(1)

    papers = []
    with open(in_path, newline="", encoding="utf-8") as f:
        papers = list(csv.DictReader(f))
    print(f"[s2] {len(papers)} papers loaded from {in_path}")

    print(f"[s2] fetching references (sleep={args.sleep}s between API calls)...")
    graph = build_citation_graph(papers, sleep_s=args.sleep, verbose=True, top_gaps=args.gaps * 2)

    s = graph.stats
    print("\n[s2] done")
    print(f"  corpus:       {s['corpus_size']} papers")
    print(f"  api calls:    {s['api_calls']}")
    print(f"  cache hits:   {s['cache_hits']}")
    print(f"  corpus edges: {s['total_edges']} (within-corpus citations)")
    print(f"  external refs:{s['external_refs']} (all references)")

    print_hubs(papers, graph.hub_scores, top_n=args.top_hubs)
    print_gaps(graph.gap_candidates, top_n=args.gaps)

    out_path = Path(args.out) if args.out else in_path.with_name(in_path.stem + "_enriched.csv")
    enrich_csv(in_path, out_path, graph)

    if args.refs_out:
        refs_path = Path(args.refs_out)
        with open(refs_path, "w", encoding="utf-8") as f:
            json.dump({
                "adjacency":       graph.adjacency,
                "hub_scores":      graph.hub_scores,
                "gap_candidates":  graph.gap_candidates,
                "all_refs":        graph.all_refs,
            }, f, indent=2)
        print(f"[s2] reference graph -> {refs_path}")

    if args.fetch_gaps > 0:
        print(f"\n[s2] fetching arXiv metadata for top {args.fetch_gaps} gap candidates...")
        gap_rows = fetch_gap_arxiv_rows(graph.gap_candidates, max_n=args.fetch_gaps)
        if gap_rows:
            append_path = Path(args.append) if args.append else out_path
            existing_rows, existing_ids = [], set()
            if append_path.exists():
                with open(append_path, newline="", encoding="utf-8") as f:
                    rdr = csv.DictReader(f)
                    existing_cols = rdr.fieldnames or []
                    for row in rdr:
                        existing_rows.append(row)
                        existing_ids.add(row.get("arxiv_id", "").split("v")[0])
            new_rows = [r for r in gap_rows if r["arxiv_id"].split("v")[0] not in existing_ids]
            all_rows = existing_rows + new_rows
            base_cols = ["title", "authors", "published", "updated", "summary",
                         "arxiv_url", "pdf_url", "arxiv_id", "categories"]
            with open(append_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=base_cols, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(all_rows)
            print(f"[s2] appended {len(new_rows)} gap papers -> {append_path} ({len(all_rows)} total)")


if __name__ == "__main__":
    main()

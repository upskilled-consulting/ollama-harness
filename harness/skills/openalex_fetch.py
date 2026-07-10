"""
openalex_fetch.py -- Fetch papers from OpenAlex (covers arXiv, SSRN, NBER, journals, etc.)

Produces the same column schema as arxiv_fetch.py so output feeds directly into
the lit-review pipeline and corpus builder without changes.

Columns: title, authors, published, updated, summary, arxiv_url, pdf_url,
         arxiv_id, categories

'arxiv_id' is used as the unique paper identifier throughout the pipeline.
For non-arXiv papers it is set to:
  - SSRN-XXXXXXX   for SSRN preprints
  - doi-...        for DOI-only papers (slashes replaced with -)
  - openalex-WXXXXXXXXX  as a last resort

Usage:
    python openalex_fetch.py "LLM trading agent financial markets"
    python openalex_fetch.py "portfolio optimization reinforcement learning" --max 200
    python openalex_fetch.py "earnings call NLP" --after 2022-01-01 --source ssrn
    python openalex_fetch.py "algorithmic trading" --source arxiv
    python openalex_fetch.py "credit risk neural network" --stats existing.csv

Options:
    --max N          Total papers to fetch (default: 200)
    --after DATE     Only papers published on or after DATE (YYYY-MM-DD)
    --before DATE    Only papers published before DATE (YYYY-MM-DD)
    --source NAME    Filter by source: ssrn | arxiv | nber | any (default: any)
    --out FILE       Output CSV path (default: derived from query slug)
    --append FILE    Append to existing CSV, skip already-present IDs
    --stats FILE     Print stats and exit
    --sort           Sort by citation count (default: relevance)
"""

import argparse
import csv
import hashlib
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

BASE_URL      = "https://api.openalex.org/works"
DEFAULT_MAX   = 200
DEFAULT_BATCH = 200   # OpenAlex max per-page is 200
DEFAULT_SLEEP = 0.12  # ~8 req/s — stays well under the 10 req/s polite limit
DEFAULT_CACHE_TTL_H = 24.0

COLUMNS = ["title", "authors", "published", "updated", "summary",
           "arxiv_url", "pdf_url", "arxiv_id", "categories"]

# OpenAlex source IDs for common preprint/working-paper sources
# Use primary_location.source.id (v2 API) -- host_organization.id was removed
_SOURCE_FILTERS = {
    "ssrn":  "primary_location.source.id:S4210172589",
    "arxiv": "primary_location.source.id:S4306400194",
    "nber":  "primary_location.source.id:S4393916240",
}

# Fields to request — keeps payload small
# OpenAlex v2: 'external_ids' -> 'ids'; 'concepts' -> 'topics'; drop 'locations'
_SELECT = (
    "id,display_name,abstract_inverted_index,publication_date,"
    "authorships,primary_location,ids,"
    "open_access,topics,cited_by_count"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _api_key() -> str:
    return os.environ.get("OPENALEX_API_KEY", "")


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40]


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC)


def _reconstruct_abstract(inv: dict | None) -> str:
    """Reconstruct abstract text from OpenAlex inverted index."""
    if not inv:
        return ""
    try:
        max_pos = max(p for positions in inv.values() for p in positions)
        words   = [""] * (max_pos + 1)
        for word, positions in inv.items():
            for p in positions:
                words[p] = word
        return " ".join(w for w in words if w)
    except (ValueError, TypeError):
        return ""


def _paper_id(work: dict) -> str:
    """Return a stable unique ID for this work, preferring arXiv > SSRN > DOI > OpenAlex."""
    # OpenAlex v2 uses 'ids' dict; fall back to top-level 'doi' field
    ids = work.get("ids") or {}

    arxiv = ids.get("arxiv") or ""
    if arxiv:
        # Strip URL prefix or 'arxiv:' prefix if present
        arxiv = re.sub(r"^https?://arxiv\.org/abs/", "", arxiv)
        return re.sub(r"^arxiv:", "", arxiv, flags=re.IGNORECASE)

    ssrn = ids.get("ssrn") or ""
    if ssrn:
        return f"SSRN-{ssrn}"

    doi = ids.get("doi") or work.get("doi") or ""
    if doi:
        doi = re.sub(r"^https?://doi\.org/", "", doi)
        # arXiv DOI prefix 10.48550/arxiv.XXXX.XXXXX -> clean arXiv ID
        m = re.match(r"^10\.48550/arxiv\.(.+)$", doi, re.IGNORECASE)
        if m:
            return m.group(1)
        return "doi-" + doi.replace("/", "-")

    oa_id = work.get("id") or ""
    return "openalex-" + oa_id.split("/")[-1]


def _paper_url(work: dict, paper_id: str) -> str:
    """Best human-readable landing page URL."""
    if paper_id.startswith("SSRN-"):
        num = paper_id[5:]
        return f"https://ssrn.com/abstract={num}"
    if not paper_id.startswith(("doi-", "openalex-")):
        # arXiv
        return f"https://arxiv.org/abs/{paper_id}"
    doi = (work.get("ids") or {}).get("doi") or work.get("doi") or ""
    if doi:
        doi = re.sub(r"^https?://doi\.org/", "", doi)
        return f"https://doi.org/{doi}"
    return work.get("id") or ""


def _pdf_url(work: dict) -> str:
    oa = work.get("open_access") or {}
    url = oa.get("oa_url") or ""
    if url and url.endswith(".pdf"):
        return url
    # Try best_oa_location
    loc = work.get("primary_location") or {}
    pdf = loc.get("pdf_url") or ""
    return pdf or url


def _authors(work: dict) -> str:
    ships = work.get("authorships") or []
    names = []
    for s in ships[:10]:   # cap to avoid huge strings
        author = s.get("author") or {}
        name   = author.get("display_name") or ""
        if name:
            names.append(name)
    return ", ".join(names)


def _categories(work: dict) -> str:
    topics = work.get("topics") or []
    terms  = [t.get("display_name", "") for t in topics[:8] if t.get("score", 0) > 0.3]
    return ", ".join(t for t in terms if t)


def _work_to_row(work: dict) -> dict:
    paper_id = _paper_id(work)
    title    = (work.get("display_name") or "").strip().replace("\n", " ")
    pub_date = work.get("publication_date") or ""
    abstract = _reconstruct_abstract(work.get("abstract_inverted_index"))
    return {
        "title":     title,
        "authors":   _authors(work),
        "published": pub_date,
        "updated":   pub_date,
        "summary":   abstract,
        "arxiv_url": _paper_url(work, paper_id),
        "pdf_url":   _pdf_url(work),
        "arxiv_id":  paper_id,
        "categories": _categories(work),
    }


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch(
    query:          str,
    max_results:    int            = DEFAULT_MAX,
    source:         str            = "any",
    sort_by_cite:   bool           = False,
    after:          datetime | None = None,
    before:         datetime | None = None,
    sleep_s:        float          = DEFAULT_SLEEP,
    existing_ids:   set[str] | None = None,
    extra_filter:   str | None      = None,
) -> list[dict]:
    """
    Fetch papers from OpenAlex matching query.
    Returns list of row dicts with same schema as arxiv_fetch.fetch().

    extra_filter: raw OpenAlex filter string appended to the filter param,
                  e.g. "concepts.id:C181236170" for finance/CAPM-tagged papers.
    """
    key     = _api_key()
    seen    = set(existing_ids or [])
    rows: list[dict] = []
    cursor  = "*"
    skipped_dup  = 0
    skipped_date = 0

    # Build filter string
    filters: list[str] = []
    if source != "any" and source in _SOURCE_FILTERS:
        filters.append(_SOURCE_FILTERS[source])
    if extra_filter:
        filters.append(extra_filter)
    if after:
        filters.append(f"publication_date:>{after.date().isoformat()}")
    if before:
        filters.append(f"publication_date:<{before.date().isoformat()}")

    sort_param = "cited_by_count:desc" if sort_by_cite else "relevance_score:desc"

    print(f"[openalex] searching {max_results} papers: {query!r}"
          + (f"  source={source}" if source != "any" else "")
          + (f"  after={after.date()}" if after else "")
          + (f"  before={before.date()}" if before else ""))

    while len(rows) < max_results:
        params: dict = {
            "search":   query,
            "select":   _SELECT,
            "per-page": min(DEFAULT_BATCH, max_results - len(rows)),
            "cursor":   cursor,
            "sort":     sort_param,
        }
        if filters:
            params["filter"] = ",".join(filters)
        # Polite pool: mailto gives higher rate limits; api_key only for premium institutional accounts
        if key:
            params["api_key"] = key
        params["mailto"] = "nickmccarty0@gmail.com"

        try:
            resp = requests.get(BASE_URL, params=params, timeout=30)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 60))
                print(f"[openalex] 429 rate-limited -- waiting {wait}s", flush=True)
                time.sleep(wait)
                continue
            if not resp.ok:
                print(f"[openalex] HTTP {resp.status_code}: {resp.text[:400]}", flush=True)
                resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[openalex] request error: {e}")
            break

        results = data.get("results") or []
        meta    = data.get("meta") or {}

        if not results:
            print(f"[openalex] no results returned (total={meta.get('count',0)})")
            break

        batch_added = 0
        for work in results:
            row = _work_to_row(work)
            pid = row["arxiv_id"]

            if pid in seen:
                skipped_dup += 1
                continue

            # Abstract filter — skip papers with no abstract (title-only records)
            if not row["summary"].strip():
                continue

            # Date double-check (OpenAlex filter is on submission, not always exact)
            pub = row["published"]
            if pub and (after or before):
                try:
                    dt = datetime.strptime(pub[:10], "%Y-%m-%d").replace(tzinfo=UTC)
                    if after and dt <= after:
                        skipped_date += 1
                        continue
                    if before and dt >= before:
                        skipped_date += 1
                        continue
                except ValueError:
                    pass

            seen.add(pid)
            rows.append(row)
            batch_added += 1

        print(f"[openalex] +{batch_added} (total {len(rows)}/{meta.get('count','?')})")

        cursor = meta.get("next_cursor")
        if not cursor:
            break

        time.sleep(sleep_s)

    if skipped_dup:
        print(f"[openalex] skipped {skipped_dup} duplicates")
    if skipped_date:
        print(f"[openalex] skipped {skipped_date} outside date range")

    return rows


# ---------------------------------------------------------------------------
# Disk cache (mirrors arxiv_fetch.fetch_cached)
# ---------------------------------------------------------------------------

def fetch_cached(
    query:        str,
    max_results:  int             = DEFAULT_MAX,
    source:       str             = "any",
    sort_by_cite: bool            = False,
    after:        datetime | None = None,
    before:       datetime | None = None,
    sleep_s:      float           = DEFAULT_SLEEP,
    existing_ids: set[str] | None = None,
    cache_dir:    Path | None     = None,
    cache_ttl_h:  float           = DEFAULT_CACHE_TTL_H,
    extra_filter: str | None      = None,
) -> list[dict]:
    if cache_dir is None:
        try:
            from harness.config import ARXIV_CACHE_DIR
            cache_dir = Path(str(ARXIV_CACHE_DIR)).parent / "openalex_cache"
        except ImportError:
            cache_dir = Path("data/openalex_cache")
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    key_data = json.dumps({
        "query":   query,
        "max":     max_results,
        "source":  source,
        "sort":    sort_by_cite,
        "after":   after.date().isoformat() if after else None,
        "before":  before.date().isoformat() if before else None,
        "extra":   extra_filter or "",
    }, sort_keys=True)
    cache_key  = hashlib.sha256(key_data.encode()).hexdigest()[:20]
    cache_file = cache_dir / f"{cache_key}.json"

    if cache_file.exists():
        age_h = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_h < cache_ttl_h:
            rows = json.loads(cache_file.read_text(encoding="utf-8"))
            print(f"[openalex] cache hit ({age_h:.1f}h old) -- {len(rows)} rows for {query!r}")
            return rows
        print(f"[openalex] cache stale ({age_h:.1f}h > {cache_ttl_h}h) -- refetching")

    rows = fetch(
        query=query,
        max_results=max_results,
        source=source,
        sort_by_cite=sort_by_cite,
        after=after,
        before=before,
        sleep_s=sleep_s,
        existing_ids=existing_ids,
        extra_filter=extra_filter,
    )

    if rows:
        cache_file.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        print(f"[openalex] cached {len(rows)} rows -> {cache_file.name}")

    return rows


# ---------------------------------------------------------------------------
# CSV I/O (mirrors arxiv_fetch)
# ---------------------------------------------------------------------------

def load_existing(path: Path) -> tuple[list[dict], set[str]]:
    rows: list[dict] = []
    ids: set[str]    = set()
    if not path.exists():
        return rows, ids
    with open(path, encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            rows.append(row)
            if row.get("arxiv_id"):
                ids.add(row["arxiv_id"])
    return rows, ids


def save_csv(rows: list[dict], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"[openalex] saved {len(rows)} rows -> {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query",    nargs="?", default="", help="Search query")
    parser.add_argument("--max",    default=DEFAULT_MAX, type=int)
    parser.add_argument("--after",  default=None, help="YYYY-MM-DD")
    parser.add_argument("--before", default=None, help="YYYY-MM-DD")
    parser.add_argument("--source", default="any",
                        choices=["any", "ssrn", "arxiv", "nber"],
                        help="Filter to a specific source (default: any)")
    parser.add_argument("--sort",   action="store_true", help="Sort by citation count")
    parser.add_argument("--out",    default=None, help="Output CSV path")
    parser.add_argument("--append", default=None, help="Append to existing CSV")
    parser.add_argument("--stats",  default=None, help="Print stats for existing CSV and exit")
    args = parser.parse_args()

    if args.stats:
        rows, ids = load_existing(Path(args.stats))
        sources = {}
        for r in rows:
            aid = r.get("arxiv_id", "")
            if aid.startswith("SSRN-"):      src = "ssrn"
            elif aid.startswith("doi-"):     src = "doi"
            elif aid.startswith("openalex-"): src = "openalex"
            else:                            src = "arxiv"
            sources[src] = sources.get(src, 0) + 1
        print(f"{Path(args.stats).name}: {len(rows)} papers")
        for src, count in sorted(sources.items(), key=lambda x: -x[1]):
            print(f"  {src:<12} {count}")
        return

    if not args.query:
        parser.print_help()
        return

    after  = _parse_date(args.after)  if args.after  else None
    before = _parse_date(args.before) if args.before else None

    existing_rows: list[dict] = []
    existing_ids:  set[str]   = set()
    if args.append:
        existing_rows, existing_ids = load_existing(Path(args.append))
        print(f"[openalex] appending to {args.append} ({len(existing_rows)} existing)")

    rows = fetch_cached(
        query=args.query,
        max_results=args.max,
        source=args.source,
        sort_by_cite=args.sort,
        after=after,
        before=before,
        existing_ids=existing_ids,
    )

    out_path = Path(args.append or args.out or f"openalex_{_slugify(args.query)}.csv")
    all_rows = existing_rows + rows
    save_csv(all_rows, out_path)
    print(f"[openalex] done. {len(rows)} new papers.")


if __name__ == "__main__":
    main()

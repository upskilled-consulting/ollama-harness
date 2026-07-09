"""
harness/skills/ssrn_scraper.py -- Reliable SSRN paper fetching.

Strategy (waterfall, fastest first):
  1. OpenAlex API lookup by SSRN ID  -- no ssrn.com contact, instant
  2. Direct PDF download via oa_url  -- bypasses Cloudflare entirely
  3. cloudscraper HTML fetch          -- solves CF JS challenge (level 1-2)
  4. Raise SSRNUnavailable            -- callers can decide whether to skip

The abstract, title, authors, and date are always available from OpenAlex.
Full-text extraction (steps 2-3) is only needed when annotation requires
more than the abstract (e.g. methods, results sections).

Parsing targets the current SSRN HTML structure (as of 2025):
  - Title:    <h1> or meta[name=citation_title]
  - Abstract: #abstractDiv or meta[name=citation_abstract]
  - Authors:  meta[name=citation_author] (multiple)
  - Date:     meta[name=citation_date] or .date-revision
  - Stats:    .paper-stat-count spans

CLI:
    python -m harness.skills.ssrn_scraper 1234567
    python -m harness.skills.ssrn_scraper https://ssrn.com/abstract=1234567
    python -m harness.skills.ssrn_scraper --batch ids.txt --out ssrn_papers.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import time
from pathlib import Path
from typing import TypedDict

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class SSRNPaper(TypedDict, total=False):
    ssrn_id:   str
    url:       str
    title:     str
    abstract:  str
    authors:   str
    date:      str
    views:     str
    downloads: str
    pdf_url:   str
    source:    str   # "openalex" | "pdf" | "html"


class SSRNUnavailable(Exception):
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SSRN_ID_RE = re.compile(r"(?:abstract[_=]?|papers\.cfm\?abstract_id=)(\d+)", re.IGNORECASE)


def _extract_id(url_or_id: str) -> str:
    """Return the bare numeric SSRN abstract_id from a URL or raw integer string."""
    m = _SSRN_ID_RE.search(url_or_id)
    if m:
        return m.group(1)
    if url_or_id.strip().isdigit():
        return url_or_id.strip()
    raise ValueError(f"Cannot extract SSRN ID from: {url_or_id!r}")


def _ssrn_url(ssrn_id: str) -> str:
    return f"https://papers.ssrn.com/sol3/papers.cfm?abstract_id={ssrn_id}"


# ---------------------------------------------------------------------------
# Strategy 1: OpenAlex API  (no ssrn.com contact)
# ---------------------------------------------------------------------------

def _fetch_openalex(ssrn_id: str) -> SSRNPaper | None:
    """
    Look up the paper in OpenAlex by SSRN ID.
    SSRN papers are registered under the DOI prefix 10.2139/ssrn.{id}.
    Returns None if not indexed yet (new papers have a days-to-weeks lag).
    """
    doi = f"10.2139/ssrn.{ssrn_id}"
    url = f"https://api.openalex.org/works/https://doi.org/{doi}"
    params = {
        "select": (
            "id,display_name,abstract_inverted_index,publication_date,"
            "authorships,primary_location,ids,open_access"
        ),
        "mailto": "nickmccarty0@gmail.com",
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        w = resp.json()
    except Exception:
        return None

    # Reconstruct abstract from inverted index
    inv = w.get("abstract_inverted_index") or {}
    abstract = ""
    if inv:
        try:
            max_pos = max(p for positions in inv.values() for p in positions)
            words   = [""] * (max_pos + 1)
            for word, positions in inv.items():
                for p in positions:
                    words[p] = word
            abstract = " ".join(w for w in words if w)
        except (ValueError, TypeError):
            pass

    authors = ", ".join(
        (s.get("author") or {}).get("display_name") or ""
        for s in (w.get("authorships") or [])[:10]
        if (s.get("author") or {}).get("display_name")
    )

    oa     = w.get("open_access") or {}
    pdf_url = oa.get("oa_url") or ""

    return SSRNPaper(
        ssrn_id  = ssrn_id,
        url      = _ssrn_url(ssrn_id),
        title    = (w.get("display_name") or "").strip(),
        abstract = abstract,
        authors  = authors,
        date     = w.get("publication_date") or "",
        views    = "",
        downloads= "",
        pdf_url  = pdf_url,
        source   = "openalex",
    )


# ---------------------------------------------------------------------------
# Strategy 2: DDGS snippet extraction
# DDG/Google index SSRN pages and return abstract snippets without touching
# ssrn.com. Works for papers indexed within a few days of posting.
# ---------------------------------------------------------------------------

_SNIPPET_NOISE = re.compile(
    r"^(by\s[\w\s,·]+\d{4}\s*[—\-–]\s*)|"
    r"(\.\.\.Read more\s*$)|"
    r"(Cited by \d+\s*)",
    re.IGNORECASE,
)

_PDF_DELIVERY_RE = re.compile(
    r"https://papers\.ssrn\.com/sol3/Delivery\.cfm/[^\s\"'>]+\.pdf[^\s\"'>]*",
    re.IGNORECASE,
)


def _ddgs_search(query: str, max_results: int = 5) -> list[dict]:
    """Direct DDGS call — avoids circular import from agent.py."""
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS  # type: ignore
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except Exception:
        return []


def _fetch_via_ddgs(ssrn_id: str, title: str = "") -> dict:
    """
    Search DDG for the SSRN paper and extract abstract snippet + any PDF links.
    Returns {abstract, pdf_url, snippets}.
    """
    queries = [f'site:papers.ssrn.com/sol3/papers.cfm abstract_id {ssrn_id}']
    if title:
        queries.append(f'ssrn "{title[:80]}"')

    snippets: list[str] = []
    pdf_urls: list[str] = []

    for q in queries:
        for r in _ddgs_search(q):
            href = r.get("href", "")
            # Only use snippets from results that are actually for this paper
            if ssrn_id not in href:
                continue
            body = r.get("body", "").strip()
            if body:
                cleaned = _SNIPPET_NOISE.sub("", body).strip()
                if cleaned and cleaned not in snippets:
                    snippets.append(cleaned)
            if "Delivery.cfm" in href and href not in pdf_urls:
                pdf_urls.append(href)

    return {
        "abstract": max(snippets, key=len) if snippets else "",
        "pdf_url":  pdf_urls[0] if pdf_urls else "",
        "snippets": snippets,
    }


# ---------------------------------------------------------------------------
# Strategy 3: Playwright via real Chrome (bypasses Cloudflare with session)
# Uses the existing headed Chrome if HARNESS_CDP_URL or HARNESS_HEADED is set;
# otherwise launches a fresh headed browser window.
# ---------------------------------------------------------------------------

def _fetch_via_playwright(ssrn_id: str) -> dict:
    """
    Navigate to the SSRN abstract page in a real/headed browser.
    Cloudflare Managed Challenge passes when the browser has a genuine fingerprint
    and (ideally) existing ssrn.com cookies from a prior real session.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        return {}

    url     = _ssrn_url(ssrn_id)
    cdp_url = os.environ.get("HARNESS_CDP_URL", "http://localhost:9222")
    result  = {}

    _JS_EXTRACT = """() => {
        const absEl = document.getElementById('abstractDiv')
                   || document.querySelector('.abstract-text')
                   || document.querySelector('[class*="abstract"]');
        const absMeta = document.querySelector('meta[name="citation_abstract"]');
        const abstract = (absEl ? absEl.innerText : '')
                      || (absMeta ? absMeta.content : '');

        const titleEl = document.querySelector('h1')
                     || document.querySelector('meta[name="citation_title"]');
        const title = (titleEl && titleEl.tagName === 'META')
                    ? titleEl.content : (titleEl ? titleEl.innerText : '');

        const authors = [...document.querySelectorAll('meta[name="citation_author"]')]
                        .map(m => m.content).join('; ');
        const dateMeta = document.querySelector('meta[name="citation_date"]');
        const date = dateMeta ? dateMeta.content : '';
        const pdfMeta = document.querySelector('meta[name="citation_pdf_url"]');
        const pdf_url = pdfMeta ? pdfMeta.content : '';

        return {abstract: abstract.trim(), title: title.trim(),
                authors, date, pdf_url};
    }"""

    with sync_playwright() as pw:
        browser = None
        owned   = False
        try:
            # Prefer connecting to an already-running Chrome instance
            browser = pw.chromium.connect_over_cdp(cdp_url)
        except Exception:
            pass

        if browser is None:
            try:
                browser = pw.chromium.launch(headless=False, args=["--no-sandbox"])
                owned = True
            except Exception as e:
                print(f"  [ssrn:playwright] could not launch browser: {e}")
                return {}

        ctx  = browser.new_context()
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            # Brief wait for CF challenge to resolve if triggered
            page.wait_for_timeout(3_000)
            data = page.evaluate(_JS_EXTRACT)
            if data.get("abstract"):
                result = data
                result["source"] = "playwright"
        except PWTimeout:
            print(f"  [ssrn:playwright] timeout loading {url}")
        except Exception as e:
            print(f"  [ssrn:playwright] error: {e}")
        finally:
            page.close()
            ctx.close()
            if owned and browser:
                browser.close()

    return result


# ---------------------------------------------------------------------------
# Strategy 4: Direct PDF download (bypasses CF on older CDN-hosted papers)
# ---------------------------------------------------------------------------

def _fetch_pdf_text(pdf_url: str) -> str:
    """Download a PDF and extract text via pdfminer / MarkItDown. Returns empty on failure."""
    if not pdf_url:
        return ""
    try:
        import io
        from markitdown import MarkItDown
        resp = requests.get(pdf_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        md   = MarkItDown()
        result = md.convert_stream(io.BytesIO(resp.content), file_extension=".pdf")
        return result.text_content or ""
    except Exception:
        pass
    # pdfminer fallback
    try:
        import io
        import pdfminer.high_level as pdfminer
        resp = requests.get(pdf_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        return pdfminer.extract_text(io.BytesIO(resp.content)) or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Strategy 3: cloudscraper HTML fetch + BeautifulSoup parsing
# ---------------------------------------------------------------------------

_SCRAPER = None   # lazy init — cloudscraper session is expensive to create


def _get_scraper():
    global _SCRAPER
    if _SCRAPER is None:
        import cloudscraper
        _SCRAPER = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
    return _SCRAPER


def _parse_ssrn_html(html: str) -> dict:
    """
    Parse SSRN abstract page HTML. Handles both the current (2024+) layout
    and the legacy layout the old scraper targeted.
    """
    soup = BeautifulSoup(html, "html.parser")

    # --- Title ---
    title = ""
    # Current layout: meta tag
    meta_title = soup.find("meta", attrs={"name": "citation_title"})
    if meta_title:
        title = meta_title.get("content", "").strip()
    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else ""

    # --- Abstract ---
    abstract = ""
    # Current layout: meta tag (most reliable)
    meta_abs = soup.find("meta", attrs={"name": "citation_abstract"})
    if meta_abs:
        abstract = meta_abs.get("content", "").strip()
    # Current layout: #abstractDiv
    if not abstract:
        div = soup.find(id="abstractDiv") or soup.find("div", class_="abstract-text")
        if div:
            abstract = div.get_text(separator=" ", strip=True)
    # Legacy layout: text splitting
    if not abstract:
        full_text = soup.get_text()
        if "Abstract\n" in full_text:
            try:
                abstract = full_text.split("Abstract\n")[1].split("Suggested Citation:")[0]
                abstract = re.sub(r"\s+", " ", abstract).strip()
            except IndexError:
                pass

    # --- Authors ---
    authors = ""
    meta_authors = soup.find_all("meta", attrs={"name": "citation_author"})
    if meta_authors:
        authors = "; ".join(m.get("content", "") for m in meta_authors)
    if not authors:
        author_div = soup.find("div", class_=re.compile(r"author", re.I))
        if author_div:
            authors = author_div.get_text(separator=", ", strip=True)

    # --- Date ---
    date = ""
    meta_date = soup.find("meta", attrs={"name": "citation_date"})
    if meta_date:
        date = meta_date.get("content", "").strip()
    if not date:
        date_span = soup.find(class_=re.compile(r"date", re.I))
        if date_span:
            date = date_span.get_text(strip=True)

    # --- Stats (current layout uses .paper-stat-count) ---
    views = downloads = ""
    stat_counts = soup.find_all(class_="paper-stat-count")
    stat_labels = soup.find_all(class_="paper-stat-label")
    for label_el, count_el in zip(stat_labels, stat_counts):
        label = label_el.get_text(strip=True).lower()
        count = count_el.get_text(strip=True).replace(",", "")
        if "view" in label:
            views = count
        elif "download" in label:
            downloads = count

    # Legacy stats fallback: box-paper-statics
    if not views and not downloads:
        stats_div = soup.find("div", class_="box-paper-statics")
        if stats_div:
            from ordered_set import OrderedSet
            stats = OrderedSet(stats_div.get_text().split("\n"))
            try:
                views = stats[stats.index("Abstract Views") + 1].strip().replace(",", "")
            except (ValueError, IndexError):
                pass
            try:
                downloads = stats[stats.index("Downloads") + 1].strip().replace(",", "")
            except (ValueError, IndexError):
                pass

    # --- PDF URL from meta ---
    pdf_url = ""
    meta_pdf = soup.find("meta", attrs={"name": "citation_pdf_url"})
    if meta_pdf:
        pdf_url = meta_pdf.get("content", "").strip()

    return {
        "title":     title,
        "abstract":  abstract,
        "authors":   authors,
        "date":      date,
        "views":     views,
        "downloads": downloads,
        "pdf_url":   pdf_url,
    }


def _fetch_html(ssrn_id: str, retries: int = 2, delay: float = 2.0) -> dict:
    """Fetch and parse the SSRN landing page via cloudscraper."""
    url = _ssrn_url(ssrn_id)
    scraper = _get_scraper()
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = scraper.get(url, timeout=20)
            if resp.status_code == 403:
                raise SSRNUnavailable(f"Cloudflare blocked ({resp.status_code})")
            resp.raise_for_status()
            parsed = _parse_ssrn_html(resp.text)
            parsed["source"] = "html"
            return parsed
        except SSRNUnavailable:
            raise
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(delay * attempt)
    raise SSRNUnavailable(f"HTML fetch failed after {retries} attempts: {last_err}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_paper(
    url_or_id: str,
    full_text: bool = False,
    sleep_s: float = 1.0,
) -> SSRNPaper:
    """
    Fetch an SSRN paper using the best available strategy.

    Args:
        url_or_id:  SSRN abstract_id (integer string) or any ssrn.com URL
        full_text:  If True, attempt to retrieve full PDF text (strategies 2-3)
        sleep_s:    Polite delay before HTML/PDF fetch attempts

    Returns:
        SSRNPaper dict

    Raises:
        SSRNUnavailable: all strategies failed
    """
    ssrn_id = _extract_id(url_or_id)

    # Strategy 1: OpenAlex (always try first)
    paper = _fetch_openalex(ssrn_id)

    if paper and not full_text:
        if paper.get("abstract"):
            return paper
        # OpenAlex has title but no abstract yet (new paper indexing lag).
        # Try DDGS snippet then Playwright before giving up.
        print(f"  [ssrn] OA: no abstract -- trying DDGS for {ssrn_id}")
        ddgs_data = _fetch_via_ddgs(ssrn_id, title=paper.get("title", ""))
        if ddgs_data.get("abstract"):
            merged = dict(paper)
            merged["abstract"] = ddgs_data["abstract"]
            merged["pdf_url"]  = merged.get("pdf_url") or ddgs_data.get("pdf_url", "")
            merged["source"]   = "ddgs"
            print(f"  [ssrn] DDGS: {len(ddgs_data['abstract'])} chars")
            return SSRNPaper(**merged)

        print(f"  [ssrn] DDGS no abstract -- trying Playwright for {ssrn_id}")
        pw_data = _fetch_via_playwright(ssrn_id)
        if pw_data.get("abstract"):
            merged = dict(paper)
            for k in ("abstract", "title", "authors", "date", "pdf_url"):
                if not merged.get(k) and pw_data.get(k):
                    merged[k] = pw_data[k]
            merged["source"] = "playwright"
            print(f"  [ssrn] Playwright: {len(pw_data['abstract'])} chars")
            return SSRNPaper(**merged)

        print(f"  [ssrn] all abstract strategies failed -- returning title-only from OA")
        return paper

    # Strategy 2: PDF (bypasses Cloudflare, good for full text)
    if full_text:
        pdf_url = (paper or {}).get("pdf_url", "")
        if pdf_url:
            time.sleep(sleep_s)
            text = _fetch_pdf_text(pdf_url)
            if text:
                result = dict(paper or {})
                result["abstract"] = result.get("abstract") or text[:3000]
                result["full_text"] = text
                result["source"]    = "pdf"
                return SSRNPaper(**result)

    # Not found in OA at all -- try DDGS then Playwright before hitting ssrn.com
    if paper is None:
        ddgs_data = _fetch_via_ddgs(ssrn_id)
        if ddgs_data.get("abstract"):
            return SSRNPaper(
                ssrn_id  = ssrn_id,
                url      = _ssrn_url(ssrn_id),
                title    = "",
                abstract = ddgs_data["abstract"],
                authors  = "",
                date     = "",
                views    = "",
                downloads= "",
                pdf_url  = ddgs_data.get("pdf_url", ""),
                source   = "ddgs",
            )
        pw_data = _fetch_via_playwright(ssrn_id)
        if pw_data.get("abstract"):
            return SSRNPaper(
                ssrn_id  = ssrn_id,
                url      = _ssrn_url(ssrn_id),
                title    = pw_data.get("title", ""),
                abstract = pw_data["abstract"],
                authors  = pw_data.get("authors", ""),
                date     = pw_data.get("date", ""),
                views    = "",
                downloads= "",
                pdf_url  = pw_data.get("pdf_url", ""),
                source   = "playwright",
            )

    # Strategy 4: cloudscraper HTML (only for papers OpenAlex couldn't find at all)
    # Note: ssrn.com uses Cloudflare Managed Challenge -- this will 403 on most new papers.
    # Kept as a best-effort fallback for older papers not in OA.
    if paper is None:
        time.sleep(sleep_s)
        try:
            html_data = _fetch_html(ssrn_id)
            html_data["ssrn_id"] = ssrn_id
            html_data["url"]     = _ssrn_url(ssrn_id)
            return SSRNPaper(**html_data)
        except SSRNUnavailable as e:
            raise SSRNUnavailable(
                f"SSRN {ssrn_id} not in OpenAlex and CF blocked HTML: {e}\n"
                f"Paper may be too new (OA lag) or require authenticated access."
            )

    return paper


def fetch_batch(
    ids: list[str],
    full_text: bool = False,
    sleep_s: float = 1.5,
    max_workers: int = 3,
) -> list[SSRNPaper | None]:
    """
    Fetch multiple SSRN papers concurrently.
    max_workers capped at 3 — aggressive parallelism triggers CF rate limiting.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    max_workers = min(max_workers, 3)
    results: list[SSRNPaper | None] = [None] * len(ids)

    def _fetch(i: int, uid: str):
        try:
            return i, fetch_paper(uid, full_text=full_text, sleep_s=sleep_s)
        except SSRNUnavailable as e:
            print(f"  [ssrn] {uid}: unavailable -- {e}")
            return i, None
        except Exception as e:
            print(f"  [ssrn] {uid}: error -- {e}")
            return i, None

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_fetch, i, uid) for i, uid in enumerate(ids)]
        for fut in as_completed(futures):
            i, paper = fut.result()
            results[i] = paper

    return results


# ---------------------------------------------------------------------------
# Integration hook: called by agent.py fetch_url_content for ssrn.com URLs
# ---------------------------------------------------------------------------

def fetch_for_agent(url: str) -> str:
    """
    Drop-in for fetch_url_content when URL is ssrn.com.
    Returns a markdown-formatted string of the paper content.
    """
    try:
        paper = fetch_paper(url, full_text=False)
    except SSRNUnavailable as e:
        return f"[SSRN unavailable: {e}]"

    lines = [f"# {paper.get('title', 'Untitled')}"]
    if paper.get("authors"):
        lines.append(f"**Authors:** {paper['authors']}")
    if paper.get("date"):
        lines.append(f"**Date:** {paper['date']}")
    lines.append(f"**URL:** {paper.get('url', '')}")
    if paper.get("views") or paper.get("downloads"):
        lines.append(f"**Views:** {paper.get('views','')}  **Downloads:** {paper.get('downloads','')}")
    lines.append("")
    lines.append("## Abstract")
    lines.append(paper.get("abstract") or "_Abstract not available_")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CSV batch scraper (mirrors the original dummyscrape / scrape functions)
# ---------------------------------------------------------------------------

def scrape_id_range(
    start: int,
    stop: int,
    out_path: str = "ssrn_papers.csv",
    sleep_s: float = 1.5,
    max_workers: int = 3,
    chunk_size: int = 200,
) -> None:
    """
    Scrape a range of SSRN abstract_ids and write to CSV.
    Uses OpenAlex + cloudscraper waterfall, chunked to avoid memory buildup.
    max_workers=3 keeps well under Cloudflare's rate limits.
    """
    import time as _time

    fieldnames = ["ssrn_id", "url", "title", "abstract", "authors",
                  "date", "views", "downloads", "pdf_url", "source"]

    out = Path(out_path)
    write_header = not out.exists()
    total = stop - start
    written = 0

    print(f"[ssrn] scraping IDs {start}..{stop} ({total} papers) -> {out}")
    print(f"       workers={max_workers}  sleep={sleep_s}s  chunk={chunk_size}")

    with open(out, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if write_header:
            writer.writeheader()

        for chunk_start in range(start, stop, chunk_size):
            chunk_end = min(chunk_start + chunk_size, stop)
            ids = [str(i) for i in range(chunk_start, chunk_end)]
            t0  = _time.monotonic()

            papers = fetch_batch(ids, full_text=False, sleep_s=sleep_s,
                                 max_workers=max_workers)

            for paper in papers:
                if paper:
                    writer.writerow(paper)
                    written += 1

            elapsed = round(_time.monotonic() - t0, 1)
            print(f"  chunk {chunk_start}-{chunk_end}: {sum(1 for p in papers if p)} written  ({elapsed}s)")

    print(f"[ssrn] done. {written}/{total} papers written -> {out}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="SSRN paper fetcher")
    ap.add_argument("target", nargs="?", help="SSRN ID or URL")
    ap.add_argument("--batch",      default=None, help="Text file of SSRN IDs (one per line)")
    ap.add_argument("--range",      nargs=2, metavar=("START", "STOP"), type=int,
                    help="Scrape integer ID range [START, STOP)")
    ap.add_argument("--out",        default="ssrn_papers.csv")
    ap.add_argument("--full-text",  action="store_true")
    ap.add_argument("--workers",    type=int, default=3)
    ap.add_argument("--sleep",      type=float, default=1.5)
    args = ap.parse_args()

    if args.range:
        scrape_id_range(args.range[0], args.range[1],
                        out_path=args.out, sleep_s=args.sleep, max_workers=args.workers)

    elif args.batch:
        ids = [l.strip() for l in Path(args.batch).read_text().splitlines()
               if l.strip() and not l.startswith("#")]
        papers = fetch_batch(ids, full_text=args.full_text,
                             sleep_s=args.sleep, max_workers=args.workers)
        fieldnames = ["ssrn_id", "url", "title", "abstract", "authors",
                      "date", "views", "downloads", "pdf_url", "source"]
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            for p in papers:
                if p:
                    w.writerow(p)
        print(f"Wrote {sum(1 for p in papers if p)} papers -> {args.out}")

    elif args.target:
        paper = fetch_paper(args.target, full_text=args.full_text)
        print(fetch_for_agent(args.target))
        print(f"\nsource: {paper.get('source')}  pdf_url: {paper.get('pdf_url','')}")

    else:
        ap.print_help()


if __name__ == "__main__":
    main()

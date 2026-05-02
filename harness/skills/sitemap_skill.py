"""
sitemap_skill.py — lightweight page discovery for a web domain.

Discovery pipeline (fastest first):
  1. GET /robots.txt  — look for "Sitemap:" directive (1 request)
  2. Parse that sitemap URL (or try /sitemap.xml directly)
  3. DDGS "site:domain" search — returns indexed pages with titles (~1-2s, no crawl)
  4. BFS HTML crawl — slow fallback, capped at max_pages

Used by the playwright navigator before the navigation loop so the LLM
can pick the right page directly instead of clicking around blind.

Slash command: /sitemap <url> [goal]
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import deque
from urllib.parse import urljoin, urlparse

import requests

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; HarnessBot/1.0)"
})
_TIMEOUT = 6


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(url: str) -> str:
    if not url.startswith("http"):
        url = "https://" + url
    return url.split("#")[0].rstrip("/")


def _base(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _domain(url: str) -> str:
    return urlparse(url).netloc


# ---------------------------------------------------------------------------
# robots.txt → sitemap URL discovery
# ---------------------------------------------------------------------------

def find_sitemap_from_robots(start_url: str) -> str | None:
    """Parse /robots.txt for a Sitemap: directive. Returns the URL or None."""
    robots_url = _base(start_url) + "/robots.txt"
    try:
        resp = _SESSION.get(robots_url, timeout=_TIMEOUT)
        resp.raise_for_status()
        for line in resp.text.splitlines():
            if line.lower().startswith("sitemap:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# DDGS "site:" search — fast, no crawl, returns indexed pages with titles
# ---------------------------------------------------------------------------

def discover_via_search(start_url: str, max_results: int = 50) -> list[dict]:
    """
    Use DuckDuckGo site: operator to discover indexed pages on a domain.
    Returns list of {url, title, body} — much faster than crawling.
    """
    try:
        from ddgs import DDGS
    except ImportError:
        return []

    domain = _domain(start_url)
    # Scope to the path if given (e.g. site:anthropic.com/research)
    parsed = urlparse(start_url if start_url.startswith("http") else "https://" + start_url)
    scope = domain + (parsed.path if parsed.path and parsed.path != "/" else "")
    query = f"site:{scope}"

    try:
        ddgs = DDGS()
        raw = list(ddgs.text(query, max_results=max_results))
    except Exception:
        return []

    results = []
    seen: set[str] = set()
    for r in raw:
        url = _normalize(r.get("href", ""))
        if not url or url in seen:
            continue
        if _domain(url) != domain:
            continue
        seen.add(url)
        results.append({
            "url":   url,
            "title": r.get("title", "")[:100],
            "body":  r.get("body", "")[:150],
            "depth": 0,
        })
    return results


# ---------------------------------------------------------------------------
# sitemap.xml parser
# ---------------------------------------------------------------------------

def _parse_sitemap_xml(content: bytes) -> list[str]:
    """Extract <loc> URLs from a sitemap or sitemap-index document."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    # sitemap index → nested <sitemap><loc>
    locs = [el.text.strip() for el in root.findall(".//sm:loc", ns) if el.text]
    return locs


def try_sitemap_xml(start_url: str, max_pages: int = 80) -> list[dict]:
    """Fetch and parse /sitemap.xml (and sitemap-index children).
    Returns list of {url, title} dicts; titles left empty (fast path)."""
    base = _base(start_url)
    # If robots.txt gave us a specific sitemap URL, try it first
    candidates = []
    if start_url != base and start_url != base + "/" and ".xml" in start_url:
        candidates.append(start_url)
    candidates += [base + "/sitemap.xml", base + "/sitemap_index.xml"]
    # deduplicate preserving order
    seen: set[str] = set()
    candidates = [c for c in candidates if not (c in seen or seen.add(c))]
    all_urls: list[str] = []

    for sitemap_url in candidates:
        try:
            resp = _SESSION.get(sitemap_url, timeout=_TIMEOUT)
            resp.raise_for_status()
        except Exception:
            continue

        locs = _parse_sitemap_xml(resp.content)
        if not locs:
            continue

        # Detect sitemap-index: all locs end in .xml
        if all(u.endswith(".xml") for u in locs[:5]):
            # Sample proportionally across all partitions so we don't just get
            # the first partition's pages (which may be a single topic)
            sub_urls = locs[:12]
            budget = max(8, max_pages // len(sub_urls))
            for sub_url in sub_urls:
                try:
                    sub = _SESSION.get(sub_url, timeout=_TIMEOUT)
                    all_urls.extend(_parse_sitemap_xml(sub.content)[:budget])
                    if len(all_urls) >= max_pages:
                        break
                except Exception:
                    continue
        else:
            all_urls.extend(locs)

        if all_urls:
            break

    seen: set[str] = set()
    results: list[dict] = []
    for u in all_urls:
        u = _normalize(u)
        if u not in seen and _domain(u) == _domain(start_url):
            seen.add(u)
            results.append({"url": u, "title": "", "depth": 0})
        if len(results) >= max_pages:
            break

    return results


# ---------------------------------------------------------------------------
# BFS HTML crawl (fallback)
# ---------------------------------------------------------------------------

def crawl_bfs(start_url: str, max_pages: int = 30, max_depth: int = 2) -> list[dict]:
    """BFS crawl staying within the same domain. Returns {url, title, depth}."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    domain = _domain(start_url)
    visited: set[str] = set()
    queue: deque = deque([(start_url, 0)])
    results: list[dict] = []

    while queue and len(visited) < max_pages:
        url, depth = queue.popleft()
        url = _normalize(url)
        if url in visited or depth > max_depth:
            continue

        try:
            resp = _SESSION.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
            if "html" not in resp.headers.get("content-type", ""):
                continue
        except Exception:
            continue

        visited.add(url)
        try:
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception:
            soup = None

        title = ""
        if soup:
            t = soup.find("title")
            title = t.get_text(strip=True)[:100] if t else ""

        results.append({"url": url, "title": title, "depth": depth})

        if depth < max_depth and soup:
            for a in soup.find_all("a", href=True):
                full = _normalize(urljoin(url, a["href"]))
                p = urlparse(full)
                if (p.netloc == domain and p.scheme in ("http", "https")
                        and full not in visited):
                    queue.append((full, depth + 1))

    return results


# ---------------------------------------------------------------------------
# Title enrichment (optional, for BFS pages without titles)
# ---------------------------------------------------------------------------

def _enrich_titles(pages: list[dict], max_fetch: int = 20):
    """Fetch page titles for entries that have none (sitemap.xml path)."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return

    fetched = 0
    for page in pages:
        if page.get("title") or fetched >= max_fetch:
            continue
        try:
            resp = _SESSION.get(page["url"], timeout=_TIMEOUT)
            soup = BeautifulSoup(resp.text, "html.parser")
            t = soup.find("title")
            page["title"] = t.get_text(strip=True)[:100] if t else ""
            fetched += 1
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def discover_pages(start_url: str, max_pages: int = 60,
                   enrich_titles: bool = True, quick: bool = False) -> list[dict]:
    """
    Discover pages on a domain using the fastest available method:

      1. robots.txt  → sitemap URL  (1 request)
      2. /sitemap.xml               (1 request)
      3. DDGS site: search          (~1-2s, no crawl, returns titles)
      4. BFS crawl                  (slow; skipped when quick=True)

    quick=True: stops after step 3, never crawls. Use from the navigator.
    """
    start_url = _normalize(start_url)
    domain    = _domain(start_url)

    # 1. robots.txt → sitemap URL
    sitemap_url = find_sitemap_from_robots(start_url)
    if sitemap_url:
        print(f"  [sitemap] found via robots.txt: {sitemap_url[:60]}")
    else:
        print("  [sitemap] no Sitemap: in robots.txt — trying /sitemap.xml")

    # 2. Parse sitemap.xml (from robots.txt hint or default path)
    pages = try_sitemap_xml(sitemap_url or start_url, max_pages=max_pages)
    if pages:
        print(f"  [sitemap] {len(pages)} URL(s) from sitemap.xml")
        if enrich_titles and not quick:
            print("  [sitemap] enriching titles (up to 20)...")
            _enrich_titles(pages, max_fetch=20)
        return pages

    # 3. DDGS site: search — fast, no crawl
    print(f"  [sitemap] no sitemap.xml — trying DDGS site:{domain} search...")
    pages = discover_via_search(start_url, max_results=min(max_pages, 50))
    if pages:
        print(f"  [sitemap] {len(pages)} URL(s) from site: search")
        return pages

    # 4. BFS crawl (slow — skipped in quick mode)
    if quick:
        print("  [sitemap] DDGS returned nothing — skipping BFS (quick mode)")
        return []

    print(f"  [sitemap] DDGS empty — BFS crawl (max {max_pages})...")
    pages = crawl_bfs(start_url, max_pages=max_pages)
    print(f"  [sitemap] {len(pages)} page(s) via crawl")
    return pages


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_for_navigator(pages: list[dict], max_entries: int = 50) -> str:
    """Compact numbered list for injection into the navigator LLM prompt."""
    if not pages:
        return ""
    shown = pages[:max_entries]
    lines = []
    for i, p in enumerate(shown):
        meta = ""
        if p.get("title"):
            meta += f"  [{p['title']}]"
        if p.get("body"):
            meta += f"  — {p['body'][:80]}"
        lines.append(f"  {i+1:3d}. {p['url']}{meta}")
    extra = f"\n  ... and {len(pages) - max_entries} more" if len(pages) > max_entries else ""
    return (
        f"Pages available on this domain ({len(pages)} discovered):\n"
        + "\n".join(lines) + extra
    )


def format_as_markdown(pages: list[dict], domain: str) -> str:
    """Full markdown report for /sitemap standalone output."""
    lines = [f"# Site Map: {domain}", "", f"**{len(pages)} page(s) discovered.**", ""]
    for p in pages:
        title = p.get("title") or p["url"]
        lines.append(f"- [{title}]({p['url']})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Relevance filter — score pages against a goal string
# ---------------------------------------------------------------------------

_STOP = frozenset({
    # articles / prepositions / conjunctions
    "the", "a", "an", "and", "or", "for", "to", "in", "of", "is",
    "are", "on", "at", "by", "with", "from", "as", "be", "this", "that",
    "it", "its",
    # meta-instruction words that describe the request, not the content
    "find", "show", "get", "list", "search", "look", "discover", "need",
    "want", "how", "what", "best", "all",
})


def score_page(page: dict, goal_tokens: set[str]) -> int:
    """Score a page dict by token overlap with the goal."""
    text = (page["url"] + " " + page.get("title", "")).lower()
    tokens = set(re.findall(r"[a-z]+", text)) - _STOP
    return len(tokens & goal_tokens)


def rank_by_goal(pages: list[dict], goal: str, top_n: int = 10) -> tuple[list[dict], int]:
    """Return (top_n pages sorted by goal relevance, count of pages with score > 0)."""
    goal_tokens = set(re.findall(r"[a-z]+", goal.lower())) - _STOP
    scored = [(score_page(p, goal_tokens), p) for p in pages]
    scored.sort(key=lambda x: -x[0])
    n_matched = sum(1 for s, _ in scored if s > 0)
    return [p for _, p in scored[:top_n]], n_matched

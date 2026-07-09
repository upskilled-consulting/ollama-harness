"""GET /api/research-history  POST /api/research-history/ingest"""

import asyncio
import os
import shutil
import sqlite3
import tempfile
import time
from datetime import UTC, datetime
from urllib.error import URLError
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from fastapi import APIRouter, Query
from pydantic import BaseModel

from harness import search_cache as sc
from harness.memory import MemoryStore, compress

router = APIRouter(tags=["research_history"])

_CHROME_HISTORY = os.path.expandvars(
    r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\History"
)
_CHROME_EPOCH_OFFSET_S = 11_644_473_600  # seconds between 1601-01-01 and 1970-01-01


# ---------------------------------------------------------------------------
# Chrome history reader
# ---------------------------------------------------------------------------

def _chrome_ts_to_iso(chrome_ts: int) -> str:
    try:
        unix_s = chrome_ts / 1_000_000 - _CHROME_EPOCH_OFFSET_S
        return datetime.fromtimestamp(unix_s, UTC).isoformat()
    except Exception:
        return ""


def _get_chrome_history(since_ts: float = 0.0, limit: int = 200) -> list[dict]:
    if not os.path.exists(_CHROME_HISTORY):
        return []
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        shutil.copy2(_CHROME_HISTORY, tmp_path)
        conn = sqlite3.connect(tmp_path)
        conn.row_factory = sqlite3.Row
        chrome_since = int((since_ts + _CHROME_EPOCH_OFFSET_S) * 1_000_000) if since_ts > 0 else 0
        rows = conn.execute(
            "SELECT url, title, visit_count, last_visit_time FROM urls "
            "WHERE last_visit_time > ? "
            "  AND url NOT LIKE 'chrome://%' "
            "  AND url NOT LIKE 'chrome-extension://%' "
            "  AND url NOT LIKE 'about:%' "
            "ORDER BY last_visit_time DESC LIMIT ?",
            (chrome_since, limit),
        ).fetchall()
        conn.close()
        return [
            {
                "url":         r["url"],
                "title":       (r["title"] or r["url"])[:120],
                "visit_count": r["visit_count"],
                "timestamp":   _chrome_ts_to_iso(r["last_visit_time"]),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[research_history] chrome history read failed: {e}")
        return []
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# URL fetcher (fast path — no LLM evaluation loop)
# ---------------------------------------------------------------------------

def _fetch_url_text(url: str, timeout: int = 10) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; harness/1.0)"})
    resp = urlopen(req, timeout=timeout)
    html = resp.read().decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)[:8_000]


# ---------------------------------------------------------------------------
# In-memory annotation (batch)
# ---------------------------------------------------------------------------

def _annotate_in_memory(store: MemoryStore, items: list[dict]) -> None:
    """Set in_memory / memory_id on each item by checking observations.task."""
    keys = [item.get("url") or item.get("title", "") for item in items]
    keys = [k for k in keys if k]
    if not keys:
        return
    placeholders = ",".join("?" * len(keys))
    try:
        with store._connect() as conn:
            rows = conn.execute(
                f"SELECT id, task FROM observations WHERE task IN ({placeholders})",
                keys,
            ).fetchall()
        in_mem = {row["task"]: row["id"] for row in rows}
    except Exception:
        in_mem = {}
    for item in items:
        key = item.get("url") or item.get("title", "")
        if key in in_mem:
            item["in_memory"] = True
            item["memory_id"] = in_mem[key]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/research-history")
async def get_research_history(
    q:      str   = Query(default=""),
    since:  float = Query(default=0.0),
    source: str   = Query(default="all"),
    limit:  int   = Query(default=50, le=200),
):
    """
    Unified semantic search over search cache, research cache, and Chrome history.

    q      — natural-language query (empty = return by recency)
    since  — unix timestamp lower bound (0 = no limit)
    source — "search" | "research" | "browser" | "all"
    limit  — max results (capped at 200)
    """
    results: list[dict] = []

    if source in ("search", "research", "all"):
        cache_source = source if source in ("search", "research") else "all"
        entries = await asyncio.to_thread(
            sc.semantic_search_entries, q, limit, since, cache_source
        )
        results.extend(entries)

    if source in ("browser", "all"):
        browser_items = await asyncio.to_thread(_get_chrome_history, since, limit)
        q_words = q.lower().split() if q else []
        for item in browser_items:
            sim = 1.0
            if q_words:
                haystack = (item["title"] + " " + item["url"]).lower()
                hits = sum(1 for w in q_words if w in haystack)
                sim = round(min(1.0, hits / len(q_words)), 3)
            results.append({
                "source":     "browser",
                "id":         item["url"],
                "title":      item["title"],
                "snippet":    f"visits: {item['visit_count']}",
                "timestamp":  item["timestamp"],
                "similarity": sim,
                "url":        item["url"],
                "in_memory":  False,
                "memory_id":  None,
            })

    # Default fields for cache entries
    for item in results:
        item.setdefault("url",       None)
        item.setdefault("in_memory", False)
        item.setdefault("memory_id", None)

    store = MemoryStore()
    _annotate_in_memory(store, results)

    if q:
        results.sort(key=lambda x: x["similarity"], reverse=True)
    else:
        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    return results[:limit]


class IngestRequest(BaseModel):
    urls: list[str]


@router.post("/research-history/ingest")
async def ingest_urls(body: IngestRequest):
    """
    Fast-path ingest: fetch URL text -> single LLM compress call -> store_direct.
    No wiggum evaluation. Caps at 20 URLs per call.
    """
    store = MemoryStore()
    out = []

    for url in body.urls[:20]:
        try:
            text = await asyncio.to_thread(_fetch_url_text, url)
        except (URLError, Exception) as e:
            out.append({"url": url, "status": "fetch_error", "error": str(e)[:120]})
            continue

        try:
            obs = await asyncio.to_thread(
                compress,
                url, "browser_history", [], text,
                text.count("\n"), len(text.encode()), [],
            )
            mid = store.store_direct(
                task=url,
                task_type="browser_history",
                title=obs["title"],
                narrative=obs["narrative"],
                facts=obs.get("facts", []),
                final_score=None,
                final="PASS",
            )
            status = "duplicate" if mid == -1 else "ok"
            out.append({"url": url, "status": status, "memory_id": mid})
        except Exception as e:
            out.append({"url": url, "status": "compress_error", "error": str(e)[:120]})

    return {"results": out}

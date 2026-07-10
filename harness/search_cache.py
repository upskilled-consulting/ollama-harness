"""
harness/search_cache.py — SQLite-backed TTL cache for DDGS search results and research contexts.

Tables:
  search_cache    — per-query DDGS results (key = SHA-256 of normalised query)
  research_cache  — full gather_research() output (key = SHA-256 of task + task_type)
                    Opt-in: only active when RESEARCH_CACHE=1 env var is set.
                    Set by autoresearch.py so interactive runs are unaffected.

ChromaDB layer (search_cache_vec / research_cache_vec):
  Semantic fallback on exact-key miss: if a sufficiently similar query has been
  cached, return those results rather than hitting DDGS again.
  Also powers GET /api/research-history semantic search.

Usage:
    from harness.search_cache import cached_search, get_research, put_research

    # Search result cache (always active):
    results = cached_search(
        query="best practices for RAG pipelines",
        search_fn=lambda q, n: list(DDGS().text(q, max_results=n)),
        ttl=86400,
        max_results=10,
    )

    # Research context cache (autoresearch only):
    hit = get_research(task, task_type)   # -> dict | None
    put_research(task, task_type, context, search_rounds, novelty_scores)

CLI:
    python -m harness.search_cache            # print stats (both tables)
    python -m harness.search_cache --clear    # delete all entries (both tables)
    python -m harness.search_cache --expired  # delete only expired entries
"""

import hashlib
import json
import os
import sqlite3
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime

from harness.config import CHROMA_DIR, SEARCH_CACHE_DB

DB_PATH     = str(SEARCH_CACHE_DB)
DEFAULT_TTL = 86_400   # 24 hours in seconds

SEMANTIC_CACHE_THRESHOLD  = 0.15   # cosine distance; below this = "same query, different words"
SEARCH_CHROMA_COLLECTION  = "search_cache_vec"
RESEARCH_CHROMA_COLLECTION = "research_cache_vec"


# ---------------------------------------------------------------------------
# DB init
# ---------------------------------------------------------------------------

def _migrate(conn: sqlite3.Connection, table: str, col_defs: list[str]):
    """Add any missing columns to table. Safe to call on fresh or existing tables."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for col_def in col_defs:
        col_name = col_def.split()[0]
        if col_name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
    conn.commit()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS search_cache (
            key        TEXT PRIMARY KEY,
            query      TEXT NOT NULL,
            results    TEXT NOT NULL,
            created_at REAL NOT NULL DEFAULT 0,
            expires_at REAL NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS research_cache (
            key            TEXT PRIMARY KEY,
            task           TEXT NOT NULL,
            task_type      TEXT NOT NULL,
            context        TEXT NOT NULL,
            search_rounds  INTEGER NOT NULL DEFAULT 0,
            novelty_scores TEXT NOT NULL DEFAULT '[]',
            created_at     REAL NOT NULL DEFAULT 0,
            expires_at     REAL NOT NULL DEFAULT 0
        )
    """)
    conn.commit()

    _migrate(conn, "search_cache",   ["created_at REAL NOT NULL DEFAULT 0",
                                      "expires_at REAL NOT NULL DEFAULT 0"])
    _migrate(conn, "research_cache", ["created_at REAL NOT NULL DEFAULT 0",
                                      "expires_at REAL NOT NULL DEFAULT 0",
                                      "search_rounds INTEGER NOT NULL DEFAULT 0",
                                      "novelty_scores TEXT NOT NULL DEFAULT '[]'"])

    conn.execute("CREATE INDEX IF NOT EXISTS idx_expires    ON search_cache(expires_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_expires ON research_cache(expires_at)")
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# ChromaDB — lazy singletons
# ---------------------------------------------------------------------------

_chroma_client  = None
_search_col     = None
_research_col   = None


def _cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


def _chroma_ef():
    device = "cuda" if _cuda_available() else "cpu"
    try:
        from harness.inference import get_embedding_function
        return get_embedding_function(device=device)
    except Exception:
        from chromadb.utils import embedding_functions
        return embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2", device=device
        )


def _get_search_col():
    global _chroma_client, _search_col
    if _search_col is not None:
        return _search_col
    try:
        import chromadb
        _chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _search_col = _chroma_client.get_or_create_collection(
            name=SEARCH_CHROMA_COLLECTION,
            embedding_function=_chroma_ef(),
            metadata={"hnsw:space": "cosine"},
        )
        return _search_col
    except Exception as e:
        print(f"[search_cache] ChromaDB unavailable: {e}")
        return None


def _get_research_col():
    global _chroma_client, _research_col
    if _research_col is not None:
        return _research_col
    try:
        import chromadb
        if _chroma_client is None:
            _chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _research_col = _chroma_client.get_or_create_collection(
            name=RESEARCH_CHROMA_COLLECTION,
            embedding_function=_chroma_ef(),
            metadata={"hnsw:space": "cosine"},
        )
        return _research_col
    except Exception as e:
        print(f"[search_cache] research ChromaDB unavailable: {e}")
        return None


def _ts_to_iso(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts, UTC).isoformat()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

def _cache_key(query: str) -> str:
    """SHA-256 of lower-cased, whitespace-normalised query."""
    normalised = " ".join(query.lower().split())
    return hashlib.sha256(normalised.encode()).hexdigest()


def get(query: str) -> list[dict] | None:
    """Return cached results for query, or None if missing/expired.
    Tries exact SHA-256 match first, then semantic fallback via ChromaDB."""
    key = _cache_key(query)
    now = time.time()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT results, expires_at FROM search_cache WHERE key = ?", (key,)
        ).fetchone()
        if row is not None:
            results_json, expires_at = row
            if expires_at < now:
                conn.execute("DELETE FROM search_cache WHERE key = ?", (key,))
                conn.commit()
            else:
                return json.loads(results_json)

        # Semantic fallback
        col = _get_search_col()
        if col is not None and col.count() > 0:
            try:
                r = col.query(query_texts=[query], n_results=1, include=["distances"])
                if r["ids"] and r["ids"][0]:
                    nearest_key = r["ids"][0][0]
                    dist = r["distances"][0][0]
                    if dist < SEMANTIC_CACHE_THRESHOLD:
                        hit = conn.execute(
                            "SELECT results, expires_at FROM search_cache WHERE key = ?",
                            (nearest_key,),
                        ).fetchone()
                        if hit is not None and hit[1] >= now:
                            print(f"[cache SEM ] {query[:60]}  (dist={dist:.3f})")
                            return json.loads(hit[0])
            except Exception as e:
                print(f"[search_cache] semantic get error: {e}")
        return None
    finally:
        conn.close()


def put(query: str, results: list[dict], ttl: int = DEFAULT_TTL) -> None:
    """Store results for query with given TTL; also evict expired rows."""
    key  = _cache_key(query)
    now  = time.time()
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO search_cache (key, query, results, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                results    = excluded.results,
                created_at = excluded.created_at,
                expires_at = excluded.expires_at
            """,
            (key, query, json.dumps(results, ensure_ascii=False), now, now + ttl),
        )
        conn.execute("DELETE FROM search_cache WHERE expires_at < ?", (now,))
        conn.commit()
    finally:
        conn.close()

    col = _get_search_col()
    if col is not None:
        try:
            col.upsert(
                ids=[key],
                documents=[query],
                metadatas=[{"query": query[:500], "created_at": now, "expires_at": now + ttl}],
            )
        except Exception as e:
            print(f"[search_cache] ChromaDB upsert failed: {e}")


# ---------------------------------------------------------------------------
# High-level helper
# ---------------------------------------------------------------------------

def cached_search(
    query: str,
    search_fn: Callable[[str, int], list[dict]],
    ttl: int = DEFAULT_TTL,
    max_results: int = 10,
) -> list[dict]:
    """
    Return cached results for query if available, otherwise call search_fn,
    store the results, and return them.

    Args:
        query:       search query string
        search_fn:   callable(query, max_results) -> list[dict]
        ttl:         cache lifetime in seconds (default 24 h)
        max_results: passed to search_fn on cache miss

    Returns:
        list of result dicts (same shape as DDGS().text() output)
    """
    cached = get(query)
    if cached is not None:
        print(f"[cache HIT ] {query[:60]}")
        return cached

    print(f"[cache MISS] {query[:60]}")
    results = search_fn(query, max_results)
    if results:
        put(query, results, ttl=ttl)
    return results


# ---------------------------------------------------------------------------
# Research context cache  (opt-in: RESEARCH_CACHE=1)
# ---------------------------------------------------------------------------

def _research_key(task: str, task_type: str) -> str:
    """SHA-256 of normalised task + task_type."""
    normalised = " ".join(task.lower().split()) + "|" + task_type.lower().strip()
    return hashlib.sha256(normalised.encode()).hexdigest()


def get_research(task: str, task_type: str) -> dict | None:
    """
    Return cached research context for (task, task_type), or None if missing/expired.
    Returns dict with keys: context, search_rounds, novelty_scores.
    Tries exact match first, then semantic fallback.
    """
    key  = _research_key(task, task_type)
    now  = time.time()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT context, search_rounds, novelty_scores, expires_at "
            "FROM research_cache WHERE key = ?", (key,)
        ).fetchone()
        if row is not None:
            context, search_rounds, novelty_json, expires_at = row
            if expires_at < now:
                conn.execute("DELETE FROM research_cache WHERE key = ?", (key,))
                conn.commit()
            else:
                print(f"[rcache HIT ] {task[:60]}")
                return {
                    "context":        context,
                    "search_rounds":  search_rounds,
                    "novelty_scores": json.loads(novelty_json),
                }

        # Semantic fallback
        col = _get_research_col()
        if col is not None and col.count() > 0:
            try:
                r = col.query(query_texts=[task], n_results=1, include=["distances", "metadatas"])
                if r["ids"] and r["ids"][0]:
                    nearest_key = r["ids"][0][0]
                    dist        = r["distances"][0][0]
                    meta        = r["metadatas"][0][0]
                    if dist < SEMANTIC_CACHE_THRESHOLD and meta.get("task_type") == task_type:
                        hit = conn.execute(
                            "SELECT context, search_rounds, novelty_scores, expires_at "
                            "FROM research_cache WHERE key = ?", (nearest_key,)
                        ).fetchone()
                        if hit is not None and hit[3] >= now:
                            print(f"[rcache SEM] {task[:60]}  (dist={dist:.3f})")
                            return {
                                "context":        hit[0],
                                "search_rounds":  hit[1],
                                "novelty_scores": json.loads(hit[2]),
                            }
            except Exception as e:
                print(f"[search_cache] research semantic get error: {e}")
        return None
    finally:
        conn.close()


def put_research(
    task: str,
    task_type: str,
    context: str,
    search_rounds: int,
    novelty_scores: list,
    ttl: int = DEFAULT_TTL,
) -> None:
    """Store full gather_research() output for (task, task_type)."""
    key  = _research_key(task, task_type)
    now  = time.time()
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO research_cache
                (key, task, task_type, context, search_rounds, novelty_scores, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                context        = excluded.context,
                search_rounds  = excluded.search_rounds,
                novelty_scores = excluded.novelty_scores,
                created_at     = excluded.created_at,
                expires_at     = excluded.expires_at
            """,
            (key, task, task_type, context, search_rounds,
             json.dumps(novelty_scores), now, now + ttl),
        )
        conn.execute("DELETE FROM research_cache WHERE expires_at < ?", (now,))
        conn.commit()
    finally:
        conn.close()

    col = _get_research_col()
    if col is not None:
        try:
            col.upsert(
                ids=[key],
                documents=[task],
                metadatas=[{
                    "task":             task[:500],
                    "task_type":        task_type,
                    "context_snippet":  context[:200],
                    "created_at":       now,
                    "expires_at":       now + ttl,
                }],
            )
        except Exception as e:
            print(f"[search_cache] research ChromaDB upsert failed: {e}")


# ---------------------------------------------------------------------------
# Semantic search — for GET /api/research-history
# ---------------------------------------------------------------------------

def semantic_search_entries(
    query: str,
    n: int = 50,
    since_ts: float = 0.0,
    source: str = "all",
) -> list[dict]:
    """
    Semantic search over search_cache and/or research_cache.
    If query is empty, returns entries by recency.

    Returns list of dicts:
      source, id, title, snippet, timestamp, similarity, url (None for cache entries)
    """
    results: list[dict] = []
    now = time.time()
    fetch_n = min(n * 3, 300)

    if source in ("search", "all"):
        if query:
            col = _get_search_col()
            if col is not None and col.count() > 0:
                try:
                    r = col.query(
                        query_texts=[query],
                        n_results=min(fetch_n, col.count()),
                        include=["distances", "documents", "metadatas"],
                    )
                    for _id, dist, doc, meta in zip(
                        r["ids"][0], r["distances"][0],
                        r["documents"][0], r["metadatas"][0]
                    ):
                        if meta.get("expires_at", 0) < now:
                            continue
                        if since_ts > 0 and meta.get("created_at", 0) < since_ts:
                            continue
                        sim = max(0.0, 1.0 - dist)
                        results.append({
                            "source":     "search",
                            "id":         _id,
                            "title":      meta.get("query") or doc or _id,
                            "snippet":    "",
                            "timestamp":  _ts_to_iso(meta.get("created_at", 0)),
                            "similarity": round(sim, 3),
                            "url":        None,
                        })
                except Exception as e:
                    print(f"[search_cache] semantic search error: {e}")
        else:
            conn = _connect()
            try:
                rows = conn.execute(
                    "SELECT key, query, created_at FROM search_cache "
                    "WHERE expires_at > ? AND created_at >= ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (now, since_ts, n),
                ).fetchall()
                for row in rows:
                    results.append({
                        "source":     "search",
                        "id":         row[0],
                        "title":      row[1],
                        "snippet":    "",
                        "timestamp":  _ts_to_iso(row[2]),
                        "similarity": 1.0,
                        "url":        None,
                    })
            finally:
                conn.close()

    if source in ("research", "all"):
        if query:
            col = _get_research_col()
            if col is not None and col.count() > 0:
                try:
                    r = col.query(
                        query_texts=[query],
                        n_results=min(fetch_n, col.count()),
                        include=["distances", "documents", "metadatas"],
                    )
                    for _id, dist, doc, meta in zip(
                        r["ids"][0], r["distances"][0],
                        r["documents"][0], r["metadatas"][0]
                    ):
                        if meta.get("expires_at", 0) < now:
                            continue
                        if since_ts > 0 and meta.get("created_at", 0) < since_ts:
                            continue
                        sim = max(0.0, 1.0 - dist)
                        results.append({
                            "source":     "research",
                            "id":         _id,
                            "title":      meta.get("task") or doc or _id,
                            "snippet":    meta.get("context_snippet", ""),
                            "timestamp":  _ts_to_iso(meta.get("created_at", 0)),
                            "similarity": round(sim, 3),
                            "url":        None,
                        })
                except Exception as e:
                    print(f"[search_cache] research semantic search error: {e}")
        else:
            conn = _connect()
            try:
                rows = conn.execute(
                    "SELECT key, task, task_type, created_at FROM research_cache "
                    "WHERE expires_at > ? AND created_at >= ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (now, since_ts, n),
                ).fetchall()
                for row in rows:
                    results.append({
                        "source":     "research",
                        "id":         row[0],
                        "title":      row[1],
                        "snippet":    f"type: {row[2]}",
                        "timestamp":  _ts_to_iso(row[3]),
                        "similarity": 1.0,
                        "url":        None,
                    })
            finally:
                conn.close()

    if query:
        results.sort(key=lambda x: x["similarity"], reverse=True)
    else:
        results.sort(key=lambda x: x["timestamp"], reverse=True)

    return results[:n]


# ---------------------------------------------------------------------------
# Management helpers
# ---------------------------------------------------------------------------

def stats() -> dict:
    """Return cache statistics for both tables."""
    now  = time.time()
    conn = _connect()
    try:
        sc_total   = conn.execute("SELECT COUNT(*) FROM search_cache").fetchone()[0]
        sc_expired = conn.execute(
            "SELECT COUNT(*) FROM search_cache WHERE expires_at < ?", (now,)
        ).fetchone()[0]
        rc_total   = conn.execute("SELECT COUNT(*) FROM research_cache").fetchone()[0]
        rc_expired = conn.execute(
            "SELECT COUNT(*) FROM research_cache WHERE expires_at < ?", (now,)
        ).fetchone()[0]
        size_kb = os.path.getsize(DB_PATH) // 1024 if os.path.exists(DB_PATH) else 0

        sc_chroma = rc_chroma = 0
        try:
            col = _get_search_col()
            if col:
                sc_chroma = col.count()
            col = _get_research_col()
            if col:
                rc_chroma = col.count()
        except Exception:
            pass

        return {
            "search":   {"total": sc_total, "expired": sc_expired, "live": sc_total - sc_expired, "chroma": sc_chroma},
            "research": {"total": rc_total, "expired": rc_expired, "live": rc_total - rc_expired, "chroma": rc_chroma},
            "size_kb":  size_kb,
        }
    finally:
        conn.close()


def clear_all() -> int:
    """Delete all entries from both tables. Returns total count deleted."""
    conn = _connect()
    try:
        n  = conn.execute("DELETE FROM search_cache").rowcount
        n += conn.execute("DELETE FROM research_cache").rowcount
        conn.commit()
        return n
    finally:
        conn.close()


def clear_expired() -> int:
    """Delete only expired entries from both tables. Returns total count deleted."""
    now  = time.time()
    conn = _connect()
    try:
        n  = conn.execute("DELETE FROM search_cache  WHERE expires_at < ?", (now,)).rowcount
        n += conn.execute("DELETE FROM research_cache WHERE expires_at < ?", (now,)).rowcount
        conn.commit()
        return n
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--clear" in args:
        n = clear_all()
        print(f"[search_cache] cleared {n} entries (both tables)")
    elif "--expired" in args:
        n = clear_expired()
        print(f"[search_cache] cleared {n} expired entries (both tables)")
    else:
        s = stats()
        sc = s["search"]
        rc = s["research"]
        print(f"[search_cache]   queries: {sc['live']} live / {sc['expired']} expired / {sc['total']} total  ({sc['chroma']} in chroma)")
        print(f"[research_cache] contexts: {rc['live']} live / {rc['expired']} expired / {rc['total']} total  ({rc['chroma']} in chroma)")
        print(f"[db] {s['size_kb']} KB  ({DB_PATH})")

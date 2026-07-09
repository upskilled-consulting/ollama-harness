"""
harness.beige_book_tool — query the local Federal Reserve Beige Book corpus.

Data lives in harness-engineering by default; override with env vars:
    BEIGE_BOOK_DB      path to beige_book.db  (SQLite FTS5)
    BEIGE_BOOK_CHROMA  path to chroma_memory/ directory

Run standalone to smoke-test:
    python -m harness.beige_book_tool "labor markets in 2022"
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys

_DEFAULT_ROOT = os.path.expanduser("~/Desktop/harness-engineering")

DB_PATH    = os.environ.get("BEIGE_BOOK_DB",     os.path.join(_DEFAULT_ROOT, "data", "beige_book.db"))
CHROMA_PATH = os.environ.get("BEIGE_BOOK_CHROMA", os.path.join(_DEFAULT_ROOT, "chroma_memory"))
CHROMA_COLLECTION = "beige_book"
EMBED_MODEL       = "all-MiniLM-L6-v2"

_DISTRICT_HINTS = {
    "boston":        "Boston",
    "new york":      "New York",
    "philadelphia":  "Philadelphia",
    "cleveland":     "Cleveland",
    "richmond":      "Richmond",
    "atlanta":       "Atlanta",
    "chicago":       "Chicago",
    "st. louis":     "St. Louis",
    "st louis":      "St. Louis",
    "minneapolis":   "Minneapolis",
    "kansas city":   "Kansas City",
    "dallas":        "Dallas",
    "san francisco": "San Francisco",
    "northeast":     None,
    "southeast":     None,
    "midwest":       None,
    "southwest":     None,
    "west":          None,
}

_chroma_col = None


def _get_chroma_col():
    global _chroma_col
    if _chroma_col is not None:
        return _chroma_col
    try:
        import chromadb
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        ef = SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)
        _chroma_col = client.get_collection(name=CHROMA_COLLECTION, embedding_function=ef)
    except Exception as exc:
        print(f"  [beige_book] ChromaDB unavailable: {exc}", file=sys.stderr)
        _chroma_col = None
    return _chroma_col


def _extract_year_range(query: str) -> tuple[int | None, int | None]:
    years = [int(y) for y in re.findall(r"\b(19\d{2}|20[012]\d)\b", query)]
    if not years:
        return None, None
    return min(years), max(years)


def _extract_districts(query: str) -> list[str]:
    q = query.lower()
    return [v for k, v in _DISTRICT_HINTS.items() if k in q and v]


def _semantic_search(query: str, districts: list[str], year_from: int | None,
                     year_to: int | None, top_k: int) -> list[dict]:
    col = _get_chroma_col()
    if col is None:
        return []
    where: dict = {}
    conditions = []
    if year_from and year_to and year_from == year_to:
        conditions.append({"report_year": {"$eq": year_from}})
    elif year_from:
        conditions.append({"report_year": {"$gte": year_from}})
    if year_to and year_to != year_from:
        conditions.append({"report_year": {"$lte": year_to}})
    if districts:
        conditions.append({"district": {"$in": districts}})
    if len(conditions) == 1:
        where = conditions[0]
    elif len(conditions) > 1:
        where = {"$and": conditions}

    try:
        kwargs = {"query_texts": [query], "n_results": top_k}
        if where:
            kwargs["where"] = where
        results = col.query(**kwargs)
        docs  = results["documents"][0]
        metas = results["metadatas"][0]
        dists = results["distances"][0]
        return [
            {"text": d, "meta": m, "score": round(1 - dist, 3)}
            for d, m, dist in zip(docs, metas, dists)
        ]
    except Exception as exc:
        print(f"  [beige_book] semantic search error: {exc}", file=sys.stderr)
        return []


def _keyword_search(query: str, districts: list[str], year_from: int | None,
                    year_to: int | None, top_k: int) -> list[dict]:
    if not os.path.exists(DB_PATH):
        return []
    try:
        conn = sqlite3.connect(DB_PATH)
        params: list = [query]
        filters = []
        if year_from:
            filters.append(f"substr(c.report_date,1,4) >= '{year_from}'")
        if year_to:
            filters.append(f"substr(c.report_date,1,4) <= '{year_to}'")
        if districts:
            placeholders = ",".join("?" * len(districts))
            filters.append(f"c.district IN ({placeholders})")
            params.extend(districts)
        where_clause = ("AND " + " AND ".join(filters)) if filters else ""
        sql = f"""
            SELECT c.report_date, c.district, c.text, fts.rank
            FROM beige_book_fts fts
            JOIN beige_book_chunks c ON fts.rowid = c.id
            WHERE beige_book_fts MATCH ? {where_clause}
            ORDER BY fts.rank
            LIMIT {top_k}
        """
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [{"text": r[2], "meta": {"report_date": r[0], "district": r[1]}, "score": None}
                for r in rows]
    except Exception as exc:
        print(f"  [beige_book] keyword search error: {exc}", file=sys.stderr)
        return []


def query_beige_book(query: str, districts: list[str] | None = None,
                     year_from: int | None = None, year_to: int | None = None,
                     top_k: int = 5) -> str:
    """
    Semantic + keyword search over the Beige Book corpus.
    Returns a formatted markdown block ready to inject into synthesis context.
    """
    if year_from is None or year_to is None:
        yf, yt = _extract_year_range(query)
        year_from = year_from or yf
        year_to   = year_to   or yt

    if districts is None:
        districts = _extract_districts(query)

    hits = _semantic_search(query, districts, year_from, year_to, top_k)
    if not hits:
        hits = _keyword_search(query, districts, year_from, year_to, top_k)

    if not hits:
        return ""

    lines = [
        "### Beige Book Context",
        f"*{len(hits)} passage(s) — query: \"{query}\"*\n",
    ]
    for h in hits:
        m    = h["meta"]
        date = m.get("report_date", "?")
        dist = m.get("district", "?")
        score = h.get("score")
        score_str = f" | score {score:.3f}" if score is not None else ""
        lines.append(f"**[{date} | {dist}{score_str}]**")
        lines.append(h["text"][:1200])
        lines.append("")

    return "\n".join(lines)


def db_stats() -> dict:
    stats: dict = {"chunks": 0, "publications": 0, "oldest": None, "newest": None, "chroma_vectors": 0}
    if os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        stats["chunks"]       = conn.execute("SELECT COUNT(*) FROM beige_book_chunks").fetchone()[0]
        stats["publications"] = conn.execute("SELECT COUNT(DISTINCT report_date) FROM beige_book_chunks").fetchone()[0]
        stats["oldest"]       = conn.execute("SELECT MIN(report_date) FROM beige_book_chunks").fetchone()[0]
        stats["newest"]       = conn.execute("SELECT MAX(report_date) FROM beige_book_chunks").fetchone()[0]
        conn.close()
    col = _get_chroma_col()
    if col:
        stats["chroma_vectors"] = col.count()
    return stats


if __name__ == "__main__":
    import json
    query = " ".join(sys.argv[1:]) or "labor markets and employment"
    print("=== DB stats ===")
    print(json.dumps(db_stats(), indent=2))
    print(f"\n=== Query: {query!r} ===\n")
    print(query_beige_book(query))

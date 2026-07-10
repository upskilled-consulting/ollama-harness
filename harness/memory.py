"""
harness/memory.py — persistent observation store for the agent pipeline.

Inspired by claude-mem's architecture but runs fully locally via Ollama.
Storage:   SQLite + FTS5 (source of truth, metadata, fallback retrieval)
Retrieval: ChromaDB + sentence-transformers (semantic cosine similarity)
Compression: glm4:9b

Lifecycle:
  1. run() start  → get_context(task)       → inject into synthesize()
  2. run() end    → compress_and_store(...)  → write to SQLite + ChromaDB

Usage:
    from harness.memory import MemoryStore, assess_novelty
    store   = MemoryStore()
    context = store.get_context(task)           # call before synthesis
    store.compress_and_store(task, ...)         # call after run completes

    # For gather_research novelty gating:
    score = assess_novelty(new_results, knowledge_state)   # 0–10
"""

import json
import os
import re
import sqlite3
from datetime import UTC, datetime
from typing import Any

from harness import inference as ollama
from harness.config import CHROMA_DIR, MEMORY_DB
from harness.security import scan_for_injection


def _scan_obs(title: str, narrative: str, facts: list[str] | None) -> bool:
    """
    Scan a compressed observation for prompt-injection patterns before writing
    to SQLite/ChromaDB. Returns True if safe, False if blocked.
    Web-fetched or synthesised content can carry adversarial instructions that
    would be injected into future sessions as trusted memory context.
    """
    combined = "\n".join(filter(None, [title, narrative] + (facts or [])))
    clean, matches = scan_for_injection(combined, source="memory_write")
    if not clean:
        print(f"  [memory] BLOCKED write — injection pattern detected: {matches[0]!r}")
        return False
    return True

COMPRESSION_MODEL   = os.environ.get("COMPRESS_MODEL", "qwen3-8b")
DB_PATH             = str(MEMORY_DB)
CHROMA_PATH         = str(CHROMA_DIR)
CHROMA_COLLECTION   = "observations_vec"
EMBED_MODEL         = "all-MiniLM-L6-v2"   # ~22MB, local, no API key
MAX_CONTEXT_OBSERVATIONS = 4    # observations injected per run
MAX_EXCERPT_CHARS   = 600       # output excerpt sent to compression model
SEMANTIC_CANDIDATES = 12        # over-fetch from ChromaDB before re-ranking


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT    NOT NULL,
    task         TEXT    NOT NULL,
    task_type    TEXT,
    title        TEXT    NOT NULL,
    narrative    TEXT    NOT NULL,
    facts        TEXT,           -- JSON array of strings
    output_path  TEXT,
    final_score  REAL,
    final        TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS observations_fts USING fts5(
    task,
    title,
    narrative,
    facts,
    content='observations',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS obs_ai AFTER INSERT ON observations BEGIN
    INSERT INTO observations_fts(rowid, task, title, narrative, facts)
    VALUES (new.id, new.task, new.title, new.narrative, COALESCE(new.facts, ''));
END;

CREATE TRIGGER IF NOT EXISTS obs_ad AFTER DELETE ON observations BEGIN
    INSERT INTO observations_fts(observations_fts, rowid, task, title, narrative, facts)
    VALUES ('delete', old.id, old.task, old.title, old.narrative, COALESCE(old.facts, ''));
END;
"""


# ---------------------------------------------------------------------------
# Compression
# ---------------------------------------------------------------------------

COMPRESS_PROMPT = """\
Summarize this completed AI agent run as a structured memory record.

Task: {task}
Task type: {task_type}
Searches: {queries}
Output: {lines} lines, {bytes} bytes
Wiggum score: {score}
Output excerpt:
{excerpt}

Respond with EXACTLY this format and nothing else:
Title: <one-line summary of what was researched and produced, max 80 chars>
Narrative: <2-3 sentences: what was researched, what the output contains, anything notable>
Facts: <JSON array of 3-5 specific factual strings worth remembering>
"""


def compress(task: str, task_type: str, queries: list[str], output_content: str,
             output_lines: int, output_bytes: int, wiggum_scores: list[float],
             _trace=None) -> dict:
    """
    Ask the compression model to summarize a completed run.
    Returns dict with keys: title, narrative, facts (list).
    """
    score_str = f"{wiggum_scores[-1]}/10" if wiggum_scores else "n/a"
    excerpt = output_content[:MAX_EXCERPT_CHARS].strip()
    query_str = "; ".join(queries[:4]) if queries else "n/a"

    prompt = COMPRESS_PROMPT.format(
        task=task,
        task_type=task_type or "unknown",
        queries=query_str,
        lines=output_lines or 0,
        bytes=output_bytes or 0,
        score=score_str,
        excerpt=excerpt,
    )

    try:
        response = ollama.chat(
            model=COMPRESSION_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1},
        )
        if _trace is not None:
            _trace.log_usage(response, stage="memory_compress")
        text = response["message"]["content"].strip()
        return _parse_compression(text)
    except Exception as e:
        return {
            "title": task[:80],
            "narrative": f"[compression failed: {e}]",
            "facts": [],
        }


def _parse_compression(text: str) -> dict:
    """Parse the fixed-format compression response."""
    text = re.sub(r"^```[a-z]*\s*", "", text.strip(), flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    result = {"title": "", "narrative": "", "facts": []}

    title_m = re.search(r'^Title:\s*(.+)', text, re.MULTILINE)
    if title_m:
        result["title"] = title_m.group(1).strip()[:80]

    narr_m = re.search(r'^Narrative:\s*(.+?)(?=^Facts:|$)', text, re.MULTILINE | re.DOTALL)
    if narr_m:
        result["narrative"] = narr_m.group(1).strip()

    facts_m = re.search(r'^Facts:\s*(\[.+?\])', text, re.MULTILINE | re.DOTALL)
    if facts_m:
        try:
            result["facts"] = json.loads(facts_m.group(1))
        except json.JSONDecodeError:
            items = re.findall(r'"([^"]+)"', facts_m.group(1))
            result["facts"] = items

    if not result["title"]:
        result["title"] = text.splitlines()[0][:80] if text else "unknown"
    if not result["narrative"]:
        result["narrative"] = text[:300]

    return result


# ---------------------------------------------------------------------------
# ChromaDB helpers
# ---------------------------------------------------------------------------

def _get_chroma_ef():
    try:
        from harness.inference import get_embedding_function
        return get_embedding_function(device="cuda" if _cuda_available() else "cpu")
    except Exception:
        from chromadb.utils import embedding_functions
        return embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBED_MODEL,
            device="cuda" if _cuda_available() else "cpu",
        )


def _get_collection_name() -> str:
    """Return backend-specific collection name to avoid dimension mismatch."""
    try:
        from harness.inference import get_embed_collection_suffix
        return CHROMA_COLLECTION + get_embed_collection_suffix()
    except Exception:
        return CHROMA_COLLECTION


def _cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


def _obs_embed_text(row) -> str:
    """Build the text that gets embedded for a single observation row."""
    parts = [row["title"] or "", row["narrative"] or ""]
    if row["facts"]:
        try:
            facts = json.loads(row["facts"])
            parts.extend(str(f) for f in facts)
        except (json.JSONDecodeError, TypeError):
            pass
    return " ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# MemoryStore
# ---------------------------------------------------------------------------

class MemoryStore:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._chroma_client = None
        self._chroma_col = None
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            for _col, _defn in [
                ("run_id",  "TEXT"),
                ("quality", "INTEGER DEFAULT 0"),
                ("tags",    "TEXT DEFAULT '[]'"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE observations ADD COLUMN {_col} {_defn}")
                except sqlite3.OperationalError:
                    pass
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_feedback_log (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id  INTEGER NOT NULL,
                    rating     INTEGER NOT NULL,
                    comment    TEXT,
                    created_at TEXT NOT NULL
                )
            """)

    # ------------------------------------------------------------------
    # ChromaDB init + migration
    # ------------------------------------------------------------------

    def _get_chroma(self):
        """Lazy-init ChromaDB client and collection. Auto-migrates if needed."""
        if self._chroma_col is not None:
            return self._chroma_col
        try:
            import chromadb
            client = chromadb.PersistentClient(path=CHROMA_PATH)
            ef = _get_chroma_ef()
            col = client.get_or_create_collection(
                name=_get_collection_name(),
                embedding_function=ef,
                metadata={"hnsw:space": "cosine"},
            )
            sqlite_count = self.count()
            chroma_count = col.count()
            if chroma_count < sqlite_count:
                self._migrate_to_chroma(col)
            self._chroma_client = client
            self._chroma_col = col
            return col
        except Exception as e:
            print(f"  [memory] ChromaDB unavailable: {e} — using FTS5 fallback")
            return None

    def _migrate_to_chroma(self, col):
        """Backfill ChromaDB from existing SQLite observations."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, title, narrative, facts FROM observations ORDER BY id"
            ).fetchall()

        existing = set(col.get(include=[])["ids"])
        to_add = [r for r in rows if str(r["id"]) not in existing]
        if not to_add:
            return

        print(f"  [memory] migrating {len(to_add)} observation(s) to ChromaDB...")
        batch_size = 50
        for i in range(0, len(to_add), batch_size):
            batch = to_add[i:i + batch_size]
            col.upsert(
                ids=[str(r["id"]) for r in batch],
                documents=[_obs_embed_text(r) for r in batch],
                metadatas=[{"task_type": "unknown", "final_score": 0.0,
                            "timestamp": ""} for r in batch],
            )
        print("  [memory] migration done")

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def compress_and_store(
        self,
        task: str,
        task_type: str,
        tool_calls: list[dict],
        output_content: str,
        output_lines: int,
        output_bytes: int,
        output_path: str,
        wiggum_scores: list[float],
        final: str,
        wiggum_issues: list[str] | None = None,
        run_id: str | None = None,
        _trace=None,
    ) -> dict:
        """
        Compress a completed run into an observation and persist it.
        Returns the stored observation dict.
        """
        queries = [tc["query"] for tc in tool_calls if tc.get("name") == "web_search"]

        obs = compress(
            task=task,
            task_type=task_type,
            queries=queries,
            output_content=output_content or "",
            output_lines=output_lines or 0,
            output_bytes=output_bytes or 0,
            wiggum_scores=wiggum_scores or [],
            _trace=_trace,
        )

        if wiggum_issues:
            issue_facts = [f"[wiggum] {issue}" for issue in wiggum_issues[:5]]
            obs["facts"] = (obs.get("facts") or []) + issue_facts

        score = wiggum_scores[-1] if wiggum_scores else None
        facts_json = json.dumps(obs["facts"]) if obs["facts"] else None

        if not _scan_obs(obs["title"], obs["narrative"], obs.get("facts")):
            return obs

        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO observations
                   (timestamp, task, task_type, title, narrative, facts, output_path, final_score, final, run_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now(UTC).isoformat(),
                    task,
                    task_type,
                    obs["title"],
                    obs["narrative"],
                    facts_json,
                    output_path,
                    score,
                    final,
                    run_id,
                ),
            )
            rowid = cursor.lastrowid

        col = self._get_chroma()
        if col is not None:
            try:
                embed_text = _obs_embed_text({
                    "title": obs["title"],
                    "narrative": obs["narrative"],
                    "facts": facts_json,
                })
                col.upsert(
                    ids=[str(rowid)],
                    documents=[embed_text],
                    metadatas=[{
                        "task_type": task_type or "unknown",
                        "final_score": score or 0.0,
                        "timestamp": datetime.now(UTC).isoformat(),
                        "quality": 0,
                    }],
                )
            except Exception as e:
                print(f"  [memory] ChromaDB upsert failed (non-fatal): {e}")

        return obs

    def store_direct(
        self,
        task: str,
        task_type: str,
        title: str,
        narrative: str,
        facts: list[str],
        timestamp: str = None,
        final_score: float = None,
        final: str = "PASS",
        output_path: str = None,
    ) -> int:
        """
        Write a pre-built observation directly to SQLite + ChromaDB,
        bypassing LLM compression. Used for bulk imports (e.g. paper corpus).
        Returns the new SQLite rowid, or -1 if the task is already indexed.
        """
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM observations WHERE task = ?", (task,)
            ).fetchone()
            if existing:
                return -1

        facts_json = json.dumps(facts) if facts else None
        ts = timestamp or datetime.now(UTC).isoformat()

        if not _scan_obs(title, narrative, facts):
            return -1

        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO observations
                   (timestamp, task, task_type, title, narrative, facts, output_path, final_score, final)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ts, task, task_type, title, narrative, facts_json, output_path, final_score, final),
            )
            rowid = cursor.lastrowid or -1

        col = self._get_chroma()
        if col is not None:
            try:
                embed_text = _obs_embed_text({
                    "title": title,
                    "narrative": narrative,
                    "facts": facts_json,
                })
                col.upsert(
                    ids=[str(rowid)],
                    documents=[embed_text],
                    metadatas=[{
                        "task_type": task_type,
                        "final_score": final_score or 0.0,
                        "timestamp": ts,
                    }],
                )
            except Exception as e:
                print(f"  [memory] ChromaDB upsert failed (non-fatal): {e}")

        return rowid

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    def get_context(self, task: str, n: int = MAX_CONTEXT_OBSERVATIONS) -> str:
        """
        Retrieve the N most relevant past observations for a task.
        Returns a formatted string for injection into the synthesis prompt,
        or empty string if no relevant history exists.
        """
        rows = self._search(task, n)
        if not rows:
            return ""

        lines = ["## Relevant past research\n"]
        for row in rows:
            date = row["timestamp"][:10]
            score_str = f"{row['final_score']:.1f}/10" if row["final_score"] else "n/a"
            task_type = row["task_type"] or "unknown"
            lines.append(f"**[{date}] {row['title']}** ({task_type}, {score_str})")
            lines.append(row["narrative"])
            if row["facts"]:
                try:
                    facts = json.loads(row["facts"])
                    if facts:
                        lines.append("Facts: " + "; ".join(str(f) for f in facts))
                except (json.JSONDecodeError, TypeError):
                    pass
            lines.append("")

        return "\n".join(lines).strip()

    def get_context_with_titles(self, task: str, n: int = MAX_CONTEXT_OBSERVATIONS) -> tuple[str, list[str]]:
        """Like get_context() but also returns observation titles for logging."""
        rows = self._search(task, n)
        if not rows:
            return "", []

        lines = ["## Relevant past research\n"]
        titles = []
        for row in rows:
            date = row["timestamp"][:10]
            score_str = f"{row['final_score']:.1f}/10" if row["final_score"] else "n/a"
            task_type = row["task_type"] or "unknown"
            title = row["title"] or ""
            titles.append(f"{title} ({score_str})")
            lines.append(f"**[{date}] {title}** ({task_type}, {score_str})")
            lines.append(row["narrative"])
            if row["facts"]:
                try:
                    facts = json.loads(row["facts"])
                    if facts:
                        lines.append("Facts: " + "; ".join(str(f) for f in facts))
                except (json.JSONDecodeError, TypeError):
                    pass
            lines.append("")

        return "\n".join(lines).strip(), titles

    def search(self, task: str, n: int = 10) -> list[sqlite3.Row]:
        """Public alias for _search — semantic + quality ranked retrieval."""
        return self._search(task, n)

    def _search(self, task: str, n: int) -> list[sqlite3.Row]:
        """
        Semantic retrieval via ChromaDB with SQLite metadata join.
        Re-ranks by blending similarity + quality score.
        Falls back to FTS5 if ChromaDB unavailable.
        """
        col = self._get_chroma()
        if col is not None and col.count() > 0:
            try:
                results = col.query(
                    query_texts=[task],
                    n_results=min(SEMANTIC_CANDIDATES, col.count()),
                    include=["distances", "metadatas"],
                )
                ids       = results["ids"][0]
                distances = results["distances"][0]

                if ids:
                    rowids = [int(i) for i in ids]
                    placeholders = ",".join("?" * len(rowids))
                    with self._connect() as conn:
                        rows_by_id = {
                            row["id"]: row
                            for row in conn.execute(
                                f"SELECT id, timestamp, task, task_type, title, "
                                f"narrative, facts, final_score, quality, tags "
                                f"FROM observations WHERE id IN ({placeholders})",
                                rowids,
                            ).fetchall()
                        }

                    scored = []
                    for rowid, dist in zip(rowids, distances):
                        row = rows_by_id.get(rowid)
                        if not row:
                            continue
                        sim   = 1.0 - (dist / 2.0)
                        raw_score = row["final_score"]
                        # Soft floor: penalise failed/low-quality runs so they don't
                        # anchor synthesis when better observations exist elsewhere.
                        if raw_score is not None and raw_score < 7.0:
                            qual = (raw_score / 10.0) * 0.5
                        else:
                            qual = (raw_score or 5.0) / 10.0
                        q_adjust = max(0.2, 1.0 + (row["quality"] or 0) * 0.15)
                        rank  = (0.7 * sim + 0.3 * qual) * q_adjust
                        scored.append((rank, row))

                    scored.sort(key=lambda x: x[0], reverse=True)

                    # Deduplicate by title — keep only the highest-ranked observation per unique title
                    seen_titles: set[str] = set()
                    deduped = []
                    for rank, row in scored:
                        t = (row["title"] or "").strip().lower()
                        if t not in seen_titles:
                            seen_titles.add(t)
                            deduped.append(row)
                        if len(deduped) >= n:
                            break
                    return deduped
            except Exception as e:
                print(f"  [memory] semantic search error ({e}) — falling back to FTS5")

        return self._search_fts(task, n)

    def _search_fts(self, task: str, n: int) -> list[sqlite3.Row]:
        """FTS5 keyword search with recency tie-breaking. Fallback only."""
        query_terms = _fts_query(task)
        with self._connect() as conn:
            if query_terms:
                try:
                    rows = conn.execute(
                        """SELECT o.id, o.timestamp, o.task, o.task_type, o.title,
                                  o.narrative, o.facts, o.final_score
                           FROM observations_fts f
                           JOIN observations o ON o.id = f.rowid
                           WHERE observations_fts MATCH ?
                           ORDER BY bm25(observations_fts), o.timestamp DESC
                           LIMIT ?""",
                        (query_terms, n),
                    ).fetchall()
                    if rows:
                        return rows
                except sqlite3.OperationalError:
                    pass

            return conn.execute(
                """SELECT id, timestamp, task, task_type, title, narrative, facts, final_score
                   FROM observations
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                (n,),
            ).fetchall()

    def list_memories(self, search="", task_type="", quality_min=-3, quality_max=3,
                      final="", page=1, per_page=25) -> dict:
        """Paginated list for the API. Returns {memories, total, page, per_page, pages}."""
        with self._connect() as conn:
            base_filters = []
            params: list = []

            if task_type:
                base_filters.append("o.task_type = ?")
                params.append(task_type)
            base_filters.append("COALESCE(o.quality, 0) >= ?")
            params.append(quality_min)
            base_filters.append("COALESCE(o.quality, 0) <= ?")
            params.append(quality_max)
            if final:
                base_filters.append("o.final = ?")
                params.append(final)

            where_sql = ("WHERE " + " AND ".join(base_filters)) if base_filters else ""

            if search:
                fts_q = _fts_query(search)
                rows = []
                if fts_q:
                    try:
                        fts_where = ("AND " + " AND ".join(base_filters)) if base_filters else ""
                        rows = conn.execute(
                            f"""SELECT o.id, o.run_id, o.timestamp, o.task, o.task_type,
                                       o.title, COALESCE(o.quality, 0) AS quality, o.tags,
                                       o.facts, o.final_score, o.final
                                FROM observations_fts f
                                JOIN observations o ON o.id = f.rowid
                                WHERE observations_fts MATCH ? {fts_where}
                                ORDER BY bm25(observations_fts), o.timestamp DESC""",
                            [fts_q] + params,
                        ).fetchall()
                    except sqlite3.OperationalError:
                        pass
                if not rows:
                    like_pat = f"%{search}%"
                    like_clause = "(o.title LIKE ? OR o.task LIKE ? OR o.narrative LIKE ?)"
                    extra_params = [like_pat, like_pat, like_pat]
                    if base_filters:
                        rows = conn.execute(
                            f"SELECT o.id, o.run_id, o.timestamp, o.task, o.task_type, "
                            f"o.title, COALESCE(o.quality, 0) AS quality, o.tags, "
                            f"o.facts, o.final_score, o.final "
                            f"FROM observations o {where_sql} AND {like_clause} "
                            f"ORDER BY o.timestamp DESC",
                            params + extra_params,
                        ).fetchall()
                    else:
                        rows = conn.execute(
                            f"SELECT o.id, o.run_id, o.timestamp, o.task, o.task_type, "
                            f"o.title, COALESCE(o.quality, 0) AS quality, o.tags, "
                            f"o.facts, o.final_score, o.final "
                            f"FROM observations o WHERE {like_clause} "
                            f"ORDER BY o.timestamp DESC",
                            extra_params,
                        ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT o.id, o.run_id, o.timestamp, o.task, o.task_type, "
                    f"o.title, COALESCE(o.quality, 0) AS quality, o.tags, "
                    f"o.facts, o.final_score, o.final "
                    f"FROM observations o {where_sql} ORDER BY o.timestamp DESC",
                    params,
                ).fetchall()

        total = len(rows)
        pages = max(1, (total + per_page - 1) // per_page)
        offset = (page - 1) * per_page
        page_rows = rows[offset:offset + per_page]

        memories = []
        for r in page_rows:
            facts = []
            if r["facts"]:
                try:
                    facts = json.loads(r["facts"])
                except (json.JSONDecodeError, TypeError):
                    pass
            memories.append({
                "id": r["id"],
                "run_id": r["run_id"],
                "timestamp": r["timestamp"],
                "task": r["task"],
                "task_type": r["task_type"],
                "title": r["title"],
                "quality": r["quality"],
                "tags": json.loads(r["tags"]) if r["tags"] else [],
                "facts_count": len(facts),
                "final_score": r["final_score"],
                "final": r["final"],
            })

        return {"memories": memories, "total": total, "page": page, "per_page": per_page, "pages": pages}

    def get_memory(self, memory_id: int) -> dict | None:
        """Full detail row. Returns dict or None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, run_id, timestamp, task, task_type, title, narrative, "
                "facts, output_path, final_score, final, COALESCE(quality, 0) AS quality, tags "
                "FROM observations WHERE id = ?",
                (memory_id,),
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        if d["facts"]:
            try:
                d["facts"] = json.loads(d["facts"])
            except (json.JSONDecodeError, TypeError):
                d["facts"] = []
        else:
            d["facts"] = []
        d["tags"] = json.loads(d["tags"]) if d["tags"] else []
        return d

    def update_memory(self, memory_id: int, title: str | None = None,
                      tags: list | None = None, quality: int | None = None) -> bool:
        """Partial update. Returns True if row existed."""
        sets: list[str] = []
        params: list[Any] = []
        if title is not None:
            sets.append("title = ?")
            params.append(title)
        if tags is not None:
            sets.append("tags = ?")
            params.append(json.dumps(tags))
        if quality is not None:
            sets.append("quality = ?")
            params.append(max(-3, min(3, quality)))
        if not sets:
            with self._connect() as conn:
                row = conn.execute("SELECT id FROM observations WHERE id = ?", (memory_id,)).fetchone()
            return row is not None
        params.append(memory_id)
        with self._connect() as conn:
            cur = conn.execute(
                f"UPDATE observations SET {', '.join(sets)} WHERE id = ?", params
            )
        return cur.rowcount > 0

    def delete_memory(self, memory_id: int) -> bool:
        """Hard delete from SQLite + ChromaDB. Returns True if existed."""
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM observations WHERE id = ?", (memory_id,))
            existed = cur.rowcount > 0
        if existed:
            col = self._get_chroma()
            if col is not None:
                try:
                    col.delete(ids=[str(memory_id)])
                except Exception as e:
                    print(f"  [memory] ChromaDB delete failed (non-fatal): {e}")
        return existed

    def add_feedback(self, memory_id: int, rating: int, comment: str = "") -> dict | None:
        """Adjust quality ± 1, clamp to [-3, 3]. Log to feedback table. Return updated row."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, COALESCE(quality, 0) AS quality FROM observations WHERE id = ?",
                (memory_id,),
            ).fetchone()
            if row is None:
                return None
            delta = 1 if rating > 0 else (-1 if rating < 0 else 0)
            new_quality = max(-3, min(3, row["quality"] + delta))
            conn.execute(
                "UPDATE observations SET quality = ? WHERE id = ?",
                (new_quality, memory_id),
            )
            conn.execute(
                "INSERT INTO memory_feedback_log (memory_id, rating, comment, created_at) VALUES (?, ?, ?, ?)",
                (memory_id, rating, comment, datetime.now(UTC).isoformat()),
            )
        return self.get_memory(memory_id)

    def prune_candidates(self) -> list[dict]:
        """Return memories with quality <= -2 or (final_score < 6 and quality < 0), newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, run_id, timestamp, task, task_type, title, "
                "COALESCE(quality, 0) AS quality, tags, facts, final_score, final "
                "FROM observations "
                "WHERE COALESCE(quality, 0) <= -2 "
                "   OR (final_score < 6 AND COALESCE(quality, 0) < 0) "
                "ORDER BY timestamp DESC",
            ).fetchall()
        result = []
        for r in rows:
            facts = []
            if r["facts"]:
                try:
                    facts = json.loads(r["facts"])
                except (json.JSONDecodeError, TypeError):
                    pass
            result.append({
                "id": r["id"],
                "run_id": r["run_id"],
                "timestamp": r["timestamp"],
                "task": r["task"],
                "task_type": r["task_type"],
                "title": r["title"],
                "quality": r["quality"],
                "tags": json.loads(r["tags"]) if r["tags"] else [],
                "facts_count": len(facts),
                "final_score": r["final_score"],
                "final": r["final"],
            })
        return result

    def get_graph(self, max_nodes: int = 600) -> dict:
        """UMAP 2D + k-means clustering of ChromaDB embeddings."""
        CLUSTER_COLORS = [
            "#6366f1", "#0ea5e9", "#10b981", "#f59e0b",
            "#ec4899", "#8b5cf6", "#14b8a6", "#f97316",
        ]
        try:
            import umap
        except ImportError:
            return {"nodes": [], "clusters": [], "error": "umap-learn not installed"}

        col = self._get_chroma()
        if col is None:
            return {"nodes": [], "clusters": [], "error": "ChromaDB unavailable"}

        total = col.count()
        if total < 5:
            return {"nodes": [], "clusters": [], "error": "not enough memories for graph"}

        # Fetch most-recent max_nodes by sampling SQLite ids first, then pulling embeddings
        if total > max_nodes:
            with self._connect() as conn:
                recent_ids = [
                    str(r[0]) for r in conn.execute(
                        "SELECT id FROM observations ORDER BY id DESC LIMIT ?", (max_nodes,)
                    ).fetchall()
                ]
            data = col.get(ids=recent_ids, include=["embeddings", "metadatas"])
        else:
            data = col.get(include=["embeddings", "metadatas"])

        ids        = data.get("ids") or []
        embeddings = data.get("embeddings")
        if embeddings is None or len(embeddings) == 0:
            return {"nodes": [], "clusters": [], "error": "no embeddings in ChromaDB"}

        import numpy as np
        from sklearn.cluster import KMeans

        emb_array = np.array(embeddings)
        reducer = umap.UMAP(n_components=2, random_state=42, low_memory=True)
        coords = reducer.fit_transform(emb_array)

        n = len(ids)
        k = min(8, max(1, n // 3))
        kmeans = KMeans(n_clusters=k, random_state=42, n_init="auto")
        labels = kmeans.fit_predict(emb_array)

        rowids: list[int | None] = []
        for _id in ids:
            try:
                rowids.append(int(_id))
            except (ValueError, TypeError):
                rowids.append(None)

        valid_rowids = [r for r in rowids if r is not None]
        sqlite_info: dict[int, dict] = {}
        if valid_rowids:
            placeholders = ",".join("?" * len(valid_rowids))
            with self._connect() as conn:
                for row in conn.execute(
                    f"SELECT id, title, COALESCE(quality, 0) AS quality, task_type "
                    f"FROM observations WHERE id IN ({placeholders})",
                    valid_rowids,
                ).fetchall():
                    sqlite_info[row["id"]] = {"title": row["title"], "quality": row["quality"], "task_type": row["task_type"]}

        nodes = []
        for i, (_id, rowid) in enumerate(zip(ids, rowids)):
            info = sqlite_info.get(rowid, {}) if rowid is not None else {}
            nodes.append({
                "id": _id,
                "x": float(coords[i, 0]),
                "y": float(coords[i, 1]),
                "label": info.get("title") or _id,
                "cluster": int(labels[i]),
                "quality": info.get("quality", 0),
                "task_type": info.get("task_type") or "unknown",
            })

        clusters = [
            {"id": c, "label": f"Cluster {c + 1}", "color": CLUSTER_COLORS[c % len(CLUSTER_COLORS)]}
            for c in range(k)
        ]

        return {"nodes": nodes, "clusters": clusters, "error": None}

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]


# ---------------------------------------------------------------------------
# Novelty scoring — for gather_research() marginal value search
# ---------------------------------------------------------------------------

def assess_novelty(new_results: list[dict], knowledge_state: str) -> int:
    """
    Score 0–10 how much new_results adds beyond knowledge_state.
    10 = entirely new information, 0 = completely redundant.

    Uses ChromaDB ephemeral collection + sentence-transformers cosine similarity.
    Falls back to word-overlap heuristic if ChromaDB unavailable.
    """
    if not knowledge_state or not new_results:
        return 10

    try:
        import chromadb
        ef = _get_chroma_ef()
        client = chromadb.EphemeralClient()
        col = client.get_or_create_collection(
            name="novelty_session",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )

        chunks = [s.strip() for s in re.split(r'[.\n]', knowledge_state)
                  if len(s.strip()) > 20]
        if not chunks:
            return 10

        col.upsert(
            ids=[f"k{i}" for i in range(len(chunks))],
            documents=chunks,
        )

        new_bodies = [r.get("body", "") for r in new_results if r.get("body", "").strip()]
        if not new_bodies:
            return 10

        results = col.query(
            query_texts=new_bodies,
            n_results=1,
            include=["distances"],
        )
        min_distances = [r[0] for r in (results["distances"] or []) if r]
        if not min_distances:
            return 10

        avg_dist = sum(min_distances) / len(min_distances)
        return min(10, round(avg_dist * 5))

    except Exception as e:
        print(f"  [novelty] chroma unavailable ({e}) — using heuristic")
        return _novelty_heuristic(new_results, knowledge_state)


def _novelty_heuristic(new_results: list[dict], knowledge_state: str) -> int:
    """Word overlap fallback."""
    new_words   = set(w for r in new_results for w in r.get("body", "").lower().split())
    known_words = set(knowledge_state.lower().split())
    if not new_words:
        return 0
    return round(len(new_words - known_words) / len(new_words) * 10)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fts_query(task: str) -> str:
    """Build a safe FTS5 MATCH query from a task string."""
    STOP = {
        "the", "a", "an", "and", "or", "for", "to", "of", "in", "on",
        "at", "by", "is", "are", "was", "be", "with", "from", "that",
        "this", "it", "as", "not", "use", "save", "search", "find",
        "best", "most", "top", "how", "what", "which", "about",
    }
    words = re.findall(r'\b[a-zA-Z]{3,}\b', task)
    terms = [w.lower() for w in words if w.lower() not in STOP]
    seen, unique = set(), []
    for t in terms:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return " OR ".join(unique[:8]) if unique else ""


# ---------------------------------------------------------------------------
# CLI — inspect the store
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    store = MemoryStore()
    device = "GPU" if _cuda_available() else "CPU"
    print(f"Memory store:  {store.db_path}")
    print(f"Observations:  {store.count()}")
    print(f"Embed device:  {device} ({EMBED_MODEL})")

    col = store._get_chroma()
    if col:
        print(f"ChromaDB:      {col.count()} vectors  ({CHROMA_PATH})")
    else:
        print("ChromaDB:      unavailable — FTS5 fallback active")

    print()

    if "--search" in sys.argv:
        idx   = sys.argv.index("--search")
        query = " ".join(sys.argv[idx + 1:])
        print(f"Query: {query!r}\n")
        ctx = store.get_context(query)
        print(ctx if ctx else "(no matches)")
    else:
        with store._connect() as conn:
            rows = conn.execute(
                "SELECT timestamp, title, task_type, final_score, final "
                "FROM observations ORDER BY timestamp DESC LIMIT 10"
            ).fetchall()
        for r in rows:
            score = f"{r['final_score']:.1f}" if r["final_score"] else "n/a"
            print(f"  [{r['timestamp'][:10]}] {r['title']!r}  "
                  f"({r['task_type']}, {score}/10, {r['final']})")

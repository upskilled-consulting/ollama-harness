"""
Regression tests for search_cache.py schema migration (commit d342f1e0).

Verifies that _connect() handles five database states correctly:
  1. Fresh DB        — no file on disk
  2. Stale v1        — original search_cache only (no research_cache table)
  3. Missing column  — search_cache exists but lacks expires_at
  4. Missing both    — search_cache lacks created_at AND expires_at
  5. research_cache  — both tables exist but research_cache lacks expires_at,
                       search_rounds, and novelty_scores

Run:
    python -m pytest tests/test_search_cache_migration.py -v
    # or simply:
    python tests/test_search_cache_migration.py
"""

import importlib
import os
import sqlite3
import sys
import tempfile
import time
import unittest

# Ensure repo root is on sys.path so `import search_cache` works.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import search_cache as sc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _index_exists(conn: sqlite3.Connection, index_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
        (index_name,),
    ).fetchone()
    return row is not None


class _MigrationTestBase(unittest.TestCase):
    """Provides a per-test temp DB and reloads search_cache to point at it."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmpdir, "test.db")
        importlib.reload(sc)
        sc.DB_PATH = self.db_path

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        os.rmdir(self._tmpdir)

    # -- assertion shortcuts ------------------------------------------------

    def assert_column_exists(self, conn, table, col):
        self.assertIn(col, _table_columns(conn, table))

    def assert_index_exists(self, conn, name):
        self.assertTrue(_index_exists(conn, name), f"index {name!r} should exist")


# ---------------------------------------------------------------------------
# Scenario 1: Fresh database
# ---------------------------------------------------------------------------

class TestFreshDatabase(_MigrationTestBase):

    def test_connect_creates_all_tables_and_indexes(self):
        conn = sc._connect()
        self.assert_column_exists(conn, "search_cache", "expires_at")
        self.assert_column_exists(conn, "search_cache", "created_at")
        self.assert_column_exists(conn, "research_cache", "expires_at")
        self.assert_column_exists(conn, "research_cache", "search_rounds")
        self.assert_column_exists(conn, "research_cache", "novelty_scores")
        self.assert_index_exists(conn, "idx_expires")
        self.assert_index_exists(conn, "idx_rc_expires")
        conn.close()

    def test_put_get_round_trip(self):
        sc.put("hello world", [{"title": "t1"}], ttl=3600)
        result = sc.get("hello world")
        self.assertIsNotNone(result)
        self.assertEqual(result[0]["title"], "t1")

    def test_put_get_research_round_trip(self):
        sc.put_research("task1", "research", "ctx", 3, [0.8, 0.6])
        rr = sc.get_research("task1", "research")
        self.assertIsNotNone(rr)
        self.assertEqual(rr["search_rounds"], 3)
        self.assertEqual(rr["novelty_scores"], [0.8, 0.6])


# ---------------------------------------------------------------------------
# Scenario 2: Stale v1 — original search_cache only
# ---------------------------------------------------------------------------

class TestStaleV1(_MigrationTestBase):

    def _create_v1_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE search_cache (
                key        TEXT PRIMARY KEY,
                query      TEXT NOT NULL,
                results    TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            )
        """)
        conn.execute("CREATE INDEX idx_expires ON search_cache(expires_at)")
        now = time.time()
        conn.execute(
            "INSERT INTO search_cache VALUES (?, ?, ?, ?, ?)",
            ("k1", "test query", "[]", now, now + 86400),
        )
        conn.commit()
        conn.close()

    def test_research_cache_created(self):
        self._create_v1_db()
        conn = sc._connect()
        self.assert_column_exists(conn, "research_cache", "expires_at")
        self.assert_index_exists(conn, "idx_rc_expires")
        conn.close()

    def test_existing_rows_preserved(self):
        self._create_v1_db()
        conn = sc._connect()
        row = conn.execute(
            "SELECT query FROM search_cache WHERE key='k1'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "test query")
        conn.close()


# ---------------------------------------------------------------------------
# Scenario 3: search_cache missing expires_at
# ---------------------------------------------------------------------------

class TestMissingExpiresAt(_MigrationTestBase):

    def _create_stale_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE search_cache (
                key        TEXT PRIMARY KEY,
                query      TEXT NOT NULL,
                results    TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        conn.execute(
            "INSERT INTO search_cache VALUES (?, ?, ?, ?)",
            ("k2", "old query", '[{"title":"old"}]', time.time()),
        )
        conn.commit()
        conn.close()

    def test_connect_succeeds(self):
        self._create_stale_db()
        conn = sc._connect()
        conn.close()

    def test_expires_at_added(self):
        self._create_stale_db()
        conn = sc._connect()
        self.assert_column_exists(conn, "search_cache", "expires_at")
        self.assert_index_exists(conn, "idx_expires")
        conn.close()

    def test_existing_rows_get_default_zero(self):
        self._create_stale_db()
        conn = sc._connect()
        row = conn.execute(
            "SELECT expires_at FROM search_cache WHERE key='k2'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 0)
        conn.close()

    def test_old_rows_treated_as_expired(self):
        self._create_stale_db()
        result = sc.get("old query")
        self.assertIsNone(result, "row with expires_at=0 should be expired")


# ---------------------------------------------------------------------------
# Scenario 4: search_cache missing created_at AND expires_at
# ---------------------------------------------------------------------------

class TestMissingBothTimestamps(_MigrationTestBase):

    def _create_stale_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE search_cache (
                key     TEXT PRIMARY KEY,
                query   TEXT NOT NULL,
                results TEXT NOT NULL
            )
        """)
        conn.execute(
            "INSERT INTO search_cache VALUES (?, ?, ?)",
            ("k3", "ancient query", "[]"),
        )
        conn.commit()
        conn.close()

    def test_connect_succeeds(self):
        self._create_stale_db()
        conn = sc._connect()
        conn.close()

    def test_both_columns_added(self):
        self._create_stale_db()
        conn = sc._connect()
        self.assert_column_exists(conn, "search_cache", "created_at")
        self.assert_column_exists(conn, "search_cache", "expires_at")
        self.assert_index_exists(conn, "idx_expires")
        conn.close()

    def test_existing_rows_get_defaults(self):
        self._create_stale_db()
        conn = sc._connect()
        row = conn.execute(
            "SELECT created_at, expires_at FROM search_cache WHERE key='k3'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 0)
        self.assertEqual(row[1], 0)
        conn.close()


# ---------------------------------------------------------------------------
# Scenario 5: research_cache missing expires_at + other columns
# ---------------------------------------------------------------------------

class TestResearchCacheMissingColumns(_MigrationTestBase):

    def _create_stale_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE search_cache (
                key        TEXT PRIMARY KEY,
                query      TEXT NOT NULL,
                results    TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE research_cache (
                key       TEXT PRIMARY KEY,
                task      TEXT NOT NULL,
                task_type TEXT NOT NULL,
                context   TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        conn.execute(
            "INSERT INTO research_cache VALUES (?, ?, ?, ?, ?)",
            ("rk1", "old task", "research", "old context", time.time()),
        )
        conn.commit()
        conn.close()

    def test_connect_succeeds(self):
        self._create_stale_db()
        conn = sc._connect()
        conn.close()

    def test_missing_columns_added(self):
        self._create_stale_db()
        conn = sc._connect()
        self.assert_column_exists(conn, "research_cache", "expires_at")
        self.assert_column_exists(conn, "research_cache", "search_rounds")
        self.assert_column_exists(conn, "research_cache", "novelty_scores")
        self.assert_index_exists(conn, "idx_rc_expires")
        conn.close()

    def test_existing_rows_get_default_zero(self):
        self._create_stale_db()
        conn = sc._connect()
        row = conn.execute(
            "SELECT expires_at FROM research_cache WHERE key='rk1'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 0)
        conn.close()

    def test_fresh_insert_after_migration(self):
        self._create_stale_db()
        sc.put_research("new task", "research", "new ctx", 5, [0.9, 0.7])
        rr = sc.get_research("new task", "research")
        self.assertIsNotNone(rr)
        self.assertEqual(rr["search_rounds"], 5)
        self.assertEqual(rr["novelty_scores"], [0.9, 0.7])


# ---------------------------------------------------------------------------
# Idempotency & eviction
# ---------------------------------------------------------------------------

class TestIdempotencyAndEviction(_MigrationTestBase):

    def test_multiple_connect_calls_are_safe(self):
        c1 = sc._connect()
        c1.close()
        c2 = sc._connect()
        c2.close()
        c3 = sc._connect()
        c3.close()

    def test_stale_rows_evicted_by_put(self):
        """Rows migrated with expires_at=0 are evicted on next put()."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE search_cache (
                key     TEXT PRIMARY KEY,
                query   TEXT NOT NULL,
                results TEXT NOT NULL
            )
        """)
        conn.execute("INSERT INTO search_cache VALUES ('s1', 'q1', '[]')")
        conn.execute("INSERT INTO search_cache VALUES ('s2', 'q2', '[]')")
        conn.commit()
        conn.close()

        importlib.reload(sc)
        sc.DB_PATH = self.db_path

        # put() triggers lazy eviction of expired (expires_at=0) rows
        sc.put("new query", [{"title": "new"}], ttl=3600)

        conn = sc._connect()
        count = conn.execute("SELECT COUNT(*) FROM search_cache").fetchone()[0]
        self.assertEqual(count, 1, "stale rows should be evicted; only new row remains")
        row = conn.execute("SELECT query FROM search_cache").fetchone()
        self.assertEqual(row[0], "new query")
        conn.close()


if __name__ == "__main__":
    unittest.main()

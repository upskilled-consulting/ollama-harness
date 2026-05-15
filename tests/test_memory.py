"""
Tests for harness/memory.py — MemoryStore CRUD, quality-weighted operations,
feedback clamping, prune candidates, and schema migration idempotency.

ChromaDB is patched out in all tests so we test the SQLite layer in isolation.
No LLM calls are made.
"""

import json
import sqlite3
from unittest.mock import patch

import pytest

from harness.memory import MemoryStore, _fts_query


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    """Fresh MemoryStore backed by a temp SQLite file, ChromaDB disabled."""
    db = str(tmp_path / "test_obs.db")
    s = MemoryStore(db_path=db)
    with patch.object(s, "_get_chroma", return_value=None):
        yield s


def _seed(store: MemoryStore, **overrides) -> int:
    """Insert one observation via store_direct(); returns its rowid."""
    kwargs = dict(
        task="Survey RLHF techniques",
        task_type="research",
        title="RLHF Overview",
        narrative="Covers PPO and DPO approaches.",
        facts=["PPO is on-policy", "DPO avoids the reward model"],
        final_score=8.5,
        final="PASS",
    )
    kwargs.update(overrides)
    return store.store_direct(**kwargs)


# ---------------------------------------------------------------------------
# Schema / migration
# ---------------------------------------------------------------------------

class TestSchema:

    def test_init_creates_observations_table(self, store):
        with store._connect() as conn:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        assert "observations" in tables

    def test_new_columns_exist(self, store):
        with store._connect() as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(observations)").fetchall()}
        assert {"run_id", "quality", "tags"}.issubset(cols)

    def test_feedback_log_table_exists(self, store):
        with store._connect() as conn:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        assert "memory_feedback_log" in tables

    def test_init_idempotent(self, store):
        """Calling _init_db() a second time must not raise."""
        store._init_db()
        assert store.count() == 0

    def test_quality_defaults_to_zero(self, store):
        _seed(store)
        with store._connect() as conn:
            q = conn.execute("SELECT COALESCE(quality, 0) FROM observations").fetchone()[0]
        assert q == 0

    def test_tags_defaults_to_empty_array(self, store):
        _seed(store)
        with store._connect() as conn:
            tags = conn.execute("SELECT tags FROM observations").fetchone()[0]
        assert json.loads(tags) == []


# ---------------------------------------------------------------------------
# store_direct / count
# ---------------------------------------------------------------------------

class TestStoreDirect:

    def test_inserts_row(self, store):
        rowid = _seed(store)
        assert rowid > 0
        assert store.count() == 1

    def test_duplicate_task_returns_minus_one(self, store):
        _seed(store, task="same-task")
        result = _seed(store, task="same-task")
        assert result == -1
        assert store.count() == 1

    def test_different_tasks_both_stored(self, store):
        _seed(store, task="task-A")
        _seed(store, task="task-B")
        assert store.count() == 2


# ---------------------------------------------------------------------------
# get_memory
# ---------------------------------------------------------------------------

class TestGetMemory:

    def test_returns_full_detail(self, store):
        rid = _seed(store)
        mem = store.get_memory(rid)
        assert mem is not None
        assert mem["title"] == "RLHF Overview"
        assert mem["narrative"] == "Covers PPO and DPO approaches."
        assert isinstance(mem["facts"], list)
        assert len(mem["facts"]) == 2

    def test_facts_parsed_from_json(self, store):
        rid = _seed(store, facts=["fact A", "fact B", "fact C"])
        mem = store.get_memory(rid)
        assert mem["facts"] == ["fact A", "fact B", "fact C"]

    def test_tags_parsed_from_json(self, store):
        rid = _seed(store)
        store.update_memory(rid, tags=["rlhf", "alignment"])
        mem = store.get_memory(rid)
        assert mem["tags"] == ["rlhf", "alignment"]

    def test_missing_id_returns_none(self, store):
        assert store.get_memory(99999) is None

    def test_quality_zero_by_default(self, store):
        rid = _seed(store)
        mem = store.get_memory(rid)
        assert mem["quality"] == 0


# ---------------------------------------------------------------------------
# update_memory
# ---------------------------------------------------------------------------

class TestUpdateMemory:

    def test_update_title(self, store):
        rid = _seed(store)
        ok = store.update_memory(rid, title="New Title")
        assert ok is True
        assert store.get_memory(rid)["title"] == "New Title"

    def test_update_tags(self, store):
        rid = _seed(store)
        ok = store.update_memory(rid, tags=["ml", "alignment"])
        assert ok is True
        assert store.get_memory(rid)["tags"] == ["ml", "alignment"]

    def test_update_quality(self, store):
        rid = _seed(store)
        ok = store.update_memory(rid, quality=2)
        assert ok is True
        assert store.get_memory(rid)["quality"] == 2

    def test_quality_clamped_to_max_three(self, store):
        rid = _seed(store)
        store.update_memory(rid, quality=99)
        assert store.get_memory(rid)["quality"] == 3

    def test_quality_clamped_to_min_neg_three(self, store):
        rid = _seed(store)
        store.update_memory(rid, quality=-99)
        assert store.get_memory(rid)["quality"] == -3

    def test_partial_update_title_only(self, store):
        rid = _seed(store)
        store.update_memory(rid, tags=["original"])
        store.update_memory(rid, title="Changed Title")
        mem = store.get_memory(rid)
        assert mem["title"] == "Changed Title"
        assert mem["tags"] == ["original"]  # unchanged

    def test_missing_id_returns_false(self, store):
        ok = store.update_memory(99999, title="Ghost")
        assert ok is False

    def test_no_fields_returns_true_if_exists(self, store):
        rid = _seed(store)
        ok = store.update_memory(rid)
        assert ok is True


# ---------------------------------------------------------------------------
# delete_memory
# ---------------------------------------------------------------------------

class TestDeleteMemory:

    def test_delete_removes_row(self, store):
        rid = _seed(store)
        assert store.count() == 1
        ok = store.delete_memory(rid)
        assert ok is True
        assert store.count() == 0

    def test_delete_returns_false_for_missing(self, store):
        ok = store.delete_memory(99999)
        assert ok is False

    def test_double_delete_returns_false(self, store):
        rid = _seed(store)
        store.delete_memory(rid)
        assert store.delete_memory(rid) is False

    def test_get_after_delete_returns_none(self, store):
        rid = _seed(store)
        store.delete_memory(rid)
        assert store.get_memory(rid) is None


# ---------------------------------------------------------------------------
# add_feedback
# ---------------------------------------------------------------------------

class TestAddFeedback:

    def test_upvote_increments_quality(self, store):
        rid = _seed(store)
        result = store.add_feedback(rid, rating=1)
        assert result is not None
        assert result["quality"] == 1

    def test_downvote_decrements_quality(self, store):
        rid = _seed(store)
        result = store.add_feedback(rid, rating=-1)
        assert result["quality"] == -1

    def test_zero_rating_no_change(self, store):
        rid = _seed(store)
        result = store.add_feedback(rid, rating=0)
        assert result["quality"] == 0

    def test_clamps_at_positive_three(self, store):
        rid = _seed(store)
        for _ in range(5):
            store.add_feedback(rid, rating=1)
        assert store.get_memory(rid)["quality"] == 3

    def test_clamps_at_negative_three(self, store):
        rid = _seed(store)
        for _ in range(5):
            store.add_feedback(rid, rating=-1)
        assert store.get_memory(rid)["quality"] == -3

    def test_logs_to_feedback_table(self, store):
        rid = _seed(store)
        store.add_feedback(rid, rating=1, comment="great output")
        with store._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_feedback_log WHERE memory_id = ?", (rid,)
            ).fetchall()
        assert len(rows) == 1
        assert rows[0]["rating"] == 1
        assert rows[0]["comment"] == "great output"

    def test_multiple_feedbacks_accumulated(self, store):
        rid = _seed(store)
        store.add_feedback(rid, rating=1)
        store.add_feedback(rid, rating=1)
        store.add_feedback(rid, rating=-1)
        assert store.get_memory(rid)["quality"] == 1

    def test_missing_id_returns_none(self, store):
        result = store.add_feedback(99999, rating=1)
        assert result is None


# ---------------------------------------------------------------------------
# list_memories
# ---------------------------------------------------------------------------

class TestListMemories:

    def _seed_many(self, store):
        ids = []
        for i in range(5):
            rid = _seed(store, task=f"task-{i}", title=f"Memory {i}",
                        task_type="research" if i % 2 == 0 else "best_practices",
                        final_score=7.0 + i * 0.5, final="PASS")
            ids.append(rid)
        return ids

    def test_returns_all_by_default(self, store):
        self._seed_many(store)
        result = store.list_memories()
        assert result["total"] == 5

    def test_pagination_page_size(self, store):
        self._seed_many(store)
        result = store.list_memories(per_page=2, page=1)
        assert len(result["memories"]) == 2
        assert result["pages"] == 3

    def test_pagination_page_two(self, store):
        self._seed_many(store)
        p1 = store.list_memories(per_page=2, page=1)
        p2 = store.list_memories(per_page=2, page=2)
        ids_p1 = {m["id"] for m in p1["memories"]}
        ids_p2 = {m["id"] for m in p2["memories"]}
        assert ids_p1.isdisjoint(ids_p2)

    def test_task_type_filter(self, store):
        self._seed_many(store)
        result = store.list_memories(task_type="research")
        for m in result["memories"]:
            assert m["task_type"] == "research"

    def test_quality_min_filter(self, store):
        ids = self._seed_many(store)
        store.update_memory(ids[0], quality=-2)
        store.update_memory(ids[1], quality=1)
        result = store.list_memories(quality_min=0)
        returned_ids = {m["id"] for m in result["memories"]}
        assert ids[0] not in returned_ids  # quality -2, excluded
        assert ids[1] in returned_ids      # quality 1, included

    def test_quality_max_filter(self, store):
        ids = self._seed_many(store)
        store.update_memory(ids[0], quality=3)
        result = store.list_memories(quality_max=0)
        returned_ids = {m["id"] for m in result["memories"]}
        assert ids[0] not in returned_ids

    def test_final_filter(self, store):
        _seed(store, task="pass-task", final="PASS")
        _seed(store, task="fail-task", final="FAIL")
        result = store.list_memories(final="FAIL")
        assert result["total"] == 1
        assert result["memories"][0]["final"] == "FAIL"

    def test_search_by_title(self, store):
        _seed(store, task="task-x", title="Speculative Decoding Survey")
        _seed(store, task="task-y", title="RLHF Overview")
        result = store.list_memories(search="Speculative")
        assert result["total"] >= 1
        titles = [m["title"] for m in result["memories"]]
        assert any("Speculative" in t for t in titles)

    def test_facts_count_in_list_rows(self, store):
        _seed(store, task="counted", facts=["a", "b", "c"])
        result = store.list_memories()
        mem = next(m for m in result["memories"] if m["task"] == "counted")
        assert mem["facts_count"] == 3

    def test_empty_store_returns_empty(self, store):
        result = store.list_memories()
        assert result["total"] == 0
        assert result["memories"] == []
        assert result["pages"] == 1


# ---------------------------------------------------------------------------
# prune_candidates
# ---------------------------------------------------------------------------

class TestPruneCandidates:

    def test_quality_minus_two_included(self, store):
        rid = _seed(store)
        store.update_memory(rid, quality=-2)
        candidates = store.prune_candidates()
        assert any(c["id"] == rid for c in candidates)

    def test_quality_minus_three_included(self, store):
        rid = _seed(store)
        store.update_memory(rid, quality=-3)
        candidates = store.prune_candidates()
        assert any(c["id"] == rid for c in candidates)

    def test_quality_minus_one_excluded_by_default(self, store):
        rid = _seed(store, final_score=9.0)
        store.update_memory(rid, quality=-1)
        candidates = store.prune_candidates()
        assert not any(c["id"] == rid for c in candidates)

    def test_low_score_and_negative_quality_included(self, store):
        rid = _seed(store, final_score=4.0)
        store.update_memory(rid, quality=-1)
        candidates = store.prune_candidates()
        assert any(c["id"] == rid for c in candidates)

    def test_low_score_neutral_quality_excluded(self, store):
        # final_score < 6 but quality == 0 — not a candidate
        rid = _seed(store, final_score=4.0)
        candidates = store.prune_candidates()
        assert not any(c["id"] == rid for c in candidates)

    def test_high_quality_excluded(self, store):
        rid = _seed(store, final_score=9.0)
        store.update_memory(rid, quality=2)
        candidates = store.prune_candidates()
        assert not any(c["id"] == rid for c in candidates)

    def test_empty_store_returns_empty(self, store):
        assert store.prune_candidates() == []

    def test_candidate_has_expected_fields(self, store):
        rid = _seed(store)
        store.update_memory(rid, quality=-2)
        candidates = store.prune_candidates()
        assert len(candidates) == 1
        c = candidates[0]
        assert "id" in c
        assert "title" in c
        assert "quality" in c
        assert "facts_count" in c


# ---------------------------------------------------------------------------
# _fts_query helper
# ---------------------------------------------------------------------------

class TestFtsQuery:

    def test_returns_empty_for_all_stopwords(self):
        assert _fts_query("the a an and or for to of") == ""

    def test_filters_short_words(self):
        result = _fts_query("ML AI")
        assert result == ""  # both < 3 chars

    def test_deduplicates_terms(self):
        result = _fts_query("neural neural networks networks")
        terms = result.split(" OR ")
        assert len(terms) == len(set(terms))

    def test_caps_at_eight_terms(self):
        words = " ".join(f"word{i}" for i in range(20))
        result = _fts_query(words)
        assert len(result.split(" OR ")) <= 8

    def test_produces_or_joined_query(self):
        result = _fts_query("transformer attention mechanism")
        assert " OR " in result

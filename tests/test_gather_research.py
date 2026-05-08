"""
Tests for gather_research() — fan-out planned queries + oversearch detector.

Constants (from agent.py):
  SEARCHES_PER_TASK = 2   minimum rounds before novelty/oversearch gating
  MAX_SEARCH_ROUNDS = 5   hard cap

Oversearch fires when round_num > SEARCHES_PER_TASK and 2+ consecutive rounds
add zero net-new domains. force_deep disables it.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _results(domains: list[str]) -> list[dict]:
    return [{"href": f"https://{d}/page", "title": d, "body": "b"} for d in domains]


def _make_trace() -> MagicMock:
    t = MagicMock()
    t.data = {}
    return t


def _setup_mocks(monkeypatch, *, results_per_round: list[list[dict]], novelty: int = 9):
    """
    Patch harness.agent so gather_research() runs without network/LLM calls.

    results_per_round[i] is returned by web_search_raw on the (i+1)-th call.
    Planned queries are always pre-fetched, so call order in the prefetch block
    is parallel (non-deterministic); we map by index in call order instead.
    """
    search_calls: list[str] = []
    compress_calls: list[int] = [0]

    def mock_search(query, max_results=None):
        search_calls.append(query)
        idx = len(search_calls) - 1
        if idx < len(results_per_round):
            return results_per_round[idx]
        return []

    def mock_compress(current, results, **kwargs):
        compress_calls[0] += 1
        return f"state_{compress_calls[0]}"

    monkeypatch.setattr("harness.agent.web_search_raw",       mock_search)
    monkeypatch.setattr("harness.agent.compress_knowledge",   mock_compress)
    monkeypatch.setattr("harness.agent.assess_novelty",       lambda r, s: novelty)
    monkeypatch.setattr("harness.agent.scan_for_injection",   lambda t, source="": (True, []))
    monkeypatch.setattr("harness.agent.MARKITDOWN_AVAILABLE", False)
    monkeypatch.setattr("harness.agent.SEARCH_QUALITY_FLOOR", 0)

    return search_calls, compress_calls


# ---------------------------------------------------------------------------
# Oversearch detector
# ---------------------------------------------------------------------------

class TestOversearchDetector:

    def test_terminates_after_two_consecutive_zero_domain_rounds(self, monkeypatch):
        """
        With the same domain in every round, oversearch fires at round 4:
          rounds 1-2: minimum window, no check
          round 3:    +0 new domains, consecutive = 1 — continue
          round 4:    +0 new domains, consecutive = 2 — break (before compress)
        compress_knowledge should be called exactly 3 times.
        """
        from harness.agent import gather_research

        same_domain = _results(["example.com"])
        _, compress_calls = _setup_mocks(
            monkeypatch,
            results_per_round=[same_domain] * 5,
        )

        planned = ["q1", "q2", "q3", "q4", "q5"]
        result = gather_research("task", _make_trace(), planned_queries=planned)

        assert compress_calls[0] == 3, (
            f"Expected 3 compress calls (rounds 1-3); got {compress_calls[0]}"
        )
        assert isinstance(result, str)

    def test_new_domain_resets_consecutive_counter(self, monkeypatch):
        """
        A new domain at round 4 resets the counter → no early termination.
        All 5 rounds complete; compress called 5 times.
        """
        from harness.agent import gather_research

        rounds = [
            _results(["a.com"]),   # round 1 — minimum window
            _results(["a.com"]),   # round 2 — minimum window
            _results(["a.com"]),   # round 3 — consecutive = 1
            _results(["b.com"]),   # round 4 — new domain → reset
            _results(["a.com"]),   # round 5 — consecutive = 1, no break
        ]
        _, compress_calls = _setup_mocks(monkeypatch, results_per_round=rounds)

        result = gather_research(
            "task", _make_trace(), planned_queries=["q1","q2","q3","q4","q5"]
        )

        assert compress_calls[0] == 5
        assert isinstance(result, str)

    def test_force_deep_disables_oversearch(self, monkeypatch):
        """
        force_deep=True: oversearch detector is disabled; all planned rounds run.
        """
        from harness.agent import gather_research

        same_domain = _results(["only-source.com"])
        _, compress_calls = _setup_mocks(
            monkeypatch,
            results_per_round=[same_domain] * 5,
        )

        result = gather_research(
            "task", _make_trace(),
            planned_queries=["q1","q2","q3","q4","q5"],
            force_deep=True,
        )

        assert compress_calls[0] == 5
        assert isinstance(result, str)

    def test_oversearch_does_not_fire_within_minimum_rounds(self, monkeypatch):
        """
        SEARCHES_PER_TASK = 2: oversearch never fires during the first 2 rounds
        even if they return the same domain repeatedly. Gap-targeted rounds may
        follow, so we assert at least 2 compresses happened (not exactly 2).
        """
        from harness.agent import gather_research

        same_domain = _results(["repeat.com"])
        _, compress_calls = _setup_mocks(
            monkeypatch,
            results_per_round=[same_domain, same_domain],
        )

        result = gather_research(
            "task", _make_trace(), planned_queries=["q1", "q2"]
        )

        assert compress_calls[0] >= 2


# ---------------------------------------------------------------------------
# Fan-out planned queries
# ---------------------------------------------------------------------------

class TestFanOutPlannedQueries:

    def test_all_planned_queries_fetched(self, monkeypatch):
        """
        All planned queries are passed to web_search_raw, even when oversearch
        terminates the loop before all rounds are processed.
        With 5 planned queries pre-fetched in parallel, web_search_raw is called
        5 times (the prefetch) regardless of when the loop breaks.
        """
        from harness.agent import gather_research

        same_domain = _results(["example.com"])
        search_calls, _ = _setup_mocks(
            monkeypatch,
            results_per_round=[same_domain] * 5,
        )

        planned = ["q1", "q2", "q3", "q4", "q5"]
        gather_research("task", _make_trace(), planned_queries=planned)

        assert len(search_calls) == 5
        assert set(search_calls) == set(planned)

    def test_prefetch_results_used_by_loop(self, monkeypatch):
        """
        The loop uses pre-fetched results (not a second web_search_raw call).
        MAX_SEARCH_ROUNDS is capped to 3 here so the loop exhausts exactly the
        planned queries with no gap-targeted rounds, keeping call counts exact.
        """
        from harness.agent import gather_research

        # 3 planned queries, each with distinct domain so no oversearch
        rounds = [
            _results(["a.com"]),
            _results(["b.com"]),
            _results(["c.com"]),
        ]
        search_calls, compress_calls = _setup_mocks(
            monkeypatch, results_per_round=rounds
        )
        monkeypatch.setattr("harness.agent.MAX_SEARCH_ROUNDS", 3)

        gather_research(
            "task", _make_trace(), planned_queries=["q1", "q2", "q3"]
        )

        # 3 planned queries → 3 pre-fetch calls, no additional loop calls
        assert len(search_calls) == 3
        assert compress_calls[0] == 3

    def test_prefetch_failure_falls_back_to_direct_search(self, monkeypatch):
        """
        If a pre-fetch raises, the loop falls back to web_search_raw directly
        for that round (the `or web_search_raw(query)` guard).
        """
        from harness.agent import gather_research

        call_n = [0]

        def flaky_search(query, max_results=None):
            call_n[0] += 1
            if call_n[0] == 2:
                raise RuntimeError("network hiccup")
            return _results(["ok.com"])

        monkeypatch.setattr("harness.agent.web_search_raw", flaky_search)
        monkeypatch.setattr("harness.agent.compress_knowledge", lambda c, r, **k: "s")
        monkeypatch.setattr("harness.agent.assess_novelty", lambda r, s: 9)
        monkeypatch.setattr("harness.agent.scan_for_injection", lambda t, source="": (True, []))
        monkeypatch.setattr("harness.agent.MARKITDOWN_AVAILABLE", False)

        # Should not raise — the prefetch error is caught and round uses fallback
        result = gather_research(
            "task", _make_trace(), planned_queries=["q1", "q2"]
        )
        assert isinstance(result, str)

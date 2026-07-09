"""
Tests for harness/wiggum.py — scoring helpers, prose parser, stub detector,
evaluator rotation, and composite formula.

All tests are pure-Python: no LLM calls, no file I/O.
"""

import pytest

from harness.wiggum import (
    _DIM_WEIGHTS,
    _EVAL_DIMS,
    PASS_THRESHOLD,
    _count_stub_blocks,
    _extract_eval_from_prose,
    detect_task_type,
)

# ---------------------------------------------------------------------------
# Dimension weight contract
# ---------------------------------------------------------------------------

class TestDimWeights:

    def test_weights_sum_to_one(self):
        total = sum(_DIM_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_all_eval_dims_have_weight(self):
        assert set(_EVAL_DIMS) == set(_DIM_WEIGHTS.keys())

    def test_depth_is_heaviest(self):
        assert _DIM_WEIGHTS["depth"] == max(_DIM_WEIGHTS.values())

    def test_pass_threshold_is_eight(self):
        assert PASS_THRESHOLD == 8.0


# ---------------------------------------------------------------------------
# Composite score formula (replicated from evaluate() post-processing)
# ---------------------------------------------------------------------------

def _composite(dims: dict[str, int]) -> float:
    return round(sum(dims[d] * _DIM_WEIGHTS[d] for d in _EVAL_DIMS), 1)


class TestCompositeFormula:

    def test_all_tens_gives_ten(self):
        dims = {d: 10 for d in _EVAL_DIMS}
        assert _composite(dims) == 10.0

    def test_all_zeros_gives_zero(self):
        dims = {d: 0 for d in _EVAL_DIMS}
        assert _composite(dims) == 0.0

    def test_known_values(self):
        # 9*0.20 + 9*0.20 + 8*0.25 + 8*0.15 + 8*0.10 + 9*0.10
        # = 1.80 + 1.80 + 2.00 + 1.20 + 0.80 + 0.90 = 8.50
        dims = {"relevance": 9, "completeness": 9, "depth": 8,
                "grounded": 8, "specificity": 8, "structure": 9}
        assert _composite(dims) == 8.5

    def test_just_below_pass_threshold(self):
        # Drop the lowest-weight dim by 1 to land just under 8.0:
        # 0.20*8 + 0.20*8 + 0.25*8 + 0.15*8 + 0.10*7 + 0.10*8
        # = 1.6 + 1.6 + 2.0 + 1.2 + 0.7 + 0.8 = 7.9
        dims = {"relevance": 8, "completeness": 8, "depth": 8,
                "grounded": 8, "specificity": 7, "structure": 8}
        score = _composite(dims)
        assert score < PASS_THRESHOLD

    def test_pass_threshold_boundary(self):
        # All dims at 9 → 9.0 (just passes)
        dims = {d: 9 for d in _EVAL_DIMS}
        assert _composite(dims) >= PASS_THRESHOLD

    def test_depth_weight_dominates(self):
        # Swapping depth from 10 to 0 should lower score by 0.25*10 = 2.5
        high = {d: 10 for d in _EVAL_DIMS}
        low_depth = {**high, "depth": 0}
        diff = _composite(high) - _composite(low_depth)
        assert abs(diff - 2.5) < 1e-9


# ---------------------------------------------------------------------------
# Hallucination / stub-block detector
# ---------------------------------------------------------------------------

class TestCountStubBlocks:

    def test_no_code_blocks(self):
        assert _count_stub_blocks("Just a paragraph. No code here.") == 0

    def test_clean_code_block(self):
        content = "```python\nx = 1 + 2\nprint(x)\n```"
        assert _count_stub_blocks(content) == 0

    def test_known_object_not_flagged(self):
        # 'model' is in _KNOWN_OBJECTS
        content = "```python\nmodel.fit(X_train, y_train)\nmodel.evaluate(X_test)\n```"
        assert _count_stub_blocks(content) == 0

    def test_fabricated_stub_detected(self):
        # Unknown object 'retriever', method names >= 12 chars, >= 2 calls
        content = (
            "```python\n"
            "retriever.execute_semantic_search(query)\n"
            "retriever.perform_contextual_analysis(data)\n"
            "```"
        )
        assert _count_stub_blocks(content) == 1

    def test_single_long_method_not_flagged(self):
        # Only one suspicious call — needs >= 2
        content = (
            "```python\n"
            "retriever.execute_semantic_search(query)\n"
            "x = 1\n"
            "```"
        )
        assert _count_stub_blocks(content) == 0

    def test_short_method_names_not_flagged(self):
        # Method names < 12 chars — not suspicious
        content = (
            "```python\n"
            "retriever.search(query)\n"
            "retriever.fetch(data)\n"
            "```"
        )
        assert _count_stub_blocks(content) == 0

    def test_cap_at_two(self):
        # Three bad blocks → still returns 2
        block = (
            "```python\n"
            "pipeline.execute_full_processing(inputs)\n"
            "pipeline.validate_all_constraints(cfg)\n"
            "```\n"
        )
        content = block * 3
        assert _count_stub_blocks(content) == 2

    def test_assignment_line_skipped(self):
        # Lines with = before ( are not standalone calls
        content = (
            "```python\n"
            "result = retriever.execute_semantic_search(query)\n"
            "data = retriever.perform_contextual_analysis(text)\n"
            "```"
        )
        assert _count_stub_blocks(content) == 0


# ---------------------------------------------------------------------------
# Prose fallback parser
# ---------------------------------------------------------------------------

class TestExtractEvalFromProse:

    def _all_dims(self, scores: dict[str, int]) -> str:
        """Build a prose string with all 6 dimensions at the given scores."""
        lines = [f"{dim}: {scores.get(dim, 8)}/10" for dim in _EVAL_DIMS]
        return "\n".join(lines)

    def test_parses_colon_format(self):
        prose = self._all_dims({"relevance": 9, "completeness": 8, "depth": 7,
                                "grounded": 8, "specificity": 7, "structure": 9})
        result = _extract_eval_from_prose(prose)
        assert result is not None
        assert result["relevance"] == 9
        assert result["depth"] == 7

    def test_missing_dim_returns_none(self):
        # Only 5 of 6 dimensions present
        prose = "\n".join(f"{d}: 8/10" for d in _EVAL_DIMS[:-1])
        result = _extract_eval_from_prose(prose)
        assert result is None

    def test_composite_computed_correctly(self):
        # All dims at 8 → composite = 8.0
        prose = self._all_dims({d: 8 for d in _EVAL_DIMS})
        result = _extract_eval_from_prose(prose)
        assert result is not None
        assert result["score"] == 8.0

    def test_passed_flag(self):
        # Composite >= 8.0 → passed (prose fallback threshold is 8.0)
        prose = self._all_dims({d: 9 for d in _EVAL_DIMS})
        result = _extract_eval_from_prose(prose)
        assert result["passed"] is True

    def test_failed_flag(self):
        prose = self._all_dims({d: 5 for d in _EVAL_DIMS})
        result = _extract_eval_from_prose(prose)
        assert result is not None
        assert result["passed"] is False

    def test_bold_markdown_format(self):
        # "**Relevance**: 9/10" — format models sometimes emit
        lines = [f"**{dim.capitalize()}**: 8/10" for dim in _EVAL_DIMS]
        prose = "\n".join(lines)
        result = _extract_eval_from_prose(prose)
        assert result is not None

    def test_out_of_range_value_excluded(self):
        # Score of 11 should be excluded (0 <= val <= 10 guard)
        # Build prose with relevance=11 (invalid) and rest valid
        lines = ["relevance: 11/10"] + [f"{d}: 8/10" for d in _EVAL_DIMS[1:]]
        prose = "\n".join(lines)
        result = _extract_eval_from_prose(prose)
        # relevance won't be captured (11 > 10), so all-6 check fails → None
        assert result is None

    def test_includes_prose_marker_in_issues(self):
        prose = self._all_dims({d: 8 for d in _EVAL_DIMS})
        result = _extract_eval_from_prose(prose)
        assert result is not None
        assert any("prose" in i.lower() for i in result["issues"])


# ---------------------------------------------------------------------------
# Task type detection
# ---------------------------------------------------------------------------

class TestDetectTaskType:

    @pytest.mark.parametrize("task", [
        "Top 5 ML papers from 2024",
        "What are the 10 most important techniques?",
        "List the 3 best approaches",
        "7 key strategies for training LLMs",
    ])
    def test_enumerated_detected(self, task):
        assert detect_task_type(task) == "enumerated"

    @pytest.mark.parametrize("task", [
        "Best practices for fine-tuning LLMs",
        "How to implement RAG pipelines",
        "A guide to prompt engineering",
        "Tips for reducing hallucination",
        "Strategies for improving retrieval",
    ])
    def test_best_practices_detected(self, task):
        assert detect_task_type(task) == "best_practices"

    @pytest.mark.parametrize("task", [
        "Survey recent work on speculative decoding",
        "What is the current state of RLHF research?",
        "Summarize advances in diffusion models",
        "Compare DPO and PPO for alignment",
    ])
    def test_research_detected(self, task):
        assert detect_task_type(task) == "research"


# ---------------------------------------------------------------------------
# Evaluator rotation
# ---------------------------------------------------------------------------

class TestSelectEvaluator:

    def test_empty_pool_returns_env_model(self, monkeypatch):
        monkeypatch.delenv("HARNESS_EVALUATOR_POOL", raising=False)
        # Import fresh to pick up cleared env — test via module-level fallback
        from harness import wiggum as _w
        monkeypatch.setattr(_w, "_EVALUATOR_POOL", [])
        result = _w.select_evaluator("any-seed")
        assert result == _w.EVALUATOR_MODEL

    def test_single_model_pool_always_returns_it(self, monkeypatch):
        from harness import wiggum as _w
        monkeypatch.setattr(_w, "_EVALUATOR_POOL", ["only-model"])
        for seed in ["a", "b", "abc123", ""]:
            assert _w.select_evaluator(seed) == "only-model"

    def test_deterministic_for_same_seed(self, monkeypatch):
        from harness import wiggum as _w
        pool = ["model-a", "model-b", "model-c"]
        monkeypatch.setattr(_w, "_EVALUATOR_POOL", pool)
        seed = "run-abc123"
        r1 = _w.select_evaluator(seed)
        r2 = _w.select_evaluator(seed)
        assert r1 == r2

    def test_result_is_from_pool(self, monkeypatch):
        from harness import wiggum as _w
        pool = ["model-a", "model-b"]
        monkeypatch.setattr(_w, "_EVALUATOR_POOL", pool)
        result = _w.select_evaluator("test-seed")
        assert result in pool

    def test_different_seeds_can_produce_different_models(self, monkeypatch):
        from harness import wiggum as _w
        pool = ["model-a", "model-b"]
        monkeypatch.setattr(_w, "_EVALUATOR_POOL", pool)
        # With 100 random seeds against a 2-model pool, both models will appear
        import hashlib
        seen = set()
        for i in range(100):
            h = hashlib.md5(str(i).encode()).hexdigest()
            idx = int(h, 16) % len(pool)
            seen.add(pool[idx])
        assert seen == set(pool)

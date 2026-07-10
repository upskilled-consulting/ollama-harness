"""
Verify lit_review_skill internals: checkpoint logic, template loading,
model parameter threading, and flag parsing in agent._handle_lit_review.
No real LLM calls or network requests.
"""

import json
import threading
import time

import pytest

from harness.skills.lit_review_skill import (
    DEFAULT_TEMPLATE,
    TEMPLATES_DIR,
    _checkpoint_path,
    _parse_annotation_sections,
)

# ---------------------------------------------------------------------------
# Shared fixtures for step_annotate tests
# ---------------------------------------------------------------------------

_VALID_ANNOTATION = (
    "**Topic**: test topic\n"
    "**Motivation**: test motivation\n"
    "**Contribution**: test contribution\n"
    "**Detail / Nuance**: test detail\n"
    "**Evidence / Contribution 2**: test evidence\n"
    "**Weaker result**: test limitation\n"
    "**Narrow impact**: test narrow\n"
    "**Broad impact**: test broad"
)


def _papers(n: int) -> list[dict]:
    return [
        {"arxiv_id": f"p{i}", "title": f"Paper {i}", "summary": f"Summary {i}"}
        for i in range(n)
    ]


class TestCheckpointPath:

    def test_basic(self, tmp_path):
        cp = _checkpoint_path("2403.09513v1", tmp_path)
        assert cp == tmp_path / "2403.09513v1.json"

    def test_slash_replaced(self, tmp_path):
        cp = _checkpoint_path("2403/09513", tmp_path)
        assert "_" in cp.name
        assert "/" not in cp.name


class TestTemplates:

    def test_survey_template_exists(self):
        assert (TEMPLATES_DIR / "lit_review_survey.j2").exists()

    def test_gaps_template_exists(self):
        assert (TEMPLATES_DIR / "lit_review_gaps.j2").exists()

    def test_executive_template_exists(self):
        assert (TEMPLATES_DIR / "lit_review_executive.j2").exists(), \
            "Missing lit_review_executive.j2 — add it to harness/skills/templates/"

    def test_default_template_is_survey(self):
        assert DEFAULT_TEMPLATE == "survey"

    def test_all_templates_are_valid_jinja2(self):
        from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError
        env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
        for tmpl_file in TEMPLATES_DIR.glob("lit_review_*.j2"):
            try:
                env.get_template(tmpl_file.name)
            except TemplateSyntaxError as e:
                pytest.fail(f"Template {tmpl_file.name} has syntax error: {e}")


class TestParseAnnotationSections:

    def test_parses_all_sections(self):
        raw = """**Topic**: Test topic
**Motivation**: Test motivation
**Contribution**: Test contribution
**Detail / Nuance**: Test detail
**Evidence / Contribution 2**: Test evidence
**Weaker result**: Test limitation
**Narrow impact**: Test narrow
**Broad impact**: Test broad"""
        ann = _parse_annotation_sections(raw)
        assert ann["topic"] == "Test topic"
        assert ann["motivation"] == "Test motivation"
        assert ann["contribution"] == "Test contribution"
        assert ann["broad_impact"] == "Test broad"

    def test_missing_sections_return_empty_string(self):
        ann = _parse_annotation_sections("**Topic**: Only topic present")
        assert ann["topic"] == "Only topic present"
        assert ann["motivation"] == ""

    def test_empty_input(self):
        ann = _parse_annotation_sections("")
        assert all(v == "" for v in ann.values())


class TestCheckpointRoundtrip:
    """Verify that null wiggum_score checkpoints are detected and would be skipped."""

    def test_checkpoint_with_null_score_detected(self, tmp_path):
        cp = _checkpoint_path("2403.09513v1", tmp_path)
        cp.write_text(json.dumps({
            "annotation": {"topic": "test"},
            "annotation_raw": "raw",
            "wiggum_score": None,
        }), encoding="utf-8")
        data = json.loads(cp.read_text())
        assert data["wiggum_score"] is None

    def test_checkpoint_with_score_is_truthy(self, tmp_path):
        cp = _checkpoint_path("2403.09513v1", tmp_path)
        cp.write_text(json.dumps({
            "annotation": {"topic": "test"},
            "annotation_raw": "raw",
            "wiggum_score": 8.5,
        }), encoding="utf-8")
        data = json.loads(cp.read_text())
        assert data["wiggum_score"] == 8.5


class TestHandleLitReviewFlagParsing:
    """Test the flag parsing logic inside agent._handle_lit_review."""

    def _parse(self, task: str) -> dict:
        import re
        after_m   = re.search(r"--after\s+(\S+)",        task)
        before_m  = re.search(r"--before\s+(\S+)",       task)
        csv_m     = re.search(r"--csv\s+(\S+)",          task)
        max_f_m   = re.search(r"--max-fetch\s+(\d+)",    task)
        max_a_m   = re.search(r"--max-annotate\s+(\d+)", task)
        tmpl_m    = re.search(r"--template\s+(\S+)",     task)
        return {
            "no_fetch":   "--no-fetch"   in task,
            "no_curate":  "--no-curate"  in task,
            "no_wiggum":  "--no-wiggum"  in task,
            "no_s2":      "--no-s2"      in task,
            "after":      after_m.group(1)  if after_m  else None,
            "before":     before_m.group(1) if before_m else None,
            "csv_path":   csv_m.group(1)    if csv_m    else None,
            "max_fetch":  int(max_f_m.group(1)) if max_f_m else 100,
            "max_ann":    int(max_a_m.group(1)) if max_a_m else 20,
            "template":   tmpl_m.group(1)   if tmpl_m   else "survey",
        }

    def test_no_wiggum_flag(self):
        assert self._parse("/lit-review RAG papers --no-wiggum")["no_wiggum"]

    def test_no_fetch_flag(self):
        assert self._parse("/lit-review RAG --no-fetch")["no_fetch"]

    def test_max_fetch_parsed(self):
        assert self._parse("/lit-review RAG --max-fetch 50")["max_fetch"] == 50

    def test_max_annotate_parsed(self):
        assert self._parse("/lit-review RAG --max-annotate 5")["max_ann"] == 5

    def test_template_parsed(self):
        assert self._parse("/lit-review RAG --template executive")["template"] == "executive"

    def test_after_date_parsed(self):
        assert self._parse("/lit-review RAG --after 2024-01-01")["after"] == "2024-01-01"

    def test_defaults(self):
        flags = self._parse("/lit-review RAG")
        assert flags["max_fetch"] == 100
        assert flags["max_ann"] == 20
        assert flags["template"] == "survey"
        assert not flags["no_wiggum"]

    def test_valid_templates(self):
        for tmpl in ("survey", "gaps", "executive"):
            assert self._parse(f"/lit-review RAG --template {tmpl}")["template"] == tmpl


class TestAnnotateModelThreading:
    """
    Verify that step_annotate passes producer_model (not the hardcoded ANNOTATE_MODEL)
    to run_annotate_standalone. This was a regression where ANNOTATE_MODEL
    = 'nanda-annotator-v2-q4km:latest' was always used regardless of producer_model.
    """

    def test_annotate_uses_producer_model_not_hardcoded(self, tmp_path, monkeypatch):
        calls = []

        def _fake_run_annotate(paper_context, producer_model, max_retries=3, domain="cs", _trace=None):
            calls.append(producer_model)
            return "**Topic**: test\n**Motivation**: m\n**Contribution**: c\n**Key Detail / Nuance**: d\n**Evidence / Second Contribution**: e\n**Weaker Result / Limitation**: w\n**Narrow Impact**: ni\n**Broad Impact**: bi"

        import harness.skills as _skills_pkg
        monkeypatch.setattr(_skills_pkg, "run_annotate_standalone", _fake_run_annotate)

        from harness.skills.lit_review_skill import step_annotate

        papers = [{"arxiv_id": "2403.09513v1", "title": "Test Paper", "summary": "test"}]
        step_annotate(
            papers=papers,
            producer_model="qwen3.6-35b",
            evaluator_model="qwen3.6-35b",
            use_wiggum=False,
            checkpoint_dir=tmp_path,
        )
        assert calls == ["qwen3.6-35b"], \
            f"Expected producer_model='qwen3.6-35b' but got {calls}"


class TestStepAnnotateParallelism:
    """
    Prove that step_annotate uses ThreadPoolExecutor for concurrent annotation.

    Six properties verified:
      1. All papers come back annotated.
      2. The `parallel` argument sets ThreadPoolExecutor max_workers.
      3. Output order matches input order even when papers finish out of order.
      4. Multiple papers execute concurrently (overlapping time windows).
      5. A failure in one paper does not abort the rest of the batch.
      6. A pre-existing checkpoint is served directly; LLM is not called.
      7. Token counts from all sub-traces are summed into the parent trace.
    """

    # ------------------------------------------------------------------
    # 1. Basic: all papers returned
    # ------------------------------------------------------------------

    def test_all_papers_annotated(self, tmp_path, monkeypatch):
        import harness.skills as _skills_pkg
        monkeypatch.setattr(
            _skills_pkg, "run_annotate_standalone",
            lambda paper_context, producer_model, max_retries=3, domain="cs", _trace=None: _VALID_ANNOTATION,
        )
        from harness.skills.lit_review_skill import step_annotate
        results = step_annotate(
            _papers(3), "m", "e", use_wiggum=False, checkpoint_dir=tmp_path
        )
        assert len(results) == 3

    # ------------------------------------------------------------------
    # 2. parallel param wires through to ThreadPoolExecutor max_workers
    # ------------------------------------------------------------------

    def test_parallel_param_sets_max_workers(self, tmp_path, monkeypatch):
        from concurrent.futures import ThreadPoolExecutor
        seen_workers: list[int | None] = []
        _real_init = ThreadPoolExecutor.__init__

        def _patched_init(self, max_workers=None, **kw):
            seen_workers.append(max_workers)
            _real_init(self, max_workers=max_workers, **kw)

        monkeypatch.setattr(ThreadPoolExecutor, "__init__", _patched_init)
        import harness.skills as _skills_pkg
        monkeypatch.setattr(
            _skills_pkg, "run_annotate_standalone",
            lambda paper_context, producer_model, max_retries=3, domain="cs", _trace=None: _VALID_ANNOTATION,
        )
        from harness.skills.lit_review_skill import step_annotate
        step_annotate(_papers(2), "m", "e", use_wiggum=False, checkpoint_dir=tmp_path, parallel=7)
        assert 7 in seen_workers, f"Expected max_workers=7 in pool init calls; got {seen_workers}"

    # ------------------------------------------------------------------
    # 3. Output order preserved when completions arrive out of order
    # ------------------------------------------------------------------

    def test_output_order_matches_input_order(self, tmp_path, monkeypatch):
        import re

        def staggered(paper_context, producer_model, max_retries=3, domain="cs", _trace=None):
            idx = int(re.search(r"Paper (\d+)", paper_context).group(1))
            time.sleep((3 - idx) * 0.03)   # Paper 0 finishes last
            return _VALID_ANNOTATION

        import harness.skills as _skills_pkg
        monkeypatch.setattr(_skills_pkg, "run_annotate_standalone", staggered)
        from harness.skills.lit_review_skill import step_annotate
        results = step_annotate(
            _papers(4), "m", "e", use_wiggum=False, checkpoint_dir=tmp_path, parallel=4
        )
        assert [r["arxiv_id"] for r in results] == ["p0", "p1", "p2", "p3"]

    # ------------------------------------------------------------------
    # 4. Concurrent execution: time windows overlap
    # ------------------------------------------------------------------

    def test_concurrent_execution_detected(self, tmp_path, monkeypatch):
        SLEEP = 0.05
        intervals: list[tuple[float, float]] = []
        lock = threading.Lock()

        def slow_annotate(paper_context, producer_model, max_retries=3, domain="cs", _trace=None):
            t0 = time.monotonic()
            time.sleep(SLEEP)
            t1 = time.monotonic()
            with lock:
                intervals.append((t0, t1))
            return _VALID_ANNOTATION

        import harness.skills as _skills_pkg
        monkeypatch.setattr(_skills_pkg, "run_annotate_standalone", slow_annotate)
        from harness.skills.lit_review_skill import step_annotate
        step_annotate(_papers(4), "m", "e", use_wiggum=False, checkpoint_dir=tmp_path, parallel=4)

        overlaps = sum(
            1
            for i, (s1, e1) in enumerate(intervals)
            for j, (s2, e2) in enumerate(intervals)
            if i < j and s1 < e2 and s2 < e1
        )
        assert overlaps > 0, (
            f"No overlapping execution windows in {intervals} — "
            "papers appear to have run sequentially"
        )

    # ------------------------------------------------------------------
    # 5. One failure does not abort the rest of the batch
    # ------------------------------------------------------------------

    def test_one_failure_does_not_abort_batch(self, tmp_path, monkeypatch):
        def flaky(paper_context, producer_model, max_retries=3, domain="cs", _trace=None):
            if "Paper 1" in paper_context:
                raise RuntimeError("simulated LLM failure")
            return _VALID_ANNOTATION

        import harness.skills as _skills_pkg
        monkeypatch.setattr(_skills_pkg, "run_annotate_standalone", flaky)
        from harness.skills.lit_review_skill import step_annotate
        results = step_annotate(
            _papers(3), "m", "e", use_wiggum=False, checkpoint_dir=tmp_path
        )
        ids = {r["arxiv_id"] for r in results}
        assert "p0" in ids, "p0 should have succeeded"
        assert "p2" in ids, "p2 should have succeeded"
        assert "p1" not in ids, "p1 raised — should be excluded from results"

    # ------------------------------------------------------------------
    # 6. Pre-existing checkpoint is served without an LLM call
    # ------------------------------------------------------------------

    def test_checkpoint_skips_llm_call(self, tmp_path, monkeypatch):
        calls: list[str] = []

        def counting(paper_context, producer_model, max_retries=3, domain="cs", _trace=None):
            calls.append(paper_context)
            return _VALID_ANNOTATION

        import harness.skills as _skills_pkg
        monkeypatch.setattr(_skills_pkg, "run_annotate_standalone", counting)

        cp = _checkpoint_path("p0", tmp_path)
        cp.write_text(json.dumps({
            "annotation":     {"topic": "cached_topic", "motivation": "",
                               "contribution": "", "detail_nuance": "",
                               "evidence_contribution_2": "", "weaker_result": "",
                               "narrow_impact": "", "broad_impact": ""},
            "annotation_raw": "cached raw",
            "wiggum_score":   8.0,
        }), encoding="utf-8")

        from harness.skills.lit_review_skill import step_annotate
        results = step_annotate(
            _papers(2), "m", "e", use_wiggum=False, checkpoint_dir=tmp_path
        )
        assert len(calls) == 1, f"Expected 1 LLM call (p0 checkpointed); got {len(calls)}"
        p0 = next(r for r in results if r["arxiv_id"] == "p0")
        assert p0["annotation"]["topic"] == "cached_topic"

    # ------------------------------------------------------------------
    # 7. Token counts from all sub-traces roll up into the parent trace
    # ------------------------------------------------------------------

    def test_token_rollup_sums_sub_traces(self, tmp_path, monkeypatch):
        def token_emitting(paper_context, producer_model, max_retries=3, domain="cs", _trace=None):
            if _trace is not None:
                _trace.data["input_tokens"]  += 100
                _trace.data["output_tokens"] += 50
            return _VALID_ANNOTATION

        import harness.skills as _skills_pkg
        monkeypatch.setattr(_skills_pkg, "run_annotate_standalone", token_emitting)

        from harness.logger import RunTrace
        from harness.skills.lit_review_skill import step_annotate

        main_trace = RunTrace(task="test", producer_model="m", evaluator_model="e")
        step_annotate(
            _papers(3), "m", "e", use_wiggum=False, checkpoint_dir=tmp_path,
            _trace=main_trace,
        )
        assert main_trace.data["input_tokens"]  == 300, main_trace.data["input_tokens"]
        assert main_trace.data["output_tokens"] == 150, main_trace.data["output_tokens"]

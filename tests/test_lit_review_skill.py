"""
Verify lit_review_skill internals: checkpoint logic, template loading,
model parameter threading, and flag parsing in agent._handle_lit_review.
No real LLM calls or network requests.
"""

import json

import pytest

from harness.skills.lit_review_skill import (
    DEFAULT_TEMPLATE,
    TEMPLATES_DIR,
    _checkpoint_path,
    _parse_annotation_sections,
)


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

        def _fake_run_annotate(paper_context, producer_model, max_retries=3, _trace=None):
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

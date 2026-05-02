"""
Verify skill parsing, auto-activation, merge, and hook helpers.
"""

from harness.skills import (
    REGISTRY,
    auto_activate,
    get_prompt_injections,
    merge_skills,
    parse_skills,
    skills_at_hook,
)


class TestParseSkills:

    def test_single_skill_extracted(self):
        clean, skills = parse_skills("/annotate Search for RAG papers")
        assert skills == ["annotate"]
        assert "/annotate" not in clean
        assert "Search for RAG papers" in clean

    def test_multiple_skills_extracted(self):
        clean, skills = parse_skills("/deep /cite Search for X and save to out.md")
        assert "deep" in skills and "cite" in skills
        assert len(skills) == 2
        assert "/deep" not in clean and "/cite" not in clean

    def test_unknown_slash_token_preserved(self):
        clean, skills = parse_skills("/nonexistent Search for X")
        assert skills == []
        assert "/nonexistent" in clean

    def test_alias_resolved(self):
        _, skills = parse_skills("/annotated-abstract some paper")
        assert skills == ["annotate"]

    def test_deduplication(self):
        _, skills = parse_skills("/annotate /annotate Search for X")
        assert skills == ["annotate"]

    def test_empty_task(self):
        clean, skills = parse_skills("")
        assert clean == ""
        assert skills == []

    def test_no_skills(self):
        clean, skills = parse_skills("Search for RAG papers and save to out.md")
        assert skills == []
        assert "Search for RAG papers" in clean

    def test_msys2_mangled_path_handled(self):
        """Git Bash converts /recall → C:/Program Files/Git/recall."""
        _, skills = parse_skills("C:/Program Files/Git/recall some query")
        assert "recall" in skills

    def test_lit_review_skill_extracted(self):
        clean, skills = parse_skills("/lit-review agentic LLM save to out.md")
        assert "lit-review" in skills
        assert "/lit-review" not in clean


class TestAutoActivate:

    class _Plan:
        complexity = "low"

    class _PlanHigh:
        complexity = "high"

    def test_returns_list(self):
        assert isinstance(auto_activate("simple task", self._Plan()), list)

    def test_deep_auto_activates(self):
        assert "deep" in auto_activate("do a comprehensive review", self._Plan())

    def test_panel_auto_activates_on_high(self):
        assert "panel" in auto_activate("any task", self._PlanHigh())

    def test_no_false_auto_on_simple_task(self):
        result = auto_activate("search for python tutorials", self._Plan())
        for name in result:
            assert REGISTRY[name]["auto"] is not None


class TestMergeSkills:

    def test_explicit_first(self):
        merged = merge_skills(["cite"], ["deep", "panel"])
        assert merged[0] == "cite"

    def test_deduplication(self):
        merged = merge_skills(["deep", "cite"], ["deep", "panel"])
        assert merged.count("deep") == 1
        assert "panel" in merged

    def test_empty_inputs(self):
        assert merge_skills([], []) == []


class TestHookHelpers:

    def test_cite_injection_at_pre_synthesis(self):
        result = get_prompt_injections(["cite"], "pre_synthesis")
        assert len(result) > 0
        assert "source" in result.lower() or "attribution" in result.lower() or "reference" in result.lower()

    def test_cite_no_injection_at_wrong_hook(self):
        assert get_prompt_injections(["cite"], "post_synthesis") == ""

    def test_no_skills_returns_empty(self):
        assert get_prompt_injections([], "pre_synthesis") == ""

    def test_skills_at_hook_filters_correctly(self):
        active = ["deep", "cite", "knowledge-graph", "panel"]
        assert "deep" in skills_at_hook(active, "pre_research")
        assert "cite" not in skills_at_hook(active, "pre_research")
        assert "knowledge-graph" in skills_at_hook(active, "post_synthesis")
        assert "panel" in skills_at_hook(active, "post_wiggum")

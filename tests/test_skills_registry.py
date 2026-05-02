"""
Verify the skill REGISTRY is structurally valid and auto-triggers fire correctly.
"""

import pytest
from harness.skills import REGISTRY, _ALIASES


EXPECTED_SKILLS = {
    "annotate", "annotated-abstract", "knowledge-graph", "panel", "deep",
    "cite", "wiggum", "email", "github", "review", "lit-review", "recall",
    "queue", "orientation", "introspect", "contextualize", "sync-wiki",
    "playwright", "sitemap", "crawl", "re-orient", "forge:plugin", "forge:list",
    "debug", "suggest", "troubleshoot", "transcribe",
}

VALID_HOOKS = {
    "pre_research", "pre_synthesis", "post_synthesis",
    "post_wiggum", "standalone", "modifier",
}

REQUIRED_KEYS = {"description", "hook", "prompt", "auto"}


class TestRegistryCompleteness:

    def test_all_expected_skills_present(self):
        missing = EXPECTED_SKILLS - set(REGISTRY.keys())
        assert not missing, f"Missing skills from REGISTRY: {missing}"

    def test_no_unexpected_skills(self):
        extra = set(REGISTRY.keys()) - EXPECTED_SKILLS
        if extra:
            pytest.skip(f"New skills found (add to EXPECTED_SKILLS): {extra}")


class TestRegistryStructure:

    @pytest.mark.parametrize("name", sorted(EXPECTED_SKILLS))
    def test_required_keys(self, name):
        if name not in REGISTRY:
            pytest.skip(f"{name} not in REGISTRY")
        missing = REQUIRED_KEYS - set(REGISTRY[name].keys())
        assert not missing, f"Skill {name!r} missing keys: {missing}"

    @pytest.mark.parametrize("name", sorted(EXPECTED_SKILLS))
    def test_valid_hook(self, name):
        if name not in REGISTRY:
            pytest.skip(f"{name} not in REGISTRY")
        hook = REGISTRY[name]["hook"]
        assert hook in VALID_HOOKS, f"Skill {name!r} has invalid hook {hook!r}"

    @pytest.mark.parametrize("name", sorted(EXPECTED_SKILLS))
    def test_auto_is_callable_or_none(self, name):
        if name not in REGISTRY:
            pytest.skip(f"{name} not in REGISTRY")
        auto = REGISTRY[name]["auto"]
        assert auto is None or callable(auto), \
            f"Skill {name!r} auto must be None or callable, got {type(auto)}"

    @pytest.mark.parametrize("name", sorted(EXPECTED_SKILLS))
    def test_description_nonempty(self, name):
        if name not in REGISTRY:
            pytest.skip(f"{name} not in REGISTRY")
        desc = REGISTRY[name]["description"]
        assert isinstance(desc, str) and len(desc) > 5


class TestAliases:

    def test_aliases_resolve_to_real_skills(self):
        for alias, target in _ALIASES.items():
            assert alias in REGISTRY, f"Alias source {alias!r} not in REGISTRY"
            assert target in REGISTRY, f"Alias target {target!r} not in REGISTRY"

    def test_annotated_abstract_alias(self):
        assert _ALIASES.get("annotated-abstract") == "annotate"


class TestAutoTriggers:

    class _PlanLow:
        complexity = "low"

    class _PlanHigh:
        complexity = "high"

    def test_deep_triggers_on_comprehensive(self):
        assert REGISTRY["deep"]["auto"]("do a comprehensive analysis", self._PlanLow())

    def test_deep_triggers_on_deep_dive(self):
        assert REGISTRY["deep"]["auto"]("deep dive into transformers", self._PlanLow())

    def test_deep_does_not_trigger_on_simple(self):
        assert not REGISTRY["deep"]["auto"]("search for python tutorials", self._PlanLow())

    def test_panel_triggers_on_high_complexity(self):
        assert REGISTRY["panel"]["auto"]("any task", self._PlanHigh())

    def test_panel_does_not_trigger_on_low(self):
        assert not REGISTRY["panel"]["auto"]("any task", self._PlanLow())

    def test_kg_triggers_on_knowledge_graph(self):
        assert REGISTRY["knowledge-graph"]["auto"]("build a knowledge graph of RAG", self._PlanLow())

    def test_kg_triggers_on_visualize(self):
        assert REGISTRY["knowledge-graph"]["auto"]("visualize the relationships", self._PlanLow())

    def test_contextualize_triggers_on_self_referential(self):
        auto = REGISTRY["contextualize"]["auto"]
        assert auto("what can you do?", self._PlanLow())
        assert auto("describe the harness", self._PlanLow())
        assert auto("tell me about yourself", self._PlanLow())

    def test_contextualize_does_not_trigger_on_normal(self):
        assert not REGISTRY["contextualize"]["auto"]("search for RAG papers", self._PlanLow())

    def test_explicit_only_skills_have_none_auto(self):
        for name in ["annotate", "cite", "wiggum", "email", "github", "review",
                     "lit-review", "recall", "queue", "orientation", "introspect",
                     "sync-wiki", "playwright", "re-orient", "debug", "suggest",
                     "troubleshoot", "transcribe"]:
            if name not in REGISTRY:
                continue
            assert REGISTRY[name]["auto"] is None, \
                f"Skill {name!r} should be explicit-only (auto=None)"

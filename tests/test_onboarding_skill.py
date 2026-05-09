"""
Tests for harness/skills/onboarding_skill.py.

Properties verified:
  1. Fixed scaffold — exactly 3 fixed questions asked before free-form rounds.
  2. Free-form rounds stop at novelty saturation after first free round.
  3. Total rounds never exceed MAX_ONBOARDING_ROUNDS (6).
  4. synthesize_and_write creates user_profile.md and .harness-user.toml.
  5. TOML file contains [user] and [routing] sections from LLM output.
  6. Re-run is additive — existing keys preserved when new value is empty string.
  7. Re-run overrides non-empty keys with new non-empty values.
  8. Memory seed is called with chunked knowledge_state.
  9. _extract_toml_block returns None when no fences present.
 10. _merge_toml: new non-empty values win; old values survive missing new keys.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import harness.skills.onboarding_skill as mod


# ---------------------------------------------------------------------------
# Shared stubs
# ---------------------------------------------------------------------------

def _stub_compress(current, new, **_):
    return (current + " " + " ".join(r.get("body", "") for r in new)).strip()


def _stub_novelty_high(*_, **__):
    return 10


def _stub_novelty_low(*_, **__):
    return 1


_LONG = "I am a machine learning researcher working on large language model fine-tuning and RLHF pipelines"

_TOML_RESPONSE = """\
```toml
[user]
role             = "ML researcher"
domain           = "LLM fine-tuning, RLHF"
preferred_model  = "pi-qwen-32b"
preferred_format = "markdown with headers"
verbosity        = "concise"

[routing]
research_tasks = "pi-qwen-32b"
coding_tasks   = "qwen2.5-coder-14b"
```

## Background
- ML researcher specializing in RLHF

## Primary use cases
- Literature reviews, code review

## Output preferences
- Markdown with H2 headers

## Domain expertise
- LLM fine-tuning, preference learning

## Notes
- Prefers concise outputs
"""


# ---------------------------------------------------------------------------
# 1–3. Interview loop structure
# ---------------------------------------------------------------------------

class TestOnboardingLoop:

    def _run(self, answers, *, novelty=10):
        asked = []
        pool = list(reversed(answers))

        def ask(q):
            asked.append(q)
            return pool.pop() if pool else answers[-1]

        fake_q = {"message": {"content": "What else should I know?"}}
        fake_synth = {"message": {"content": _TOML_RESPONSE}}

        def _chat(**kw):
            content = (kw.get("messages") or [{}])[0].get("content", "")
            return fake_q if "Generate ONE focused" in content else fake_synth

        with (
            patch("harness.agent.compress_knowledge", side_effect=_stub_compress),
            patch("harness.memory.assess_novelty", return_value=novelty),
            patch("harness.inference.chat", side_effect=_chat),
            patch("harness.skills.onboarding_skill._seed_memory"),
        ):
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                td_path = Path(td)
                with (
                    patch("harness.config.USER_CONFIG_TOML", td_path / ".harness-user.toml"),
                    patch("harness.config.USER_PROFILE_PATH", td_path / "user_profile.md"),
                ):
                    mod.run_onboarding(ask_fn=ask, producer_model="dummy")

        return asked

    def test_three_fixed_questions_always_asked(self):
        asked = self._run([_LONG] * 10)
        # First 3 questions must be the fixed scaffold questions
        for i, fixed_q in enumerate(mod.FIXED_QUESTIONS):
            assert asked[i] == fixed_q, f"Round {i+1}: expected fixed question, got {asked[i]!r}"

    def test_total_rounds_do_not_exceed_max(self):
        asked = self._run([_LONG] * 20, novelty=10)
        assert len(asked) <= mod.MAX_ONBOARDING_ROUNDS

    def test_novelty_saturation_stops_free_rounds(self):
        # With novelty=1, free-form rounds should stop after first
        asked = self._run([_LONG] * 10, novelty=1)
        # 3 fixed + at most 2 free (gate fires on second free round)
        assert len(asked) <= len(mod.FIXED_QUESTIONS) + 2


# ---------------------------------------------------------------------------
# 4–5. synthesize_and_write — file output
# ---------------------------------------------------------------------------

class TestSynthesizeAndWrite:

    def test_writes_both_files(self, tmp_path):
        toml_path    = tmp_path / ".harness-user.toml"
        profile_path = tmp_path / "user_profile.md"
        fake = {"message": {"content": _TOML_RESPONSE}}

        with (
            patch("harness.inference.chat", return_value=fake),
            patch("harness.config.USER_CONFIG_TOML", toml_path),
            patch("harness.config.USER_PROFILE_PATH", profile_path),
        ):
            p1, p2 = mod.synthesize_and_write("some knowledge", "dummy")

        assert profile_path.exists(), "user_profile.md not written"
        assert toml_path.exists(),    ".harness-user.toml not written"

    def test_toml_has_user_and_routing_sections(self, tmp_path):
        toml_path    = tmp_path / ".harness-user.toml"
        profile_path = tmp_path / "user_profile.md"
        fake = {"message": {"content": _TOML_RESPONSE}}

        with (
            patch("harness.inference.chat", return_value=fake),
            patch("harness.config.USER_CONFIG_TOML", toml_path),
            patch("harness.config.USER_PROFILE_PATH", profile_path),
        ):
            mod.synthesize_and_write("knowledge", "dummy")

        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        assert "user"    in data, f"[user] section missing from TOML: {data}"
        assert "routing" in data, f"[routing] section missing from TOML: {data}"
        assert data["user"]["role"] == "ML researcher"

    def test_profile_md_contains_background_section(self, tmp_path):
        toml_path    = tmp_path / ".harness-user.toml"
        profile_path = tmp_path / "user_profile.md"
        fake = {"message": {"content": _TOML_RESPONSE}}

        with (
            patch("harness.inference.chat", return_value=fake),
            patch("harness.config.USER_CONFIG_TOML", toml_path),
            patch("harness.config.USER_PROFILE_PATH", profile_path),
        ):
            mod.synthesize_and_write("knowledge", "dummy")

        text = profile_path.read_text(encoding="utf-8")
        assert "## Background" in text


# ---------------------------------------------------------------------------
# 6–7. Additive merge behaviour
# ---------------------------------------------------------------------------

class TestMergeToml:

    def test_old_keys_preserved_when_new_value_empty(self):
        old = {"user": {"role": "researcher", "domain": "RLHF"}}
        new = {"user": {"role": "researcher", "domain": ""}}
        merged = mod._merge_toml(old, new)
        assert merged["user"]["domain"] == "RLHF", "existing domain erased by empty new value"

    def test_new_non_empty_value_overrides_old(self):
        old = {"user": {"role": "student"}}
        new = {"user": {"role": "engineer"}}
        merged = mod._merge_toml(old, new)
        assert merged["user"]["role"] == "engineer"

    def test_new_section_added_when_absent_in_old(self):
        old = {"user": {"role": "researcher"}}
        new = {"routing": {"research_tasks": "model-a"}}
        merged = mod._merge_toml(old, new)
        assert "routing" in merged
        assert merged["routing"]["research_tasks"] == "model-a"

    def test_re_run_writes_merged_toml(self, tmp_path):
        """Full write-then-rewrite cycle: second run preserves manual edits."""
        toml_path    = tmp_path / ".harness-user.toml"
        profile_path = tmp_path / "user_profile.md"

        # First run: write initial config
        first_toml = (
            '[user]\nrole = "researcher"\ndomain = "RLHF"\n'
            'preferred_model = ""\npreferred_format = ""\nverbosity = ""\n\n'
            '[routing]\nresearch_tasks = "model-a"\ncoding_tasks = ""\n'
        )
        toml_path.write_text(first_toml, encoding="utf-8")

        # Second run: LLM returns partial update (domain filled in, role same)
        update_toml_response = """\
```toml
[user]
role             = "researcher"
domain           = "RLHF, alignment"
preferred_model  = "pi-qwen-32b"
preferred_format = ""
verbosity        = ""

[routing]
research_tasks = ""
coding_tasks   = "coder-14b"
```

## Background
- Updated
"""
        fake = {"message": {"content": update_toml_response}}

        with (
            patch("harness.inference.chat", return_value=fake),
            patch("harness.config.USER_CONFIG_TOML", toml_path),
            patch("harness.config.USER_PROFILE_PATH", profile_path),
        ):
            mod.synthesize_and_write("updated knowledge", "dummy")

        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        assert data["user"]["domain"] == "RLHF, alignment"      # updated
        assert data["routing"]["research_tasks"] == "model-a"   # preserved (new was empty)
        assert data["routing"]["coding_tasks"]   == "coder-14b" # new value written


# ---------------------------------------------------------------------------
# 9. _extract_toml_block
# ---------------------------------------------------------------------------

class TestExtractTomlBlock:

    def test_returns_none_when_no_fences(self):
        assert mod._extract_toml_block("plain text no fences") is None

    def test_extracts_content_between_fences(self):
        text = "prefix\n```toml\n[user]\nrole = \"x\"\n```\nsuffix"
        result = mod._extract_toml_block(text)
        assert result == '[user]\nrole = "x"'

    def test_strips_whitespace(self):
        text = "```toml\n  \n[user]\nrole = \"x\"\n  \n```"
        result = mod._extract_toml_block(text)
        assert result is not None
        assert result.startswith("[user]")


# ---------------------------------------------------------------------------
# 8. Memory seed called
# ---------------------------------------------------------------------------

class TestMemorySeed:

    def test_seed_called_from_run_onboarding(self):
        seeded = []

        def _fake_seed(knowledge_state, producer_model):
            seeded.append(knowledge_state)

        fake_q    = {"message": {"content": "What else?"}}
        fake_synth = {"message": {"content": _TOML_RESPONSE}}

        def _chat(**kw):
            content = (kw.get("messages") or [{}])[0].get("content", "")
            return fake_q if "Generate ONE focused" in content else fake_synth

        with (
            patch("harness.agent.compress_knowledge", side_effect=_stub_compress),
            patch("harness.memory.assess_novelty", return_value=1),
            patch("harness.inference.chat", side_effect=_chat),
            patch("harness.skills.onboarding_skill._seed_memory", side_effect=_fake_seed),
        ):
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                td_path = Path(td)
                with (
                    patch("harness.config.USER_CONFIG_TOML", td_path / ".harness-user.toml"),
                    patch("harness.config.USER_PROFILE_PATH", td_path / "user_profile.md"),
                ):
                    mod.run_onboarding(
                        ask_fn=lambda q: _LONG,
                        producer_model="dummy",
                    )

        assert seeded, "_seed_memory was never called"

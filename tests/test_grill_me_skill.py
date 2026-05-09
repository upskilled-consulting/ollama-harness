"""
Tests for harness/skills/grill_me_skill.py.

Properties verified:
  1. Fatigue detector — 2 consecutive short answers terminates the loop.
  2. Empty answer terminates the loop immediately.
  3. Loop does not exceed max_rounds.
  4. Novelty gate stops the loop early after min_rounds when novelty is low.
  5. force_thorough=True disables novelty gate and runs to max_rounds.
  6. plan_question round 1 returns a goal-based question without an LLM call.
  7. plan_question round 2+ calls the LLM.
  8. synthesize_brief calls the LLM and returns its response.
  9. run_grill_me writes a .md brief file and returns its path.
 10. --for flag is parsed as target_skill.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import harness.skills.grill_me_skill as mod

# ---------------------------------------------------------------------------
# Shared stubs
# ---------------------------------------------------------------------------

def _make_ask(answers: list[str]):
    pool = list(reversed(answers))
    def ask(_q: str) -> str:
        return pool.pop() if pool else answers[-1]
    return ask


def _stub_compress(current: str, new: list[dict], **_) -> str:
    return (current + " " + " ".join(r.get("body", "") for r in new)).strip()


_LONG = "I need a very comprehensive and detailed system for managing complex data pipelines with real-time monitoring"
_SHORT = "yes"


# ---------------------------------------------------------------------------
# Loop behaviour — grill_me()
# Tests patch plan_question to avoid LLM calls in loop tests.
# ---------------------------------------------------------------------------

class TestGrillMeLoop:

    def _run(self, answers, *, min_rounds=3, max_rounds=8,
             novelty=10, force_thorough=False):
        asked = []
        def ask(q):
            asked.append(q)
            return answers[min(len(asked) - 1, len(answers) - 1)]

        with (
            patch("harness.skills.grill_me_skill.plan_question", return_value="What is your goal?"),
            patch("harness.agent.compress_knowledge", side_effect=_stub_compress),
            patch("harness.memory.assess_novelty", return_value=novelty),
        ):
            result = mod.grill_me(
                goal="test goal",
                ask_fn=ask,
                producer_model="dummy",
                min_rounds=min_rounds,
                max_rounds=max_rounds,
                force_thorough=force_thorough,
            )
        return result, asked

    # 1. Fatigue detector
    def test_fatigue_stops_after_consecutive_short_answers(self):
        answers = [_SHORT] * mod.MAX_INTERVIEW_ROUNDS
        _, asked = self._run(answers, min_rounds=2, max_rounds=8, novelty=10)
        # After FATIGUE_CONSECUTIVE=2 short answers the loop should stop
        assert len(asked) <= 2 + mod.FATIGUE_CONSECUTIVE

    # 2. Empty answer terminates immediately
    def test_empty_answer_terminates_immediately(self):
        _, asked = self._run([""], min_rounds=1, max_rounds=8)
        assert len(asked) == 1

    # 3. Max rounds cap
    def test_does_not_exceed_max_rounds(self):
        answers = [_LONG] * 10
        _, asked = self._run(answers, min_rounds=2, max_rounds=4, novelty=10)
        assert len(asked) <= 4

    # 4. Novelty gate stops after min_rounds
    def test_novelty_gate_stops_after_min_rounds(self):
        answers = [_LONG] * 10
        min_r = 3
        _, asked = self._run(answers, min_rounds=min_r, max_rounds=8, novelty=1)
        # Gate fires on round min_rounds+1 → should ask at most min_rounds+1 questions
        assert len(asked) <= min_r + 1

    # 5. --thorough disables novelty gate
    def test_thorough_runs_all_rounds_despite_low_novelty(self):
        answers = [_LONG] * 10
        _, asked = self._run(answers, min_rounds=2, max_rounds=5,
                             novelty=1, force_thorough=True)
        assert len(asked) == 5


# ---------------------------------------------------------------------------
# plan_question
# ---------------------------------------------------------------------------

class TestPlanQuestion:

    # 6. Round 1: no LLM call
    def test_round_1_no_llm_call(self):
        with patch("harness.inference.chat") as mock_chat:
            q = mod.plan_question("build a RAG system", "", round_num=1, producer_model="dummy")
        mock_chat.assert_not_called()
        assert isinstance(q, str) and len(q) > 0

    def test_round_1_contains_goal(self):
        q = mod.plan_question("build a RAG system", "", round_num=1, producer_model="dummy")
        assert "RAG system" in q

    # 7. Round 2+: LLM call
    def test_round_2_calls_llm(self):
        fake = {"message": {"content": "What is your data scale?"}}
        with patch("harness.inference.chat", return_value=fake) as mock_chat:
            q = mod.plan_question(
                "build a RAG system",
                "User wants semantic search over papers.",
                round_num=2,
                producer_model="dummy",
            )
        mock_chat.assert_called_once()
        assert isinstance(q, str) and len(q) > 0

    def test_round_2_question_includes_knowledge_state_in_prompt(self):
        fake = {"message": {"content": "How many papers?"}}
        with patch("harness.inference.chat", return_value=fake) as mock_chat:
            mod.plan_question(
                "rag", "User wants ChromaDB.", round_num=3, producer_model="dummy"
            )
        prompt = mock_chat.call_args[1]["messages"][0]["content"]
        assert "ChromaDB" in prompt


# ---------------------------------------------------------------------------
# synthesize_brief
# ---------------------------------------------------------------------------

class TestSynthesizeBrief:

    # 8. Calls LLM, returns response content
    def test_calls_llm_with_knowledge_state(self):
        expected_brief = (
            "## Context\n- RAG system\n"
            "## Goals\n- Search papers\n"
            "## Constraints & non-goals\n- Local only\n"
            "## Open questions\n- Which embedder?\n"
            "## Suggested next steps\n- Index data\n"
        )
        fake = {"message": {"content": expected_brief}}
        knowledge = "User wants local RAG over arXiv papers."
        with patch("harness.inference.chat", return_value=fake) as mock_chat:
            brief = mod.synthesize_brief("build rag", knowledge, "dummy")
        mock_chat.assert_called_once()
        prompt = mock_chat.call_args[1]["messages"][0]["content"]
        assert "local RAG" in prompt
        assert brief == expected_brief.strip()

    def test_brief_contains_required_section_headings(self):
        sections = [
            "## Context", "## Goals", "## Constraints",
            "## Open questions", "## Suggested next steps",
        ]
        content = "\n".join(f"{s}\n- item\n" for s in sections)
        fake = {"message": {"content": content}}
        with patch("harness.inference.chat", return_value=fake):
            brief = mod.synthesize_brief("goal", "knowledge", "dummy")
        for s in sections:
            assert s in brief, f"Missing section: {s!r}"


# ---------------------------------------------------------------------------
# run_grill_me — integration
# ---------------------------------------------------------------------------

class TestRunGrillMe:

    # 9. Writes .md file and returns its path
    def test_writes_brief_file(self, tmp_path):
        brief_content = (
            "## Context\n- slides\n"
            "## Goals\n- communicate research\n"
            "## Constraints & non-goals\n- 20 slides max\n"
            "## Open questions\n- audience?\n"
            "## Suggested next steps\n- draft outline\n"
        )
        fake_q    = {"message": {"content": "What is your target audience?"}}
        fake_brief = {"message": {"content": brief_content}}

        def _chat(**kwargs):
            content = (kwargs.get("messages") or [{}])[0].get("content", "")
            return fake_q if "Generate ONE focused" in content else fake_brief

        with (
            patch("harness.inference.chat", side_effect=_chat),
            patch("harness.agent.compress_knowledge", side_effect=_stub_compress),
            patch("harness.memory.assess_novelty", return_value=10),
            patch("harness.config.BRIEFS_DIR", tmp_path),
        ):
            # Re-import so BRIEFS_DIR is picked up from config at call-time
            path_str = mod.run_grill_me(
                task="/grill-me create slides",
                producer_model="dummy",
                ask_fn=_make_ask([_LONG] * 10),
            )

        path = Path(path_str)
        assert path.exists(), f"Brief not written: {path}"
        assert path.suffix == ".md"
        text = path.read_text(encoding="utf-8")
        assert "## Context" in text

    # 10. --for flag
    def test_for_flag_sets_target_skill(self):
        captured = {}

        def _fake_grill_me(goal, ask_fn, *, target_skill="general", **_):
            captured["target_skill"] = target_skill
            return "knowledge"

        def _fake_brief(goal, ks, producer_model, target_skill="general", trace=None, **_):
            captured["brief_skill"] = target_skill
            return (
                "## Context\n- test\n## Goals\n- test\n"
                "## Constraints & non-goals\n- test\n"
                "## Open questions\n- test\n## Suggested next steps\n- test\n"
            )

        with (
            patch("harness.skills.grill_me_skill.grill_me", side_effect=_fake_grill_me),
            patch("harness.skills.grill_me_skill.synthesize_brief", side_effect=_fake_brief),
        ):
            with tempfile.TemporaryDirectory() as td:
                with patch("harness.config.BRIEFS_DIR", Path(td)):
                    mod.run_grill_me(
                        task="/grill-me build slides --for deck",
                        producer_model="dummy",
                        ask_fn=_make_ask([_LONG]),
                    )

        assert captured.get("target_skill") == "deck", f"Got: {captured}"
        assert captured.get("brief_skill") == "deck"

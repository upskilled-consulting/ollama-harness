"""
grill_me_skill.py — /grill-me: saturation-driven user interview.

Mirrors gather_research() loop shape:
  - plan_question() is the analogue of plan_query()
  - user answers are the analogue of web search results
  - assess_novelty() + compress_knowledge() gate and compress as usual
  - fatigue detector (2+ consecutive short answers) mirrors oversearch detector

Output: structured knowledge brief written to data/briefs/<slug>.md
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Callable

MIN_INTERVIEW_ROUNDS = 3
MAX_INTERVIEW_ROUNDS = 8
NOVELTY_THRESHOLD    = 3   # same as gather_research()
SHORT_ANSWER_WORDS   = 15  # fatigue detector floor
FATIGUE_CONSECUTIVE  = 2   # bail after N consecutive short answers

_COMPRESS_MODEL = os.environ.get(
    "COMPRESS_MODEL",
    os.environ.get("HARNESS_PRODUCER_MODEL", "pi-qwen-32b"),
)

_QUESTION_PROMPT = """\
Goal: {goal}
Target output: {target_skill}
Round: {round_num} of {max_rounds}

What is already known:
{knowledge_state}

Generate ONE focused follow-up question to learn important information NOT yet covered above.
Early rounds should cover: who is asking, what they need, why it matters, constraints, success criteria.
Later rounds should drill into specifics.
Output ONLY the question, nothing else."""

_BRIEF_PROMPT = """\
You interviewed a user about their goal. Below is all the information gathered.
Synthesize it into a structured markdown knowledge brief.

Goal: {goal}
Target output: {target_skill}

Knowledge gathered:
{knowledge_state}

Write the brief using EXACTLY these five headers in order:
## Context
## Goals
## Constraints & non-goals
## Open questions
## Suggested next steps

Be concise. Each section: 2-5 bullet points. Output ONLY the brief, nothing else."""


def plan_question(
    goal: str,
    knowledge_state: str,
    round_num: int,
    producer_model: str = _COMPRESS_MODEL,
    target_skill: str = "general",
    trace=None,
) -> str:
    """Generate one targeted interview question for the current round."""
    if round_num == 1 or not knowledge_state:
        return f"Tell me about your goal: {goal.strip()} — what are you trying to accomplish and why?"

    from harness.inference import chat as _chat

    prompt = _QUESTION_PROMPT.format(
        goal=goal,
        target_skill=target_skill or "general",
        round_num=round_num,
        max_rounds=MAX_INTERVIEW_ROUNDS,
        knowledge_state=knowledge_state[:1200],
    )
    resp = _chat(
        model=producer_model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.4, "num_predict": 120},
    )
    if trace is not None:
        trace.log_usage(resp, stage="grill_question")
    question = resp["message"]["content"].strip().strip('"')
    return question or f"What else should I know about your goal for round {round_num}?"


def synthesize_brief(
    goal: str,
    knowledge_state: str,
    producer_model: str = _COMPRESS_MODEL,
    target_skill: str = "general",
    trace=None,
) -> str:
    """Turn the accumulated knowledge_state into a structured markdown brief."""
    from harness.inference import chat as _chat

    prompt = _BRIEF_PROMPT.format(
        goal=goal,
        target_skill=target_skill or "general",
        knowledge_state=knowledge_state[:3000],
    )
    resp = _chat(
        model=producer_model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.2, "num_predict": 800},
    )
    if trace is not None:
        trace.log_usage(resp, stage="grill_brief")
    return resp["message"]["content"].strip()


def grill_me(
    goal: str,
    ask_fn: Callable[[str], str],
    producer_model: str = _COMPRESS_MODEL,
    min_rounds: int = MIN_INTERVIEW_ROUNDS,
    max_rounds: int = MAX_INTERVIEW_ROUNDS,
    force_thorough: bool = False,
    target_skill: str = "general",
    trace=None,
) -> str:
    """
    Core interview loop. Returns accumulated knowledge_state.

    ask_fn(question) -> answer  — caller provides blocking I/O
    (terminal: input(); dashboard: gate event + SSE answer)
    """
    from harness.agent import compress_knowledge
    from harness.memory import assess_novelty

    knowledge_state = ""
    short_answer_streak = 0

    for round_num in range(1, max_rounds + 1):
        question = plan_question(
            goal, knowledge_state, round_num, producer_model, target_skill, trace
        )
        print(f"\n[grill-me] round {round_num}/{max_rounds}: {question}", flush=True)

        answer = ask_fn(question)

        if not answer or not answer.strip():
            print("  [grill-me] empty answer — stopping early", flush=True)
            break

        answer = answer.strip()
        word_count = len(answer.split())
        if word_count < SHORT_ANSWER_WORDS:
            short_answer_streak += 1
            print(f"  [grill-me] short answer ({word_count} words), streak={short_answer_streak}", flush=True)
        else:
            short_answer_streak = 0

        result_packet = [{"body": f"Q: {question}\nA: {answer}"}]

        if round_num > min_rounds:
            novelty = assess_novelty(result_packet, knowledge_state)
            print(f"  [grill-me] novelty={novelty}/10", flush=True)
            if not force_thorough and novelty < NOVELTY_THRESHOLD:
                print("  [grill-me] saturation — stopping", flush=True)
                break

        if short_answer_streak >= FATIGUE_CONSECUTIVE:
            print("  [grill-me] fatigue detected — stopping", flush=True)
            break

        knowledge_state = compress_knowledge(
            knowledge_state, result_packet, producer_model=producer_model, trace=trace
        )

    return knowledge_state


def run_grill_me(
    task: str,
    producer_model: str,
    ask_fn: Callable[[str], str],
    trace=None,
) -> str:
    """
    Entry point. Parses flags, runs interview, writes brief, returns brief path.

    Flags:
      --thorough          disable novelty gate, run all rounds
      --for <skill>       tailor questions toward target skill output
    """
    from harness.config import BRIEFS_DIR

    # Parse flags
    force_thorough = "--thorough" in task
    target_skill   = "general"
    for_match = re.search(r"--for\s+(\S+)", task)
    if for_match:
        target_skill = for_match.group(1)

    # Strip flags and skill tokens to get the bare goal
    goal = re.sub(r"/grill-me\s*", "", task)
    goal = re.sub(r"--thorough\s*", "", goal)
    goal = re.sub(r"--for\s+\S+\s*", "", goal).strip()
    if not goal:
        goal = "general user interview"

    print(f"\n[grill-me] starting interview — goal: {goal!r}", flush=True)
    if force_thorough:
        print("  [grill-me] --thorough: novelty gate disabled", flush=True)
    if target_skill != "general":
        print(f"  [grill-me] --for {target_skill}: questions tailored to {target_skill} output", flush=True)

    knowledge_state = grill_me(
        goal=goal,
        ask_fn=ask_fn,
        producer_model=producer_model,
        force_thorough=force_thorough,
        target_skill=target_skill,
        trace=trace,
    )

    print("\n[grill-me] synthesizing brief...", flush=True)
    brief = synthesize_brief(goal, knowledge_state, producer_model, target_skill, trace)

    # Write brief
    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^\w-]", "-", goal[:40].lower()).strip("-")
    ts   = time.strftime("%Y%m%d_%H%M%S")
    brief_path = BRIEFS_DIR / f"{slug}-{ts}.md"
    header = f"# Brief: {goal}\n\n_Target: {target_skill} | {ts}_\n\n"
    brief_path.write_text(header + brief, encoding="utf-8")

    print(f"\n[grill-me] brief → {brief_path}", flush=True)
    print("\n" + brief, flush=True)

    return str(brief_path)

"""
onboarding_skill.py — /onboarding: first-run personalization via guided interview.

Extends /grill-me with three additions:
  1. Fixed question scaffold — first 3 rounds are always role/domain, use cases, output prefs
  2. Persistent config output — data/user_profile.md + .harness-user.toml
  3. ChromaDB memory seed — domain terms embedded into user_context collection

Re-run is additive: new answers are merged into existing config rather than overwriting it.
Question cap is 6 (3 fixed + 3 free-form) — respects that the user is new to the system.
"""

from __future__ import annotations

import re
import time
import tomllib
from collections.abc import Callable
from pathlib import Path

MAX_ONBOARDING_ROUNDS = 6   # 3 fixed + up to 3 free-form novelty-gated
MIN_FREE_ROUNDS       = 1   # minimum free-form rounds after the scaffold

FIXED_QUESTIONS = [
    "What is your role and primary domain? (e.g. ML researcher, software engineer, data scientist — and what area you work in)",
    "What are your main use cases for this agent? What kinds of tasks do you expect to run most often?",
    "How do you prefer your outputs formatted? (e.g. concise bullet points, detailed prose, markdown with headers, code-first)",
]

_PROFILE_PROMPT = """\
You interviewed a user to learn who they are and how they use this AI agent harness.
Below is all the information gathered. Synthesize it into two artifacts.

Knowledge gathered:
{knowledge_state}

--- ARTIFACT 1: TOML CONFIG ---
Write a TOML config block that starts with ```toml and ends with ```.
Use EXACTLY this structure (fill in values from the interview; use empty string "" if unknown):

```toml
[user]
role             = ""
domain           = ""
preferred_model  = ""
preferred_format = ""
verbosity        = ""

[routing]
research_tasks = ""
coding_tasks   = ""
```

--- ARTIFACT 2: MARKDOWN PROFILE ---
After the toml block, write a human-readable profile using these headers:
## Background
## Primary use cases
## Output preferences
## Domain expertise
## Notes

Be concise. Each section: 2–4 bullet points. Output ONLY the two artifacts, nothing else."""


def _extract_toml_block(text: str) -> str | None:
    """Pull the content between ```toml ... ``` fences."""
    m = re.search(r"```toml\s*(.*?)```", text, re.DOTALL)
    return m.group(1).strip() if m else None


def _extract_markdown_profile(text: str) -> str:
    """Strip the toml fence block and return the remaining markdown."""
    stripped = re.sub(r"```toml.*?```", "", text, flags=re.DOTALL).strip()
    return stripped


def _load_existing_toml() -> dict:
    from harness.config import USER_CONFIG_TOML
    if not USER_CONFIG_TOML.exists():
        return {}
    try:
        return tomllib.loads(USER_CONFIG_TOML.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _merge_toml(old: dict, new: dict) -> dict:
    """Additive merge: new values override old; old keys absent in new are preserved."""
    merged = {}
    for section in set(list(old.keys()) + list(new.keys())):
        old_sec = old.get(section, {})
        new_sec = new.get(section, {})
        merged[section] = {**old_sec, **{k: v for k, v in new_sec.items() if v}}
    return merged


def _dict_to_toml(d: dict) -> str:
    lines = []
    for section, values in d.items():
        lines.append(f"[{section}]")
        for k, v in values.items():
            lines.append(f'{k} = "{v}"')
        lines.append("")
    return "\n".join(lines).strip()


def _seed_memory(knowledge_state: str, producer_model: str) -> None:
    """Embed key user-context chunks into ChromaDB user_context collection."""
    try:
        import chromadb

        from harness.memory import CHROMA_PATH, _get_chroma_ef

        ef = _get_chroma_ef()
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        col = client.get_or_create_collection(
            name="user_context",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
        chunks = [s.strip() for s in re.split(r"[.\n]", knowledge_state) if len(s.strip()) > 20]
        if not chunks:
            return
        ts = str(int(time.time()))
        col.upsert(
            ids=[f"uctx_{ts}_{i}" for i in range(len(chunks))],
            documents=chunks,
            metadatas=[{"source": "onboarding", "timestamp": ts}] * len(chunks),
        )
        print(f"  [onboarding] seeded {len(chunks)} chunks into user_context memory")
    except Exception as e:
        print(f"  [onboarding] memory seed skipped: {e}")


def synthesize_and_write(
    knowledge_state: str,
    producer_model: str,
    trace=None,
) -> tuple[Path, Path]:
    """
    Turn knowledge_state into a TOML config + markdown profile.
    Merges with any existing .harness-user.toml.
    Returns (user_profile_path, user_config_toml_path).
    """
    from harness.config import USER_CONFIG_TOML, USER_PROFILE_PATH
    from harness.inference import chat as _chat

    prompt = _PROFILE_PROMPT.format(knowledge_state=knowledge_state[:3000])
    resp = _chat(
        model=producer_model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.2, "num_predict": 1000},
    )
    if trace is not None:
        trace.log_usage(resp, stage="onboarding_synth")
    output = resp["message"]["content"].strip()

    # --- TOML ---
    toml_str = _extract_toml_block(output)
    if toml_str:
        try:
            new_data = tomllib.loads(toml_str)
        except Exception:
            new_data = {}
        old_data = _load_existing_toml()
        merged   = _merge_toml(old_data, new_data)
        final_toml = _dict_to_toml(merged)
        USER_CONFIG_TOML.write_text(final_toml + "\n", encoding="utf-8")
        print(f"  [onboarding] config → {USER_CONFIG_TOML}")
    else:
        print("  [onboarding] TOML extraction failed — skipping config write")

    # --- Markdown profile ---
    md = _extract_markdown_profile(output)
    if not md:
        md = knowledge_state  # fallback: raw knowledge
    ts = time.strftime("%Y-%m-%d %H:%M")
    header = f"# User Profile\n\n_Last updated: {ts}_\n\n"
    USER_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    USER_PROFILE_PATH.write_text(header + md, encoding="utf-8")
    print(f"  [onboarding] profile → {USER_PROFILE_PATH}")

    return USER_PROFILE_PATH, USER_CONFIG_TOML


def run_onboarding(
    ask_fn: Callable[[str], str],
    producer_model: str,
    trace=None,
) -> None:
    """
    Run the onboarding interview and write persistent config + profile.

    3 fixed rounds (role, use cases, output prefs) followed by up to 3 free-form
    novelty-gated rounds — 6 total cap, regardless of grill_me defaults.
    """
    from harness.agent import compress_knowledge
    from harness.memory import assess_novelty
    from harness.skills.grill_me_skill import plan_question

    existing = _load_existing_toml()
    is_rerun = bool(existing)
    if is_rerun:
        print("\n[onboarding] existing profile found — running in update mode (additive)")
    else:
        print("\n[onboarding] No user profile found. Starting personalization interview (~2 min).")
        print("  Answer a few questions so the agent can tailor its behaviour to you.")

    knowledge_state = ""

    # Phase 1 — fixed scaffold (3 questions, no novelty gate)
    for i, question in enumerate(FIXED_QUESTIONS, start=1):
        print(f"\n[onboarding] {i}/{MAX_ONBOARDING_ROUNDS}: {question}", flush=True)
        answer = ask_fn(question)
        if not answer or not answer.strip():
            continue
        packet = [{"body": f"Q: {question}\nA: {answer.strip()}"}]
        knowledge_state = compress_knowledge(knowledge_state, packet,
                                             producer_model=producer_model, trace=trace)

    # Phase 2 — free-form novelty-gated rounds (up to 3 more)
    free_start = len(FIXED_QUESTIONS) + 1
    short_streak = 0
    for round_num in range(free_start, MAX_ONBOARDING_ROUNDS + 1):
        question = plan_question(
            goal="onboarding: learn about this user to personalise the agent",
            knowledge_state=knowledge_state,
            round_num=round_num,
            producer_model=producer_model,
            target_skill="user profile",
            trace=trace,
        )
        print(f"\n[onboarding] {round_num}/{MAX_ONBOARDING_ROUNDS}: {question}", flush=True)
        answer = ask_fn(question)
        if not answer or not answer.strip():
            break
        answer = answer.strip()
        if len(answer.split()) < 10:
            short_streak += 1
            if short_streak >= 2:
                break
        else:
            short_streak = 0

        packet = [{"body": f"Q: {question}\nA: {answer}"}]

        # Novelty gate fires after the first free round
        if round_num > free_start:
            novelty = assess_novelty(packet, knowledge_state)
            print(f"  [onboarding] novelty={novelty}/10", flush=True)
            if novelty < 3:
                print("  [onboarding] saturation — stopping", flush=True)
                break

        knowledge_state = compress_knowledge(knowledge_state, packet,
                                             producer_model=producer_model, trace=trace)

    print("\n[onboarding] synthesizing profile...", flush=True)
    synthesize_and_write(knowledge_state, producer_model, trace)

    print("\n[onboarding] seeding memory...", flush=True)
    _seed_memory(knowledge_state, producer_model)

    print("\n[onboarding] complete. Run /orientation to see your configured environment.\n",
          flush=True)

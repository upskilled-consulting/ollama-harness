"""
scripts/seed_rl_bank.py — Expand the RL task bank using the LLM.

Reads existing prompts from rl_bank.jsonl, samples a subset as few-shot examples,
asks the LLM to generate N new diverse variants per batch, deduplicates against
the existing set, and appends new entries to the bank.

Usage:
    python scripts/seed_rl_bank.py [--count 20] [--batch 5] [--task-type research]
    python scripts/seed_rl_bank.py --count 30 --task-type web_search
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from harness.inference import chat as _chat

BANK_PATH = Path(__file__).parent.parent / "tasks" / "rl_bank.jsonl"

TASK_TYPES = ["research", "web_search", "analysis", "synthesis", "comparison"]

_SYSTEM = """\
You are a task generator for an AI agent training pipeline.

Your job is to produce diverse, high-quality task prompts that an AI research agent
would be asked to complete. Each task should:
- Be specific enough that a well-performing agent can produce a verifiably good response
- Cover a distinct topic or angle not already in the existing bank
- Be completable via web search + synthesis (no live data feeds, no login required)
- Vary in difficulty (easy/medium/hard) and subtopic

Task types:
  research    — survey, best-practices, tradeoffs, state-of-the-art
  comparison  — compare X vs Y across defined criteria
  analysis    — analyze a concept, technique, or architectural decision in depth
  synthesis   — synthesize multiple sources into a structured overview
  web_search  — find specific current information (pricing, benchmarks, releases)

Output ONLY a JSON array of objects with keys:
  prompt      — the full task string (1-2 sentences, no "save to" path)
  task_type   — one of: research, comparison, analysis, synthesis, web_search
  difficulty  — one of: easy, medium, hard

No markdown fences, no commentary — just the JSON array."""

_USER_TMPL = """\
Existing prompts in the bank (do NOT duplicate these topics):
{existing}

Generate {count} new diverse task prompts. Focus on task_type: {task_type}.
Cover different subtopics, angles, and difficulties. Return only the JSON array."""


def _load_bank(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def _prompt_fingerprint(prompt: str) -> str:
    """Simple word-set fingerprint for deduplication."""
    words = set(re.findall(r"\b\w{4,}\b", prompt.lower()))
    return frozenset(words)


def _too_similar(new_prompt: str, existing_fps: list) -> bool:
    new_fp = _prompt_fingerprint(new_prompt)
    for fp in existing_fps:
        overlap = len(new_fp & fp) / max(len(new_fp | fp), 1)
        if overlap > 0.55:
            return True
    return False


def generate_batch(existing: list[dict], count: int, task_type: str, model: str) -> list[dict]:
    sample = random.sample(existing, min(12, len(existing))) if existing else []
    existing_str = "\n".join(f"- {r['prompt']}" for r in sample) if sample else "(none yet)"

    user_msg = _USER_TMPL.format(
        existing=existing_str,
        count=count,
        task_type=task_type,
    )

    resp = _chat(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user",   "content": user_msg},
        ],
        options={"temperature": 0.8, "num_predict": 4096},
    )
    raw = resp["message"]["content"].strip()
    raw = re.sub(r"^```[a-z]*\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        items = json.loads(raw)
        if not isinstance(items, list):
            print(f"  [seed] unexpected response shape: {type(items)}")
            return []
        return items
    except json.JSONDecodeError as e:
        print(f"  [seed] JSON parse failed: {e}")
        print(f"  [seed] raw response:\n{raw[:400]}")
        return []


def main():
    ap = argparse.ArgumentParser(description="Expand RL task bank via LLM generation")
    ap.add_argument("--count",     type=int, default=20,        help="Total new prompts to add")
    ap.add_argument("--batch",     type=int, default=5,         help="Prompts per LLM call")
    ap.add_argument("--task-type", default="research",          help=f"One of: {', '.join(TASK_TYPES)} (or 'all')")
    ap.add_argument("--model",     default="",                  help="Model to use (default: COMPRESS_MODEL)")
    ap.add_argument("--output",    default=str(BANK_PATH),      help="Output JSONL path")
    args = ap.parse_args()

    if not args.model:
        from harness.agent import COMPRESS_MODEL
        model = COMPRESS_MODEL
    else:
        model = args.model

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    existing = _load_bank(out_path)
    existing_fps = [_prompt_fingerprint(r["prompt"]) for r in existing]
    print(f"[seed] existing bank: {len(existing)} prompts")
    print(f"[seed] target: +{args.count} new prompts  task_type={args.task_type}  model={model}")

    task_types = TASK_TYPES if args.task_type == "all" else [args.task_type]
    added = 0
    attempts = 0
    max_attempts = args.count * 3  # give up after 3x attempts to avoid infinite loop

    with open(out_path, "a", encoding="utf-8") as f:
        while added < args.count and attempts < max_attempts:
            task_type = task_types[attempts % len(task_types)]
            batch_size = min(args.batch, args.count - added)
            print(f"\n[seed] generating {batch_size} prompts  type={task_type}  (added {added}/{args.count})")

            candidates = generate_batch(existing, batch_size, task_type, model)
            attempts += 1

            for item in candidates:
                prompt = (item.get("prompt") or "").strip()
                if not prompt or len(prompt) < 20:
                    continue
                if _too_similar(prompt, existing_fps):
                    print(f"  [seed] skipped (too similar): {prompt[:60]}")
                    continue

                rec = {
                    "prompt":     prompt,
                    "task_type":  item.get("task_type", task_type),
                    "difficulty": item.get("difficulty", "medium"),
                }
                f.write(json.dumps(rec) + "\n")
                f.flush()
                existing.append(rec)
                existing_fps.append(_prompt_fingerprint(prompt))
                added += 1
                print(f"  [seed] added [{added}]: {prompt[:70]}")

                if added >= args.count:
                    break

    print(f"\n[seed] done — added {added} prompts to {out_path}")
    print(f"[seed] bank total: {len(existing)} prompts")


if __name__ == "__main__":
    main()

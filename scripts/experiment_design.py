"""
experiment_design.py — LLM-driven ExperimentSpec generation.

Takes a plain-English description of what you want to test and produces a
validated ExperimentSpec JSON ready to hand to experiment_runner.py.

The LLM is given: the ExperimentSpec schema, available task IDs with
descriptions, known env var toggles (mutable_scope options), and your
research question. It returns a complete spec — you review it and optionally
run it immediately.

Usage (CLI):
    python experiment_design.py "does the prior knowledge pass improve depth?"
    python experiment_design.py "compare wiggum panel on vs off for T_A and T_B"
    python experiment_design.py --from-file autoresearch_program.md
    python experiment_design.py "..." --run          # design then immediately run
    python experiment_design.py "..." --out spec.json  # write to specific path

Usage (module):
    from experiment_design import design_experiment
    spec = design_experiment("what effect does search round count have on score?")

Environment:
    conda activate ollama-pi
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from experiment_panel import ExperimentSpec

from harness.inference import OllamaLike as _OllamaLike

_KEEP_ALIVE = int(os.environ.get("OLLAMA_KEEP_ALIVE", -1))
_chat = _OllamaLike(keep_alive=_KEEP_ALIVE).chat
_MODEL = os.environ.get("EXPERIMENT_DESIGN_MODEL", "pi-qwen-32b")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_EXPERIMENTS_DIR = os.path.join(_BASE_DIR, "experiments")


# ---------------------------------------------------------------------------
# Task registry summary (for the design prompt)
# ---------------------------------------------------------------------------

def _task_registry_summary() -> str:
    try:
        from eval_suite import SUITE
        lines = []
        for t in SUITE:
            lines.append(f'  "{t["id"]}": {t.get("desc", "")}')
        return "\n".join(lines)
    except Exception:
        return '  "T_A": top 5, context engineering\n  "T_B": open-ended, cost management\n  "T_C": top 3, agent failure modes\n  "T_D": top 3, context window management\n  "T_E": open-ended, prompt injection defense'


# ---------------------------------------------------------------------------
# Known mutable_scope catalog (env var toggles)
# ---------------------------------------------------------------------------

_MUTABLE_SCOPE_CATALOG = """\
Known mutable_scope options (type=env):

  Prior knowledge pass (planner.py — currently always on, add toggle):
    {"type":"env","var":"HARNESS_SKIP_PRIOR_KNOWLEDGE","levels":{"off":"","on":"1"}}

  Wiggum panel (panel.py — multi-persona evaluation):
    {"type":"env","var":"WIGGUM_PANEL","levels":{"off":"","on":"1"}}

  Research cache (agent.py — 24h SQLite cache):
    {"type":"env","var":"RESEARCH_CACHE","levels":{"off":"","on":"1"}}

  Producer model swap:
    {"type":"env","var":"HARNESS_PRODUCER_MODEL","levels":{"baseline":"pi-qwen-32b","treatment":"<other-model>"}}

  Synthesis instruction (autoresearch.py optimization target — write to .env as SYNTH_INSTRUCTION):
    {"type":"env","var":"SYNTH_INSTRUCTION","levels":{"baseline":"<current>","treatment":"<candidate>"}}

For code-level changes not expressible as env vars (e.g. adding a new pipeline step),
set mutable_scope.type to "manual" and describe the change in mutable_scope.change — the
runner will print a reminder to apply it before each treatment level."""


# ---------------------------------------------------------------------------
# Design prompt
# ---------------------------------------------------------------------------

_DESIGN_PROMPT = """\
You design controlled experiments for an LLM agent research harness.

You will be given a research question or hypothesis and must produce a complete
ExperimentSpec JSON. The spec will be used directly to run a completely
randomized design (CRD) experiment via experiment_runner.py.

## ExperimentSpec schema

{{
  "title":               string — short, descriptive, slug-friendly,
  "hypothesis":          string — a falsifiable claim with a measurable threshold,
  "falsified_if":        string — "mean <metric> delta < <N>" or similar numeric form,
  "factor":              {{"name": string, "levels": [string, string]}},
  "tasks":               [task_id, ...],    — pick 2-3 from the registry below,
  "replications":        integer — 2 or 3 (3 preferred for noise robustness),
  "response_variables":  [string, ...],     — e.g. ["score_r1","depth_r1","wiggum_rounds"],
  "controlled_variables":{{"producer": string, "evaluator": string, ...}},
  "mutable_scope":       {{"type":"env","var":string,"levels":{{"off":string,"on":string}}}},
  "notes":               string — optional context, rationale, or caveats
}}

## Available task IDs

{task_registry}

## Available mutable_scope options

{mutable_scope_catalog}

## Wiggum scoring dimensions (available as response_variables)

  score_r1       — wiggum composite score on the first evaluation round (0–10)
  score_final    — wiggum composite score after all revision rounds (0–10)
  depth_r1       — depth dimension on round 1 (weight 0.25 — most sensitive to content quality)
  grounded_r1    — groundedness on round 1 (weight 0.15 — penalizes hallucinated APIs/stubs)
  specificity_r1 — specificity dimension on round 1 (weight 0.10)
  wiggum_rounds  — total revision rounds before PASS or MAX_ROUNDS
  output_bytes   — output document size in bytes

## Rules for a good spec

1. The hypothesis must be falsifiable: it must specify a NUMERIC threshold.
   Bad:  "The panel improves output quality."
   Good: "Enabling the wiggum panel improves mean score_r1 by >= 0.3 points."

2. falsified_if must be parseable: "mean <metric> delta < <N>" where <metric>
   is one of the response_variables and <N> is a number.

3. Choose tasks that are representative and cover different task_types:
   - enumerated (T_A, T_C, T_D) — tests that require exact item counts
   - best_practices (T_B, T_E) — open-ended synthesis
   - Mix them to avoid task-type confounds.

4. Factor levels: the first level is the BASELINE (feature disabled / current behaviour).
   The second level is the TREATMENT (feature enabled / the change you want to test).
   IMPORTANT: if the env var is a SKIP or DISABLE flag, invert the values so factor "off"
   maps to the skip var being set (feature absent) and factor "on" maps to var being empty
   (feature present). Example: HARNESS_SKIP_X → levels: {"off":"1","on":""}
   This ensures delta = treatment - baseline = improvement from enabling the feature.

5. replications: use 3. Use 2 only if runs are very expensive (>10 min each).

6. controlled_variables: always specify producer and evaluator model names.

## Research question

{research_question}

## Output

Respond with a valid JSON object only — no preamble, no explanation, no markdown fences.
The JSON must be a complete ExperimentSpec matching the schema above exactly."""


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def design_experiment(
    research_question: str,
    model: str | None = None,
) -> ExperimentSpec:
    """
    Call the LLM to generate an ExperimentSpec from a plain-English question.
    Returns a validated ExperimentSpec (raises ValueError if the LLM output is unparseable).
    """
    model = model or _MODEL
    task_registry = _task_registry_summary()

    prompt = _DESIGN_PROMPT.format(
        task_registry=task_registry,
        mutable_scope_catalog=_MUTABLE_SCOPE_CATALOG,
        research_question=research_question,
    )

    print(f"[design] generating spec (model={model})...")
    response = _chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.3, "think": False},
    )
    raw = response["message"]["content"].strip()

    # Strip markdown fences and thinking tags
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    try:
        spec_dict = json.loads(raw)
    except json.JSONDecodeError as e:
        # Attempt to extract JSON object from within the text
        m = re.search(r"\{[\s\S]+\}", raw)
        if m:
            try:
                spec_dict = json.loads(m.group(0))
            except json.JSONDecodeError:
                raise ValueError(f"LLM returned non-JSON: {raw[:300]}") from e
        else:
            raise ValueError(f"LLM returned non-JSON: {raw[:300]}") from e

    # Validate required fields
    required = ["title", "hypothesis", "falsified_if", "factor", "tasks",
                "replications", "response_variables", "controlled_variables", "mutable_scope"]
    missing = [k for k in required if k not in spec_dict]
    if missing:
        raise ValueError(f"LLM spec missing fields: {missing}\nGot: {json.dumps(spec_dict, indent=2)[:500]}")

    return ExperimentSpec.from_dict(spec_dict)


def _save_spec(spec: ExperimentSpec, out_path: str | None = None) -> str:
    if out_path is None:
        slug = re.sub(r"[^\w-]", "-", spec.title.lower())[:40].strip("-")
        out_dir = os.path.join(_EXPERIMENTS_DIR, slug)
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "spec.json")
    else:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(spec.to_json())
    return out_path


def _print_spec(spec: ExperimentSpec) -> None:
    print(f"\n{'='*60}")
    print(f" Experiment: {spec.title}")
    print(f"{'='*60}")
    print(f" Hypothesis:   {spec.hypothesis}")
    print(f" Falsified if: {spec.falsified_if}")
    print(f" Factor:       {spec.factor['name']}  levels={spec.factor['levels']}")
    print(f" Tasks:        {spec.tasks}  replications={spec.replications}")
    print(f" Mutable:      {json.dumps(spec.mutable_scope)}")
    print(f" Response vars:{spec.response_variables}")
    if spec.notes:
        print(f" Notes:        {spec.notes}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Design an experiment spec from a research question.")
    parser.add_argument("question", nargs="?", help="Plain-English research question")
    parser.add_argument("--from-file", metavar="PATH", help="Read research question from a file")
    parser.add_argument("--out", metavar="PATH", help="Write spec to this path (default: experiments/<slug>/spec.json)")
    parser.add_argument("--model", default=_MODEL, help=f"LLM model (default: {_MODEL})")
    parser.add_argument("--run", action="store_true", help="Run the experiment immediately after design")
    parser.add_argument("--dry-run", action="store_true", help="With --run: print CRD order only")
    args = parser.parse_args()

    if args.from_file:
        with open(args.from_file, encoding="utf-8") as f:
            question = f.read().strip()
    elif args.question:
        question = args.question
    else:
        parser.print_help()
        sys.exit(1)

    try:
        spec = design_experiment(question, model=args.model)
    except ValueError as e:
        print(f"\n[error] {e}")
        sys.exit(1)

    _print_spec(spec)

    out_path = _save_spec(spec, args.out)
    print(f"\n[design] spec written to: {out_path}")

    if args.run:
        print("\n[design] launching experiment runner...")
        from experiment_runner import run_experiment
        run_experiment(out_path, resume=False, dry_run=args.dry_run)
    else:
        print(f"\nTo run:     python experiment_runner.py {out_path}")
        print(f"To analyze: python experiment_analyzer.py {out_path}")

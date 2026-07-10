"""
harness.eval.experiment_panel — Three-persona evaluation panel for experiments.

Unlike panel.py (which evaluates document content quality), this panel evaluates
the experiment itself as a knowledge-producing artifact. Input is an ExperimentSpec
+ list of wiggum traces (one per task run); output is structured verdicts from
three epistemically distinct personas.

Personas:
  1. Methodologist     — design validity: falsifiability, confound control, replication
  2. Knowledge Auditor — epistemic validity: did output respond to feedback?
  3. Loop Optimizer    — actionability: does the analysis advance the next iteration?

Usage (module):
    from harness.eval.experiment_panel import ExperimentSpec, run_experiment_panel
    spec    = ExperimentSpec(title=..., hypothesis=..., ...)
    traces  = [...]
    reviews = run_experiment_panel(spec, traces)
"""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import asdict, dataclass

from harness.inference import OllamaLike as _OllamaLike

_KEEP_ALIVE = int(os.environ.get("OLLAMA_KEEP_ALIVE", -1))
_chat = _OllamaLike(keep_alive=_KEEP_ALIVE).chat

_DEFAULT_MODELS = {
    "Methodologist":     os.environ.get("EXPERIMENT_PANEL_METHODOLOGIST_MODEL", "glm4:9b"),
    "Knowledge Auditor": os.environ.get("EXPERIMENT_PANEL_AUDITOR_MODEL",       "pi-qwen-32b"),
    "Loop Optimizer":    os.environ.get("EXPERIMENT_PANEL_OPTIMIZER_MODEL",     "pi-qwen-32b"),
}


@contextmanager
def _nullctx():
    yield


# ---------------------------------------------------------------------------
# ExperimentSpec
# ---------------------------------------------------------------------------

@dataclass
class ExperimentSpec:
    title:                str
    hypothesis:           str
    falsified_if:         str
    factor:               dict           # {"name": str, "levels": list[str]}
    tasks:                list[str]
    replications:         int
    response_variables:   list[str]
    controlled_variables: dict
    mutable_scope:        dict
    notes:                str = ""
    task_defs:            dict = None    # optional inline task definitions keyed by task_id
    fixed_env:            dict = None    # env vars applied to every run regardless of treatment

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> ExperimentSpec:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Persona definitions
# ---------------------------------------------------------------------------

EXPERIMENT_PERSONAS = [
    {
        "name": "Methodologist",
        "system": (
            "You evaluate experimental design rigor for machine learning research. "
            "You check: (1) Is the hypothesis falsifiable — does it specify a measurable threshold? "
            "(2) Are confounds controlled — is only one variable changed at a time? "
            "(3) Is replication adequate — enough runs to distinguish signal from noise? "
            "(4) Are response variables appropriate — do they measure what the hypothesis claims? "
            "(5) Is there randomization in run order to prevent systematic bias? "
            "You flag any design flaw that would make the results uninterpretable. "
            "You are rigorous: a well-intentioned but under-powered experiment is still a bad experiment."
        ),
        "focus": "hypothesis falsifiability, confound control, replication adequacy, and run order randomization",
        "verdict_options": ["SOUND", "MARGINAL", "UNSOUND"],
        "verdict_guide": (
            "SOUND: hypothesis is falsifiable, confounds controlled, replications adequate. "
            "MARGINAL: one fixable design flaw (e.g. insufficient replications, one confound). "
            "UNSOUND: hypothesis is unfalsifiable, or multiple confounds, or results uninterpretable."
        ),
    },
    {
        "name": "Knowledge Auditor",
        "system": (
            "You evaluate whether an experiment produced genuine new knowledge. "
            "You read round-by-round evaluation traces — score trajectory, evaluator feedback, "
            "and output content excerpts — to assess: "
            "(1) Did the output actually change between revision rounds in response to feedback? "
            "(2) Do the final conclusions follow from the observed score data? "
            "(3) Are alternative explanations addressed, or does the analysis jump to the favoured conclusion? "
            "(4) Was any finding already known from prior runs (confirming rather than discovering)? "
            "You flag circular reasoning, confirmation bias, and rounds where feedback was ignored. "
            "You read the trace carefully — a high final score does not mean the experiment was informative."
        ),
        "focus": "feedback-to-content alignment, conclusion soundness, and genuine information gain",
        "verdict_options": ["VALID", "INCONCLUSIVE", "INVALID"],
        "verdict_guide": (
            "VALID: conclusions follow from data, feedback was acted on, new knowledge produced. "
            "INCONCLUSIVE: conclusions are plausible but not clearly supported. "
            "INVALID: conclusions contradict the data, or feedback was systematically ignored."
        ),
    },
    {
        "name": "Loop Optimizer",
        "system": (
            "You evaluate whether experiment findings are actionable for the next iteration. "
            "You check: "
            "(1) Does the analysis identify a specific variable to change next? "
            "(2) Are effect sizes large enough to distinguish signal from noise? "
            "(3) Is there a concrete next experiment clearly implied by the results? "
            "(4) Did this experiment advance understanding, or just confirm a prior belief? "
            "You return a next_experiment_suggestion: a concrete, specific proposal for what to test next — "
            "including what factor to vary, what level to compare, and what tasks to use. "
            "Be specific: name the file and function if a code change is implied."
        ),
        "focus": "actionability, effect size, and a concrete next-experiment proposal",
        "verdict_options": ["ADVANCE", "REVISE", "REDESIGN"],
        "verdict_guide": (
            "ADVANCE: findings are clear and actionable — update the baseline and design the next experiment. "
            "REVISE: findings are suggestive but need more replications or cleaner factor isolation. "
            "REDESIGN: findings are inconclusive or contradictory — the experiment spec needs to change."
        ),
    },
]


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

_METHODOLOGIST_PROMPT = """\
Experiment specification:
{spec_json}

Run summary (per task):
{run_summary}

Evaluate the experimental design from your perspective, focusing on: {focus}

Verdict options: {verdict_options}
Verdict guide: {verdict_guide}

Be specific. Name the exact design flaw if one exists.

Respond with valid JSON only, no preamble:
{{
  "score": integer 0-10,
  "verdict": one of {verdict_options},
  "issues": ["specific design flaw"],
  "strengths": ["specific design strength"]
}}"""

_AUDITOR_PROMPT = """\
Experiment hypothesis: {hypothesis}

Round-by-round evaluation traces (one entry per task run):
{trace_json}

Evaluate whether genuine new knowledge was produced, focusing on: {focus}

Verdict options: {verdict_options}
Verdict guide: {verdict_guide}

Check specifically: for each run, did the output content change meaningfully between rounds
in the direction the evaluator feedback requested?

Respond with valid JSON only, no preamble:
{{
  "score": integer 0-10,
  "verdict": one of {verdict_options},
  "issues": ["specific epistemic problem with evidence from the trace"],
  "strengths": ["specific thing done well"]
}}"""

_OPTIMIZER_PROMPT = """\
Experiment specification:
{spec_json}

Final results summary:
{results_summary}

Evaluate actionability for the next loop iteration, focusing on: {focus}

Verdict options: {verdict_options}
Verdict guide: {verdict_guide}

You MUST provide a next_experiment_suggestion — a concrete, specific proposal for what to test next.
Name the factor, comparison levels, tasks, and the file/function to change if code is involved.

Respond with valid JSON only, no preamble:
{{
  "score": integer 0-10,
  "verdict": one of {verdict_options},
  "issues": ["specific actionability gap"],
  "strengths": ["specific actionable finding"],
  "next_experiment_suggestion": "concrete proposal: factor=..., levels=[...], tasks=[...], change=..."
}}"""


# ---------------------------------------------------------------------------
# Trace formatting
# ---------------------------------------------------------------------------

def _format_run_summary(traces: list[dict]) -> str:
    lines = []
    for t in traces:
        task_id = t.get("task_id", "?")
        rounds  = t.get("rounds", [])
        scores  = [r.get("score", 0) for r in rounds]
        lines.append(
            f"  task={task_id}  rounds={len(rounds)}  "
            f"scores={scores}  final_score={scores[-1] if scores else '?'}  status={t.get('final', '?')}"
        )
    return "\n".join(lines) if lines else "(no runs)"


def _format_trace_for_auditor(traces: list[dict], max_content_chars: int = 400) -> str:
    out = []
    for t in traces:
        out.append(f"=== Task: {t.get('task_id', '?')} ===")
        for r in t.get("rounds", []):
            out.append(
                f"  Round {r.get('round', '?')}: score={r.get('score', '?')}  dims={json.dumps(r.get('dims', {}))}\n"
                f"  feedback: {r.get('feedback', '')[:300]}\n"
                f"  content_excerpt: {r.get('content', '')[:max_content_chars]}..."
            )
    return "\n".join(out) if out else "(no traces)"


def _format_results_summary(spec: ExperimentSpec, traces: list[dict]) -> str:
    lines = [
        f"Hypothesis: {spec.hypothesis}",
        f"Falsified if: {spec.falsified_if}",
        "",
        "Per-task results:",
    ]
    for t in traces:
        task_id = t.get("task_id", "?")
        rounds  = t.get("rounds", [])
        scores  = [r.get("score", 0) for r in rounds]
        r1_dims = rounds[0].get("dims", {}) if rounds else {}
        lines.append(
            f"  {task_id}: r1_score={scores[0] if scores else '?'}  "
            f"final_score={scores[-1] if scores else None}  rounds={len(rounds)}  status={t.get('final', '?')}"
        )
        if r1_dims:
            lines.append(f"    r1_dims: {json.dumps(r1_dims)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def _parse_response(raw: str, persona_name: str) -> dict:
    try:
        clean = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        clean = re.sub(r"\s*```$", "", clean)
        clean = re.sub(r"<think>.*?</think>", "", clean, flags=re.DOTALL).strip()
        data  = json.loads(clean)
        result = {
            "persona":   persona_name,
            "score":     int(data.get("score", 5)),
            "verdict":   str(data.get("verdict", "INDETERMINATE")),
            "issues":    [i for i in data.get("issues", []) if i],
            "strengths": [s for s in data.get("strengths", []) if s],
            "raw":       raw,
        }
        if "next_experiment_suggestion" in data:
            result["next_experiment_suggestion"] = str(data["next_experiment_suggestion"])
        return result
    except (json.JSONDecodeError, ValueError):
        pass

    verdict_m = re.search(r"\b(SOUND|UNSOUND|MARGINAL|VALID|INVALID|INCONCLUSIVE|ADVANCE|REVISE|REDESIGN)\b", raw)
    score_m   = re.search(r"\b(\d(?:\.\d)?)\s*(?:/\s*10|out of 10)\b", raw)
    return {
        "persona":   persona_name,
        "score":     int(float(score_m.group(1))) if score_m else 5,
        "verdict":   verdict_m.group(1) if verdict_m else "INDETERMINATE",
        "issues":    [],
        "strengths": [],
        "raw":       raw,
    }


def run_experiment_panel(
    spec:   ExperimentSpec,
    traces: list[dict],
    models: dict | None = None,
    trace=None,
) -> list[dict]:
    """Run the three-persona experiment panel in parallel."""
    _models   = {**_DEFAULT_MODELS, **(models or {})}
    spec_json = spec.to_json()

    run_summary       = _format_run_summary(traces)
    trace_for_auditor = _format_trace_for_auditor(traces)
    results_summary   = _format_results_summary(spec, traces)

    def _build_prompt(persona: dict) -> str:
        name = persona["name"]
        opts = json.dumps(persona["verdict_options"])
        if name == "Methodologist":
            return _METHODOLOGIST_PROMPT.format(
                spec_json=spec_json, run_summary=run_summary,
                focus=persona["focus"], verdict_options=opts, verdict_guide=persona["verdict_guide"],
            )
        elif name == "Knowledge Auditor":
            return _AUDITOR_PROMPT.format(
                hypothesis=spec.hypothesis, trace_json=trace_for_auditor,
                focus=persona["focus"], verdict_options=opts, verdict_guide=persona["verdict_guide"],
            )
        else:
            return _OPTIMIZER_PROMPT.format(
                spec_json=spec_json, results_summary=results_summary,
                focus=persona["focus"], verdict_options=opts, verdict_guide=persona["verdict_guide"],
            )

    def _run_persona(persona: dict) -> dict | None:
        name  = persona["name"]
        model = _models[name]
        if trace is not None:
            trace.name_thread(f"exp_panel/{name}")
        print(f"  [exp_panel] {name} (model={model})...")
        try:
            prompt = _build_prompt(persona)
            ctx    = trace.span(f"exp_panel/{name}") if trace is not None else _nullctx()
            with ctx:
                response = _chat(
                    model=model,
                    messages=[
                        {"role": "system", "content": persona["system"]},
                        {"role": "user",   "content": prompt},
                    ],
                    options={"temperature": 0.2, "think": False},
                )
            raw    = response["message"]["content"].strip()
            review = _parse_response(raw, name)
            print(f"    [{name}] score={review['score']}/10  verdict={review.get('verdict', '?')}  issues={len(review['issues'])}")
            return review
        except Exception as e:
            print(f"  [exp_panel] {name} failed ({e}) -- skipping")
            return None

    reviews = []
    with ThreadPoolExecutor(max_workers=len(EXPERIMENT_PERSONAS)) as pool:
        futures = {pool.submit(_run_persona, p): p["name"] for p in EXPERIMENT_PERSONAS}
        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
                if result is not None:
                    reviews.append(result)
            except Exception as e:
                print(f"  [exp_panel] {name} failed ({e}) -- skipping")

    order = {p["name"]: i for i, p in enumerate(EXPERIMENT_PERSONAS)}
    reviews.sort(key=lambda r: order.get(r["persona"], 99))
    return reviews


def experiment_panel_decision(reviews: list[dict]) -> dict:
    by_persona  = {r["persona"]: r for r in reviews}
    methodologist = by_persona.get("Methodologist", {})
    auditor       = by_persona.get("Knowledge Auditor", {})
    optimizer     = by_persona.get("Loop Optimizer", {})

    m_verdict = methodologist.get("verdict", "UNSOUND")
    a_verdict = auditor.get("verdict", "INVALID")
    o_verdict = optimizer.get("verdict", "REDESIGN")

    if m_verdict == "UNSOUND":
        return {
            "decision":   "REDESIGN",
            "confidence": 0.9,
            "rationale":  f"Methodologist: {m_verdict} — experiment design invalid",
            "next_experiment_suggestion": optimizer.get("next_experiment_suggestion"),
        }

    if m_verdict in ("SOUND", "MARGINAL") and a_verdict == "VALID" and o_verdict == "ADVANCE":
        scores = [r.get("score", 0) for r in reviews if r.get("score") is not None]
        confidence = round(sum(scores) / (10 * len(scores)), 2) if scores else 0.5
        return {
            "decision":   "KEEP",
            "confidence": confidence,
            "rationale":  "All three personas agree: sound design, valid findings, actionable next step",
            "next_experiment_suggestion": optimizer.get("next_experiment_suggestion"),
        }

    if o_verdict == "REDESIGN":
        return {
            "decision":   "REDESIGN",
            "confidence": 0.7,
            "rationale":  f"Loop Optimizer: {o_verdict} — findings insufficient to advance",
            "next_experiment_suggestion": optimizer.get("next_experiment_suggestion"),
        }

    return {
        "decision":   "REVISE",
        "confidence": 0.5,
        "rationale":  f"Mixed verdicts — Methodologist:{m_verdict} Auditor:{a_verdict} Optimizer:{o_verdict}",
        "next_experiment_suggestion": optimizer.get("next_experiment_suggestion"),
    }


def experiment_panel_issues(reviews: list[dict]) -> list[str]:
    seen:   set[str] = set()
    issues: list[str] = []
    for r in reviews:
        for issue in r.get("issues", []):
            key = issue.lower().strip()
            if key not in seen:
                seen.add(key)
                issues.append(f"[{r['persona']}] {issue}")
    return issues

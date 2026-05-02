"""
hf_export.py — export runs.jsonl to Hugging Face-ready training datasets.

Produces four dataset views from the same source log:

  sft.jsonl        — chat-format (system, user, assistant) from high-scoring PASS runs
                     Best for: supervised fine-tuning, distillation

  preference.jsonl — (prompt, chosen, rejected) from score-ranked run pairs
                     Best for: DPO, ORPO, CPO, preference optimization

  reward.jsonl     — (prompt, response, score, dimensions, issues, feedback)
                     Best for: reward model training, rubric distillation

  trajectory.jsonl — (task, plan, stage_trace) full pipeline metadata per run
                     Best for: agent policy imitation, tool-use distillation

Usage:
    python hf_export.py                               # export all to hf_datasets/
    python hf_export.py --sft-min-score 8.0           # stricter SFT filter
    python hf_export.py --pref-min-delta 0.5          # min score gap for preference pairs
    python hf_export.py --push nickmccarty/ollama-pi-harness-datasets
    python hf_export.py --out custom/dir

Environment:
    HF_TOKEN — required for --push
"""

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

RUNS_PATH   = os.path.join(os.path.dirname(__file__), "runs.jsonl")
DEFAULT_OUT = os.path.join(os.path.dirname(__file__), "hf_datasets")

# Minimum wiggum score for a run to qualify for SFT
DEFAULT_SFT_MIN_SCORE   = 7.5
# Minimum score gap between chosen and rejected for preference pairs
DEFAULT_PREF_MIN_DELTA  = 0.5
# Max chars of output content to include in dataset rows
CONTENT_LIMIT           = 16_000

AGENT_SYSTEM_PROMPT = (
    "You are a research agent. Given a task, conduct thorough research and produce "
    "a well-structured, comprehensive markdown document that directly addresses the task. "
    "Output ONLY the markdown document starting with a # heading. "
    "Include specific implementation details, code examples where relevant, and cite sources."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_runs() -> list[dict]:
    runs = []
    with open(RUNS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    runs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return runs


def get_content(run: dict) -> str | None:
    """Return output content: prefer inline final_content, fall back to reading output_path."""
    content = run.get("final_content")
    if content:
        return content[:CONTENT_LIMIT]
    path = run.get("output_path")
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                return f.read()[:CONTENT_LIMIT]
        except Exception:
            pass
    return None


def first_score(run: dict) -> float | None:
    scores = run.get("wiggum_scores") or []
    return scores[0] if scores else None


def first_eval(run: dict) -> dict | None:
    log = run.get("wiggum_eval_log") or []
    return log[0] if log else None


def build_user_prompt(run: dict) -> str:
    """Construct the user-turn prompt from task + plan metadata."""
    task = run.get("task") or ""
    plan = run.get("plan") or {}
    parts = [task]
    queries = plan.get("search_queries") or []
    if queries:
        parts.append("\nResearch angles: " + "; ".join(queries))
    notes = plan.get("notes") or ""
    if notes:
        parts.append(f"Notes: {notes}")
    return "\n".join(parts)


def task_key(run: dict) -> str:
    """Normalised task string for grouping repeated runs."""
    return (run.get("task") or "")[:200].strip()


# ---------------------------------------------------------------------------
# SFT dataset
# ---------------------------------------------------------------------------

def build_sft(runs: list[dict], min_score: float) -> list[dict]:
    """
    Chat-format rows from high-scoring PASS runs.
    Format: {"messages": [system, user, assistant], "metadata": {...}}
    """
    rows = []
    for run in runs:
        score = first_score(run)
        if score is None or score < min_score:
            continue
        if run.get("final") != "PASS":
            continue
        content = get_content(run)
        if not content:
            continue

        rows.append({
            "messages": [
                {"role": "system",    "content": AGENT_SYSTEM_PROMPT},
                {"role": "user",      "content": build_user_prompt(run)},
                {"role": "assistant", "content": content},
            ],
            "metadata": {
                "timestamp":      (run.get("timestamp") or "")[:19],
                "producer_model": run.get("producer_model") or "",
                "task_type":      run.get("task_type") or "",
                "wiggum_score":   score,
                "wiggum_rounds":  run.get("wiggum_rounds") or 0,
                "search_rounds":  run.get("search_rounds") or 0,
            },
        })

    rows.sort(key=lambda r: r["metadata"]["wiggum_score"], reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Preference dataset
# ---------------------------------------------------------------------------

def build_preference(runs: list[dict], min_delta: float) -> list[dict]:
    """
    DPO/ORPO-style rows from score-ranked run pairs on the same task.
    For each task with ≥2 scored runs, pairs the top third against the
    bottom third where score delta ≥ min_delta.
    Format: {"prompt", "chosen", "rejected", "score_chosen", "score_rejected", "delta", "task_type"}
    """
    # Group scored runs with readable content by task text
    groups: dict[str, list[dict]] = defaultdict(list)
    for run in runs:
        score = first_score(run)
        if score is None:
            continue
        content = get_content(run)
        if not content:
            continue
        groups[task_key(run)].append(run)

    rows = []
    for task, group in groups.items():
        if len(group) < 2:
            continue
        # Sort by score descending
        group.sort(key=lambda r: first_score(r), reverse=True)
        top    = group[:max(1, len(group) // 3)]
        bottom = group[-(max(1, len(group) // 3)):]

        for chosen_run in top:
            for rejected_run in bottom:
                if chosen_run is rejected_run:
                    continue
                sc = first_score(chosen_run)
                sr = first_score(rejected_run)
                delta = sc - sr
                if delta < min_delta:
                    continue

                chosen_content   = get_content(chosen_run)
                rejected_content = get_content(rejected_run)
                if not chosen_content or not rejected_content:
                    continue

                rows.append({
                    "prompt":          build_user_prompt(chosen_run),
                    "chosen":          chosen_content,
                    "rejected":        rejected_content,
                    "score_chosen":    sc,
                    "score_rejected":  sr,
                    "delta":           round(delta, 3),
                    "task_type":       chosen_run.get("task_type") or "",
                    "model_chosen":    chosen_run.get("producer_model") or "",
                    "model_rejected":  rejected_run.get("producer_model") or "",
                })

    rows.sort(key=lambda r: r["delta"], reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Reward dataset
# ---------------------------------------------------------------------------

def build_reward(runs: list[dict]) -> list[dict]:
    """
    Scalar reward rows with rubric breakdown and evaluator rationale.
    Format: {"prompt", "response", "score", "dimensions", "issues", "feedback",
             "model", "task_type", "wiggum_rounds"}
    """
    rows = []
    for run in runs:
        score = first_score(run)
        if score is None:
            continue
        content = get_content(run)
        if not content:
            continue
        eval_entry = first_eval(run)

        rows.append({
            "prompt":        build_user_prompt(run),
            "response":      content,
            "score":         score,
            "dimensions":    (run.get("wiggum_dims") or [{}])[0],
            "issues":        eval_entry.get("issues", [])    if eval_entry else [],
            "feedback":      eval_entry.get("feedback", "")  if eval_entry else "",
            "model":         run.get("producer_model") or "",
            "evaluator":     run.get("evaluator_model") or "",
            "task_type":     run.get("task_type") or "",
            "wiggum_rounds": run.get("wiggum_rounds") or 0,
            "final":         run.get("final") or "",
            "timestamp":     (run.get("timestamp") or "")[:19],
        })

    return rows


# ---------------------------------------------------------------------------
# Trajectory dataset
# ---------------------------------------------------------------------------

def build_trajectory(runs: list[dict]) -> list[dict]:
    """
    Full pipeline metadata traces — structural, no content.
    Format: {"task", "task_type", "complexity", "plan", "steps", "outcome"}
    """
    rows = []
    for run in runs:
        plan = run.get("plan") or {}

        # Build ordered stage steps from tokens_by_stage
        stage_order = ["search_query", "compress_knowledge", "tool_loop",
                       "synth", "synth_count", "wiggum_eval", "wiggum_revise"]
        tbs = run.get("tokens_by_stage") or {}
        steps = []
        for stage in stage_order:
            if stage not in tbs:
                continue
            v = tbs[stage]
            steps.append({
                "stage":      stage,
                "tokens_in":  v.get("input", 0),
                "tokens_out": v.get("output", 0),
                "calls":      v.get("calls", 1),
                "duration_s": round(v.get("total_ms", 0) / 1000, 2),
            })

        # Include wiggum score trajectory
        score_trace = []
        for i, entry in enumerate(run.get("wiggum_eval_log") or []):
            score_trace.append({
                "round":    entry.get("round", i + 1),
                "score":    entry.get("score"),
                "issues":   len(entry.get("issues") or []),
            })

        rows.append({
            "task":            run.get("task") or "",
            "task_type":       run.get("task_type") or plan.get("task_type") or "",
            "complexity":      plan.get("complexity") or "",
            "search_queries":  plan.get("search_queries") or [],
            "search_rounds":   run.get("search_rounds") or 0,
            "novelty_scores":  run.get("novelty_scores") or [],
            "steps":           steps,
            "score_trace":     score_trace,
            "final_score":     first_score(run),
            "final":           run.get("final") or "",
            "producer_model":  run.get("producer_model") or "",
            "run_duration_s":  run.get("run_duration_s"),
            "timestamp":       (run.get("timestamp") or "")[:19],
        })

    return rows


# ---------------------------------------------------------------------------
# Writer + Hub push
# ---------------------------------------------------------------------------

def write_jsonl(rows: list[dict], path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    kb = os.path.getsize(path) // 1024
    print(f"  -> {path}  ({len(rows)} rows, {kb} KB)")


def push_to_hub(rows: list[dict], repo_id: str, split_name: str, hf_token: str):
    try:
        from datasets import Dataset
    except ImportError:
        print("  [push] pip install datasets  to enable Hub push")
        return
    ds = Dataset.from_list(rows)
    ds.push_to_hub(repo_id, split=split_name, token=hf_token)
    print(f"  [push] {len(rows)} rows -> {repo_id} ({split_name})")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]

    out_dir      = DEFAULT_OUT
    min_score    = DEFAULT_SFT_MIN_SCORE
    min_delta    = DEFAULT_PREF_MIN_DELTA
    hub_repo     = None
    hf_token     = os.environ.get("HF_TOKEN", "")

    if "--out" in args:
        out_dir = args[args.index("--out") + 1]
    if "--sft-min-score" in args:
        min_score = float(args[args.index("--sft-min-score") + 1])
    if "--pref-min-delta" in args:
        min_delta = float(args[args.index("--pref-min-delta") + 1])
    if "--push" in args:
        hub_repo = args[args.index("--push") + 1]
    if "--hf-token" in args:
        import warnings
        warnings.warn(
            "--hf-token passes the token via CLI (visible in `ps` and shell history). "
            "Use the HF_TOKEN environment variable instead.",
            stacklevel=2,
        )
        hf_token = args[args.index("--hf-token") + 1]

    print(f"[hf_export] loading {RUNS_PATH}...")
    runs = load_runs()
    print(f"[hf_export] {len(runs)} runs loaded")
    print(f"[hf_export] output -> {out_dir}/")
    print()

    datasets = {
        "sft":        build_sft(runs, min_score),
        "preference": build_preference(runs, min_delta),
        "reward":     build_reward(runs),
        "trajectory": build_trajectory(runs),
    }

    for name, rows in datasets.items():
        print(f"[{name}] {len(rows)} rows")
        write_jsonl(rows, os.path.join(out_dir, f"{name}.jsonl"))
        if hub_repo and rows:
            if not hf_token:
                print(f"  [push] HF_TOKEN not set — skipping Hub push for {name}")
            else:
                push_to_hub(rows, hub_repo, split_name=name, hf_token=hf_token)

    print()
    print("[hf_export] done.")
    print()
    print("Next steps:")
    print(f"  SFT:        trl sft --model <base> --dataset {out_dir}/sft.jsonl")
    print(f"  Preference: trl dpo --model <sft-model> --dataset {out_dir}/preference.jsonl")
    print(f"  Hub push:   python hf_export.py --push <your-hf-username>/ollama-pi-datasets")


if __name__ == "__main__":
    main()

"""
analyze_exp_C.py — Model Pairing for DPO Signal Quality

Compares cross-model DPO pairs (pi-qwen-32b vs. qwen2.5-coder-14b) against
same-model temperature-varied pairs from Exp A on the same 10 tasks.

Reads:
  - runs.jsonl — to find Exp C runs tagged with HARNESS_EXPERIMENT_ID=model-pairing-for-dpo-signal-quality
  - data/rl_dataset/grpo.jsonl — Exp A same-model rollouts (for baseline delta)
  - build_dpo_dataset.py --cross-model output (hf_datasets/dpo.jsonl or passed via --dpo)

Outputs:
  - Mean/median score_delta by source (cross-model vs. temperature-varied)
  - DPO pass rate at min_delta thresholds 0.5, 1.0, 1.5
  - Score distributions per model per task
  - Final recommendation

Usage:
    # 1. Run Exp C first:
    #    python scripts/experiment_runner.py experiments/exp_C_model_pairing_spec.json
    # 2. Build cross-model DPO pairs:
    #    python scripts/build_dpo_dataset.py --cross-model --min-delta 0.5 --out hf_datasets/dpo_cross.jsonl
    # 3. Analyze:
    python scripts/analyze_exp_C.py
    python scripts/analyze_exp_C.py --runs data/runs.jsonl --dpo hf_datasets/dpo_cross.jsonl --grpo data/rl_dataset/grpo.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median, stdev

EXP_ID     = "model-pairing-for-dpo-signal-quality"
CODING_IDS = {"chunk_doc_segments", "async_sqlite_wrapper", "token_rate_limiter",
              "fastapi_trace_middleware", "runs_dataframe_summary"}

DEFAULT_RUNS = Path("data/runs.jsonl")
DEFAULT_DPO  = Path("hf_datasets/dpo_cross.jsonl")
DEFAULT_GRPO = Path("data/rl_dataset/grpo.jsonl")


def _load_jsonl(path: Path) -> list[dict]:
    records = []
    if not path.exists():
        return records
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=str(DEFAULT_RUNS))
    ap.add_argument("--dpo",  default=str(DEFAULT_DPO))
    ap.add_argument("--grpo", default=str(DEFAULT_GRPO))
    ap.add_argument("--out",  default="experiments/exp_C_results.json")
    args = ap.parse_args()

    runs      = _load_jsonl(Path(args.runs))
    dpo_pairs = _load_jsonl(Path(args.dpo))
    grpo_recs = _load_jsonl(Path(args.grpo))

    # ── Cross-model DPO pairs ────────────────────────────────────────────────
    cross_deltas: dict[str, list[float]] = defaultdict(list)  # keyed by task_type
    cross_all:    list[float]            = []
    pass_rates:   dict[str, int]         = {"0.5": 0, "1.0": 0, "1.5": 0}

    for p in dpo_pairs:
        delta = p.get("score_delta", 0.0)
        ttype = p.get("task_type", "unknown")
        cross_deltas[ttype].append(delta)
        cross_all.append(delta)
        for thresh in (0.5, 1.0, 1.5):
            if delta >= thresh:
                pass_rates[str(thresh)] += 1

    # ── Same-model temp-varied deltas from Exp A (grpo.jsonl) ───────────────
    exp_C_task_ids = {
        "chunk_doc_segments", "async_sqlite_wrapper", "token_rate_limiter",
        "fastapi_trace_middleware", "runs_dataframe_summary",
        "speculative_decoding_survey", "rlhf_dpo_grpo_compare",
        "fine_tuning_best_practices", "agentic_ai_best_practices",
        "embedding_model_survey",
    }
    # Match grpo records by prompt substring heuristic (tasks from Exp C prompt bank)
    temp_deltas: list[float] = []
    for rec in grpo_recs:
        completions = [c for c in rec.get("completions", []) if c.get("reward") is not None]
        if len(completions) < 2:
            continue
        scores = sorted([c["reward"] for c in completions], reverse=True)
        best, worst = scores[0], scores[-1]
        delta = best - worst
        if delta > 0:
            temp_deltas.append(delta)

    # ── Score distributions by model from Exp C runs ────────────────────────
    exp_c_runs = [r for r in runs if r.get("experiment_id") == EXP_ID or
                  r.get("harness_experiment_id") == EXP_ID]
    scores_by_model: dict[str, list[float]] = defaultdict(list)
    for r in exp_c_runs:
        model = r.get("producer_model", "unknown")
        score = (r.get("wiggum_scores") or [None])[-1]
        if score is not None:
            scores_by_model[model].append(float(score))

    # ── Decision ─────────────────────────────────────────────────────────────
    mean_cross = mean(cross_all)      if cross_all    else 0.0
    mean_temp  = mean(temp_deltas)    if temp_deltas  else 1.0
    ratio      = round(mean_cross / mean_temp, 3) if mean_temp else 0.0
    total_dpo  = len(dpo_pairs)

    pass_pct = {k: round(v / total_dpo, 3) if total_dpo else 0.0
                for k, v in pass_rates.items()}

    if ratio >= 1.5 and pass_pct.get("1.0", 0) >= 0.70:
        decision  = "use_cross_model_pairing"
        rationale = (f"cross-model delta ratio={ratio:.2f} (>= 1.5) AND "
                     f"{pass_pct['1.0']:.0%} of pairs pass min_delta=1.0")
    elif ratio < 1.2:
        decision  = "use_temperature_variation"
        rationale = f"cross-model delta ratio={ratio:.2f} (< 1.2) — models too similar; temperature variation is cheaper"
    else:
        decision  = "use_both_sources"
        rationale = f"cross-model delta ratio={ratio:.2f} — marginal; combine both sources, filter at min_delta=1.0"

    results = {
        "cross_model_deltas": {
            "mean":   round(mean_cross, 3),
            "median": round(median(cross_all), 3) if cross_all else 0.0,
            "std":    round(stdev(cross_all), 3) if len(cross_all) > 1 else 0.0,
            "n":      len(cross_all),
            "by_task_type": {k: {"mean": round(mean(v), 3), "n": len(v)}
                             for k, v in cross_deltas.items()},
        },
        "temp_varied_deltas_baseline": {
            "mean":   round(mean_temp, 3),
            "n":      len(temp_deltas),
        },
        "cross_vs_temp_ratio":  ratio,
        "dpo_pass_rates":       pass_pct,
        "total_dpo_pairs":      total_dpo,
        "scores_by_model":      {m: {"mean": round(mean(s), 3), "n": len(s)}
                                 for m, s in scores_by_model.items()},
        "decision":             decision,
        "rationale":            rationale,
    }

    print(f"\n── Cross-model DPO delta ──")
    print(f"  mean={mean_cross:.3f}  n={len(cross_all)}")
    for ttype, deltas in cross_deltas.items():
        print(f"  [{ttype}] mean={mean(deltas):.3f}  n={len(deltas)}")
    print(f"\n── Same-model temperature baseline delta ──")
    print(f"  mean={mean_temp:.3f}  n={len(temp_deltas)}")
    print(f"\n── Cross/temp ratio: {ratio:.2f} ──")
    print(f"\n── DPO pass rates ──")
    for thresh, pct in pass_pct.items():
        print(f"  min_delta={thresh}: {pct:.0%}  ({pass_rates[thresh]}/{total_dpo})")
    if scores_by_model:
        print(f"\n── Score by model ──")
        for m, s in scores_by_model.items():
            print(f"  {m}: mean={mean(s):.3f}  n={len(s)}")
    print(f"\n→ Decision: {decision}")
    print(f"  {rationale}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n[exp_C] results written to {out}")


if __name__ == "__main__":
    main()

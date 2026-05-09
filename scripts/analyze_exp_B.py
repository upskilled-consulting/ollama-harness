"""
analyze_exp_B.py — Leverage vs. Wiggum Scalar as GRPO Reward

Reads data/rl_dataset/grpo.jsonl (with leverage field added by collect_rl_data.py patch).
For each task, computes:
  - Kendall-tau(leverage_rank, score_rank) across rollouts
  - "Verbose outliers": rollouts where score >= 7.0 and leverage in bottom quartile
  - Rank diff between score-only and combined (0.7×score_norm + 0.3×leverage_norm)

Decision output: prints which reward to use for GRPO based on exp_B thresholds.

Usage:
    python scripts/analyze_exp_B.py
    python scripts/analyze_exp_B.py --grpo data/rl_dataset/grpo.jsonl --out experiments/exp_B_results.json
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import mean

DEFAULT_GRPO = Path("data/rl_dataset/grpo.jsonl")


def kendall_tau(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    concordant = discordant = tied_x = tied_y = 0
    for i in range(n):
        for j in range(i + 1, n):
            dx, dy = xs[i] - xs[j], ys[i] - ys[j]
            prod = dx * dy
            if prod > 0:   concordant += 1
            elif prod < 0: discordant += 1
            else:
                if dx == 0: tied_x += 1
                if dy == 0: tied_y += 1
    denom = math.sqrt((concordant + discordant + tied_x) * (concordant + discordant + tied_y))
    return round((concordant - discordant) / denom, 4) if denom else 0.0


def rank_list(xs: list[float]) -> list[int]:
    """Return 0-based rank indices (0 = highest)."""
    indexed = sorted(range(len(xs)), key=lambda i: xs[i], reverse=True)
    ranks = [0] * len(xs)
    for rank, idx in enumerate(indexed):
        ranks[idx] = rank
    return ranks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grpo", default=str(DEFAULT_GRPO))
    ap.add_argument("--out",  default="experiments/exp_B_results.json")
    args = ap.parse_args()

    path = Path(args.grpo)
    if not path.exists():
        print(f"[exp_B] grpo file not found: {path}")
        return

    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    print(f"[exp_B] {len(records)} task records loaded")

    all_taus:          list[float] = []
    all_verbose:       list[dict]  = []   # high-score low-leverage cases
    combined_disagree: list[float] = []   # fraction of pairs where combined reranks vs score

    for rec in records:
        completions = [c for c in rec.get("completions", [])
                       if c.get("reward") is not None and c.get("leverage") is not None]
        if len(completions) < 2:
            continue

        scores    = [c["reward"]   for c in completions]
        leverages = [c["leverage"] for c in completions]

        tau = kendall_tau(scores, leverages)
        all_taus.append(tau)

        # Verbose outlier: score high but leverage in bottom quartile
        lev_sorted = sorted(leverages)
        q1_lev = lev_sorted[len(lev_sorted) // 4]
        for c in completions:
            if c["reward"] >= 7.0 and c["leverage"] <= q1_lev:
                all_verbose.append({
                    "prompt_hash": rec.get("prompt_hash"),
                    "run_id":      c.get("run_id"),
                    "score":       c["reward"],
                    "leverage":    c["leverage"],
                })

        # Combined reward disagreement
        max_s = max(scores)    or 1.0
        max_l = max(leverages) or 1.0
        combined = [0.7 * (s / max_s) + 0.3 * (l / max_l)
                    for s, l in zip(scores, leverages)]

        score_ranks   = rank_list(scores)
        combined_ranks = rank_list(combined)
        diffs = sum(1 for a, b in zip(score_ranks, combined_ranks) if a != b)
        combined_disagree.append(diffs / len(completions))

    mean_tau        = round(mean(all_taus), 4)        if all_taus        else 0.0
    verbose_rate    = len(all_verbose) / max(sum(len(r.get("completions", [])) for r in records), 1)
    mean_disagree   = round(mean(combined_disagree), 4) if combined_disagree else 0.0

    # Decision
    if mean_tau >= 0.85:
        decision  = "use_score_only"
        rationale = f"Kendall-tau={mean_tau:.4f} — leverage and score agree on >{mean_tau:.0%} of pairs; leverage adds noise"
    elif mean_tau >= 0.65:
        decision  = "use_combined_reward"
        rationale = f"Kendall-tau={mean_tau:.4f} — moderate disagreement; use 0.7×score_norm + 0.3×leverage_norm"
    else:
        decision  = "investigate_manually"
        rationale = f"Kendall-tau={mean_tau:.4f} — systematic disagreement; inspect verbose_outliers before deciding"

    results = {
        "kendall_tau_mean":            mean_tau,
        "kendall_tau_per_task":        all_taus,
        "verbose_outliers_count":      len(all_verbose),
        "verbose_outlier_rate":        round(verbose_rate, 4),
        "verbose_outliers_sample":     all_verbose[:10],
        "combined_rerank_rate":        mean_disagree,
        "n_tasks":                     len(records),
        "decision":                    decision,
        "rationale":                   rationale,
    }

    print(f"\n── Kendall-τ(leverage, score) ──")
    print(f"  mean: {mean_tau:+.4f}")
    print(f"  per-task: {[round(t, 3) for t in all_taus]}")
    print(f"\n── Verbose outliers (score>=7.0, leverage in bottom Q1) ──")
    print(f"  count: {len(all_verbose)}  rate: {verbose_rate:.2%}")
    print(f"\n── Combined vs. score rank disagreement: {mean_disagree:.2%} of rollouts reranked ──")
    print(f"\n→ Decision: {decision}")
    print(f"  {rationale}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n[exp_B] results written to {out}")


if __name__ == "__main__":
    main()

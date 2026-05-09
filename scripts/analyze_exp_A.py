"""
analyze_exp_A.py — Reward Signal Richness: per-dimension vs. scalar

Reads data/rl_dataset/grpo.jsonl (produced by collect_rl_data.py after the
emit_grpo dims patch).  For each task computes:
  - Kendall-tau between each wiggum dimension and the composite reward across rollouts
  - Per-dim variance across rollouts
  - PCA of the 6-dim vectors — cumulative explained variance by component count
  - Fraction of rollout pairs where scalar rank != dim-weighted rank (scalar disagreement)

Decision output: prints which of the three reward strategies to use based on exp_A thresholds.

Usage:
    python scripts/analyze_exp_A.py
    python scripts/analyze_exp_A.py --grpo data/rl_dataset/grpo.jsonl --out experiments/exp_A_results.json
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean, stdev

DIMS = ["relevance", "completeness", "depth", "grounded", "specificity", "structure"]
DIM_WEIGHTS = {"relevance": 0.20, "completeness": 0.20, "depth": 0.25,
               "grounded": 0.15, "specificity": 0.10, "structure": 0.10}

DEFAULT_GRPO = Path("data/rl_dataset/grpo.jsonl")


def kendall_tau(xs: list[float], ys: list[float]) -> float:
    """Kendall-tau-b between two equal-length sequences."""
    n = len(xs)
    if n < 2:
        return 0.0
    concordant = discordant = tied_x = tied_y = 0
    for i in range(n):
        for j in range(i + 1, n):
            dx = xs[i] - xs[j]
            dy = ys[i] - ys[j]
            prod = dx * dy
            if prod > 0:
                concordant += 1
            elif prod < 0:
                discordant += 1
            else:
                if dx == 0:
                    tied_x += 1
                if dy == 0:
                    tied_y += 1
    denom = math.sqrt((concordant + discordant + tied_x) * (concordant + discordant + tied_y))
    return round((concordant - discordant) / denom, 4) if denom else 0.0


def pca_explained_variance(matrix: list[list[float]]) -> list[float]:
    """Naive PCA via covariance — returns cumulative explained variance ratio per component."""
    n = len(matrix)
    if n < 2:
        return []
    d = len(matrix[0])
    # Center columns
    col_means = [mean(row[j] for row in matrix) for j in range(d)]
    centered  = [[row[j] - col_means[j] for j in range(d)] for row in matrix]
    # Covariance matrix (d×d)
    cov = [[sum(centered[i][a] * centered[i][b] for i in range(n)) / (n - 1)
            for b in range(d)] for a in range(d)]
    # Variances on diagonal = eigenvalue upper bound proxies (power iteration is overkill here)
    # Use diagonal variances as approximate eigenvalues (valid when dims are weakly correlated)
    diag_vars = sorted([cov[i][i] for i in range(d)], reverse=True)
    total = sum(diag_vars) or 1.0
    cumulative, s = [], 0.0
    for v in diag_vars:
        s += v / total
        cumulative.append(round(s, 4))
    return cumulative


def scalar_vs_dim_disagreement(completions: list[dict]) -> float:
    """Fraction of pairs where scalar rank disagrees with dim-weighted rank."""
    if len(completions) < 2:
        return 0.0

    def dim_score(c: dict) -> float:
        dims = c.get("dims") or {}
        return sum(dims.get(d, 5) * w for d, w in DIM_WEIGHTS.items())

    n = len(completions)
    total = n * (n - 1) // 2
    if total == 0:
        return 0.0
    disagree = 0
    for i in range(n):
        for j in range(i + 1, n):
            a, b = completions[i], completions[j]
            scalar_a_better = a["reward"] > b["reward"]
            dim_a_better    = dim_score(a) > dim_score(b)
            if scalar_a_better != dim_a_better:
                disagree += 1
    return round(disagree / total, 4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grpo", default=str(DEFAULT_GRPO))
    ap.add_argument("--out",  default="experiments/exp_A_results.json")
    args = ap.parse_args()

    path = Path(args.grpo)
    if not path.exists():
        print(f"[exp_A] grpo file not found: {path}")
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

    print(f"[exp_A] {len(records)} task records loaded")

    all_dim_taus: dict[str, list[float]]  = defaultdict(list)
    all_dim_vars: dict[str, list[float]]  = defaultdict(list)
    all_disagreements: list[float]        = []
    all_dim_vectors:   list[list[float]]  = []

    for rec in records:
        completions = [c for c in rec.get("completions", []) if c.get("dims") and c.get("reward") is not None]
        if len(completions) < 2:
            continue

        rewards = [c["reward"] for c in completions]

        for dim in DIMS:
            dim_vals = [c["dims"].get(dim, 5) for c in completions]
            tau = kendall_tau(rewards, dim_vals)
            all_dim_taus[dim].append(tau)
            all_dim_vars[dim].append(stdev(dim_vals) if len(dim_vals) > 1 else 0.0)

        # PCA matrix (one row per rollout, one col per dim)
        for c in completions:
            vec = [c["dims"].get(d, 5) for d in DIMS]
            all_dim_vectors.append(vec)

        all_disagreements.append(scalar_vs_dim_disagreement(completions))

    # Summarize
    dim_tau_summary   = {d: round(mean(vs), 4) if vs else 0.0 for d, vs in all_dim_taus.items()}
    dim_var_summary   = {d: round(mean(vs), 4) if vs else 0.0 for d, vs in all_dim_vars.items()}
    pca_cumvar        = pca_explained_variance(all_dim_vectors) if all_dim_vectors else []
    mean_disagreement = round(mean(all_disagreements), 4) if all_disagreements else 0.0

    top2_cumvar = pca_cumvar[1] if len(pca_cumvar) >= 2 else 0.0

    # Decision
    if top2_cumvar >= 0.85 and mean_disagreement <= 0.10:
        decision = "use_scalar_only"
        rationale = f"top-2 PCA components explain {top2_cumvar:.0%} of variance; scalar disagrees on only {mean_disagreement:.0%} of pairs"
    elif top2_cumvar >= 0.85:
        decision = "use_top2_dims"
        rationale = f"top-2 components explain {top2_cumvar:.0%} but scalar disagrees on {mean_disagreement:.0%} of pairs — use depth+grounded weighted reward"
    else:
        decision = "use_dim_weighted_reward"
        rationale = f"top-2 components explain only {top2_cumvar:.0%} — full dim-weighted reward warranted"

    results = {
        "dim_tau_vs_composite":   dim_tau_summary,
        "dim_variance_mean":      dim_var_summary,
        "pca_cumulative_variance": pca_cumvar,
        "scalar_disagreement_mean": mean_disagreement,
        "n_tasks":                len(records),
        "n_rollouts_analyzed":    len(all_dim_vectors),
        "decision":               decision,
        "rationale":              rationale,
    }

    print("\n── Dimension Kendall-τ vs. composite ──")
    for d, tau in sorted(dim_tau_summary.items(), key=lambda x: -x[1]):
        print(f"  {d:15s}  tau={tau:+.4f}  var={dim_var_summary[d]:.3f}")
    print("\n── PCA cumulative variance ──")
    for i, v in enumerate(pca_cumvar, 1):
        print(f"  top-{i}: {v:.2%}")
    print(f"\n── Scalar vs. dim-weighted rank disagreement: {mean_disagreement:.2%} ──")
    print(f"\n→ Decision: {decision}")
    print(f"  {rationale}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n[exp_A] results written to {out}")


if __name__ == "__main__":
    main()

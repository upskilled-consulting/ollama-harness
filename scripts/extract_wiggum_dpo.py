"""
scripts/extract_wiggum_dpo.py — Extract DPO pairs from Wiggum revision rounds.

Each agent run stores per-round content + scores in wiggum_eval_log.
The first draft (low score) vs the final revised output (high score) are
natural chosen/rejected pairs with gaps of 5–8 points.

Usage:
    python scripts/extract_wiggum_dpo.py
    python scripts/extract_wiggum_dpo.py --min-gap 2.0 --max-per-prompt 3
    python scripts/extract_wiggum_dpo.py --runs data/runs.jsonl --out data/rl_dataset/wiggum_dpo.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from harness.config import DATA_DIR, RUNS_FILE

DEFAULT_OUT = DATA_DIR / "rl_dataset" / "wiggum_dpo.jsonl"


def _prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _clean_prompt(task: str) -> str:
    """Strip 'save to <path>' suffix appended by collect_rl_data."""
    task = re.sub(r"\s+save to\s+\S+\.md\s*$", "", task, flags=re.IGNORECASE).strip()
    return task


def extract_pairs(
    runs_path: Path,
    min_gap: float,
    max_per_prompt: int,
    use_intermediate: bool,
    exclude_types: set[str] | None = None,
) -> list[dict]:
    """Return DPO records from wiggum_eval_log revision rounds."""
    lines = runs_path.read_text(encoding="utf-8").strip().splitlines()

    # Group by prompt hash so we can cap max_per_prompt
    by_prompt: dict[str, list[dict]] = {}

    for line in lines:
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue

        elog = r.get("wiggum_eval_log") or []
        if len(elog) < 2:
            continue

        # Entries with actual content
        with_content = [e for e in elog if e.get("content") and isinstance(e["content"], str)]
        if len(with_content) < 2:
            continue

        task      = r.get("task", "")
        prompt    = _clean_prompt(task)
        if not prompt or prompt.startswith("/"):
            continue

        ph        = _prompt_hash(prompt)
        task_type = r.get("task_type", "research")
        if exclude_types and task_type in exclude_types:
            continue
        run_id    = r.get("run_id", "")

        if use_intermediate:
            # Emit every consecutive pair (round n → round n+1) with positive gap
            for i in range(len(with_content) - 1):
                rej = with_content[i]
                cho = with_content[i + 1]
                gap = cho.get("score", 0) - rej.get("score", 0)
                if gap < min_gap:
                    continue
                rec = _make_record(prompt, ph, task_type, run_id,
                                   cho, rej, gap)
                by_prompt.setdefault(ph, []).append(rec)
        else:
            # Only first vs last
            first = with_content[0]
            last  = with_content[-1]
            gap   = last.get("score", 0) - first.get("score", 0)
            if gap < min_gap:
                continue
            rec = _make_record(prompt, ph, task_type, run_id, last, first, gap)
            by_prompt.setdefault(ph, []).append(rec)

    # Cap per prompt, keep highest-gap pairs
    results: list[dict] = []
    for ph, recs in by_prompt.items():
        recs.sort(key=lambda x: x["score_gap"], reverse=True)
        results.extend(recs[:max_per_prompt])

    results.sort(key=lambda x: x["score_gap"], reverse=True)
    return results


def _make_record(prompt, ph, task_type, run_id, chosen_entry, rejected_entry, gap):
    return {
        "prompt":         prompt,
        "chosen":         chosen_entry["content"],
        "rejected":       rejected_entry["content"],
        "chosen_score":   chosen_entry.get("score", 0),
        "rejected_score": rejected_entry.get("score", 0),
        "score_gap":      round(gap, 2),
        "task_type":      task_type,
        "prompt_hash":    ph,
        "run_id":         run_id,
        "source":         "wiggum_revision",
        "chosen_round":   chosen_entry.get("round"),
        "rejected_round": rejected_entry.get("round"),
    }


def main():
    ap = argparse.ArgumentParser(description="Extract Wiggum revision DPO pairs")
    ap.add_argument("--runs",           default=str(RUNS_FILE),    help="Path to runs.jsonl")
    ap.add_argument("--out",            default=str(DEFAULT_OUT),  help="Output JSONL path")
    ap.add_argument("--min-gap",        type=float, default=1.0,   help="Min score gap (default 1.0)")
    ap.add_argument("--max-per-prompt", type=int,   default=3,     help="Max pairs per prompt (default 3)")
    ap.add_argument("--intermediate",    action="store_true",       help="Also emit consecutive round pairs")
    ap.add_argument("--overwrite",       action="store_true",       help="Overwrite output instead of append")
    ap.add_argument("--exclude-types",   default="annotate",        help="Comma-separated task_types to exclude (default: annotate)")
    args = ap.parse_args()

    runs_path = Path(args.runs)
    if not runs_path.exists():
        print(f"[extract] runs file not found: {runs_path}")
        sys.exit(1)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    exclude_types = set(t.strip() for t in args.exclude_types.split(",") if t.strip())
    print(f"[extract] reading {runs_path.name}  min-gap={args.min_gap}  max-per-prompt={args.max_per_prompt}  exclude={exclude_types or 'none'}")
    pairs = extract_pairs(runs_path, args.min_gap, args.max_per_prompt, args.intermediate, exclude_types)
    print(f"[extract] extracted {len(pairs)} pairs")

    if not pairs:
        print("[extract] nothing to write")
        return

    mode = "w" if args.overwrite else "a"
    with open(out_path, mode, encoding="utf-8") as f:
        for rec in pairs:
            f.write(json.dumps(rec) + "\n")

    print(f"[extract] wrote {len(pairs)} pairs -> {out_path}")

    # Stats
    gaps = [p["score_gap"] for p in pairs]
    print(f"  gap  avg={sum(gaps)/len(gaps):.1f}  min={min(gaps):.1f}  max={max(gaps):.1f}")
    prompts = len({p["prompt_hash"] for p in pairs})
    print(f"  unique prompts: {prompts}")
    task_types = {}
    for p in pairs:
        task_types[p["task_type"]] = task_types.get(p["task_type"], 0) + 1
    print(f"  task_types: {dict(sorted(task_types.items(), key=lambda x: -x[1]))}")


if __name__ == "__main__":
    main()

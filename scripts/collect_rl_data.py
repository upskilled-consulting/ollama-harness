"""
scripts/collect_rl_data.py — Collect RL training data via agent rollouts.

For each task in the bank, runs K rollouts at varied synthesis temperatures,
collects Wiggum scores and trajectory traces, then exports:
  data/rl_dataset/dpo.jsonl   — chosen/rejected pairs (score_gap >= min_gap)
  data/rl_dataset/grpo.jsonl  — all completions with rewards (HF GRPO format)

Checkpoints every rollout to SQLite so interrupted runs resume cleanly.

Usage:
    python scripts/collect_rl_data.py
    python scripts/collect_rl_data.py --rollouts 6 --min-gap 1.5 --limit 10
    python scripts/collect_rl_data.py --task-type research --rollouts 4
    python scripts/collect_rl_data.py --resume-only   # skip tasks with no cached rollouts
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from harness.config import DATA_DIR, RUNS_FILE

RL_DIR        = DATA_DIR / "rl_dataset"
ROLLOUTS_DIR  = DATA_DIR / "rl_rollouts"
CHECKPOINT_DB = DATA_DIR / "rl_checkpoint.db"
DEFAULT_BANK  = Path(__file__).parent.parent / "tasks" / "rl_bank.jsonl"

# Temperature schedule — cycles through rollouts for output diversity
TEMPS = [0.1, 0.5, 0.8, 0.3, 0.7, 0.2, 0.9, 0.4]


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------

def _init_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rollouts (
            prompt_hash  TEXT,
            rollout_idx  INTEGER,
            run_id       TEXT,
            score        REAL,
            out_path     TEXT,
            PRIMARY KEY (prompt_hash, rollout_idx)
        )
    """)
    conn.commit()
    return conn


def _checkpoint_get(conn: sqlite3.Connection, ph: str, idx: int) -> dict | None:
    row = conn.execute(
        "SELECT run_id, score, out_path FROM rollouts WHERE prompt_hash=? AND rollout_idx=?",
        (ph, idx),
    ).fetchone()
    return {"run_id": row[0], "score": row[1], "out_path": row[2]} if row else None


def _checkpoint_put(conn: sqlite3.Connection, ph: str, idx: int,
                    run_id: str, score: float, out_path: str):
    conn.execute(
        "INSERT OR REPLACE INTO rollouts VALUES (?,?,?,?,?)",
        (ph, idx, run_id, score, out_path),
    )
    conn.commit()


def _has_any_rollout(conn: sqlite3.Connection, ph: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM rollouts WHERE prompt_hash=? LIMIT 1", (ph,)
    ).fetchone())


# ---------------------------------------------------------------------------
# Run lookup
# ---------------------------------------------------------------------------

def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()[:12]


def _get_run(run_id: str) -> dict:
    if not run_id or not RUNS_FILE.exists():
        return {}
    with open(RUNS_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
                if r.get("run_id") == run_id:
                    return r
            except json.JSONDecodeError:
                pass
    return {}


# ---------------------------------------------------------------------------
# Single rollout
# ---------------------------------------------------------------------------

def run_rollout(prompt: str, temp: float, out_path: Path, score_only: bool = False) -> tuple[str, float, dict]:
    """Run the agent once. Returns (run_id, wiggum_score, run_data).

    score_only=True sets WIGGUM_MAX_ROUNDS=1 so Wiggum evaluates the raw
    synthesis output without revision. This preserves quality variance across
    temperature-varied rollouts, which is what we need for DPO pairs.
    """
    import harness.agent as agent

    task = f"{prompt} save to {out_path}"
    os.environ["HARNESS_SYNTH_TEMPERATURE"] = str(temp)
    os.environ["HARNESS_SYNTH_INSTRUCTION"] = (
        "output ONLY the markdown starting with #  "
        "Write a thorough, well-structured research document that directly and "
        "completely addresses the task above. Use the research findings as your "
        "primary source. Organize with clear H2 sections, specific details, and "
        "concrete examples where available."
    )
    if score_only:
        os.environ["WIGGUM_MAX_ROUNDS"] = "1"
    try:
        agent.run(task, use_wiggum=True)
    except Exception as e:
        print(f"    [collect] agent.run raised: {e}")
        return "", 0.0, {}
    finally:
        os.environ.pop("HARNESS_SYNTH_TEMPERATURE", None)
        os.environ.pop("HARNESS_SYNTH_INSTRUCTION", None)
        if score_only:
            os.environ.pop("WIGGUM_MAX_ROUNDS", None)

    run_id   = os.environ.get("HARNESS_RUN_ID", "")
    run_data = _get_run(run_id)
    scores   = run_data.get("wiggum_scores") or []
    score    = float(scores[-1]) if scores else 0.0
    return run_id, score, run_data


# ---------------------------------------------------------------------------
# Per-task collection
# ---------------------------------------------------------------------------

def collect_task(rec: dict, n_rollouts: int, conn: sqlite3.Connection,
                 resume_only: bool, score_only: bool = False) -> list[dict]:
    prompt    = rec["prompt"]
    ph        = _prompt_hash(prompt)
    task_type = rec.get("task_type", "research")

    if resume_only and not _has_any_rollout(conn, ph):
        print(f"  [collect] skip (resume-only, no prior rollouts): {prompt[:60]}")
        return []

    print(f"\n{'─'*70}")
    print(f"[task] {prompt[:80]}")
    print(f"       hash={ph}  type={task_type}  rollouts={n_rollouts}")

    results = []
    for i in range(n_rollouts):
        cached = _checkpoint_get(conn, ph, i)
        if cached:
            run_data = _get_run(cached["run_id"])
            results.append({
                "idx":        i,
                "run_id":     cached["run_id"],
                "score":      cached["score"],
                "content":    run_data.get("final_content", ""),
                "trajectory": run_data.get("trajectory", []),
                "temp":       TEMPS[i % len(TEMPS)],
            })
            print(f"  rollout {i}  [cached]  score={cached['score']:.1f}")
            continue

        temp     = TEMPS[i % len(TEMPS)]
        out_path = ROLLOUTS_DIR / f"{ph}_{i}.md"
        print(f"  rollout {i}  temp={temp} ...", end="", flush=True)

        t0 = time.monotonic()
        run_id, score, run_data = run_rollout(prompt, temp, out_path, score_only=score_only)
        elapsed = round(time.monotonic() - t0, 1)

        _checkpoint_put(conn, ph, i, run_id, score, str(out_path))
        results.append({
            "idx":        i,
            "run_id":     run_id,
            "score":      score,
            "content":    run_data.get("final_content", ""),
            "trajectory": run_data.get("trajectory", []),
            "temp":       temp,
        })
        print(f"  score={score:.1f}  {elapsed}s  run={run_id}")
        time.sleep(0.5)

    return results


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def emit_dpo(prompt: str, task_type: str, results: list[dict],
             min_gap: float, f) -> bool:
    valid = [r for r in results if r.get("content")]
    if len(valid) < 2:
        return False
    valid.sort(key=lambda r: r["score"], reverse=True)
    chosen, rejected = valid[0], valid[-1]
    gap = chosen["score"] - rejected["score"]
    if gap < min_gap:
        print(f"  [dpo] skip — gap {gap:.1f} < {min_gap}")
        return False
    f.write(json.dumps({
        "prompt":         prompt,
        "chosen":         chosen["content"],
        "rejected":       rejected["content"],
        "chosen_score":   chosen["score"],
        "rejected_score": rejected["score"],
        "score_gap":      round(gap, 2),
        "task_type":      task_type,
        "prompt_hash":    _prompt_hash(prompt),
        "chosen_run":     chosen["run_id"],
        "rejected_run":   rejected["run_id"],
    }) + "\n")
    f.flush()
    print(f"  [dpo]  gap={gap:.1f}  chosen={chosen['score']:.1f}  rejected={rejected['score']:.1f}")
    return True


def _leverage(score: float, content: str, run_data: dict) -> float:
    lines       = len(content.splitlines()) if content else 1
    runtime_h   = (run_data.get("run_duration_s") or 1) / 3600
    return round(score * lines / max(runtime_h, 1e-4), 2)


def emit_grpo(prompt: str, task_type: str, results: list[dict], f) -> bool:
    completions = []
    for r in results:
        if not r.get("content"):
            continue
        run_data = _get_run(r["run_id"])
        dims     = (run_data.get("wiggum_dims") or [{}])[-1]
        lev      = _leverage(r["score"], r["content"], run_data)
        completions.append({
            "content":    r["content"],
            "reward":     r["score"],
            "leverage":   lev,
            "dims":       dims,
            "trajectory": r["trajectory"],
            "run_id":     r["run_id"],
            "temp":       r["temp"],
        })
    if not completions:
        return False
    rewards = [c["reward"] for c in completions]
    f.write(json.dumps({
        "prompt":       prompt,
        "completions":  completions,
        "task_type":    task_type,
        "prompt_hash":  _prompt_hash(prompt),
        "mean_reward":  round(sum(rewards) / len(rewards), 2),
        "max_reward":   max(rewards),
        "min_reward":   min(rewards),
        "n_rollouts":   len(completions),
    }) + "\n")
    f.flush()
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Collect RL training data from agent rollouts")
    ap.add_argument("--bank",        default=str(DEFAULT_BANK), help="Task bank JSONL")
    ap.add_argument("--rollouts",    type=int,   default=4,     help="Rollouts per task")
    ap.add_argument("--min-gap",     type=float, default=1.0,   help="Min score gap for DPO pairs")
    ap.add_argument("--limit",       type=int,   default=0,     help="Max tasks (0=all)")
    ap.add_argument("--task-type",   default="",                help="Filter to task_type")
    ap.add_argument("--resume-only", action="store_true",       help="Only continue tasks that have at least one rollout")
    ap.add_argument("--export-only", action="store_true",       help="Skip rollouts; re-export from checkpoint DB")
    ap.add_argument("--score-only",  action="store_true",       help="Single Wiggum eval pass, no revision (preserves score variance for DPO)")
    args = ap.parse_args()

    bank_path = Path(args.bank)
    if not bank_path.exists():
        print(f"[collect] bank not found: {bank_path}")
        sys.exit(1)

    tasks = []
    with open(bank_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if args.task_type and rec.get("task_type") != args.task_type:
                    continue
                tasks.append(rec)
            except json.JSONDecodeError:
                pass

    if args.limit:
        tasks = tasks[: args.limit]

    mode_tag = "score-only" if args.score_only else "full-revision"
    print(f"[collect] {len(tasks)} tasks  ×{args.rollouts} rollouts  min-gap={args.min_gap}  mode={mode_tag}")

    RL_DIR.mkdir(parents=True, exist_ok=True)
    ROLLOUTS_DIR.mkdir(parents=True, exist_ok=True)

    conn = _init_db(CHECKPOINT_DB)

    dpo_path  = RL_DIR / "dpo.jsonl"
    grpo_path = RL_DIR / "grpo.jsonl"

    n_dpo = n_grpo = 0

    with open(dpo_path, "a", encoding="utf-8") as dpo_f, \
         open(grpo_path, "a", encoding="utf-8") as grpo_f:

        for rec in tasks:
            if args.export_only:
                ph = _prompt_hash(rec["prompt"])
                results = []
                for i in range(args.rollouts):
                    cached = _checkpoint_get(conn, ph, i)
                    if cached:
                        run_data = _get_run(cached["run_id"])
                        results.append({
                            "idx":        i,
                            "run_id":     cached["run_id"],
                            "score":      cached["score"],
                            "content":    run_data.get("final_content", ""),
                            "trajectory": run_data.get("trajectory", []),
                            "temp":       TEMPS[i % len(TEMPS)],
                        })
            else:
                results = collect_task(rec, args.rollouts, conn, args.resume_only, score_only=args.score_only)

            if not results:
                continue

            task_type = rec.get("task_type", "research")
            if emit_dpo(rec["prompt"], task_type, results, args.min_gap, dpo_f):
                n_dpo += 1
            if emit_grpo(rec["prompt"], task_type, results, grpo_f):
                n_grpo += 1

    conn.close()

    print(f"\n{'═'*70}")
    print("[collect] done")
    print(f"  DPO pairs : {n_dpo}  → {dpo_path}")
    print(f"  GRPO recs : {n_grpo}  → {grpo_path}")


if __name__ == "__main__":
    main()

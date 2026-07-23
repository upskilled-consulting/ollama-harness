"""
scripts/rollout_local.py - the LOCAL half of the improvement loop.

No self-hosted GitHub Actions runner (which on a PUBLIC repo would let fork PRs run
code on this box, exposing .env secrets). Instead this runs hourly via Windows Task
Scheduler: pull the CI-mined corpus, roll a batch through the teacher, push the state.

Safe to run repeatedly:
  - single-instance lock (skips if a previous run is still going)
  - skips cleanly if the teacher (8087) is not served
  - git steps are non-fatal (a bad pull/push is logged, retried next hour)

    python scripts/rollout_local.py          # full run (Task Scheduler uses this)
    python scripts/rollout_local.py --check  # validate env only; no rollout, no push
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOCK = REPO / ".rollout.lock"
LOG = REPO / "data" / "rollout_local.log"
HEALTH = "http://localhost:8087/health"
ENDPOINTS = ('{"qwen3-coder-next":{"url":"http://localhost:8087/v1",'
             '"model_id":"qwen3-coder-next","backend":"llamacpp"}}')
BATCH = 30


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def teacher_up() -> bool:
    try:
        with urllib.request.urlopen(HEALTH, timeout=5) as r:
            return getattr(r, "status", 200) == 200
    except Exception:
        return False


def git(*a: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO), *a], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="validate env; no rollout/push")
    ap.add_argument("--limit", type=int, default=BATCH)
    args = ap.parse_args()

    if LOCK.exists() and time.time() - LOCK.stat().st_mtime < 3 * 3600:
        log("another rollout in progress (fresh lock); skipping")
        return
    if not teacher_up():
        log("teacher (8087) not served; skipping this run")
        return

    if args.check:
        pend = subprocess.run(
            [sys.executable, "-c",
             "import sqlite3;print(sqlite3.connect(r'%s').execute("
             "'SELECT COUNT(*) FROM commits WHERE rolled_out=0').fetchone()[0])"
             % (REPO / "data" / "commits.db")],
            capture_output=True, text=True).stdout.strip()
        log(f"[check] teacher up, lock free, pending commits={pend or 'n/a'}")
        return

    LOCK.write_text(str(os.getpid()))
    try:
        pull = git("pull", "--ff-only")
        if pull.returncode != 0:
            log(f"pull skipped/failed (continuing on local DB): {pull.stderr.strip()[:120]}")

        env = dict(os.environ, HARNESS_ENDPOINTS=ENDPOINTS)
        rc = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "rollout_from_sqlite.py"),
             "--db", "data/commits.db", "--table", "commits", "--limit", str(args.limit),
             "--out", "data/rl/corpus_winners.jsonl",
             "--", "--k", "3", "--temp", "0.8", "--min-f1", "0.3",
             "--workers", "1", "--holdout-frac", "0"],
            cwd=str(REPO), env=env).returncode
        if rc != 0:
            log(f"rollout exited {rc}; leaving rows pending")
            return

        git("add", "data/commits.db", "data/vulns.db", "data/rl/corpus_winners.jsonl")
        if git("diff", "--cached", "--quiet").returncode != 0:
            git("commit", "-m", f"rollout: {time.strftime('%FT%TZ', time.gmtime())} [skip ci]")
            push = git("push")
            log("pushed rollout state" if push.returncode == 0
                else f"push failed (retry next run): {push.stderr.strip()[:120]}")
        else:
            log("no new rollout state to commit")
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    main()

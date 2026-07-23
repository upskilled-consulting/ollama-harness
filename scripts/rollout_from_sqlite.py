"""
scripts/rollout_from_sqlite.py - the GPU half of the loop. Drains not-yet-rolled-out
rows from a mined SQLite corpus, runs teacher rollouts via the existing harvest engine,
and marks them done. Runs on the self-hosted (RTX 5000) GitHub Actions runner, where
the teacher endpoint is served.

    HARNESS_ENDPOINTS='{"qwen3-coder-next":{...:8087...}}' \
    python scripts/rollout_from_sqlite.py --db data/commits.db --table commits \
        --limit 40 --out data/rl/ts.multiturn.jsonl -- --k 3 --temp 0.8 --min-f1 0.3

Everything after `--` is passed straight to harvest_multirepo.py.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--table", choices=["commits", "vulns"], default="commits")
    ap.add_argument("--limit", type=int, default=40, help="rows to roll out this run")
    ap.add_argument("--out", required=True, help="winners JSONL (appended by the harvest)")
    ap.add_argument("--work-dir", default=os.path.join(tempfile.gettempdir(), "rollout_repos"))
    ap.add_argument("--model", default="qwen3-coder-next")
    ap.add_argument("harvest_args", nargs=argparse.REMAINDER,
                    help="args after -- go to harvest_multirepo.py")
    args = ap.parse_args()

    sha_col = "fix_sha" if args.table == "vulns" else "sha"
    q_col = "cwe_desc" if args.table == "vulns" else "question"

    db = sqlite3.connect(args.db)
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if args.table not in tables:
        print(f"[rollout] table '{args.table}' not present yet (no corpus mined); nothing to do")
        return
    rows = db.execute(
        f"SELECT {sha_col}, parent, repo, {q_col}, gold_files, gold_ranges "
        f"FROM {args.table} WHERE rolled_out=0 LIMIT ?", (args.limit,)).fetchall()
    if not rows:
        print("[rollout] nothing pending", flush=True)
        return
    print(f"[rollout] {len(rows)} pending rows from {args.table}", flush=True)

    # export to the questions JSONL shape harvest_multirepo consumes
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    shas = []
    for sha, parent, repo, question, gfiles, granges in rows:
        shas.append(sha)
        # for vulns the CWE description IS the exploration task
        q = (f"In this repository, find the code affected by this vulnerability: {question}"
             if args.table == "vulns" else question)
        tmp.write(json.dumps({"sha": sha, "parent": parent, "repo": repo, "question": q,
                              "gold_files": json.loads(gfiles),
                              "gold_ranges": json.loads(granges)}) + "\n")
    tmp.close()

    extra = args.harvest_args[1:] if args.harvest_args[:1] == ["--"] else args.harvest_args
    cmd = [sys.executable, str(HERE / "harvest_multirepo.py"),
           "--questions", tmp.name, "--out", args.out, "--model", args.model,
           "--work-dir", args.work_dir, *extra]
    print("[rollout] ->", " ".join(cmd), flush=True)
    rc = subprocess.run(cmd).returncode
    os.unlink(tmp.name)

    if rc == 0:
        db.executemany(f"UPDATE {args.table} SET rolled_out=1 WHERE {sha_col}=?",
                       [(s,) for s in shas])
        db.commit()
        print(f"[rollout] marked {len(shas)} rows rolled_out=1", flush=True)
    else:
        print(f"[rollout] harvest exited {rc}; leaving rows pending for retry", flush=True)
    db.close()


if __name__ == "__main__":
    main()

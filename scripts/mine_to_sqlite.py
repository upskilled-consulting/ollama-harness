"""
scripts/mine_to_sqlite.py - hourly feeder: mine training commits from target repos
into a SQLite corpus. Idempotent (sha PRIMARY KEY + INSERT OR IGNORE) and stamped
with commit_date + mined_at so decontamination-by-recency is provable per model.
GPU-free -- reuses mine_explore_eval's filters; runs on a GitHub Actions runner.

    python scripts/mine_to_sqlite.py --db data/commits.db --repos data/mine_repos.txt \
        --since "14 days ago" --workdir /tmp/mine
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import mine_explore_eval as M  # noqa: E402

SCHEMA = """
CREATE TABLE IF NOT EXISTS commits (
    sha         TEXT PRIMARY KEY,
    repo        TEXT NOT NULL,
    parent      TEXT NOT NULL,
    subject     TEXT,
    question    TEXT,
    gold_files  TEXT,
    gold_ranges TEXT,
    commit_date TEXT,
    mined_at    TEXT,
    rolled_out  INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_rolled ON commits(rolled_out);
CREATE INDEX IF NOT EXISTS idx_repo   ON commits(repo);
"""


def sh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


# git says this, on stderr and with a non-zero exit, when --shallow-since selects NO commits.
# It is not a failure: it is a repository with nothing in the window. Matched as a substring
# because the trailing number is a transport code that varies.
_NO_COMMITS_IN_WINDOW = "error processing shallow info"


def clone_or_update(url: str, dest: str, since: str) -> tuple[bool, str]:
    """Shallow + blobless clone of just the recent window -- cheap enough to run hourly.

    RETURNS GIT'S STDERR, because the caller cannot otherwise tell two very different things
    apart. A repo with no commits in the window and a repo that has been renamed, deleted or
    gone auth-gated both exited non-zero here, and both printed one generic `clone/fetch
    failed`. The first is noise -- Textualize/rich has not been touched since June and there is
    nothing to mine. The second is a hole in the corpus that nobody is being told about.

    Five repos printed that line every run for at least two nights and the distinction was not
    recoverable from the log, because this function dropped `r.stderr` on the floor.
    """
    if os.path.isdir(os.path.join(dest, ".git")):
        r = sh("git", "-C", dest, "fetch", "--quiet", f"--shallow-since={since}", "origin")
    else:
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        r = sh("git", "clone", "--quiet", "--filter=blob:none",
               f"--shallow-since={since}", url, dest)
    return r.returncode == 0, (r.stderr or "").strip()


def repo_url(name: str) -> str:
    if name.startswith(("http://", "https://", "git@")):
        return name
    return f"https://github.com/{name}.git"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/commits.db")
    ap.add_argument("--repos", default="data/mine_repos.txt")
    ap.add_argument("--since", default="14 days ago")
    ap.add_argument("--limit", type=int, default=300, help="max commits scanned per repo")
    ap.add_argument("--max-files", type=int, default=3)
    ap.add_argument("--workdir", default=os.path.join(tempfile.gettempdir(), "mine_sqlite"))
    args = ap.parse_args()

    # strip INLINE comments too (`owner/repo  # note`), not just full-line comments --
    # otherwise the note becomes part of the repo name and every clone fails.
    repos = [r for ln in open(args.repos, encoding="utf-8")
             if (r := ln.split("#", 1)[0].strip())]
    if not repos:
        raise SystemExit(f"no repos in {args.repos}")

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(args.db)
    db.executescript(SCHEMA)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    total_new = 0
    for name in repos:
        owner_name = name.replace("/", "_").replace(".git", "")
        dest = os.path.join(args.workdir, owner_name)
        ok, err = clone_or_update(repo_url(name), dest, args.since)
        if not ok:
            # QUIET IS NOT BROKEN. Distinguish them in the log so a real corpus hole -- a
            # renamed or deleted repo -- is not buried under repos that simply have not
            # committed lately, and so the daily run stops reading as five recurring errors.
            if _NO_COMMITS_IN_WINDOW in err:
                print(f"[quiet] {name}: no commits since {args.since}", flush=True)
            else:
                print(f"[skip] {name}: clone/fetch failed: "
                      f"{err.splitlines()[-1] if err else 'no stderr from git'}", flush=True)
            continue

        M.GIT_CWD = dest                                     # target this clone
        rows = M.mine(limit=args.limit, max_files=args.max_files, code_only=True,
                      relaxed=True, since=args.since)         # relaxed gate for public repos

        new = 0
        for r in rows:
            cdate = M.git("show", "-s", "--format=%cI", r["sha"]).strip()
            cur = db.execute(
                "INSERT OR IGNORE INTO commits "
                "(sha, repo, parent, subject, question, gold_files, gold_ranges, "
                " commit_date, mined_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (r["sha"], name, r["parent"], r["subject"], r["question"],
                 json.dumps(r["gold_files"]), json.dumps(r["gold_ranges"]), cdate, now))
            new += cur.rowcount
        db.commit()
        total_new += new
        print(f"[{name}] scanned {len(rows)} minable, +{new} new", flush=True)

    n = db.execute("SELECT COUNT(*) FROM commits").fetchone()[0]
    pend = db.execute("SELECT COUNT(*) FROM commits WHERE rolled_out=0").fetchone()[0]
    print(f"\n[db] +{total_new} new this run | {n} total | {pend} awaiting rollout", flush=True)
    db.close()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    main()

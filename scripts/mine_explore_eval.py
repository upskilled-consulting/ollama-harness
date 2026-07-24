"""
scripts/mine_explore_eval.py - build (and run) an explorer eval set from git history.

Turns the harness repo's OWN commits into (question -> gold file:line) pairs for
grading the FastContext explorer. For each localized, well-described commit:
  - the commit message becomes an exploration question;
  - the OLD line ranges the commit modified (in the PARENT state) become the gold
    answer locations;
  - the explorer is run against the repo checked out at the PARENT sha (a git
    worktree), and its citation trail is graded by file / line F1 against gold.

Data ceiling is small (~76 usable commits) -> this is an EVAL yardstick, NOT
training data. Use it to measure prompt/loop changes to the explorer, and (later)
to check whether a SWE-bench-trained explorer transfers to this repo.

    python scripts/mine_explore_eval.py                 # build the eval set (no GPU)
    python scripts/mine_explore_eval.py --run --limit 10   # grade explorer (GPU)
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

CONV     = re.compile(r"^(fix|feat|refactor|perf|test|build|style)(\([^)]*\))?:\s*(.+)", re.I)
CODE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx"}
HUNK     = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")


def _a(s: str) -> str:                       # cp1252-safe console
    return (s or "").encode("ascii", "replace").decode()


# Set to a repo path to mine a repo OTHER than the cwd (e.g. a cloned public repo
# for RL-corpus harvesting). None -> operate on the current working directory.
GIT_CWD: str | None = None


def git(*args: str) -> str:
    base = ["git"] + (["-C", GIT_CWD] if GIT_CWD else [])
    return subprocess.run([*base, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


# ---------------------------------------------------------------------------
# mine
# ---------------------------------------------------------------------------

def parse_commit(sha: str) -> tuple[str, str | None, dict]:
    subject = git("show", "-s", "--format=%s", sha).strip()
    parents = git("show", "-s", "--format=%P", sha).strip().split()
    parent  = parents[0] if parents else None
    diff    = git("show", "--unified=0", "--format=", "-M", sha)
    files: dict[str, list] = {}
    cur = None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            cur = line[6:]
            files.setdefault(cur, [])
        elif line.startswith("@@") and cur is not None:
            m = HUNK.match(line)
            if m:
                a = int(m.group(1))
                b = int(m.group(2) or "1")
                files[cur].append((a, a) if b == 0 else (a, a + b - 1))
    return subject, parent, files


def _exists_at(rev: str, path: str) -> bool:
    # git cat-file -e <rev>:<path> exits 0 iff the blob exists at that revision.
    base = ["git"] + (["-C", GIT_CWD] if GIT_CWD else [])
    return subprocess.run([*base, "cat-file", "-e", f"{rev}:{path}"],
                          capture_output=True).returncode == 0


# Real-world repos rarely use conventional prefixes -- they squash PR titles ("Fix
# connection pool leak"). Those ARE good localization questions. So the mining gate
# for public repos is not "conventional" but "descriptive, not maintenance noise".
_NOISE = re.compile(
    r"^(merge\b|revert\b|bump\b|release\b|v?\d+\.\d+|version\b|chore\b|ci\b|"
    r"docs?\b|typo\b|wip\b|fixup\b|format\b|lint\b|update changelog|"
    r"prepare release|back to dev|\[pre-commit|rename\b|cleanup\b|style\b)", re.I)


def is_minable(subject: str) -> bool:
    """A commit subject descriptive enough to become a 'where is the code that does
    X' question, and not maintenance noise. Used as the relaxed gate for public repos."""
    s = (subject or "").strip()
    if not s or _NOISE.match(s):
        return False
    return len(s.split()) >= 3 and len(s) >= 15


def question_from(subject: str) -> str:
    m = CONV.match(subject)
    core = (m.group(3) if m else subject).strip()
    return f"In this repository, where is the code responsible for: {core}?"


def mine(limit: int, max_files: int, code_only: bool,
         relaxed: bool = False, since: str | None = None) -> list[dict]:
    # relaxed=True (public repos): accept any descriptive subject. False (our repo):
    # require a conventional-commit prefix, which our own history uses.
    #
    # `since` (YYYY-MM-DD) is the decontamination control. A public repo's code may sit
    # in the model's pretraining set, so "found the file" can be recall rather than
    # exploration. Commits authored AFTER the model's training cutoff cannot be
    # memorized, which makes recency -- not obscurity -- the reliable guarantee.
    gate = is_minable if relaxed else (lambda s: bool(CONV.match(s)))
    log_args = ["log", "--no-merges", "--pretty=format:%H", f"-{limit}"]
    if since:
        log_args.append(f"--since={since}")
    rows = []
    for sha in git(*log_args).split():
        subject, parent, files = parse_commit(sha)
        if not parent or not gate(subject):
            continue
        cfiles = {f: r for f, r in files.items()
                  if (not code_only) or Path(f).suffix in CODE_EXT}
        # Keep only files that EXIST at the parent state the explorer runs against.
        # A commit that adds a new file gives it gold ranges the explorer can never
        # cite (the file isn't there yet) -> an unfair, methodology-driven 0/0.
        cfiles = {f: r for f, r in cfiles.items() if _exists_at(parent, f)}
        if not (1 <= len(cfiles) <= max_files):
            continue
        rows.append({
            "sha":         sha,
            "parent":      parent,
            "subject":     subject,
            "question":    question_from(subject),
            "gold_files":  sorted(cfiles.keys()),
            "gold_ranges": {f: r for f, r in cfiles.items()},
        })
    return rows


# ---------------------------------------------------------------------------
# grade
# ---------------------------------------------------------------------------

def _parse_cite(c: str) -> tuple[str, tuple[int, int] | None]:
    c = c.strip()
    if ":" in c:
        path, _, rng = c.partition(":")
        try:
            if "-" in rng:
                s, _, e = rng.partition("-")
                return path, (int(s), int(e or s))
            return path, (int(rng), int(rng))
        except ValueError:
            return path, None
    return c, None


# A path with an optional line or line-range: "src/a.ts:10-42", "src/a.ts:10", "src/a.ts".
# Anchored on a real file extension so prose words and bare numbers are not mistaken for
# citations.
# The extension must be 2-5 chars: a 1-char tail makes "e.g." and "i.e." parse as
# citations, which silently tanks precision for any model that writes normal prose.
_CITE_RE = re.compile(
    r"(?<![\w/.-])((?:[\w.-]+/)*[\w.-]+\.[A-Za-z][A-Za-z0-9]{1,4})"
    r"(?::(\d+)(?:\s*[-–]\s*(\d+))?)?")


def extract_citations(text: str) -> list[str]:
    """Pull path[:range] citations out of the explorer's free-text final answer.

    grade_trail scores the ACTION trail -- where the model looked. This scores what it
    SAID, which is what the calling agent actually consumes. A model can read the gold
    file and then cite something else entirely (the 0.6B cited .netrc fixtures while
    fabricating grep output), and that failure is invisible to a trail-only metric.
    """
    out, seen = [], set()
    for m in _CITE_RE.finditer(text or ""):
        path, s, e = m.group(1), m.group(2), m.group(3)
        cite = path if not s else (f"{path}:{s}-{e}" if e else f"{path}:{s}")
        if cite not in seen:
            seen.add(cite)
            out.append(cite)
    return out


def grade_answer(text: str, gold_files: list[str], gold_ranges: dict) -> dict:
    """file_f1 / line_recall over the model's STATED citations."""
    return grade_trail(extract_citations(text), gold_files, gold_ranges)


def grade_trail(trail: list[str], gold_files: list[str], gold_ranges: dict) -> dict:
    cited_files: set[str] = set()
    cited_ranges: dict[str, list] = {}
    for c in trail:
        p, rng = _parse_cite(c)
        if not p:
            continue
        cited_files.add(p)
        if rng:
            cited_ranges.setdefault(p, []).append(rng)

    gold_set = set(gold_files)
    tp   = len(cited_files & gold_set)
    prec = tp / len(cited_files) if cited_files else 0.0
    rec  = tp / len(gold_set) if gold_set else 0.0
    file_f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0

    hit = tot = 0                                  # line-level recall on matched files
    for f, ranges in gold_ranges.items():
        for gs, ge in ranges:
            tot += 1
            if any(cs <= ge and ce >= gs for cs, ce in cited_ranges.get(f, [])):
                hit += 1
    line_recall = hit / tot if tot else 0.0

    return {"file_f1": round(file_f1, 3), "line_recall": round(line_recall, 3),
            "found_files": sorted(cited_files & gold_set)}


# ---------------------------------------------------------------------------
# run (GPU): explore each parent-state repo, grade the trail
# ---------------------------------------------------------------------------

def run_eval(rows: list[dict], model: str) -> list[dict]:
    import os

    from harness.explorer import explore_codebase
    results = []
    for i, r in enumerate(rows, 1):
        base = tempfile.mkdtemp(prefix="fc_wt_")
        wt = os.path.join(base, "tree")   # must NOT pre-exist: git worktree add refuses existing dirs
        try:
            add = subprocess.run(["git", "worktree", "add", "--detach", wt, r["parent"]],
                                 capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
            if add.returncode != 0 or not os.path.isdir(wt):
                print(f"  [{i}/{len(rows)}] WORKTREE FAILED: {add.stderr.strip()[:140]}", flush=True)
                results.append({"file_f1": 0.0, "line_recall": 0.0, "found_files": [],
                                "sha": r["sha"], "error": "worktree_add"})
                continue
            trail_str = explore_codebase(r["question"], wt, model=model,
                                         verbose=False, temperature=0.0)
            trail = [ln.strip() for ln in trail_str.splitlines()[1:] if ln.startswith("  ")]
            g = grade_trail(trail, r["gold_files"], r["gold_ranges"])
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", wt],
                           capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
            shutil.rmtree(base, ignore_errors=True)
        g.update(sha=r["sha"], question=r["question"], gold_files=r["gold_files"])
        results.append(g)
        print(f"  [{i}/{len(rows)}] file_f1={g['file_f1']} line_recall={g['line_recall']} "
              f"gold={r['gold_files']} found={g['found_files']}", flush=True)
    return results


# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3000)
    ap.add_argument("--max-files", type=int, default=3)
    ap.add_argument("--all-files", action="store_true", help="include non-code files")
    ap.add_argument("--run", action="store_true", help="grade the explorer (needs GPU + fastcontext)")
    ap.add_argument("--n", type=int, default=8, help="examples to grade in --run mode")
    ap.add_argument("--model", default="fastcontext-rl")
    ap.add_argument("--out", default="data/eval/explore_eval.jsonl")
    args = ap.parse_args()

    rows = mine(args.limit, args.max_files, code_only=not args.all_files)
    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    print(f"[mine] {len(rows)} eval examples -> {outp}")
    print(f"[mine] gold-file counts: {dict(collections.Counter(len(r['gold_files']) for r in rows))}")
    for r in rows[:6]:
        print(_a(f"  {r['sha'][:8]} {r['gold_files']} :: {r['question'][:66]}"))

    if args.run:
        run_rows = rows[:args.n]
        print(f"\n[run] grading explorer ({args.model}) on {len(run_rows)} examples...")
        results = run_eval(run_rows, args.model)
        import statistics as st
        print(f"\n[run] mean file_f1={st.mean(r['file_f1'] for r in results):.3f}  "
              f"mean line_recall={st.mean(r['line_recall'] for r in results):.3f}")
        Path("data/eval/explore_eval_graded.json").write_text(
            json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

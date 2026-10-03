"""
scripts/mine_vulns_to_sqlite.py - Antares/VLoc-style vulnerability-localization corpus.

Sources the GitHub Advisory Database (GHSA records in OSV JSON -- they carry CWE ids
AND fix-commit references), then for each fix commit pulls its changed files + line
ranges and its parent (the pre-fix, vulnerable snapshot) via the GitHub API. The task
is a CWE + generic category description; the ground truth is the fix-PR's code files
(tests/docs/config excluded). Mirrors VLoc Bench.

Idempotent (fix_sha PRIMARY KEY). GPU-free; runs on a GitHub Actions runner with
GITHUB_TOKEN for rate limits.

    git clone --depth 1 https://github.com/github/advisory-database /tmp/advdb
    python scripts/mine_vulns_to_sqlite.py --adv-dir /tmp/advdb/advisories/github-reviewed \
        --db data/vulns.db --limit 200
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mine_explore_eval import HUNK, is_gold_code_file  # noqa: E402  (reuse diff parser)

# Generic CWE category descriptions (Antares-style: no advisory text, just the class).
# Covers the most common web/library CWEs; unknown ids fall back to the bare id + name.
CWE_DESC = {
    "CWE-79":  "Cross-site Scripting (XSS): the software does not neutralize user-controllable input before it is placed in output used as a web page served to other users.",
    "CWE-89":  "SQL Injection: the software constructs a SQL command using externally-influenced input without neutralizing special elements that could modify the intended command.",
    "CWE-78":  "OS Command Injection: the software constructs an OS command using externally-influenced input without neutralizing special elements that could modify the intended command.",
    "CWE-22":  "Path Traversal: the software uses external input to construct a pathname without neutralizing sequences such as '..' that resolve outside a restricted directory.",
    "CWE-352": "Cross-Site Request Forgery (CSRF): the web application does not verify that a well-formed, valid, consistent request was intentionally provided by the user.",
    "CWE-434": "Unrestricted Upload of File with Dangerous Type: the software allows the attacker to upload or transfer files of dangerous types that can be automatically processed.",
    "CWE-94":  "Code Injection: the software constructs code using externally-influenced input without neutralizing special elements that could modify the intended code.",
    "CWE-502": "Deserialization of Untrusted Data: the application deserializes untrusted data without sufficiently verifying that the resulting data will be valid.",
    "CWE-918": "Server-Side Request Forgery (SSRF): the web server receives a URL from an upstream component and retrieves its contents without validating the destination.",
    "CWE-611": "XML External Entity (XXE): the software processes an XML document that can contain entities resolving to external, unintended resources.",
    "CWE-77":  "Command Injection: the software constructs a command using externally-influenced input without neutralizing special elements that could modify the intended command.",
    "CWE-400": "Uncontrolled Resource Consumption: the software does not properly control the allocation and maintenance of a limited resource, enabling denial of service.",
    "CWE-200": "Exposure of Sensitive Information: the software exposes sensitive information to an actor not explicitly authorized to have access to it.",
    "CWE-287": "Improper Authentication: the software does not prove or insufficiently proves that a claimed identity is correct.",
    "CWE-863": "Incorrect Authorization: the software performs an authorization check but does not correctly perform it, allowing unintended access.",
    "CWE-862": "Missing Authorization: the software does not perform an authorization check when an actor attempts to access a resource or perform an action.",
    "CWE-1321": "Prototype Pollution: modification of the prototype of a base object, allowing an attacker to add or modify properties that exist on all objects.",
    "CWE-20":  "Improper Input Validation: the product does not validate or incorrectly validates input that affects the control flow or data flow of a program.",
    "CWE-601": "Open Redirect: a web application accepts a user-controlled input specifying a link to an external site and uses it in a redirect.",
    "CWE-916": "Use of Password Hash With Insufficient Computational Effort: the software uses a weak hashing scheme for passwords, easing brute-force attacks.",
    "CWE-327": "Use of a Broken or Risky Cryptographic Algorithm: the use of a broken or risky cryptographic algorithm risks exposure of sensitive information.",
    "CWE-843": "Type Confusion: the program allocates or initializes a resource using one type but accesses it using an incompatible type.",
    "CWE-732": "Incorrect Permission Assignment for Critical Resource: the software assigns permissions to a security-critical resource that allow unintended access.",
    "CWE-798": "Use of Hard-coded Credentials: the software contains hard-coded credentials for its own inbound authentication or outbound communication.",
    "CWE-116": "Improper Encoding or Escaping of Output: the software does not correctly encode or escape output intended for a downstream component, altering how it is parsed.",
    "CWE-770": "Allocation of Resources Without Limits or Throttling: the software allocates a reusable resource without limits, enabling resource exhaustion.",
    "CWE-789": "Memory Allocation with Excessive Size Value: the software allocates memory based on an untrusted size value without validating that it is within expected limits.",
    "CWE-524": "Use of Cache Containing Sensitive Information: the code caches sensitive information that may be read by an actor not authorized to access it.",
    "CWE-125": "Out-of-bounds Read: the software reads data past the end, or before the beginning, of the intended buffer.",
    "CWE-190": "Integer Overflow or Wraparound: a calculation can produce a value that wraps around, leading to incorrect resource sizing or logic.",
    "CWE-476": "NULL Pointer Dereference: the software dereferences a pointer it expects to be valid but is NULL, causing a crash or exit.",
    "CWE-74":  "Injection: the software constructs a command, query, or output using externally-influenced input without neutralizing special elements.",
    "CWE-113": "HTTP Response Splitting: the software includes unvalidated data in an HTTP header, allowing injection of additional headers or responses.",
    "CWE-1333": "Inefficient Regular Expression Complexity (ReDoS): a regex can be forced into worst-case behavior, causing denial of service on crafted input.",
    "CWE-295": "Improper Certificate Validation: the software does not validate, or incorrectly validates, a certificate, enabling spoofing or interception.",
    "CWE-209": "Generation of Error Message Containing Sensitive Information: an error message reveals details that help an attacker.",
    "CWE-668": "Exposure of Resource to Wrong Sphere: the software exposes a resource to a control sphere not intended to have access to it.",
}

# Test-file conventions differ by language and this was written for JS/Python only:
# Go's `bits_test.go` and Java's `FooTest.java` / `src/test/java/` sailed through and
# landed in gold. Caught by an end-to-end run on a real Go advisory, not by inspection.
_TEST_RE = re.compile(r"(^|/)(tests?|__tests__|spec|specs|e2e|fixtures?|examples?|docs?|"
                      r"benchmarks?|testdata)(/|$)|\.(test|spec)\.|(^|/)conftest\.py$|"
                      r"_test\.(go|py|rs)$|(^|/)test_[^/]+\.py$|"
                      r"(Test|Tests|IT|TestCase)\.(java|kt|scala)$|"
                      r"(^|/)src/test/", re.I)
_COMMIT_URL = re.compile(r"github\.com/([^/]+/[^/]+)/commit/([0-9a-f]{7,40})", re.I)

SCHEMA = """
CREATE TABLE IF NOT EXISTS vulns (
    fix_sha     TEXT PRIMARY KEY,
    repo        TEXT NOT NULL,
    parent      TEXT NOT NULL,
    ghsa        TEXT,
    cwe         TEXT,
    cwe_desc    TEXT,
    gold_files  TEXT,
    gold_ranges TEXT,
    commit_date TEXT,
    mined_at    TEXT,
    rolled_out  INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_v_rolled ON vulns(rolled_out);
CREATE INDEX IF NOT EXISTS idx_v_cwe    ON vulns(cwe);

-- Advisories we resolved and then REJECTED. Without this the miner has no memory of a failed
-- attempt: `seen` holds only rows that made it into vulns, so an advisory whose fix commit is
-- too wide (or has no parent, or 404s) is re-fetched on every single run, forever, and it does
-- it at the HEAD of a stable rglob order. That is how a daily job burned its entire --limit
-- budget re-confirming the same rejections and reported `resolved 300, +0 new` for five days
-- while 680 advisories sat pending behind it. A rejection is a result and has to be durable.
CREATE TABLE IF NOT EXISTS mine_attempts (
    fix_sha   TEXT PRIMARY KEY,
    ghsa      TEXT,
    repo      TEXT,
    reason    TEXT NOT NULL,
    n_files   INTEGER,
    tried_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_a_reason ON mine_attempts(reason);

-- GOLD_FILTER_VERSION backfill bookkeeping (see backfill()). A row/advisory is listed here once it
-- has been re-checked under the current filter, so the hourly backfill is resumable and idles
-- when done. outcome: regold: unchanged|added|unreachable ; retry: mined|rejected:<why>|...
CREATE TABLE IF NOT EXISTS gold_backfill (
    kind      TEXT NOT NULL,          -- 'regold' (existing vulns row) | 'retry' (no_code_files rejection)
    fix_sha   TEXT NOT NULL,
    version   INTEGER NOT NULL,
    outcome   TEXT,
    done_at   TEXT,
    PRIMARY KEY (kind, fix_sha, version)
);
"""

# Bump when the set of files gold_from_commit keeps changes. Rows mined (and advisories rejected)
# under an older filter are then re-checked by backfill(). v2 = 2026-10-03 CODE_EXT widening.
GOLD_FILTER_VERSION = 2


def gh_get(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "fc-vuln-miner"})
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 403 and "rate limit" in (e.headers.get("x-ratelimit-remaining", "") or "") + str(e):
                wait = 2 ** attempt * 5
                print(f"  [rate limited] sleeping {wait}s", flush=True)
                time.sleep(wait)
                continue
            return None
        except Exception:
            return None
    return None


def _holdout(require: bool = False) -> tuple[set, set]:
    """VLoc Bench advisories/repos we must never mine -- otherwise we train on the test set.
    Repo-level too: a different advisory in the same repo still leaks structure and style.

    `require` turns the warning into an abort. The file was untracked for months, so every CI
    run checked out a tree without it, printed one line into a log nobody reads, and mined
    unfiltered -- the exact contamination the guard exists to prevent, announced as a warning
    and therefore invisible. CI passes --require-holdout: a corpus job with no guard should go
    red, not quietly produce rows that have to be purged later.
    """
    p = Path(__file__).resolve().parent.parent / "data" / "vloc_holdout.json"
    if not p.exists():
        if require:
            raise SystemExit(f"[vulns] FATAL: no {p} and --require-holdout was given. "
                             "Mining now would import VLoc test-set rows.")
        print("[vulns] WARNING: no data/vloc_holdout.json -- mining WITHOUT test-set exclusion")
        return set(), set()
    d = json.loads(p.read_text(encoding="utf-8"))
    return set(d.get("ghsa") or []), {r.lower() for r in (d.get("repos") or [])}


def advisories(adv_dir: str, require_holdout: bool = False):
    """Yield (ghsa_id, cwe_id, repo, sha) for GHSA records with a CWE and a fix commit."""
    hold_g, hold_r = _holdout(require_holdout)
    skipped = 0
    for path in Path(adv_dir).rglob("GHSA-*.json"):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        cwes = (d.get("database_specific") or {}).get("cwe_ids") or []
        if not cwes:
            continue
        for ref in d.get("references") or []:
            m = _COMMIT_URL.search(ref.get("url", ""))
            if m:
                if d.get("id") in hold_g or m.group(1).lower() in hold_r:
                    skipped += 1
                    break                                    # VLoc holdout -- never mine
                yield d.get("id"), cwes[0], m.group(1), m.group(2)
                break                                        # one fix commit per advisory
    if skipped:
        print(f"[vulns] skipped {skipped} advisories in the VLoc holdout", flush=True)


def gold_from_commit(commit: dict) -> tuple[dict, str, str]:
    """Code files changed by the fix (tests/docs/config excluded) -> {path: [(a,b)...]}."""
    files: dict[str, list] = {}
    for f in commit.get("files") or []:
        fn = f.get("filename", "")
        if not is_gold_code_file(fn) or _TEST_RE.search(fn):
            continue
        ranges = []
        for line in (f.get("patch") or "").splitlines():
            m = HUNK.match(line)
            if m:
                a = int(m.group(1)); b = int(m.group(2) or "1")
                ranges.append((a, a) if b == 0 else (a, a + b - 1))
        files[fn] = ranges
    parent = (commit.get("parents") or [{}])[0].get("sha", "")
    date = (((commit.get("commit") or {}).get("committer") or {}).get("date")) or ""
    return files, parent, date


def api_calls_left() -> int:
    """Remaining core-API quota for this token (the /rate_limit call itself is free)."""
    d = gh_get("https://api.github.com/rate_limit") or {}
    return int(((d.get("resources") or {}).get("core") or {}).get("remaining") or 0)


def insert_vuln(db, full_sha, repo, parent, ghsa, cwe, files, date, now) -> int:
    cur = db.execute(
        "INSERT OR IGNORE INTO vulns (fix_sha, repo, parent, ghsa, cwe, cwe_desc, "
        "gold_files, gold_ranges, commit_date, mined_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (full_sha, repo, parent, ghsa, cwe,
         CWE_DESC.get(cwe, f"{cwe}: (generic category description unavailable)"),
         json.dumps(sorted(files)), json.dumps(files), date, now))
    return cur.rowcount


def backfill(db, adv_dir: str, regold_budget: int, retry_budget: int, max_files: int,
             require_holdout: bool, now: str) -> None:
    """Re-check what was mined under an older gold filter (GOLD_FILTER_VERSION).

    WHY. Until v2 the filter kept py/js/ts only. Rows already stored kept only their incidental
    files as gold (TYPO3 fd0be9fe: one ajax-request.js for an all-PHP fix), and 9,298 advisories
    were rejected as no_code_files because every fix file was Go/Java/PHP/C/... The normal loop
    never revisits either: a stored row is `seen`, a rejection is `tried`.

    regold: refetch each stored row's fix through the same API + gold_from_commit, ADD the files
            the old filter dropped. Existing entries are never rewritten -- they came from the same
            API and filter, so they are already right.
    retry:  re-resolve no_code_files rejections; mine the ones that now have gold (respecting
            --max-files), otherwise record the new verdict.

    Budgeted against the live API quota and resumable through gold_backfill, so it can run every
    hour until both backlogs are empty and then costs nothing.
    """
    V = GOLD_FILTER_VERSION
    left = api_calls_left()
    regold_budget = max(0, min(regold_budget, left - 100))
    stats: dict[str, int] = {}

    def mark(kind, sha, outcome):
        db.execute("INSERT OR REPLACE INTO gold_backfill VALUES (?,?,?,?,?)", (kind, sha, V, outcome, now))
        stats[f"{kind}:{outcome.split(':')[0]}"] = stats.get(f"{kind}:{outcome.split(':')[0]}", 0) + 1

    rows = db.execute(
        "SELECT fix_sha, repo, gold_files, gold_ranges FROM vulns WHERE fix_sha NOT IN "
        "(SELECT fix_sha FROM gold_backfill WHERE kind='regold' AND version=?) LIMIT ?",
        (V, regold_budget)).fetchall()
    for fix, repo, gf, gr in rows:
        commit = gh_get(f"https://api.github.com/repos/{repo}/commits/{fix}")
        if not commit:
            if api_calls_left() < 50:
                break                                      # out of quota: resume next run, unmarked
            mark("regold", fix, "unreachable"); continue
        new, _, _ = gold_from_commit(commit)
        old_r, old_f = json.loads(gr or "{}"), json.loads(gf or "[]")
        add = {p: r for p, r in new.items() if p not in old_r and p not in old_f}
        if add:
            db.execute("UPDATE vulns SET gold_files=?, gold_ranges=? WHERE fix_sha=?",
                       (json.dumps(sorted(set(old_f) | set(add))), json.dumps({**old_r, **add}), fix))
            mark("regold", fix, f"added:{len(add)}")
        else:
            mark("regold", fix, "unchanged")
        db.commit()

    retry_budget = max(0, min(retry_budget, api_calls_left() - 100))
    if retry_budget:
        by7: dict[str, list] = {}
        for (s,) in db.execute(
                "SELECT fix_sha FROM mine_attempts WHERE reason='no_code_files' AND fix_sha NOT IN "
                "(SELECT fix_sha FROM gold_backfill WHERE kind='retry' AND version=?)", (V,)):
            by7.setdefault(s[:7].lower(), []).append(s)
        done = 0
        for ghsa, cwe, repo, sha in advisories(adv_dir, require_holdout):
            if done >= retry_budget:
                break
            cands = by7.get(sha[:7].lower(), [])
            hit = next((s for s in cands if s.startswith(sha) or sha.startswith(s)), None)
            if hit is None:
                continue
            cands.remove(hit)
            commit = gh_get(f"https://api.github.com/repos/{repo}/commits/{hit}")
            done += 1
            if not commit:
                if api_calls_left() < 50:
                    break
                mark("retry", hit, "unreachable"); continue
            files, parent, date = gold_from_commit(commit)
            why = ("no_parent" if not parent else "no_code_files" if not files
                   else "too_many_files" if len(files) > max_files else None)
            if why:
                db.execute("UPDATE mine_attempts SET reason=?, n_files=?, tried_at=? WHERE fix_sha=?",
                           (why, len(files), now, hit))
                mark("retry", hit, f"rejected:{why}")
            else:
                insert_vuln(db, commit.get("sha", hit), repo, parent, ghsa, cwe, files, date, now)
                db.execute("DELETE FROM mine_attempts WHERE fix_sha=?", (hit,))
                mark("retry", hit, "mined")
                print(f"  +{cwe:9s} {repo}@{hit[:10]}  {len(files)} file(s)  [recovered]", flush=True)
            db.commit()

    remaining = {k: db.execute(q, (V,)).fetchone()[0] for k, q in (
        ("regold", "SELECT COUNT(*) FROM vulns WHERE fix_sha NOT IN "
                   "(SELECT fix_sha FROM gold_backfill WHERE kind='regold' AND version=?)"),
        ("retry", "SELECT COUNT(*) FROM mine_attempts WHERE reason='no_code_files' AND fix_sha NOT IN "
                  "(SELECT fix_sha FROM gold_backfill WHERE kind='retry' AND version=?)"))}
    print(f"[backfill v{V}] this run: {stats or 'nothing'} | still to check: {remaining}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adv-dir", required=True, help="dir of github/advisory-database records")
    ap.add_argument("--db", default="data/vulns.db")
    ap.add_argument("--limit", type=int, default=200, help="max NEW advisories to resolve/run")
    ap.add_argument("--max-files", type=int, default=5)
    ap.add_argument("--require-holdout", action="store_true",
                    help="abort if data/vloc_holdout.json is missing (CI uses this)")
    ap.add_argument("--retry-rejected", action="store_true",
                    help="also re-resolve advisories rejected on an earlier run (use after "
                         "changing --max-files or the gold filter, which changes the verdict)")
    ap.add_argument("--regold-budget", type=int, default=0,
                    help="re-check up to N stored rows under GOLD_FILTER_VERSION (see backfill)")
    ap.add_argument("--retry-budget", type=int, default=0,
                    help="re-resolve up to N no_code_files rejections under GOLD_FILTER_VERSION")
    args = ap.parse_args()

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(args.db)
    db.executescript(SCHEMA)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    seen = {r[0] for r in db.execute("SELECT fix_sha FROM vulns").fetchall()}
    tried = set() if args.retry_rejected else {
        r[0] for r in db.execute("SELECT fix_sha FROM mine_attempts").fetchall()}

    def reject(sha_: str, ghsa_: str, repo_: str, why: str, n: int | None = None) -> None:
        """Record a rejection so the next run spends its budget somewhere new."""
        db.execute("INSERT OR REPLACE INTO mine_attempts "
                   "(fix_sha, ghsa, repo, reason, n_files, tried_at) VALUES (?,?,?,?,?,?)",
                   (sha_, ghsa_, repo_, why, n, now))
        db.commit()
        rejected[why] = rejected.get(why, 0) + 1

    if args.regold_budget or args.retry_budget:
        backfill(db, args.adv_dir, args.regold_budget, args.retry_budget, args.max_files,
                 args.require_holdout, now)
        seen = {r[0] for r in db.execute("SELECT fix_sha FROM vulns").fetchall()}

    added = resolved = 0
    rejected: dict[str, int] = {}
    for ghsa, cwe, repo, sha in advisories(args.adv_dir, args.require_holdout):
        if resolved >= args.limit:
            break
        if any(s.startswith(sha) or sha.startswith(s) for s in seen):
            continue                                         # already have this fix
        if any(s.startswith(sha) or sha.startswith(s) for s in tried):
            continue                                         # already resolved and rejected
        commit = gh_get(f"https://api.github.com/repos/{repo}/commits/{sha}")
        resolved += 1
        if not commit:
            reject(sha, ghsa, repo, "unreachable")
            continue
        files, parent, date = gold_from_commit(commit)
        full_sha = commit.get("sha", sha)
        if not parent:
            reject(full_sha, ghsa, repo, "no_parent")
            continue
        if not files:
            reject(full_sha, ghsa, repo, "no_code_files", 0)
            continue
        if len(files) > args.max_files:
            reject(full_sha, ghsa, repo, "too_many_files", len(files))
            continue
        cur = db.execute(
            "INSERT OR IGNORE INTO vulns (fix_sha, repo, parent, ghsa, cwe, cwe_desc, "
            "gold_files, gold_ranges, commit_date, mined_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (full_sha, repo, parent, ghsa, cwe,
             CWE_DESC.get(cwe, f"{cwe}: (generic category description unavailable)"),
             json.dumps(sorted(files)), json.dumps(files), date, now))
        added += cur.rowcount
        seen.add(full_sha)
        if cur.rowcount:
            print(f"  +{cwe:9s} {repo}@{full_sha[:10]}  {len(files)} file(s)", flush=True)
        db.commit()

    n = db.execute("SELECT COUNT(*) FROM vulns").fetchone()[0]
    pend = db.execute("SELECT COUNT(*) FROM vulns WHERE rolled_out=0").fetchone()[0]
    skipped_known = db.execute("SELECT COUNT(*) FROM mine_attempts").fetchone()[0]
    print(f"\n[vulns] resolved {resolved} advisories, +{added} new | {n} total | {pend} pending",
          flush=True)
    # A zero that is not broken down is unreadable: `+0 new` looked for five days like the
    # advisory feed had gone quiet, when in fact every candidate was being rejected for a
    # knowable reason. Print the reasons, always, so the next zero explains itself.
    if rejected:
        detail = "  ".join(f"{k}={v}" for k, v in sorted(rejected.items()))
        print(f"[vulns] rejected this run: {detail}", flush=True)
    print(f"[vulns] {skipped_known} advisories permanently rejected and no longer re-fetched "
          f"(--retry-rejected to reconsider)", flush=True)
    if resolved >= args.limit:
        print(f"[vulns] hit --limit {args.limit}; more candidates remain -- re-run to continue",
              flush=True)
    db.close()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    main()

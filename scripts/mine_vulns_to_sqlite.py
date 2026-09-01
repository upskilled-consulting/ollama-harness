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
from mine_explore_eval import CODE_EXT, HUNK  # noqa: E402  (reuse diff parser)

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
"""


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


def _holdout() -> tuple[set, set]:
    """VLoc Bench advisories/repos we must never mine -- otherwise we train on the test set.
    Repo-level too: a different advisory in the same repo still leaks structure and style."""
    p = Path(__file__).resolve().parent.parent / "data" / "vloc_holdout.json"
    if not p.exists():
        print("[vulns] WARNING: no data/vloc_holdout.json -- mining WITHOUT test-set exclusion")
        return set(), set()
    d = json.loads(p.read_text(encoding="utf-8"))
    return set(d.get("ghsa") or []), {r.lower() for r in (d.get("repos") or [])}


def advisories(adv_dir: str):
    """Yield (ghsa_id, cwe_id, repo, sha) for GHSA records with a CWE and a fix commit."""
    hold_g, hold_r = _holdout()
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
        if Path(fn).suffix not in CODE_EXT or _TEST_RE.search(fn):
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adv-dir", required=True, help="dir of github/advisory-database records")
    ap.add_argument("--db", default="data/vulns.db")
    ap.add_argument("--limit", type=int, default=200, help="max NEW advisories to resolve/run")
    ap.add_argument("--max-files", type=int, default=5)
    args = ap.parse_args()

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(args.db)
    db.executescript(SCHEMA)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    seen = {r[0] for r in db.execute("SELECT fix_sha FROM vulns").fetchall()}

    added = resolved = 0
    for ghsa, cwe, repo, sha in advisories(args.adv_dir):
        if resolved >= args.limit:
            break
        if any(s.startswith(sha) or sha.startswith(s) for s in seen):
            continue                                         # already have this fix
        commit = gh_get(f"https://api.github.com/repos/{repo}/commits/{sha}")
        resolved += 1
        if not commit:
            continue
        files, parent, date = gold_from_commit(commit)
        if not parent or not (1 <= len(files) <= args.max_files):
            continue
        full_sha = commit.get("sha", sha)
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
    print(f"\n[vulns] resolved {resolved} advisories, +{added} new | {n} total | {pend} pending", flush=True)
    db.close()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    main()

"""
eval_suite.py — regression harness for the agent pipeline.

Runs a fixed set of representative tasks and checks content criteria beyond
file existence: minimum size, section count, absence of placeholders, and
presence of implementation notes.

Run after any model swap, Modelfile change, or harness modification to detect
regressions before they accumulate.

Usage:
    python eval_suite.py              # run all tasks then check criteria
    python eval_suite.py --fast       # check existing output files only (no re-runs)
    python eval_suite.py --no-wiggum  # run tasks but skip wiggum loop (faster)
    python eval_suite.py --generated [path]  # run generated tasks from tinytroupe_tasks.py

Environment:
    conda activate ollama-pi
"""

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import json
import os
import re
import subprocess
import sys

KB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_base")

# ---------------------------------------------------------------------------
# Criterion factories
# ---------------------------------------------------------------------------

def min_bytes(n: int):
    def check(content: str):
        b = len(content.encode("utf-8"))
        ok = b >= n
        return ok, f"{b} bytes (need >= {n})"
    check.__name__ = f"min_bytes({n})"
    return check


def min_lines(n: int):
    def check(content: str):
        lines = content.count("\n") + 1
        ok = lines >= n
        return ok, f"{lines} lines (need >= {n})"
    check.__name__ = f"min_lines({n})"
    return check


def exact_sections(n: int):
    """Exactly n H2-level content sections (excluding structural headers)."""
    structural = {"introduction", "conclusion", "summary", "overview", "background", "references"}
    def check(content: str):
        headers = re.findall(r'^##\s+(.+)', content, re.MULTILINE)
        items = [h for h in headers if re.sub(r'^[\d.\s]+', '', h).strip().lower() not in structural]
        ok = len(items) == n
        return ok, f"{len(items)} content sections (need exactly {n})"
    check.__name__ = f"exact_sections({n})"
    return check


def min_sections(n: int):
    """At least n H2-level sections (any)."""
    def check(content: str):
        headers = re.findall(r'^##\s+\S', content, re.MULTILINE)
        ok = len(headers) >= n
        return ok, f"{len(headers)} H2 sections (need >= {n})"
    check.__name__ = f"min_sections({n})"
    return check


def no_placeholders():
    """Output must not contain placeholder text."""
    BAD = [
        "[placeholder]", "TODO", "brief implementation note", "add example here",
        "implementation note here", "your example here",
    ]
    def check(content: str):
        found = [b for b in BAD if b.lower() in content.lower()]
        ok = len(found) == 0
        return ok, ("clean" if ok else f"placeholder text found: {found}")
    check.__name__ = "no_placeholders"
    return check


def has_impl_notes():
    """Output must contain at least one implementation note or code example."""
    MARKERS = ["implementation note", "example:", "```", "**example", "**implementation"]
    def check(content: str):
        found = any(m.lower() in content.lower() for m in MARKERS)
        return found, ("has implementation notes/examples" if found else "no implementation notes or examples found")
    check.__name__ = "has_impl_notes"
    return check


def no_file_path_refs():
    """Output must not mention file save paths (producer artifact)."""
    def check(content: str):
        # Common producer artifact: "This document is saved to ~/..."
        patterns = [r'saved to ~/\S+\.md', r'save.*~/\S+\.md', r'written to ~/\S+\.md']
        found = any(re.search(p, content, re.IGNORECASE) for p in patterns)
        return not found, ("clean" if not found else "output contains file path reference (producer artifact)")
    check.__name__ = "no_file_path_refs"
    return check


def has_nanda_sections():
    """Output must contain the core Nanda annotation sections."""
    REQUIRED = ["**Topic**", "**Motivation**", "**Contribution**"]
    EVIDENCE = ["**Evidence", "**Broad impact**", "**Narrow impact**"]
    def check(content: str):
        missing = [s for s in REQUIRED if s not in content]
        has_evidence = any(s in content for s in EVIDENCE)
        if missing:
            return False, f"missing sections: {missing}"
        if not has_evidence:
            return False, "missing evidence/impact section"
        return True, "all core sections present"
    check.__name__ = "has_nanda_sections"
    return check


def no_annotate_artifacts():
    """Output must not contain conversation loops or truncation artifacts."""
    BAD = ["--- EOF ---", "--- End", "[truncated]", "Sure, here", "Of course,"]
    def check(content: str):
        found = [b for b in BAD if b in content]
        return len(found) == 0, ("clean" if not found else f"artifacts found: {found}")
    check.__name__ = "no_annotate_artifacts"
    return check


def mentions_skill_names(required: list[str]):
    """Output must mention at least N of the required real skill names."""
    def check(content: str):
        found = [s for s in required if s in content]
        ok = len(found) >= max(1, len(required) // 2)
        return ok, f"found {len(found)}/{len(required)} required skills: {found}"
    check.__name__ = "mentions_skill_names"
    return check


def no_hallucinated_skills():
    """Output must not contain fabricated skill names not in the real registry."""
    FAKE = [
        "/research", "/visualize", "/translate",
        "/validate", "/compress", "/enumerate", "/summarize",
        "/writetofile", "/writetodisk", "/writetolog", "/writetotag",
        "/writetotemplate", "/writetotext", "/writetotitle", "/writetotopic",
    ]
    def check(content: str):
        found = [f for f in FAKE if f in content.lower()]
        return len(found) == 0, ("clean" if not found else f"hallucinated skills: {found}")
    check.__name__ = "no_hallucinated_skills"
    return check


def has_h1_heading():
    """Output must start with a # heading."""
    def check(content: str):
        ok = bool(re.search(r'^#\s+\S', content.strip(), re.MULTILINE))
        return ok, ("has H1 heading" if ok else "missing H1 heading")
    check.__name__ = "has_h1_heading"
    return check


# ---------------------------------------------------------------------------
# Task registry
# ---------------------------------------------------------------------------

BASE     = "~/Desktop/harness-engineering"
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_suite_fixtures")

SUITE = [
    {
        "id": "T_A",
        "desc": "top 5, context engineering",
        "task": f"Search for the top 5 context engineering techniques used in production LLM agents and save to {BASE}/eval-context-engineering.md",
        "output": f"{BASE}/eval-context-engineering.md",
        "kb_file": os.path.join(KB_DIR, "T_A.md"),
        "criteria": [
            min_bytes(800),
            min_lines(15),
            exact_sections(5),
            no_placeholders(),
            has_impl_notes(),
            no_file_path_refs(),
        ],
    },
    {
        "id": "T_B",
        "desc": "open-ended, cost management",
        "task": f"Search for best practices for cost envelope management in production AI agents and save to {BASE}/eval-cost-management.md",
        "output": f"{BASE}/eval-cost-management.md",
        "kb_file": os.path.join(KB_DIR, "T_B.md"),
        "criteria": [
            min_bytes(800),
            min_lines(15),
            min_sections(3),
            no_placeholders(),
            has_impl_notes(),
            no_file_path_refs(),
        ],
    },
    {
        "id": "T_C",
        "desc": "top 3, agent failure modes",
        "task": f"Search for the 3 most common failure modes in multi-agent AI systems and save to {BASE}/eval-agent-failure-modes.md",
        "output": f"{BASE}/eval-agent-failure-modes.md",
        "kb_file": os.path.join(KB_DIR, "T_C.md"),
        "criteria": [
            min_bytes(600),
            min_lines(10),
            exact_sections(3),
            no_placeholders(),
            has_impl_notes(),
            no_file_path_refs(),
        ],
    },
    {
        "id": "T_D",
        "desc": "top 3, context window management",
        "task": f"Search for the top 3 context window management strategies for production LLM applications and save to {BASE}/eval-context-window.md",
        "output": f"{BASE}/eval-context-window.md",
        "kb_file": os.path.join(KB_DIR, "T_D.md"),
        "criteria": [
            min_bytes(600),
            min_lines(10),
            exact_sections(3),
            no_placeholders(),
            has_impl_notes(),
            no_file_path_refs(),
        ],
    },
    {
        "id": "T_ANN",
        "desc": "annotate: ReAct paper fixture",
        "task": f"/annotate {FIXTURES}/ann_fixture.md {BASE}/eval-annotate-react.md",
        "output": f"{BASE}/eval-annotate-react.md",
        "kb_file": None,
        "criteria": [
            min_bytes(300),
            min_lines(8),
            has_nanda_sections(),
            no_annotate_artifacts(),
            no_placeholders(),
        ],
    },
    {
        "id": "T_E",
        "desc": "open-ended, prompt injection defense",
        "task": f"Search for best practices for prompt injection defense in production AI systems and save to {BASE}/eval-prompt-injection.md",
        "output": f"{BASE}/eval-prompt-injection.md",
        "kb_file": os.path.join(KB_DIR, "T_E.md"),
        "criteria": [
            min_bytes(800),
            min_lines(15),
            min_sections(3),
            no_placeholders(),
            has_impl_notes(),
            no_file_path_refs(),
        ],
    },
    {
        "id": "T_F",
        "desc": "introspect: agent skillset (no web search)",
        "task": f"/introspect Describe the agent's skill registry and pipeline stages and save to {BASE}/eval-introspect.md",
        "output": f"{BASE}/eval-introspect.md",
        "kb_file": None,
        "criteria": [
            min_bytes(400),
            min_lines(10),
            has_h1_heading(),
            mentions_skill_names(["/annotate", "/cite", "/deep", "/knowledge-graph", "/panel",
                                   "/recall", "/review", "/email", "/lit-review"]),
            no_hallucinated_skills(),
            no_placeholders(),
        ],
    },
    {
        "id": "T_G",
        "desc": "file-based synthesis: autoresearch program",
        "task": f"Read {BASE}/autoresearch_program.md and summarize the autoresearch program's design, metric, and keep rule, save to {BASE}/eval-autoresearch-summary.md",
        "output": f"{BASE}/eval-autoresearch-summary.md",
        "kb_file": None,
        "criteria": [
            min_bytes(400),
            min_lines(10),
            min_sections(2),
            no_placeholders(),
            no_file_path_refs(),
        ],
    },
    {
        "id": "T_H",
        "desc": "OOD topic: top 5, non-LLM domain",
        "task": f"Search for the top 5 nutrient synergies that support cognitive performance and save to {BASE}/eval-nutrient-synergies.md",
        "output": f"{BASE}/eval-nutrient-synergies.md",
        "kb_file": None,
        "criteria": [
            min_bytes(600),
            min_lines(10),
            exact_sections(5),
            no_placeholders(),
            has_impl_notes(),
            no_file_path_refs(),
        ],
    },
]


# ---------------------------------------------------------------------------
# Memory retrieval smoke test
# ---------------------------------------------------------------------------

def check_memory_retrieval() -> list[dict]:
    """
    Verify the paper corpus is indexed and get_context() returns relevant results.
    Returns list of result dicts (same shape as check_task results).
    """
    results = []

    # Import here so eval_suite works even when memory deps are absent
    try:
        from harness.memory import MemoryStore
    except ImportError as e:
        return [{"criterion": "memory_import", "passed": False, "detail": str(e)}]

    store = MemoryStore()

    # Check 1: paper count
    try:
        with store._connect() as conn:
            paper_count = conn.execute(
                "SELECT COUNT(*) FROM observations WHERE task_type = 'paper'"
            ).fetchone()[0]
        ok = paper_count > 0
        results.append({
            "criterion": "paper_count",
            "passed": ok,
            "detail": f"{paper_count} papers indexed",
        })
    except Exception as e:
        results.append({"criterion": "paper_count", "passed": False, "detail": str(e)})
        return results

    # Check 2: retrieval returns results for a domain query
    try:
        ctx = store.get_context("agentic reasoning language model chain of thought")
        ok = bool(ctx and len(ctx) > 50)
        results.append({
            "criterion": "retrieval_returns_results",
            "passed": ok,
            "detail": f"{len(ctx)} chars returned" if ctx else "empty response",
        })
    except Exception as e:
        results.append({"criterion": "retrieval_returns_results", "passed": False, "detail": str(e)})
        return results

    # Check 3: retrieval result surfaces at least one paper observation
    # get_context() formats paper rows as "**[date] title** (paper, n/a)"
    ok = "(paper," in (ctx or "") or "(paper " in (ctx or "")
    results.append({
        "criterion": "retrieval_contains_paper_obs",
        "passed": ok,
        "detail": "paper observations surfaced" if ok else "no paper observations in result",
    })

    return results


# ---------------------------------------------------------------------------
# Generated task loader (from tinytroupe_tasks.py output)
# ---------------------------------------------------------------------------

GENERATED_TASKS_DEFAULT = os.path.join(os.path.dirname(__file__), "generated_tasks.json")


def load_generated_suite(path: str = GENERATED_TASKS_DEFAULT) -> list[dict]:
    """
    Load tasks generated by tinytroupe_tasks.py and convert criteria_specs to
    callable criterion functions so they work with check_task() / score_suite().

    Returns a list of task dicts in the same format as SUITE.
    """
    from tinytroupe_tasks import criteria_to_functions

    if not os.path.exists(path):
        raise FileNotFoundError(f"Generated tasks file not found: {path}")

    with open(path, encoding="utf-8") as f:
        raw_tasks = json.load(f)

    tasks = []
    for t in raw_tasks:
        if "criteria_specs" not in t:
            continue
        task_dict = {
            "id": t["id"],
            "desc": t.get("desc", "generated"),
            "task": t["task"],
            "output": t["output"],
            "criteria": criteria_to_functions(t["criteria_specs"]),
        }
        tasks.append(task_dict)

    return tasks


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_task(task_def: dict, use_wiggum: bool = True) -> bool:
    """Run agent.py for a task. Returns True if agent exited cleanly."""
    cmd = [sys.executable, "-m", "harness.agent"]
    if not use_wiggum:
        cmd.append("--no-wiggum")

    task_str = task_def["task"]
    kb = task_def.get("kb_file", "")
    is_enumerated = any(c.__name__.startswith("exact_sections") for c in task_def.get("criteria", []))
    if kb and os.path.exists(kb) and is_enumerated:
        task_str += f" read {kb}"
        print(f"  [kb ] {task_def['id']}: injecting {os.path.basename(kb)}")

    cmd.append(task_str)

    print(f"  [run] {task_def['id']}: {task_def['desc']}")
    result = subprocess.run(cmd, capture_output=False)
    return result.returncode == 0


def check_task(task_def: dict) -> list[dict]:
    """Check all criteria for a task's output. Returns list of result dicts."""
    output_path = os.path.expanduser(task_def["output"])
    results = []

    if not os.path.exists(output_path):
        return [{"criterion": "file_exists", "passed": False, "detail": f"not found: {output_path}"}]

    with open(output_path, encoding="utf-8") as f:
        content = f.read()

    if not content.strip():
        return [{"criterion": "file_not_empty", "passed": False, "detail": "file is empty"}]

    for criterion_fn in task_def["criteria"]:
        passed, detail = criterion_fn(content)
        results.append({
            "criterion": criterion_fn.__name__,
            "passed": passed,
            "detail": detail,
        })

    return results


def score_suite(
    task_ids: list[str] | None = None,
    runs_jsonl: str = "data/runs.jsonl",
    extra_tasks: list[dict] | None = None,
) -> float:
    """
    Run a subset of SUITE tasks (plus any extra_tasks) and return a composite float metric.

    Composite = 0.7 * mean_wiggum_r1 + 0.3 * criteria_rate * 10

    Wiggum r1 score comes from the most recent runs.jsonl entries matching the
    eval task fingerprints. Criteria rate is the fraction of content criteria passed.

    task_ids:    list of SUITE task IDs to run (e.g. ["T_A", "T_B"]). None = all SUITE tasks.
    extra_tasks: additional task dicts (e.g. from load_generated_suite()) appended to the run.
    Returns a float in [0, 10].
    """
    suite_tasks = [t for t in SUITE if task_ids is None or t["id"] in task_ids]
    tasks = suite_tasks + (extra_tasks or [])
    if not tasks:
        return 0.0

    # Note run count before
    try:
        with open(runs_jsonl, encoding="utf-8") as f:
            n_before = sum(1 for l in f if l.strip())
    except FileNotFoundError:
        n_before = 0

    # Run tasks
    for task_def in tasks:
        run_task(task_def, use_wiggum=True)

    # Read new runs.jsonl entries
    try:
        with open(runs_jsonl, encoding="utf-8") as f:
            all_runs = [json.loads(l) for l in f if l.strip()]
    except FileNotFoundError:
        all_runs = []

    new_runs = all_runs[n_before:]

    # Build fingerprint map: task id → substring to match against runs.jsonl task field
    FIXED_FINGERPRINTS = {
        "T_A": "top 5 context engineering",
        "T_B": "cost envelope management",
        "T_C": "3 most common failure modes",
        "T_D": "context window management strategies",
        "T_E": "prompt injection defense",
    }
    fingerprints = {}
    for t in tasks:
        tid = t["id"]
        if tid in FIXED_FINGERPRINTS:
            fingerprints[tid] = FIXED_FINGERPRINTS[tid]
        else:
            # Generated tasks: use output filename stem as fingerprint
            out = t.get("output", "")
            stem = os.path.splitext(os.path.basename(out))[0].replace("-", " ").replace("_", " ")
            fingerprints[tid] = stem

    wiggum_scores = []
    for run in new_runs:
        task_str = run.get("task", "").lower()
        for tid, fp in fingerprints.items():
            if fp.lower() in task_str:
                scores = run.get("wiggum_scores", [])
                if scores:
                    wiggum_scores.append(scores[0])
                break

    mean_wiggum = sum(wiggum_scores) / len(wiggum_scores) if wiggum_scores else 0.0

    # Content criteria
    total_criteria = 0
    passed_criteria = 0
    for task_def in tasks:
        results = check_task(task_def)
        total_criteria += len(results)
        passed_criteria += sum(1 for r in results if r["passed"])
    criteria_rate = passed_criteria / total_criteria if total_criteria else 0.0

    composite = round(0.7 * mean_wiggum + 0.3 * criteria_rate * 10, 3)
    return composite


def print_results(task_def: dict, results: list[dict]):
    passed_all = all(r["passed"] for r in results)
    status = "PASS" if passed_all else "FAIL"
    print(f"\n  {task_def['id']} ({task_def['desc']}) — {status}")
    for r in results:
        mark = "✓" if r["passed"] else "✗"
        print(f"    {mark} {r['criterion']}: {r['detail']}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Parse --generated [path] flag
    gen_tasks = None
    if "--generated" in sys.argv:
        idx = sys.argv.index("--generated")
        gen_path = GENERATED_TASKS_DEFAULT
        if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("--"):
            gen_path = sys.argv[idx + 1]
        gen_tasks = load_generated_suite(gen_path)
        print(f"  [generated] loaded {len(gen_tasks)} tasks from {gen_path}")

    # --score [--tasks T_A,T_B] — machine-readable composite float for autoresearch
    if "--score" in sys.argv:
        task_ids = None
        if "--tasks" in sys.argv:
            idx = sys.argv.index("--tasks")
            if idx + 1 < len(sys.argv):
                task_ids = [t.strip() for t in sys.argv[idx + 1].split(",")]
        score = score_suite(task_ids=task_ids, extra_tasks=gen_tasks)
        print(f"{score:.3f}")
        sys.exit(0)

    fast = "--fast" in sys.argv
    no_wiggum = "--no-wiggum" in sys.argv

    all_tasks = SUITE + (gen_tasks or [])

    print("\n======================================")
    print(" Eval Suite")
    print(f" mode: {'fast (criteria check only)' if fast else 'full (run + check)'}")
    if gen_tasks:
        print(f" + {len(gen_tasks)} generated tasks")
    print("======================================\n")

    total_tasks = len(all_tasks)
    passed_tasks = 0
    total_criteria = 0
    passed_criteria = 0

    for task_def in all_tasks:
        if not fast:
            ok = run_task(task_def, use_wiggum=not no_wiggum)
            if not ok:
                print(f"  [warn] agent.py exited with error for {task_def['id']}")

        results = check_task(task_def)
        print_results(task_def, results)

        task_passed = all(r["passed"] for r in results)
        if task_passed:
            passed_tasks += 1
        total_criteria += len(results)
        passed_criteria += sum(1 for r in results if r["passed"])

    # Memory retrieval smoke test (always runs, no agent.py invocation)
    print("\n  T_MEM (memory retrieval smoke test)")
    mem_results = check_memory_retrieval()
    mem_passed = all(r["passed"] for r in mem_results)
    print(f"  T_MEM — {'PASS' if mem_passed else 'FAIL'}")
    for r in mem_results:
        mark = "✓" if r["passed"] else "✗"
        print(f"    {mark} {r['criterion']}: {r['detail']}")
    total_criteria += len(mem_results)
    passed_criteria += sum(1 for r in mem_results if r["passed"])
    if mem_passed:
        passed_tasks += 1
    total_tasks += 1

    print("\n======================================")
    print(f" Tasks:    {passed_tasks}/{total_tasks} passed")
    print(f" Criteria: {passed_criteria}/{total_criteria} passed")
    print(f" Overall:  {'PASS' if passed_tasks == total_tasks else 'FAIL'}")
    print("======================================\n")

    sys.exit(0 if passed_tasks == total_tasks else 1)

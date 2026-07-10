"""
harness.eval.eval_suite — regression harness for the agent pipeline.

Runs a fixed set of representative tasks and checks content criteria beyond
file existence: minimum size, section count, absence of placeholders, and
presence of implementation notes.

Run after any model swap, Modelfile change, or harness modification to detect
regressions before they accumulate.

Usage:
    python -m harness.eval.eval_suite                  # run all tasks then check criteria
    python -m harness.eval.eval_suite --fast           # check existing output files only
    python -m harness.eval.eval_suite --no-wiggum      # run tasks but skip wiggum loop
    python -m harness.eval.eval_suite --score          # print composite float and exit
    python -m harness.eval.eval_suite --score --tasks T_B,T_D,T_E
    python -m harness.eval.eval_suite --generated [path]

Environment:
    HARNESS_EVAL_BASE   output directory for eval files (default: ~/Desktop/ollama-harness)
"""

import json
import os
import re
import subprocess
import sys

# Output base dir — override with HARNESS_EVAL_BASE env var
BASE = os.environ.get("HARNESS_EVAL_BASE", "~/Desktop/ollama-harness")

_HERE    = os.path.dirname(os.path.abspath(__file__))
KB_DIR   = os.path.join(_HERE, "knowledge_base")
FIXTURES = os.path.join(_HERE, "eval_suite_fixtures")

GENERATED_TASKS_DEFAULT = os.path.join(_HERE, "generated_tasks.json")


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
    MARKERS = ["implementation note", "example:", "```", "**example", "**implementation"]
    def check(content: str):
        found = any(m.lower() in content.lower() for m in MARKERS)
        return found, ("has implementation notes/examples" if found else "no implementation notes or examples found")
    check.__name__ = "has_impl_notes"
    return check


def no_file_path_refs():
    def check(content: str):
        patterns = [r'saved to ~/\S+\.md', r'save.*~/\S+\.md', r'written to ~/\S+\.md']
        found = any(re.search(p, content, re.IGNORECASE) for p in patterns)
        return not found, ("clean" if not found else "output contains file path reference (producer artifact)")
    check.__name__ = "no_file_path_refs"
    return check


def has_nanda_sections():
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
    BAD = ["--- EOF ---", "--- End", "[truncated]", "Sure, here", "Of course,"]
    def check(content: str):
        found = [b for b in BAD if b in content]
        return len(found) == 0, ("clean" if not found else f"artifacts found: {found}")
    check.__name__ = "no_annotate_artifacts"
    return check


def mentions_skill_names(required: list[str]):
    def check(content: str):
        found = [s for s in required if s in content]
        ok = len(found) >= max(1, len(required) // 2)
        return ok, f"found {len(found)}/{len(required)} required skills: {found}"
    check.__name__ = "mentions_skill_names"
    return check


def no_hallucinated_skills():
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
    def check(content: str):
        ok = bool(re.search(r'^#\s+\S', content.strip(), re.MULTILINE))
        return ok, ("has H1 heading" if ok else "missing H1 heading")
    check.__name__ = "has_h1_heading"
    return check


# ---------------------------------------------------------------------------
# Task registry
# ---------------------------------------------------------------------------

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
    results = []
    try:
        from harness.memory import MemoryStore
    except ImportError as e:
        return [{"criterion": "memory_import", "passed": False, "detail": str(e)}]

    store = MemoryStore()

    try:
        with store._connect() as conn:
            paper_count = conn.execute(
                "SELECT COUNT(*) FROM observations WHERE task_type = 'paper'"
            ).fetchone()[0]
        ok = paper_count > 0
        results.append({"criterion": "paper_count", "passed": ok, "detail": f"{paper_count} papers indexed"})
    except Exception as e:
        results.append({"criterion": "paper_count", "passed": False, "detail": str(e)})
        return results

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

    ok = "(paper," in (ctx or "") or "(paper " in (ctx or "")
    results.append({
        "criterion": "retrieval_contains_paper_obs",
        "passed": ok,
        "detail": "paper observations surfaced" if ok else "no paper observations in result",
    })

    return results


# ---------------------------------------------------------------------------
# Generated task loader
# ---------------------------------------------------------------------------

def load_generated_suite(path: str = GENERATED_TASKS_DEFAULT) -> list[dict]:
    try:
        from tinytroupe_tasks import criteria_to_functions  # type: ignore[import]
    except ImportError as e:
        raise ImportError(f"tinytroupe_tasks not available: {e}") from e

    if not os.path.exists(path):
        raise FileNotFoundError(f"Generated tasks file not found: {path}")

    with open(path, encoding="utf-8") as f:
        raw_tasks = json.load(f)

    tasks = []
    for t in raw_tasks:
        if "criteria_specs" not in t:
            continue
        task_dict = {
            "id":       t["id"],
            "desc":     t.get("desc", "generated"),
            "task":     t["task"],
            "output":   t["output"],
            "criteria": criteria_to_functions(t["criteria_specs"]),
        }
        tasks.append(task_dict)

    return tasks


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_task(task_def: dict, use_wiggum: bool = True) -> bool:
    """Run the agent for a task. Returns True if the agent exited cleanly."""
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
    """Check all criteria for a task's output file."""
    output_path = os.path.expanduser(task_def["output"])
    if not os.path.exists(output_path):
        return [{"criterion": "file_exists", "passed": False, "detail": f"not found: {output_path}"}]

    with open(output_path, encoding="utf-8") as f:
        content = f.read()

    if not content.strip():
        return [{"criterion": "file_not_empty", "passed": False, "detail": "file is empty"}]

    results = []
    for criterion_fn in task_def["criteria"]:
        passed, detail = criterion_fn(content)
        results.append({"criterion": criterion_fn.__name__, "passed": passed, "detail": detail})

    return results


def score_suite(
    task_ids: list[str] | None = None,
    runs_jsonl: str = "data/runs.jsonl",
    extra_tasks: list[dict] | None = None,
) -> float:
    """
    Run a subset of SUITE tasks and return a composite float metric.

    Composite = 0.7 * mean_wiggum_r1 + 0.3 * criteria_rate * 10

    Returns a float in [0, 10].
    """
    suite_tasks = [t for t in SUITE if task_ids is None or t["id"] in task_ids]
    tasks = suite_tasks + (extra_tasks or [])
    if not tasks:
        return 0.0

    try:
        with open(runs_jsonl, encoding="utf-8") as f:
            n_before = sum(1 for line in f if line.strip())
    except FileNotFoundError:
        n_before = 0

    for task_def in tasks:
        run_task(task_def, use_wiggum=True)

    try:
        with open(runs_jsonl, encoding="utf-8") as f:
            all_runs = [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        all_runs = []

    new_runs = all_runs[n_before:]

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

    total_criteria = 0
    passed_criteria = 0
    for task_def in tasks:
        results = check_task(task_def)
        total_criteria += len(results)
        passed_criteria += sum(1 for r in results if r["passed"])
    criteria_rate = passed_criteria / total_criteria if total_criteria else 0.0

    return round(0.7 * mean_wiggum + 0.3 * criteria_rate * 10, 3)


def print_results(task_def: dict, results: list[dict]) -> None:
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
    gen_tasks = None
    if "--generated" in sys.argv:
        idx = sys.argv.index("--generated")
        gen_path = GENERATED_TASKS_DEFAULT
        if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("--"):
            gen_path = sys.argv[idx + 1]
        gen_tasks = load_generated_suite(gen_path)
        print(f"  [generated] loaded {len(gen_tasks)} tasks from {gen_path}")

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

    total_tasks = passed_tasks = total_criteria = passed_criteria = 0

    for task_def in all_tasks:
        if not fast:
            ok = run_task(task_def, use_wiggum=not no_wiggum)
            if not ok:
                print(f"  [warn] agent exited with error for {task_def['id']}")
        results = check_task(task_def)
        print_results(task_def, results)
        total_tasks += 1
        if all(r["passed"] for r in results):
            passed_tasks += 1
        total_criteria += len(results)
        passed_criteria += sum(1 for r in results if r["passed"])

    print("\n  T_MEM (memory retrieval smoke test)")
    mem_results = check_memory_retrieval()
    mem_passed = all(r["passed"] for r in mem_results)
    print(f"  T_MEM — {'PASS' if mem_passed else 'FAIL'}")
    for r in mem_results:
        mark = "✓" if r["passed"] else "✗"
        print(f"    {mark} {r['criterion']}: {r['detail']}")
    total_criteria += len(mem_results)
    passed_criteria += sum(1 for r in mem_results if r["passed"])
    total_tasks += 1
    if mem_passed:
        passed_tasks += 1

    print("\n======================================")
    print(f" Tasks:    {passed_tasks}/{total_tasks} passed")
    print(f" Criteria: {passed_criteria}/{total_criteria} passed")
    print(f" Overall:  {'PASS' if passed_tasks == total_tasks else 'FAIL'}")
    print("======================================\n")

    sys.exit(0 if passed_tasks == total_tasks else 1)

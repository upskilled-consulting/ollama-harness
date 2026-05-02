"""
tinytroupe_tasks.py — synthetic eval task generation via persona simulation.

Uses TinyTroupe personas (if available) or falls back to raw ollama.chat to generate
diverse research task requests from 8 practitioner archetypes. Output is saved as
generated_tasks.json in eval_suite.py SUITE format.

Install TinyTroupe (not on PyPI — install from GitHub):
    pip install git+https://github.com/microsoft/TinyTroupe.git@main

Usage:
    conda activate ollama-pi
    python tinytroupe_tasks.py                      # generate all personas, save to generated_tasks.json
    python tinytroupe_tasks.py --out custom.json    # custom output path
    python tinytroupe_tasks.py --count 2            # tasks per persona (default 1)
    python tinytroupe_tasks.py --dry-run            # print without saving

The generated tasks extend the autoresearch eval surface beyond the 5 fixed tasks.
"""

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import argparse
import json
import os
import os as _os
import re
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

from harness import inference as ollama

# ---------------------------------------------------------------------------
# TinyTroupe availability check
# ---------------------------------------------------------------------------

try:
    import tinytroupe  # noqa: F401
    from tinytroupe import config_manager
    from tinytroupe.agent import TinyPerson
    TINYTROUPE_AVAILABLE = True
except ImportError:
    TINYTROUPE_AVAILABLE = False

MODEL = "pi-qwen-32b"
BASE = "~/Desktop/harness-engineering"
OUTPUT_DEFAULT = os.path.join(os.path.dirname(__file__), "generated_tasks.json")

# ---------------------------------------------------------------------------
# Persona definitions
# ---------------------------------------------------------------------------

PERSONAS = [
    {
        "id": "P_devops",
        "name": "Jordan",
        "role": "Senior DevOps Engineer",
        "context": (
            "You maintain CI/CD pipelines and Kubernetes clusters at a mid-size SaaS company. "
            "You are evaluating AI agent tooling for infrastructure automation tasks. "
            "You care deeply about reliability, observability, and cost control."
        ),
    },
    {
        "id": "P_datasci",
        "name": "Priya",
        "role": "Staff Data Scientist",
        "context": (
            "You build ML pipelines and experiment tracking systems. "
            "You are exploring LLM-based agents to automate data exploration and reporting. "
            "You value reproducibility, statistical rigor, and explainability."
        ),
    },
    {
        "id": "P_backend",
        "name": "Marcus",
        "role": "Backend Engineer",
        "context": (
            "You design high-throughput APIs and distributed services in Python and Go. "
            "You are integrating AI agents into your company's microservices architecture. "
            "You care about latency, fault tolerance, and clean API contracts."
        ),
    },
    {
        "id": "P_pm",
        "name": "Sofia",
        "role": "Product Manager (AI Products)",
        "context": (
            "You own the roadmap for an AI-powered feature set in a B2B SaaS product. "
            "You need to understand technical trade-offs to set realistic expectations with engineering. "
            "You focus on user value, time-to-market, and risk management."
        ),
    },
    {
        "id": "P_security",
        "name": "Alex",
        "role": "Security Engineer",
        "context": (
            "You are responsible for threat modelling and secure-by-default practices at a fintech company. "
            "You are assessing risks introduced by AI agents that have tool-calling capabilities. "
            "You prioritize attack surface reduction, auditability, and compliance."
        ),
    },
    {
        "id": "P_mleng",
        "name": "Tanaka",
        "role": "ML Infrastructure Engineer",
        "context": (
            "You build and operate the serving infrastructure for large language models. "
            "You work on batching, caching, quantization, and inference optimization. "
            "You care about throughput, latency percentiles, and GPU utilization."
        ),
    },
    {
        "id": "P_founder",
        "name": "Elena",
        "role": "Technical Startup Founder",
        "context": (
            "You are building a B2B AI product with a small team and limited budget. "
            "You are choosing between building on top of existing LLM APIs and fine-tuning your own models. "
            "You care about cost efficiency, time-to-market, and differentiation."
        ),
    },
    {
        "id": "P_techlead",
        "name": "Kwame",
        "role": "Tech Lead",
        "context": (
            "You lead a team of 8 engineers building an AI research assistant product. "
            "You set technical standards, review architecture decisions, and mentor junior engineers. "
            "You care about maintainability, team velocity, and avoiding technical debt."
        ),
    },
]

# ---------------------------------------------------------------------------
# Criteria factories (mirrors eval_suite.py — kept local to avoid circular import)
# ---------------------------------------------------------------------------

def _min_bytes(n):
    def check(content):
        b = len(content.encode("utf-8"))
        return b >= n, f"{b} bytes (need >= {n})"
    check.__name__ = f"min_bytes({n})"
    return check

def _min_lines(n):
    def check(content):
        lines = content.count("\n") + 1
        return lines >= n, f"{lines} lines (need >= {n})"
    check.__name__ = f"min_lines({n})"
    return check

def _exact_sections(n):
    structural = {"introduction", "conclusion", "summary", "overview", "background", "references"}
    def check(content):
        headers = re.findall(r'^##\s+(.+)', content, re.MULTILINE)
        items = [h for h in headers if re.sub(r'^[\d.\s]+', '', h).strip().lower() not in structural]
        return len(items) == n, f"{len(items)} content sections (need exactly {n})"
    check.__name__ = f"exact_sections({n})"
    return check

def _min_sections(n):
    def check(content):
        headers = re.findall(r'^##\s+\S', content, re.MULTILINE)
        return len(headers) >= n, f"{len(headers)} H2 sections (need >= {n})"
    check.__name__ = f"min_sections({n})"
    return check

def _no_placeholders():
    BAD = ["[placeholder]", "TODO", "brief implementation note", "add example here",
           "implementation note here", "your example here"]
    def check(content):
        found = [b for b in BAD if b.lower() in content.lower()]
        return len(found) == 0, ("clean" if not found else f"placeholder text found: {found}")
    check.__name__ = "no_placeholders"
    return check

def _has_impl_notes():
    MARKERS = ["implementation note", "example:", "```", "**example", "**implementation"]
    def check(content):
        found = any(m.lower() in content.lower() for m in MARKERS)
        return found, ("has implementation notes/examples" if found else "no implementation notes or examples found")
    check.__name__ = "has_impl_notes"
    return check

def _no_file_path_refs():
    def check(content):
        patterns = [r'saved to ~/\S+\.md', r'save.*~/\S+\.md', r'written to ~/\S+\.md']
        found = any(re.search(p, content, re.IGNORECASE) for p in patterns)
        return not found, ("clean" if not found else "output contains file path reference (producer artifact)")
    check.__name__ = "no_file_path_refs"
    return check

# ---------------------------------------------------------------------------
# Task extraction from LLM response
# ---------------------------------------------------------------------------

def _extract_count(task_text: str) -> int | None:
    """Return N if the task asks for 'top N' or 'N most' items, else None."""
    m = re.search(r'\b(?:top|best)\s+(\d+)\b', task_text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r'\b(\d+)\s+most\b', task_text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def build_criteria(task_text: str, count: int | None) -> list:
    """Return a list of serialisable criterion specs for a generated task."""
    criteria = []
    if count is not None and 2 <= count <= 7:
        criteria.append({"type": "exact_sections", "n": count})
        criteria.append({"type": "min_bytes", "n": 600})
        criteria.append({"type": "min_lines", "n": 10})
    else:
        criteria.append({"type": "min_sections", "n": 3})
        criteria.append({"type": "min_bytes", "n": 800})
        criteria.append({"type": "min_lines", "n": 15})
    criteria.append({"type": "no_placeholders"})
    criteria.append({"type": "has_impl_notes"})
    criteria.append({"type": "no_file_path_refs"})
    return criteria


def criteria_to_functions(specs: list) -> list:
    """Convert serialised criterion specs back to callable criterion functions."""
    fns = []
    for spec in specs:
        t = spec["type"]
        if t == "exact_sections":
            fns.append(_exact_sections(spec["n"]))
        elif t == "min_sections":
            fns.append(_min_sections(spec["n"]))
        elif t == "min_bytes":
            fns.append(_min_bytes(spec["n"]))
        elif t == "min_lines":
            fns.append(_min_lines(spec["n"]))
        elif t == "no_placeholders":
            fns.append(_no_placeholders())
        elif t == "has_impl_notes":
            fns.append(_has_impl_notes())
        elif t == "no_file_path_refs":
            fns.append(_no_file_path_refs())
    return fns

# ---------------------------------------------------------------------------
# Generation backends
# ---------------------------------------------------------------------------

_TASK_PROMPT_TEMPLATE = """\
You are {name}, a {role}.

{context}

A colleague asks: "What would you most want an AI research agent to investigate and write up for you right now?"

Respond with exactly one research task request in this format:
TASK: <one sentence describing what to search for and what to save, including a filename like eval-<topic>.md>

Keep it under 25 words. Be specific to your role. Do NOT include file paths — just the filename (e.g. eval-topic.md).
Examples of good tasks:
- "Search for the top 5 Kubernetes cost optimization strategies and save to eval-k8s-cost.md"
- "Search for best practices for ML experiment reproducibility and save to eval-ml-reproducibility.md"
"""


def _generate_with_ollama(persona: dict) -> str:
    """Generate a task string via raw ollama.chat (fallback path)."""
    prompt = _TASK_PROMPT_TEMPLATE.format(
        name=persona["name"],
        role=persona["role"],
        context=persona["context"],
    )
    response = ollama.chat(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.8},
    )
    return response.message.content.strip()


def _generate_with_tinytroupe(persona: dict) -> str:
    """Generate a task string via TinyTroupe persona simulation."""
    # Configure TinyTroupe to use Ollama
    config_manager.update("api_type", "ollama")
    config_manager.update("model", MODEL)

    person = TinyPerson(persona["name"])
    person.define("role", persona["role"])
    person.define("personality_traits", [persona["context"]])

    person.listen_and_act(
        "A colleague asks: 'What would you most want an AI research agent to investigate "
        "and write up for you right now?' Reply with exactly: TASK: <one sentence describing "
        "what to search for, ending with a filename like eval-<topic>.md>"
    )

    actions = person.pop_actions_and_get_contents_for("TALK")
    return actions[0] if actions else ""


def generate_task_text(persona: dict) -> str:
    """Generate raw LLM response for a persona, using TinyTroupe if available."""
    if TINYTROUPE_AVAILABLE:
        try:
            return _generate_with_tinytroupe(persona)
        except Exception as e:
            print(f"  [warn] TinyTroupe failed for {persona['name']}: {e} — falling back to ollama")
    return _generate_with_ollama(persona)


def parse_task_line(raw: str, persona: dict, index: int) -> dict | None:
    """Extract TASK: line from raw LLM response and build a task dict."""
    m = re.search(r'TASK:\s*(.+)', raw, re.IGNORECASE)
    if not m:
        print(f"  [warn] no TASK: line from {persona['name']} — skipping")
        return None

    task_text = m.group(1).strip()

    # Find or create output filename
    fn_match = re.search(r'(eval-[\w\-]+\.md)', task_text, re.IGNORECASE)
    if fn_match:
        filename = fn_match.group(1).lower()
    else:
        slug = re.sub(r'[^\w]+', '-', persona["role"].lower()).strip('-')
        filename = f"eval-gen-{slug}-{index}.md"

    # Build full task string with save path
    if re.search(r'\bsave\b', task_text, re.IGNORECASE):
        # Replace bare filename with full path
        task_full = re.sub(r'(eval-[\w\-]+\.md)', f'{BASE}/{filename}', task_text)
        if filename not in task_full:
            task_full = f"{task_text} — save to {BASE}/{filename}"
    else:
        task_full = f"{task_text} Save to {BASE}/{filename}."

    count = _extract_count(task_text)
    criteria_specs = build_criteria(task_text, count)

    return {
        "id": f"{persona['id']}_{index}",
        "desc": f"generated: {persona['role']}",
        "task": task_full,
        "output": f"{BASE}/{filename}",
        "criteria_specs": criteria_specs,   # serialisable; eval_suite loads and converts
        "persona": persona["name"],
        "raw_response": raw,
    }

# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate(count_per_persona: int = 1, dry_run: bool = False) -> list[dict]:
    """Run all personas and return list of task dicts."""
    tasks = []
    for persona in PERSONAS:
        for i in range(count_per_persona):
            print(f"  [{persona['id']}] Generating task {i+1}/{count_per_persona} for {persona['name']} ({persona['role']})...")
            raw = generate_task_text(persona)
            task = parse_task_line(raw, persona, i + 1)
            if task:
                tasks.append(task)
                print(f"    → {task['task'][:80]}...")
    return tasks


def save(tasks: list[dict], path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2)
    print(f"\n  [saved] {len(tasks)} tasks → {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic eval tasks from personas")
    parser.add_argument("--out", default=OUTPUT_DEFAULT, help="Output JSON path")
    parser.add_argument("--count", type=int, default=1, help="Tasks per persona")
    parser.add_argument("--dry-run", action="store_true", help="Print tasks without saving")
    args = parser.parse_args()

    print(f"\n{'='*50}")
    print(" TinyTroupe Task Generator")
    print(f" Backend: {'tinytroupe' if TINYTROUPE_AVAILABLE else 'ollama (fallback)'}")
    print(f" Model:   {MODEL}")
    print(f" Personas: {len(PERSONAS)}  |  Tasks per persona: {args.count}")
    print(f"{'='*50}\n")

    tasks = generate(count_per_persona=args.count, dry_run=args.dry_run)

    print(f"\n  Generated {len(tasks)} tasks total.")

    if args.dry_run:
        print("\n--- DRY RUN (not saving) ---")
        for t in tasks:
            print(f"\n  [{t['id']}] {t['desc']}")
            print(f"    task:   {t['task']}")
            print(f"    output: {t['output']}")
            print(f"    criteria: {[s['type'] for s in t['criteria_specs']]}")
    else:
        save(tasks, args.out)

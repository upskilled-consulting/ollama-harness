"""
Run the harness test suite.

Usage:
    python run_tests.py              # full suite
    python run_tests.py --fast       # skip slow tests (omits real-Ollama submit test)
    python run_tests.py tests/test_gather_research.py   # single file
    python run_tests.py -k oversearch                   # keyword filter (passed to pytest)
    python run_tests.py --fast -k leverage              # combinable

Slow tests (skipped with --fast):
    test_submit_valid_task_returns_item_id  — spins up a real Ollama run, ~9 min
"""

import subprocess
import sys

SLOW = [
    "test_submit_valid_task_returns_item_id",
]


def main() -> None:
    argv = sys.argv[1:]
    fast = "--fast" in argv
    extra = [a for a in argv if a != "--fast"]

    cmd = [sys.executable, "-m", "pytest", "--tb=short", "-v"]

    if fast:
        skip_expr = " and ".join(f"not {t}" for t in SLOW)
        cmd += ["-k", skip_expr]
        print(f"[run_tests] fast mode — skipping: {', '.join(SLOW)}")
    else:
        print("[run_tests] full suite — slow tests included (pass --fast to skip)")

    cmd += extra if extra else ["tests/"]

    result = subprocess.run(cmd)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()

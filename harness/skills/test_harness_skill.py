"""
test_harness_skill.py — /test-harness standalone skill.

Runs the harness test suite via run_tests.py, captures output, and writes
it to agent-workspace/test-results/latest.txt so the agent can retrieve
results across sessions without re-running the suite.

Usage (via agent.py):
    python agent.py "/test-harness"               # fast suite (default)
    python agent.py "/test-harness --full"        # include slow Ollama test
    python agent.py "/test-harness -k oversearch" # keyword filter
"""

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE        = Path(__file__).parent.parent.parent   # project root
RESULTS_DIR = HERE / "agent-workspace" / "test-results"
LATEST      = RESULTS_DIR / "latest.txt"


def run_test_harness_standalone(task: str) -> dict:
    """
    Parse flags from task string, run the suite, save output, return result dict.

    Returns:
        output      — full captured stdout+stderr
        passed      — int (parsed from summary line, -1 if not found)
        failed      — int
        warnings    — int
        duration_s  — float (-1 if not parsed)
        summary     — the pytest summary line ("22 passed, 0 failed in 14.3s")
        output_path — str path to the saved latest.txt
        fast        — bool (True when slow tests were skipped)
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    tokens = task.split()
    full   = "--full" in tokens

    cmd = [sys.executable, str(HERE / "run_tests.py")]
    if not full:
        cmd.append("--fast")

    # Pass through any -k <keyword> or other pytest flags
    passthrough = []
    skip_next   = False
    for tok in tokens:
        if skip_next:
            passthrough += ["-k", tok]
            skip_next = False
            continue
        if tok in ("--full", "--fast"):
            continue
        if tok == "-k":
            skip_next = True
            continue
        passthrough.append(tok)
    cmd.extend(passthrough)

    mode = "full" if full else "fast"
    print(f"\n[skill:test-harness] running {mode} suite: {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        cwd=str(HERE),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = result.stdout + ("\n" + result.stderr if result.stderr.strip() else "")

    # Write latest + timestamped copy
    LATEST.write_text(output, encoding="utf-8")
    ts_path = RESULTS_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    ts_path.write_text(output, encoding="utf-8")

    # Parse pytest summary line (handles deselected, xfailed, xpassed, etc.)
    summary_m = re.search(r"=+ (.+?) in ([\d.]+)s =+", output)
    if summary_m:
        body     = summary_m.group(1)
        duration = float(summary_m.group(2))
        summary  = f"{body} in {duration}s"
        passed   = int(m.group(1)) if (m := re.search(r"(\d+) passed", body)) else 0
        failed   = int(m.group(1)) if (m := re.search(r"(\d+) failed", body)) else 0
        warnings = int(m.group(1)) if (m := re.search(r"(\d+) warning", body)) else 0
    else:
        passed = failed = warnings = -1
        duration = -1.0
        summary  = "(pytest summary not found)"

    # Extract FAILED block lines for quick reporting
    failed_lines = [l for l in output.splitlines() if l.startswith("FAILED ")]

    status = "PASS" if result.returncode == 0 else "FAIL"
    print(f"[skill:test-harness] {status} — {summary}")
    print(f"[skill:test-harness] output saved -> {LATEST}")

    return {
        "output":       output,
        "passed":       passed,
        "failed":       failed,
        "warnings":     warnings,
        "duration_s":   duration,
        "summary":      summary,
        "failed_lines": failed_lines,
        "output_path":  str(LATEST),
        "fast":         not full,
        "returncode":   result.returncode,
    }

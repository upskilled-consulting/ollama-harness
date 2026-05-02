"""
supervisor.py — convergence monitor for the harness pipeline.

Reads runs.jsonl and computes four signals that indicate whether the system
is collapsing toward a fixed point:

  1. wiggum_score_variance    — std dev of final wiggum scores across recent runs.
                                Low variance means the evaluator stops differentiating outputs.
  2. output_size_cv           — coefficient of variation (std/mean) of output_bytes.
                                Low CV means outputs are converging in length/density.
  3. search_utilization       — mean fraction of MAX_SEARCH_ROUNDS used.
                                Consistently low = novelty gate firing too early.
  4. content_similarity       — mean pairwise similarity between successive final_content
                                values (difflib SequenceMatcher). High = content converging.

When a signal crosses its warning threshold, prints a diagnosis and recommends
an intervention. Interventions are advisory only — the supervisor does not modify
pipeline behaviour yet.

Usage:
    python supervisor.py              # analyze last 20 runs
    python supervisor.py --n 30       # analyze last N runs
    python supervisor.py --json       # machine-readable output
    python supervisor.py --task-type research   # filter to one task type
"""

import sys
import math
import argparse
from difflib import SequenceMatcher
from datetime import datetime, timezone

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from harness.utils import load_runs, safe_mean, safe_stddev  # noqa: E402

MAX_SEARCH_ROUNDS = 5   # must match agent.py

# ---------------------------------------------------------------------------
# Warning thresholds
# ---------------------------------------------------------------------------
THRESHOLDS = {
    "wiggum_score_variance": {
        "warn":  0.5,   # std dev below this → evaluator not differentiating
        "label": "Wiggum score variance",
        "unit":  "σ",
        "low_is_bad": True,
    },
    "output_size_cv": {
        "warn":  0.10,  # CV below this → outputs converging in size
        "label": "Output size CV (std/mean)",
        "unit":  "",
        "low_is_bad": True,
    },
    "search_utilization": {
        "warn":  0.45,  # below this → saturating at ≤ 2/5 rounds consistently
        "label": "Search utilization (rounds used / max)",
        "unit":  "",
        "low_is_bad": True,
    },
    "content_similarity": {
        "warn":  0.65,  # above this → successive outputs too similar
        "label": "Content similarity (sequential pairs)",
        "unit":  "",
        "low_is_bad": False,
    },
}

INTERVENTIONS = {
    "wiggum_score_variance": [
        "Rotate the wiggum rubric — add a novelty-biased evaluator 1-in-5 runs",
        "Temporarily lower PASS_THRESHOLD in wiggum.py to accept more diverse outputs",
        "Add a /deep or higher-temperature synthesis pass to surface different angles",
    ],
    "output_size_cv": [
        "Vary num_predict across runs (e.g. 4096 → 8192 alternating)",
        "Add task-format diversity to the eval suite (T_G / T_H task types)",
        "Check whether SYNTH_INSTRUCTION is forcing uniform structure regardless of task",
    ],
    "search_utilization": [
        "Raise NOVELTY_EPSILON (currently 0.15) to let more sub-threshold rounds through",
        "Lower NOVELTY_THRESHOLD from 3 to 2 to require stronger saturation before stopping",
        "Expand eval tasks to include topics where current knowledge_state is sparse",
    ],
    "content_similarity": [
        "Drop memory influence for 1-in-N runs (skip memory.get_context())",
        "Rotate compression prompts in compress_and_store() to avoid schema lock-in",
        "Add raw excerpt memory alongside compressed summaries in memory.py",
    ],
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load(n: int, task_type_filter: str = None) -> list[dict]:
    return load_runs(n=n, task_type=task_type_filter)


# ---------------------------------------------------------------------------
# Signal computations
# ---------------------------------------------------------------------------


def compute_wiggum_score_variance(runs: list[dict]) -> dict:
    """Std dev of final wiggum scores across runs that used the eval loop."""
    eligible = [r for r in runs if r.get("wiggum_scores")]
    if len(eligible) < 3:
        return {"value": float("nan"), "n": len(eligible), "note": "fewer than 3 wiggum runs"}
    final_scores = [r["wiggum_scores"][-1] for r in eligible]
    revision_deltas = []
    for r in eligible:
        scores = r["wiggum_scores"]
        if len(scores) >= 2:
            revision_deltas.append(scores[-1] - scores[0])
    result = {
        "value": safe_stddev(final_scores),
        "n": len(eligible),
        "mean_final_score": safe_mean(final_scores),
        "mean_revision_delta": safe_mean(revision_deltas) if revision_deltas else float("nan"),
    }
    return result


def compute_output_size_cv(runs: list[dict]) -> dict:
    """Coefficient of variation of output_bytes across research runs."""
    eligible = [r for r in runs if (r.get("output_bytes") or 0) > 0
                and r.get("task_type") not in ("email", "github", "review", "recall", "queue")]
    if len(eligible) < 3:
        return {"value": float("nan"), "n": len(eligible), "note": "fewer than 3 eligible runs"}
    sizes = [r["output_bytes"] for r in eligible]
    mean  = safe_mean(sizes)
    cv    = safe_stddev(sizes) / mean if mean > 0 else float("nan")
    return {"value": cv, "n": len(eligible), "mean_bytes": mean}


def compute_search_utilization(runs: list[dict]) -> dict:
    """Mean fraction of MAX_SEARCH_ROUNDS used, inferred from total_search_chars."""
    eligible = [r for r in runs
                if r.get("task_type") not in ("email", "github", "review", "recall", "queue", "introspect", "annotate")
                and not r.get("orchestrated")]
    if len(eligible) < 3:
        return {"value": float("nan"), "n": len(eligible), "note": "fewer than 3 search runs"}

    # Proxy: tool_calls that are web searches
    utilizations = []
    for r in eligible:
        tool_calls = r.get("tool_calls", []) or []
        search_calls = [tc for tc in tool_calls if tc.get("tool") == "web_search"]
        n_rounds = len(search_calls) if search_calls else None
        if n_rounds is None:
            # Fallback: estimate from total_search_chars
            chars = r.get("total_search_chars", 0) or 0
            # ~1800 chars/round is SEARCH_QUALITY_FLOOR; cap at MAX_SEARCH_ROUNDS
            n_rounds = min(max(1, chars // 1800), MAX_SEARCH_ROUNDS) if chars > 0 else 1
        utilizations.append(n_rounds / MAX_SEARCH_ROUNDS)

    return {
        "value": safe_mean(utilizations),
        "n": len(eligible),
        "min": min(utilizations),
        "max": max(utilizations),
    }


def compute_content_similarity(runs: list[dict]) -> dict:
    """Mean SequenceMatcher similarity between consecutive final_content values."""
    contents = [r.get("final_content", "") or "" for r in runs if r.get("final_content")]
    if len(contents) < 2:
        return {"value": float("nan"), "n": len(contents), "note": "fewer than 2 runs with content"}
    pairs = []
    for a, b in zip(contents, contents[1:]):
        # Cap at 4000 chars each to keep it fast
        ratio = SequenceMatcher(None, a[:4000], b[:4000]).ratio()
        pairs.append(ratio)
    return {
        "value": safe_mean(pairs),
        "n": len(pairs) + 1,
        "max_pair": max(pairs),
        "min_pair": min(pairs),
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

_ANSI = {
    "red":    "\033[91m",
    "yellow": "\033[93m",
    "green":  "\033[92m",
    "reset":  "\033[0m",
    "bold":   "\033[1m",
}


def _color(text: str, color: str, use_color: bool = True) -> str:
    if not use_color or color not in _ANSI:
        return text
    return f"{_ANSI[color]}{text}{_ANSI['reset']}"


def _signal_status(name: str, result: dict) -> tuple[str, str]:
    """Return (status_label, color)."""
    cfg   = THRESHOLDS[name]
    value = result.get("value", float("nan"))
    if math.isnan(value):
        return "UNKNOWN", "yellow"
    warn  = cfg["warn"]
    low_bad = cfg["low_is_bad"]
    if (low_bad and value < warn) or (not low_bad and value > warn):
        return "WARN", "red"
    return "OK", "green"


def report(runs: list[dict], use_color: bool = True, as_json: bool = False) -> dict:
    signals = {
        "wiggum_score_variance": compute_wiggum_score_variance(runs),
        "output_size_cv":        compute_output_size_cv(runs),
        "search_utilization":    compute_search_utilization(runs),
        "content_similarity":    compute_content_similarity(runs),
    }

    if as_json:
        out = {"runs_analyzed": len(runs), "signals": {}}
        for name, result in signals.items():
            status, _ = _signal_status(name, result)
            out["signals"][name] = {**result, "status": status,
                                    "threshold": THRESHOLDS[name]["warn"]}
        print(json.dumps(out, indent=2))
        return out

    # Human-readable report
    bold  = _ANSI["bold"]  if use_color else ""
    reset = _ANSI["reset"] if use_color else ""

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{bold}=== Supervisor Report  {now}  ({len(runs)} runs analyzed) ==={reset}\n")

    any_warn = False
    for name, result in signals.items():
        cfg    = THRESHOLDS[name]
        status, color = _signal_status(name, result)
        value  = result.get("value", float("nan"))
        note   = result.get("note", "")

        label  = cfg["label"]
        unit   = cfg["unit"]
        val_str = f"{value:.3f}{unit}" if not math.isnan(value) else "n/a"
        thresh  = cfg["warn"]
        status_str = _color(f"[{status}]", color, use_color)

        detail_parts = [f"n={result.get('n', '?')}"]
        for k in ("mean_final_score", "mean_revision_delta", "mean_bytes", "min", "max", "max_pair"):
            if k in result and not math.isnan(result[k]):
                detail_parts.append(f"{k}={result[k]:.2f}")
        if note:
            detail_parts.append(note)
        detail = "  " + ", ".join(detail_parts)

        print(f"  {status_str:20} {label}")
        print(f"             value={val_str}  threshold={thresh}{unit}")
        print(detail)
        print()

        if status == "WARN":
            any_warn = True
            print(f"  {_color('Diagnosis:', 'yellow', use_color)} {name.replace('_', ' ')} is below threshold.")
            for ix, action in enumerate(INTERVENTIONS[name], 1):
                print(f"    {ix}. {action}")
            print()

    if not any_warn:
        print(_color("  All signals within normal range. No intervention needed.", "green", use_color))

    print()
    return {name: {**result, "status": _signal_status(name, result)[0]} for name, result in signals.items()}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Harness convergence monitor")
    parser.add_argument("--n",         type=int, default=20, help="Number of recent runs to analyze")
    parser.add_argument("--json",      action="store_true",  help="Machine-readable JSON output")
    parser.add_argument("--task-type", type=str, default=None, help="Filter to one task_type")
    parser.add_argument("--no-color",  action="store_true",  help="Disable ANSI color")
    args = parser.parse_args()

    runs = _load(args.n, task_type_filter=args.task_type)
    if not runs:
        print(f"[supervisor] no runs found in {RUNS_FILE}")
        sys.exit(1)

    use_color = not args.no_color and sys.stdout.isatty()
    report(runs, use_color=use_color, as_json=args.json)

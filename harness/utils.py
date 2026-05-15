"""
harness/utils.py — shared utilities for runs, stats, text, and display.

Consolidates helpers that were previously duplicated across scripts:
  analytics.py, inspect_run.py, supervisor.py, failure_patterns.py,
  search_analysis.py, wiki_tools.py
"""

from __future__ import annotations

import json
import math
import re
import statistics
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from harness.config import RUNS_FILE

# ---------------------------------------------------------------------------
# Date context
# ---------------------------------------------------------------------------

def current_date_context() -> str:
    """Return a one-line date string for injection into LLM prompts."""
    now = datetime.now(UTC)
    return f"Current date: {now.strftime('%Y-%m-%d')} (year: {now.year})"


# ---------------------------------------------------------------------------
# Run loading
# ---------------------------------------------------------------------------

def iter_runs(path: Path | str | None = None) -> Iterator[dict]:
    """Yield parsed run dicts from runs.jsonl, skipping malformed lines."""
    src = Path(path) if path else RUNS_FILE
    if not src.exists():
        return
    with src.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    pass


def load_runs(
    n: int | None = None,
    task_type: str | None = None,
    final: str | None = None,
    path: Path | str | None = None,
) -> list[dict]:
    """
    Load runs from runs.jsonl with optional filters.

    Args:
        n:         Return only the last N matching runs.
        task_type: Filter to runs with this task_type.
        final:     Filter to runs with this final status ('PASS', 'FAIL', 'ERROR').
        path:      Override the default RUNS_FILE path.
    """
    runs = list(iter_runs(path))
    if task_type:
        runs = [r for r in runs if r.get("task_type") == task_type]
    if final:
        runs = [r for r in runs if r.get("final") == final]
    return runs[-n:] if n else runs


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

_TS_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%f+00:00",
    "%Y-%m-%dT%H:%M:%S+00:00",
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
)


def parse_ts(ts: str) -> datetime | None:
    """Parse an ISO 8601 timestamp string to a UTC-aware datetime. Returns None on failure."""
    if not ts:
        return None
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(ts[: len(fmt) + 2], fmt).replace(tzinfo=UTC)
        except ValueError:
            pass
    return None


def fmt_ts(ts: str, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Format a run timestamp string for display. Returns raw slice on parse failure."""
    dt = parse_ts(ts)
    return dt.strftime(fmt) if dt else ts[:16]


# ---------------------------------------------------------------------------
# Basic statistics
# ---------------------------------------------------------------------------

def safe_mean(values: list[float]) -> float:
    return statistics.mean(values) if values else float("nan")


def safe_stddev(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) >= 2 else float("nan")


def mean_sd(values: list[float]) -> tuple[float, float]:
    """Return (mean, std_dev). Returns (0.0, 0.0) for empty input."""
    if not values:
        return 0.0, 0.0
    m = statistics.mean(values)
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    return m, sd


def correlation(xs: list[float], ys: list[float]) -> float:
    """Pearson r. Returns nan if fewer than 3 pairs or zero variance."""
    if len(xs) < 3:
        return float("nan")
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(
        sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)
    )
    return num / den if den else float("nan")


# ---------------------------------------------------------------------------
# Text / NLP helpers
# ---------------------------------------------------------------------------

STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "can", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "or", "and", "but", "not",
    "no", "it", "its", "this", "that", "these", "those", "there", "their",
    "they", "we", "i", "you", "he", "she", "what", "which", "who", "how",
    "when", "where", "if", "than", "then", "so", "also", "only", "more",
    "any", "all", "each", "both", "about", "into", "through", "during",
    "before", "after", "above", "below", "between", "out", "off", "over",
    "under", "just", "because", "while", "although", "however", "though",
    # search-specific stopwords
    "best", "top", "use", "using", "based", "include", "includes", "including",
    "example", "examples", "different", "most", "ai", "llm", "model", "models",
})


def normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text: str, stop: frozenset[str] | None = None) -> list[str]:
    """Lowercase word tokens ≥3 chars, excluding stopwords."""
    sw = stop if stop is not None else STOPWORDS
    return [w for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in sw]


def keywords(text: str) -> set[str]:
    """Unigram + bigram keyword set for similarity/clustering."""
    tokens = tokenize(text)
    unigrams = set(tokens)
    bigrams = {f"{tokens[i]}_{tokens[i+1]}" for i in range(len(tokens) - 1)}
    return unigrams | bigrams


def jaccard(a: set, b: set) -> float:
    """Jaccard similarity between two sets. Returns 0 if both empty."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def top_terms(texts: list[str], n: int = 20) -> list[tuple[str, int]]:
    """Most common tokens across a list of texts."""
    counter: Counter = Counter()
    for t in texts:
        counter.update(tokenize(t))
    return counter.most_common(n)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def bar(value: float, max_val: float, width: int = 30, char: str = "#") -> str:
    """ASCII progress bar."""
    filled = int(round(value / max_val * width)) if max_val else 0
    return char * filled + "." * (width - filled)


def week_label(dt: datetime) -> str:
    """ISO week label, e.g. '2026-W18'."""
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


# ---------------------------------------------------------------------------
# Run inspection / pretty-print
# ---------------------------------------------------------------------------

def fmt_stage(stage: str, vals: dict) -> str:
    return (
        f"    {stage:<16}  "
        f"in={vals.get('input', 0):>5}  "
        f"out={vals.get('output', 0):>5}  "
        f"calls={vals.get('calls', 0)}  "
        f"ms={vals.get('total_ms', 0):.0f}"
    )


def print_run(d: dict, idx: int | None = None) -> None:
    label = f"Run {idx}" if idx is not None else "Run"
    print(f"\n{'='*60}")
    print(f" {label}: {fmt_ts(d.get('timestamp', ''))}")
    print(f"  task:     {d.get('task', '')[:70]}")
    print(f"  producer: {d.get('producer_model', '?')}  evaluator: {d.get('evaluator_model', '?')}")
    print(f"  type:     {d.get('task_type', '?')}  final: {d.get('final', '?')}  "
          f"duration: {d.get('run_duration_s', '?')}s")
    print(f"  tokens:   in={d.get('input_tokens', 0)}  out={d.get('output_tokens', 0)}")
    stages = d.get("tokens_by_stage") or {}
    if stages:
        print("  by stage:")
        for s, v in stages.items():
            print(fmt_stage(s, v))
    scores = d.get("wiggum_scores") or []
    print(f"  wiggum:   rounds={d.get('wiggum_rounds', 0)}  scores={scores}")
    dims = d.get("wiggum_dims") or []
    for i, dim in enumerate(dims):
        ds = "  ".join(f"{k[:3]}={v}" for k, v in dim.items())
        print(f"    round {i+1}: [{ds}]")
    print(f"  output:   {d.get('output_path', '?')}  "
          f"({d.get('output_bytes', '?')} bytes, {d.get('output_lines', '?')} lines)")


def summary_table(runs: list[dict]) -> None:
    """Print a compact tabular summary of a list of runs."""
    print(f"\n{'#':<4} {'timestamp':<20} {'type':<12} {'final':<6} "
          f"{'dur(s)':<8} {'in_tok':<8} {'out_tok':<8} {'scores'}")
    for i, d in enumerate(runs):
        ts    = fmt_ts(d.get("timestamp", ""))
        ttype = (d.get("task_type") or "")[:11]
        final = (d.get("final") or "?")
        dur   = d.get("run_duration_s", "?")
        tin   = d.get("input_tokens", 0)
        tout  = d.get("output_tokens", 0)
        ws    = d.get("wiggum_scores") or []
        print(f"{i+1:<4} {ts:<20} {ttype:<12} {final:<6} "
              f"{str(dur):<8} {tin:<8} {tout:<8} {ws}")


def print_summary(runs: list[dict]) -> None:
    """Print aggregate analytics for a list of runs."""
    total  = len(runs)
    if not total:
        print("No runs.")
        return
    passed = sum(1 for r in runs if r.get("final") == "PASS")
    errors = sum(1 for r in runs if r.get("final") == "ERROR")
    floor  = sum(1 for r in runs if r.get("quality_floor_hit"))

    def _avg(lst, key):
        vals = [r.get(key) for r in lst if r.get(key) is not None]
        return round(safe_mean(vals), 1) if vals else "n/a"

    def _avg_score(lst):
        scores = [r["wiggum_scores"][0] for r in lst if r.get("wiggum_scores")]
        return round(safe_mean(scores), 1) if scores else "n/a"

    dual   = [r for r in runs if len(r.get("tool_calls") or []) >= 2]
    single = [r for r in runs if len(r.get("tool_calls") or []) == 1]

    print(f"\n{'='*42}")
    print(" Pipeline Analytics")
    print(f"{'='*42}")
    print(f"  Total runs     : {total}")
    print(f"  PASS           : {passed}  ({round(passed/total*100)}%)")
    print(f"  ERROR          : {errors}")
    print(f"  Quality floor  : {floor} hits")
    print()
    print(f"  {'':20}  {'single':>8}  {'dual':>8}")
    print(f"  {'':20}  {'------':>8}  {'------':>8}")
    print(f"  {'runs':20}  {len(single):>8}  {len(dual):>8}")
    print(f"  {'avg output bytes':20}  {_avg(single, 'output_bytes'):>8}  {_avg(dual, 'output_bytes'):>8}")
    print(f"  {'avg output lines':20}  {_avg(single, 'output_lines'):>8}  {_avg(dual, 'output_lines'):>8}")
    print(f"  {'avg 1st wiggum':20}  {_avg_score(single):>8}  {_avg_score(dual):>8}")
    print(f"{'='*42}\n")


# ---------------------------------------------------------------------------
# Wiggum issue extraction  (used by failure_patterns.py)
# ---------------------------------------------------------------------------

def load_issues(path: Path | str | None = None) -> list[dict]:
    """
    Extract every wiggum issue string from runs.jsonl.
    Returns list of {issue, task, task_type, score, timestamp}.
    """
    records = []
    for r in iter_runs(path):
        task      = r.get("task", "")
        task_type = r.get("task_type") or "unknown"
        ts        = r.get("timestamp", "")
        for rd in (r.get("wiggum_eval_log") or []):
            score  = rd.get("score")
            for iss in (rd.get("issues") or []):
                if isinstance(iss, str) and iss.strip():
                    records.append({
                        "issue":     iss.strip(),
                        "task":      task[:80],
                        "task_type": task_type,
                        "score":     score,
                        "timestamp": ts[:10],
                    })
    return records


# ---------------------------------------------------------------------------
# Search call extraction  (used by search_analysis.py)
# ---------------------------------------------------------------------------

def extract_searches(runs: list[dict]) -> list[dict]:
    """Flatten all web_search tool calls into dicts with run metadata."""
    rows = []
    for r in runs:
        ts        = parse_ts(r.get("timestamp", ""))
        score     = (r.get("wiggum_scores") or [None])[0]
        model     = r.get("producer_model", "unknown")
        task_type = r.get("task_type", "")
        run_id    = r.get("run_id", "")
        n_search  = sum(1 for tc in (r.get("tool_calls") or [])
                        if tc.get("name") == "web_search")
        for tc in (r.get("tool_calls") or []):
            if tc.get("name") != "web_search":
                continue
            rows.append({
                "ts":           ts,
                "run_id":       run_id,
                "query":        tc.get("query", ""),
                "result_chars": tc.get("result_chars", 0),
                "score_r1":     score,
                "model":        model,
                "task_type":    task_type,
                "n_in_run":     n_search,
                "total_search_chars": r.get("total_search_chars", 0),
                "wiggum_rounds": r.get("wiggum_rounds", 0),
                "final":        r.get("final", ""),
            })
    rows.sort(key=lambda x: x["ts"] or datetime.min.replace(tzinfo=UTC))
    return rows

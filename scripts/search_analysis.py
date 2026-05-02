"""
search_analysis.py — chronological analysis of agentic search activity.

Reads runs.jsonl and produces:
  1. Overall search volume over time (by session week)
  2. Query topic evolution (sliding term-frequency windows)
  3. Search efficiency: result_chars vs wiggum score_r1
  4. Query specificity drift (query length as proxy)
  5. Per-model search behaviour
  6. Top repeated queries (what the agent keeps asking)
  7. Search yield distribution (chars returned per query)

Usage:
    python search_analysis.py [--out report.md] [--top-terms 15] [--weeks 4]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

_BASE = Path(__file__).parent
_RUNS = _BASE / "runs.jsonl"

# ── Stopwords ─────────────────────────────────────────────────────────────────
_STOP = {
    "the", "a", "an", "and", "or", "of", "in", "for", "to", "on", "with",
    "how", "what", "are", "is", "do", "does", "can", "use", "using",
    "best", "top", "3", "5", "10", "2", "4", "ai", "llm", "model", "models",
    "based", "from", "that", "this", "it", "by", "at", "as", "be", "vs",
    "when", "which", "have", "has", "been", "will", "would", "could", "should",
    "most", "more", "than", "into", "over", "about", "through", "between",
    "include", "includes", "including", "example", "examples", "different",
}


# ── Data loading ──────────────────────────────────────────────────────────────

def load_runs() -> list[dict]:
    runs = []
    with open(_RUNS, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    runs.append(json.loads(line))
                except Exception:
                    pass
    return runs


def parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f+00:00", "%Y-%m-%dT%H:%M:%S+00:00",
                "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(ts[:26], fmt[:len(ts[:26])]).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def extract_searches(runs: list[dict]) -> list[dict]:
    """Flatten all web_search tool calls into a list of dicts with run metadata."""
    rows = []
    for r in runs:
        ts = parse_ts(r.get("timestamp", ""))
        score = (r.get("wiggum_scores") or [None])[0]
        model = r.get("producer_model", "unknown")
        task_type = r.get("task_type", "")
        session = r.get("session_id", "")
        run_id = r.get("run_id", "")
        n_search_calls = sum(1 for tc in (r.get("tool_calls") or [])
                             if tc.get("name") == "web_search")
        for tc in (r.get("tool_calls") or []):
            if tc.get("name") != "web_search":
                continue
            rows.append({
                "ts":          ts,
                "run_id":      run_id,
                "session":     session,
                "query":       tc.get("query", ""),
                "result_chars": tc.get("result_chars", 0),
                "score_r1":    score,
                "model":       model,
                "task_type":   task_type,
                "n_in_run":    n_search_calls,
                "total_search_chars": r.get("total_search_chars", 0),
                "wiggum_rounds": r.get("wiggum_rounds", 0),
                "final":       r.get("final", ""),
            })
    rows.sort(key=lambda x: x["ts"] or datetime.min.replace(tzinfo=timezone.utc))
    return rows


# ── Helpers ───────────────────────────────────────────────────────────────────

def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z]{3,}", text.lower())
    return [w for w in words if w not in _STOP]


def week_label(ts: datetime) -> str:
    iso = ts.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def bar(value: float, max_val: float, width: int = 30, char: str = "#") -> str:
    filled = int(round(value / max_val * width)) if max_val else 0
    return char * filled + "." * (width - filled)


def mean_sd(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    m = statistics.mean(values)
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    return m, sd


def correlation(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 3:
        return float("nan")
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return num / den if den else float("nan")


# ── Analysis sections ─────────────────────────────────────────────────────────

def section_volume(searches: list[dict]) -> str:
    by_week: dict[str, int] = defaultdict(int)
    by_week_chars: dict[str, int] = defaultdict(int)
    for s in searches:
        if not s["ts"]:
            continue
        wk = week_label(s["ts"])
        by_week[wk] += 1
        by_week_chars[wk] += s["result_chars"]

    weeks = sorted(by_week)
    max_q = max(by_week.values()) if by_week else 1

    lines = ["## 1. Search Volume Over Time\n"]
    lines.append(f"{'Week':<12} {'Queries':>7}  {'Chars (K)':>9}  {'':30}")
    lines.append("-" * 65)
    for wk in weeks:
        q = by_week[wk]
        c = by_week_chars[wk] // 1000
        lines.append(f"{wk:<12} {q:>7}  {c:>9}  {bar(q, max_q)}")

    total_q = sum(by_week.values())
    total_c = sum(by_week_chars.values())
    lines.append(f"\n**Total:** {total_q} queries across {len(weeks)} weeks  |  "
                 f"{total_c/1_000_000:.2f}M chars retrieved")
    return "\n".join(lines)


def section_topic_evolution(searches: list[dict], top_n: int = 15, n_windows: int = 4) -> str:
    """Split timeline into n_windows equal chunks, show top terms per window."""
    dated = [s for s in searches if s["ts"]]
    if not dated:
        return "## 2. Topic Evolution\n(no dated searches)"

    ts_sorted = sorted(dated, key=lambda x: x["ts"])
    chunk = max(1, len(ts_sorted) // n_windows)
    lines = ["## 2. Topic Evolution (term frequency by time window)\n"]

    all_window_terms: list[Counter] = []
    window_labels = []

    for i in range(n_windows):
        start = i * chunk
        end = (i + 1) * chunk if i < n_windows - 1 else len(ts_sorted)
        window = ts_sorted[start:end]
        if not window:
            continue
        t0 = window[0]["ts"].strftime("%Y-%m-%d")
        t1 = window[-1]["ts"].strftime("%Y-%m-%d")
        label = f"W{i+1} ({t0} → {t1}, n={len(window)})"
        window_labels.append(label)
        tf: Counter = Counter()
        for s in window:
            tf.update(tokenize(s["query"]))
        all_window_terms.append(tf)

    # Find terms that appear in at least 2 windows for the evolution table
    all_terms: set[str] = set()
    for tf in all_window_terms:
        all_terms.update(t for t, _ in tf.most_common(top_n))

    for i, (label, tf) in enumerate(zip(window_labels, all_window_terms)):
        lines.append(f"### {label}")
        top = tf.most_common(top_n)
        max_c = top[0][1] if top else 1
        for term, count in top:
            lines.append(f"  {term:<28} {count:>3}  {bar(count, max_c, 20)}")
        lines.append("")

    return "\n".join(lines)


def section_efficiency(searches: list[dict]) -> str:
    """Correlate per-run search volume with score."""
    # Aggregate by run_id
    runs_agg: dict[str, dict] = {}
    for s in searches:
        rid = s["run_id"]
        if rid not in runs_agg:
            runs_agg[rid] = {
                "queries": 0, "total_chars": 0,
                "score": s["score_r1"], "model": s["model"],
                "rounds": s["wiggum_rounds"],
            }
        runs_agg[rid]["queries"] += 1
        runs_agg[rid]["total_chars"] += s["result_chars"]

    scored = [v for v in runs_agg.values() if v["score"] is not None]
    if not scored:
        return "## 3. Search Efficiency\n(no scored runs)"

    xs_q = [v["queries"] for v in scored]
    ys   = [v["score"]   for v in scored]
    xs_c = [v["total_chars"] / 1000 for v in scored]

    r_q = correlation(xs_q, ys)
    r_c = correlation(xs_c, ys)

    # Bucket by query count
    buckets: dict[str, list[float]] = defaultdict(list)
    for v in scored:
        q = v["queries"]
        key = f"{q:2d} queries"
        buckets[key].append(v["score"])

    lines = ["## 3. Search Efficiency (queries → score)\n"]
    lines.append(f"Pearson r(n_queries, score_r1) = **{r_q:+.3f}**")
    lines.append(f"Pearson r(total_chars_K, score_r1) = **{r_c:+.3f}**\n")
    lines.append(f"{'Queries/run':<12} {'n':>4}  {'score mean±sd':>14}  {'dist':20}")
    lines.append("-" * 60)

    score_mean_all = statistics.mean(ys)
    for key in sorted(buckets):
        scores = buckets[key]
        m, sd = mean_sd(scores)
        delta = m - score_mean_all
        lines.append(f"{key:<12} {len(scores):>4}  {m:>6.2f} ± {sd:<5.2f}  "
                     f"{'^' if delta > 0 else 'v'}{abs(delta):.2f} vs mean")

    # Yield distribution
    yields = [s["result_chars"] for s in searches if s["result_chars"] > 0]
    if yields:
        lines.append(f"\n**Query yield:** mean={statistics.mean(yields):.0f} chars  "
                     f"median={statistics.median(yields):.0f}  "
                     f"p90={sorted(yields)[int(len(yields)*0.9)]}")

    return "\n".join(lines)


def section_specificity(searches: list[dict]) -> str:
    """Track query length (word count) over time as specificity proxy."""
    dated = [s for s in searches if s["ts"]]
    if not dated:
        return "## 4. Query Specificity\n(no dated searches)"

    ts_sorted = sorted(dated, key=lambda x: x["ts"])
    n_windows = 8
    chunk = max(1, len(ts_sorted) // n_windows)

    lines = ["## 4. Query Specificity Over Time (word count proxy)\n"]
    lines.append(f"{'Window':<8} {'Period':<24} {'n':>4}  {'words mean':>10}  trend")
    lines.append("-" * 65)

    prev_mean = None
    for i in range(n_windows):
        start = i * chunk
        end = (i + 1) * chunk if i < n_windows - 1 else len(ts_sorted)
        window = ts_sorted[start:end]
        if not window:
            continue
        t0 = window[0]["ts"].strftime("%m-%d")
        t1 = window[-1]["ts"].strftime("%m-%d")
        lengths = [len(s["query"].split()) for s in window]
        m = statistics.mean(lengths)
        trend = ""
        if prev_mean is not None:
            diff = m - prev_mean
            trend = f"{'^' if diff > 0 else 'v'}{abs(diff):.1f}"
        lines.append(f"W{i+1:<6}  {t0}→{t1:<18}  {len(window):>4}  {m:>10.1f}  {trend}")
        prev_mean = m

    all_lengths = [len(s["query"].split()) for s in ts_sorted]
    lines.append(f"\n**Overall:** mean={statistics.mean(all_lengths):.1f} words/query  "
                 f"range={min(all_lengths)}–{max(all_lengths)}")
    return "\n".join(lines)


def section_by_model(searches: list[dict]) -> str:
    by_model: dict[str, list[dict]] = defaultdict(list)
    for s in searches:
        by_model[s["model"]].append(s)

    lines = ["## 5. Search Behaviour by Model\n"]
    lines.append(f"{'Model':<28} {'queries':>7}  {'q/run':>5}  {'chars/q':>8}  {'score mean':>10}")
    lines.append("-" * 70)

    for model, ss in sorted(by_model.items(), key=lambda x: -len(x[1])):
        n = len(ss)
        runs_seen = len({s["run_id"] for s in ss})
        q_per_run = n / runs_seen if runs_seen else 0
        chars_per_q = statistics.mean(s["result_chars"] for s in ss)
        scores = [s["score_r1"] for s in ss if s["score_r1"] is not None]
        score_str = f"{statistics.mean(scores):.2f}" if scores else "n/a"
        lines.append(f"{model:<28} {n:>7}  {q_per_run:>5.1f}  {chars_per_q:>8.0f}  {score_str:>10}")

    return "\n".join(lines)


def section_top_queries(searches: list[dict], top_n: int = 25) -> str:
    counter: Counter = Counter(s["query"].strip().lower() for s in searches)
    lines = ["## 6. Top Repeated Queries\n"]
    lines.append(f"{'#':>3}  {'Count':>5}  Query")
    lines.append("-" * 80)
    for i, (q, c) in enumerate(counter.most_common(top_n), 1):
        lines.append(f"{i:>3}  {c:>5}  {q[:75]}")

    unique = sum(1 for _, c in counter.items() if c == 1)
    lines.append(f"\n**{len(counter)} unique queries** ({unique} seen once, "
                 f"{len(counter)-unique} repeated)")
    return "\n".join(lines)


def section_zero_yield(searches: list[dict]) -> str:
    """Queries that returned ≤100 chars — likely failed or blocked searches."""
    zero = [s for s in searches if s["result_chars"] <= 100]
    if not zero:
        return "## 7. Zero-Yield Queries\nNone — all queries returned results."

    by_model: Counter = Counter(s["model"] for s in zero)
    lines = [f"## 7. Zero-Yield Queries (≤100 chars returned)\n",
             f"**{len(zero)} / {len(searches)}** queries ({100*len(zero)/len(searches):.1f}%) returned ≤100 chars\n",
             f"By model: {dict(by_model.most_common())}\n",
             "\nSample zero-yield queries:"]
    for s in zero[:10]:
        ts = s["ts"].strftime("%Y-%m-%d") if s["ts"] else "?"
        lines.append(f"  [{ts}] {s['query'][:70]}")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="", help="Save report to this .md file")
    parser.add_argument("--top-terms", type=int, default=15)
    parser.add_argument("--windows", type=int, default=4,
                        help="Number of time windows for topic evolution")
    args = parser.parse_args()

    runs = load_runs()
    searches = extract_searches(runs)

    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print(f"[search_analysis] {len(runs)} runs loaded, {len(searches)} web_search calls\n")

    sections = [
        f"# Agentic Search Activity Analysis\n\n"
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  \n"
        f"Runs: {len(runs)}  |  Web searches: {len(searches)}  |  "
        f"Runs with search: {len({s['run_id'] for s in searches})}\n",

        section_volume(searches),
        section_topic_evolution(searches, top_n=args.top_terms, n_windows=args.windows),
        section_efficiency(searches),
        section_specificity(searches),
        section_by_model(searches),
        section_top_queries(searches),
        section_zero_yield(searches),
    ]

    report = "\n\n---\n\n".join(sections)
    print(report)

    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"\n[search_analysis] report saved to {args.out}")


if __name__ == "__main__":
    main()

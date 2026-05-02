"""
failure_patterns.py — Aggregate wiggum issues across runs.jsonl and write
a ranked failure pattern report to wiki/failure-patterns.md.

Clustering strategy: keyword/phrase fingerprinting — no LLM, no embeddings.
Each issue is normalised, tokenised into bigrams, then grouped by overlapping
bigram sets. Groups are ranked by frequency and presented with representative
examples.

Usage:
    python failure_patterns.py              # write wiki/failure-patterns.md
    python failure_patterns.py --print      # print to stdout instead
    python failure_patterns.py --min-count 3  # only show clusters seen 3+ times
"""

import sys
import re
import argparse
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harness.utils import load_issues, keywords as _keywords, jaccard  # noqa: E402

HERE     = Path(__file__).parent
WIKI_OUT = HERE / "wiki" / "failure-patterns.md"


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def cluster_issues(records: list[dict], threshold: float = 0.15) -> list[dict]:
    """
    Greedy single-linkage clustering by Jaccard similarity on keyword sets.
    Returns list of cluster dicts sorted by size descending.
    """
    kw_sets = [_keywords(r["issue"]) for r in records]
    labels  = [-1] * len(records)
    next_label = 0

    for i in range(len(records)):
        if labels[i] != -1:
            continue
        labels[i] = next_label
        for j in range(i + 1, len(records)):
            if labels[j] != -1:
                continue
            if jaccard(kw_sets[i], kw_sets[j]) >= threshold:
                labels[j] = next_label
        next_label += 1

    clusters = defaultdict(list)
    for idx, label in enumerate(labels):
        clusters[label].append(records[idx])

    # Sort clusters by size descending
    result = sorted(clusters.values(), key=len, reverse=True)
    return result


def _representative(cluster: list[dict]) -> str:
    """Pick the shortest issue string as the cluster representative."""
    return min(cluster, key=lambda r: len(r["issue"]))["issue"]


def _most_common_task_type(cluster: list[dict]) -> str:
    counts = defaultdict(int)
    for r in cluster:
        counts[r["task_type"]] += 1
    return max(counts, key=counts.get)


def _avg_score(cluster: list[dict]) -> float | None:
    scores = [r["score"] for r in cluster if r["score"] is not None]
    return round(sum(scores) / len(scores), 1) if scores else None


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

PREAMBLE = """\
# Failure Pattern Analysis

Auto-generated from `runs.jsonl` wiggum evaluation issues.
Clusters built by keyword/bigram Jaccard similarity (threshold 0.15).

> Re-run: `python failure_patterns.py`

Generated: {date}  |  Total issues analysed: {total}  |  Clusters found: {clusters}

---

"""

CLUSTER_TMPL = """\
## {rank}. {representative} *(×{count})*

| | |
|---|---|
| **Occurrences** | {count} |
| **Avg wiggum score** | {avg_score} |
| **Most common task type** | {task_type} |

**Representative examples:**
{examples}

---

"""


def build_report(clusters: list[dict], total_issues: int, min_count: int = 2) -> str:
    filtered = [c for c in clusters if len(c) >= min_count]
    sections = [PREAMBLE.format(
        date=datetime.now().strftime("%Y-%m-%d"),
        total=total_issues,
        clusters=len(filtered),
    )]

    for rank, cluster in enumerate(filtered, 1):
        # Up to 3 distinct example issues
        seen = set()
        examples = []
        for r in cluster:
            key = _normalise(r["issue"])[:60]
            if key not in seen:
                seen.add(key)
                examples.append(f"- {r['issue']}")
            if len(examples) >= 3:
                break

        avg = _avg_score(cluster)
        sections.append(CLUSTER_TMPL.format(
            rank=rank,
            representative=_representative(cluster)[:120],
            count=len(cluster),
            avg_score=f"{avg}/10" if avg is not None else "n/a",
            task_type=_most_common_task_type(cluster),
            examples="\n".join(examples),
        ))

    return "".join(sections)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--print",     action="store_true", help="Print to stdout instead of writing file")
    parser.add_argument("--min-count", type=int, default=2, help="Minimum cluster size to include (default: 2)")
    parser.add_argument("--threshold", type=float, default=0.15, help="Jaccard similarity threshold (default: 0.15)")
    args = parser.parse_args()

    print(f"Loading issues from {RUNS_PATH.name}...")
    records = load_issues()
    print(f"  {len(records)} issues extracted from {RUNS_PATH.name}")

    if not records:
        print("No issues found — nothing to cluster.")
        return

    print("Clustering...")
    clusters = cluster_issues(records, threshold=args.threshold)
    print(f"  {len(clusters)} clusters found (>= {args.min_count} occurrences: "
          f"{sum(1 for c in clusters if len(c) >= args.min_count)})")

    report = build_report(clusters, len(records), min_count=args.min_count)

    if args.print:
        print("\n" + report)
    else:
        WIKI_OUT.write_text(report, encoding="utf-8")
        print(f"Written -> {WIKI_OUT}")
        # Print top 5 cluster summaries
        print("\nTop failure patterns:")
        for i, c in enumerate(clusters[:5], 1):
            if len(c) < args.min_count:
                break
            print(f"  {i}. ({len(c)}x) {_representative(c)[:100]}")


if __name__ == "__main__":
    main()

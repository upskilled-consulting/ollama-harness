"""
curator.py — Persona-based paper filter for fine-tuning dataset curation.

Runs each annotated paper through 5 LLM personas. Papers that don't earn
sufficient collective approval are excluded from the training dataset.

Personas:
  1. Pragmatic Engineer    — values actionable implementation insights
  2. Academic Rigorist     — values methodological soundness + evidence quality
  3. Synthesis Thinker     — values cross-paper connectivity + conceptual clarity
  4. Contrarian            — looks for oversold claims, trivial contributions
  5. Newcomer              — values accessibility + field-entry value

Scoring:
  - Each persona scores 1–5 (5 = strong keep, 1 = strong reject)
  - Paper passes if: mean >= MEAN_THRESHOLD and no score < VETO_FLOOR
  - Default: mean >= 3.5, veto floor = 2

Usage:
    python curator.py                                   # curate all *_annotated.csv files
    python curator.py --input arxiv_agentic_papers_annotated.csv
    python curator.py --mean-threshold 3.0 --veto-floor 1  # lenient
    python curator.py --dry-run                         # score only, no output files
    python curator.py --stats                           # show pass/fail counts from existing log

Output:
    arxiv_*_curated.csv     — filtered rows (same columns as input)
    curation_log.jsonl      — per-paper decisions with per-persona scores and reasons
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

from harness.inference import chat as _llm_chat

HERE = Path(__file__).parent

_KEEP_ALIVE    = int(os.environ.get("OLLAMA_KEEP_ALIVE", -1))
_DEFAULT_MODEL = os.environ.get("CURATOR_MODEL", os.environ.get("PRODUCER_MODEL", "llama3.2:3b"))

LOG_PATH = HERE / "data" / "curation_log.jsonl"

MEAN_THRESHOLD = 3.5
VETO_FLOOR     = 2

# ---------------------------------------------------------------------------
# Personas
# ---------------------------------------------------------------------------

PERSONAS = [
    {
        "name": "Pragmatic Engineer",
        "system": (
            "You are a senior software engineer evaluating whether a research paper annotation "
            "is worth including in a fine-tuning dataset for an AI research assistant. "
            "You care about one thing: does this paper offer concrete, actionable implementation "
            "insights that a practitioner could use? Overly theoretical papers with no practical "
            "pathway score low. Papers with specific methods, architectures, or techniques a "
            "developer could implement score high."
        ),
    },
    {
        "name": "Academic Rigorist",
        "system": (
            "You are a research scientist evaluating whether a research paper annotation "
            "is worth including in a fine-tuning dataset for an AI research assistant. "
            "You care about methodological soundness: are claims backed by experiments? "
            "Are baselines reasonable? Is evidence clearly presented? "
            "Papers with vague claims or missing evaluation score low. "
            "Papers with clear methodology and honest limitations score high."
        ),
    },
    {
        "name": "Synthesis Thinker",
        "system": (
            "You are a knowledge architect evaluating whether a research paper annotation "
            "is worth including in a fine-tuning dataset for an AI research assistant. "
            "You care about connectivity: does this paper introduce a concept, technique, "
            "or finding that connects meaningfully to the broader landscape of AI agent research? "
            "Narrow or incremental papers with little cross-paper relevance score low. "
            "Papers that introduce transferable ideas score high."
        ),
    },
    {
        "name": "Contrarian",
        "system": (
            "You are a skeptical reviewer evaluating whether a research paper annotation "
            "is worth including in a fine-tuning dataset for an AI research assistant. "
            "Your job is to push back: is the contribution actually novel, or is it "
            "incremental? Is the paper overselling minor results? Is the problem it solves "
            "real and important, or manufactured? "
            "Papers that overclaim or address trivial problems score low. "
            "Only genuinely novel, well-scoped contributions score high from you."
        ),
    },
    {
        "name": "Newcomer",
        "system": (
            "You are an ML student trying to break into AI agent research, evaluating "
            "whether a research paper annotation is worth including in a dataset for "
            "an AI research assistant you will use. "
            "You care about whether reading this paper would meaningfully help you "
            "understand important concepts, patterns, or open problems in the field. "
            "Highly specialised or prerequisite-heavy papers score low for you. "
            "Papers that illuminate a key idea or problem clearly score high."
        ),
    },
]

_SCORE_PROMPT = """\
Paper title: {title}

Annotation:
{annotation}

{topic_line}Rate this paper's value for inclusion.

Respond with EXACTLY two lines:
SCORE: <integer 1-5>
REASON: <one sentence explaining your score>

Do not add any other text.\
"""


# ---------------------------------------------------------------------------
# Markdown abstract loader (reused from build_finetune_from_annotations.py)
# ---------------------------------------------------------------------------

def _load_abstracts() -> dict[str, str]:
    """Return {arxiv_id: abstract_text} from all arxiv_*.md files."""
    abstracts: dict[str, str] = {}
    for md in HERE.glob("arxiv_*.md"):
        text   = md.read_text(encoding="utf-8", errors="replace")
        chunks = re.split(r"\n(?=## )", text)
        for chunk in chunks:
            if not chunk.startswith("## "):
                continue
            id_m  = re.search(r"\[Abstract\]\(https://arxiv\.org/abs/([^\)]+)\)", chunk)
            abs_m = re.search(r"\*\*Abstract:\*\*\s*\n(.*?)(?=\n---|\Z)", chunk, re.DOTALL)
            if not id_m or not abs_m:
                continue
            raw_id   = id_m.group(1)
            abstract = re.sub(r"\s+", " ", abs_m.group(1)).strip()
            abstracts[raw_id]                     = abstract
            abstracts[raw_id.replace(".", "-", 1)] = abstract
    return abstracts


# ---------------------------------------------------------------------------
# Annotation formatter (mirrors build_finetune_from_annotations.py)
# ---------------------------------------------------------------------------

_SECTION_COLS = [
    "topic", "motivation", "contribution", "detail_nuance",
    "evidence_contribution_2", "weaker_result", "narrow_impact", "broad_impact",
]
_SECTION_HEADERS = [
    "**Topic**", "**Motivation**", "**Contribution**", "**Detail / Nuance**",
    "**Evidence / Contribution 2**", "**Weaker result**", "**Narrow impact**", "**Broad impact**",
]


def _format_annotation(row: dict) -> str:
    parts = []
    for header, col in zip(_SECTION_HEADERS, _SECTION_COLS):
        text = (row.get(col) or "").strip()
        if text:
            parts.append(f"{header}\n{text}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# LLM scoring
# ---------------------------------------------------------------------------

def _llm(system: str, user: str, model: str, _trace=None) -> tuple[str, int, int]:
    resp = _llm_chat(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        options={"temperature": 0.2},
        keep_alive=_KEEP_ALIVE,
    )
    if _trace is not None:
        _trace.log_usage(resp, stage="curate")
    text    = resp["message"]["content"].strip()
    in_tok  = resp.get("prompt_eval_count", 0) or 0
    out_tok = resp.get("eval_count", 0) or 0
    return text, in_tok, out_tok


def _parse_score_reason(text: str) -> tuple[int | None, str]:
    score_m  = re.search(r"^SCORE:\s*([1-5])", text, re.MULTILINE)
    reason_m = re.search(r"^REASON:\s*(.+)$", text, re.MULTILINE)
    score  = int(score_m.group(1)) if score_m else None
    reason = reason_m.group(1).strip() if reason_m else text[:120]
    return score, reason


def score_paper(
    arxiv_id: str,
    title: str,
    annotation: str,
    model: str,
    query: str = "",
    mean_threshold: float = MEAN_THRESHOLD,
    veto_floor: int = VETO_FLOOR,
    _trace=None,
) -> dict:
    """
    Run all 5 personas against this paper. Returns decision dict:
    {arxiv_id, title, scores: [{persona, score, reason}], mean, passed, veto_by}
    """
    topic_line = f"This paper is being evaluated for a literature review about: {query}\n\n" if query else ""
    user_prompt = _SCORE_PROMPT.format(title=title, annotation=annotation[:1200], topic_line=topic_line)
    scores = []
    total_in = total_out = 0

    for persona in PERSONAS:
        text, in_tok, out_tok = _llm(persona["system"], user_prompt, model, _trace=_trace)
        score, reason = _parse_score_reason(text)
        scores.append({
            "persona": persona["name"],
            "score":   score,
            "reason":  reason,
        })
        total_in  += in_tok
        total_out += out_tok

    valid_scores: list[int] = [s["score"] for s in scores if isinstance(s["score"], int)]
    mean = round(sum(valid_scores) / len(valid_scores), 2) if valid_scores else 0.0

    veto_by = [s["persona"] for s in scores if isinstance(s["score"], int) and s["score"] < veto_floor]
    passed  = mean >= mean_threshold and len(veto_by) == 0

    return {
        "arxiv_id":   arxiv_id,
        "title":      title,
        "scores":     scores,
        "mean":       mean,
        "passed":     passed,
        "veto_by":    veto_by,
        "tokens_in":  total_in,
        "tokens_out": total_out,
    }


# ---------------------------------------------------------------------------
# Already-curated lookup (idempotency)
# ---------------------------------------------------------------------------

def _load_log() -> dict[str, dict]:
    """Return {arxiv_id: decision} from existing curation_log.jsonl."""
    if not LOG_PATH.exists():
        return {}
    results = {}
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            results[d["arxiv_id"]] = d
        except (json.JSONDecodeError, KeyError):
            pass
    return results


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",          help="Single annotated CSV to curate (default: all arxiv_*_annotated.csv)")
    parser.add_argument("--mean-threshold", type=float, default=MEAN_THRESHOLD)
    parser.add_argument("--veto-floor",     type=int,   default=VETO_FLOOR)
    parser.add_argument("--model",          default=_DEFAULT_MODEL)
    parser.add_argument("--dry-run",        action="store_true", help="Score only, write log but no curated CSV")
    parser.add_argument("--stats",          action="store_true", help="Print stats from existing log and exit")
    args = parser.parse_args()

    mean_threshold = args.mean_threshold
    veto_floor     = args.veto_floor

    if args.stats:
        log = _load_log()
        if not log:
            print("No curation log found.")
            return
        passed = sum(1 for d in log.values() if d["passed"])
        failed = len(log) - passed
        vetoed = sum(1 for d in log.values() if d.get("veto_by"))
        print(f"Curation log: {len(log)} papers  |  {passed} passed  |  {failed} failed  |  {vetoed} vetoed")
        # Top veto personas
        from collections import Counter
        veto_counts = Counter(p for d in log.values() for p in d.get("veto_by", []))
        if veto_counts:
            print("Veto counts by persona:")
            for persona, count in veto_counts.most_common():
                print(f"  {persona}: {count}")
        return

    # Determine input CSVs
    if args.input:
        csv_paths = [Path(args.input)]
    else:
        csv_paths = sorted((HERE / "data").glob("arxiv_*_annotated.csv"))

    if not csv_paths:
        print("No annotated CSV files found.")
        sys.exit(1)

    print("Loading abstracts from arxiv markdown files...")
    abstracts = _load_abstracts()
    print(f"  {len(abstracts) // 2} abstracts loaded")

    existing_log = _load_log()
    print(f"  {len(existing_log)} papers already curated (will skip)\n")

    log_file = open(LOG_PATH, "a", encoding="utf-8")

    for csv_path in csv_paths:
        rows = []
        with open(csv_path, encoding="utf-8", errors="replace") as f:
            rows = list(csv.DictReader(f))

        curated_rows = []
        passed_count = failed_count = skipped_count = 0

        out_path = csv_path.with_name(csv_path.stem.replace("_annotated", "_curated") + ".csv")
        fieldnames = rows[0].keys() if rows else []

        print(f"Curating {csv_path.name} ({len(rows)} papers)...")

        for row in rows:
            arxiv_id = row.get("filename", "").strip()
            if not arxiv_id:
                continue

            # Idempotency
            if arxiv_id in existing_log:
                decision = existing_log[arxiv_id]
                if decision["passed"]:
                    curated_rows.append(row)
                    passed_count += 1
                else:
                    failed_count += 1
                skipped_count += 1
                continue

            annotation = _format_annotation(row)
            if not annotation.strip():
                continue

            # Title from abstracts map or fallback
            title = arxiv_id

            decision = score_paper(arxiv_id, title, annotation, args.model,
                                   mean_threshold=mean_threshold, veto_floor=veto_floor)

            verdict = "PASS" if decision["passed"] else "FAIL"
            veto    = f" [veto: {', '.join(decision['veto_by'])}]" if decision["veto_by"] else ""
            print(f"  {arxiv_id}  mean={decision['mean']:.1f}  {verdict}{veto}")

            log_file.write(json.dumps(decision) + "\n")
            log_file.flush()

            if decision["passed"]:
                curated_rows.append(row)
                passed_count += 1
            else:
                failed_count += 1

        log_file.close()

        total   = passed_count + failed_count
        pct     = round(100 * passed_count / total, 1) if total else 0

        print(f"\n  {csv_path.name}: {passed_count}/{total} passed ({pct}%)  |  {skipped_count} skipped (cached)")

        if not args.dry_run and curated_rows:
            with open(out_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(curated_rows)
            print(f"  Written -> {out_path.name}")

    print(f"\nDone. Full log: {LOG_PATH.name}")
    print("Next step: python build_finetune_from_annotations.py  (uses *_curated.csv instead of *_annotated.csv)")


if __name__ == "__main__":
    main()

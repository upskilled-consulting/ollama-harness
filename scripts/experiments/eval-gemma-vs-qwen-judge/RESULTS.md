# Results: small-judge comparison + the eval-pipeline bugs it surfaced

Goal was to find an independent evaluator (different family from the Qwen3.6 producer)
that fits 16 GB and can replace/augment the Wiggum judge. We scored a fixed batch of
existing outputs (data/eval/benchmark_*.md) with several judges against the 35B as anchor.

## Headline: the judge comparison was CONFOUNDED — do not trust its rankings
Every test file was graded under the WRONG rubric, so the scores measure leniency-under-a-
broken-rubric, not judge quality. Two stacked eval-pipeline bugs, found while investigating:

### Bug 1 — task-type misclassification (FIXED)
`detect_task_type()` knew only {osint, enumerated, best_practices, else->research} and
`TASK_CRITERIA` had only those keys. Real task types — coding, comparison, analysis,
planning — all fell through to the **research** rubric, which says "penalize claims not
traceable to named sources; do not require code." A correct, complete async-SQLite-pool
implementation was therefore graded as if it were a literature review: grounded=2 (no
citations) -> composite **2.0**. The 35B was faithfully applying a mis-assigned rubric;
the small judges applied the same wrong rubric leniently (~8). Neither was validated.

Fix (harness/wiggum.py):
- Added `coding` to `detect_task_type` (ordered after how-to/top-N so guides stay guides).
- Added TASK_CRITERIA for coding, comparison, analysis, planning (all 6 benchmark types
  now covered).
- `evaluate(task_type=...)` accepts an explicit type; callers that know it (task-suite
  records) bypass detection. Unknown types fall back to research instead of KeyError-ing.
- comparison/analysis/planning are intentionally NOT auto-detected (their verbs appear in
  ordinary research prompts) — they rely on the explicit-type path.

Validation: same coding file under the correct `coding` rubric scored 5.1 vs 2.0 under
research. (Still not ~8 — see Bug 2.)

### Bug 2 — long code is truncated before the judge sees it (NOT yet fixed)
`evaluate()` summarizes content >6000 chars and hard-caps it at `_EVAL_CONTENT_CAP=4000`.
The 7945-char code file's required concurrency test sits at the end and is cut off, so the
judge sees half an implementation and scores completeness=3. Raw-first-4000ch and the prose
summary both land ~3.6 under the coding rubric — i.e. no judge ever sees a *complete* code
submission. Needs a code-aware fix (don't prose-summarize code; chunk or raise the cap for
coding tasks; competes with VRAM, so design carefully).

## Confounded judge numbers (kept for the record only — NOT a verdict)
Scored under the (wrong) research rubric, n=8:

| judge               | mean | range   | corr vs 35B | note |
|---------------------|------|---------|-------------|------|
| 35B anchor          | 5.05 | 2.2–6.4 | —           | strict under wrong rubric |
| qwen3-8b            | 8.00 | 7.7–8.6 | -0.62       | Qwen family |
| gemma-4-E4B         | 8.16 | 7.2–8.6 | -0.21       | Google family |
| Qwen2.5-14B         | 7.78 | 7.4–8.7 | -0.53       | bigger, same blind spot |
| Selene-1-Mini (8B)  | 9.0  | 9–9     | flat        | purpose-built judge; degenerate here |

All small judges scored the 2.2-anchor coding file 8–9 — but under the wrong rubric, so
this does NOT establish they are "blind." Re-run required after Bug 2 is fixed.

## Cloud arm: blocked
`kimi-k2.5:cloud` via Ollama returns HTTP 403 "this model requires a subscription". GLM-5.1
cloud likely same. Needs an entitled endpoint before a cloud judge can be tested.

## CORRECTED RUN — after both bugs fixed (this is the real answer)
Re-scored the same 8 files with correct per-type rubrics + head/tail content
(results.jsonl; the confounded run is kept as results_v1_confounded.jsonl).

| judge      | mean | range   | corr vs 35B | MAE  |
|------------|------|---------|-------------|------|
| 35B anchor | 6.03 | 5.1–6.8 | —           | —    |
| qwen3-8b   | 7.85 | 7.5–8.4 | **+0.54**   | 1.83 |

**The rubric fix flipped the conclusion.** qwen3-8b's correlation with the strong
judge went from **-0.62 (anti-correlated, wrong rubric) to +0.54 (positively
correlated, correct rubric)**. The earlier "small judges are blind" was largely an
artifact of the rubric bug, NOT a real property of the judges.

What remains is a **consistent leniency offset**: the 8B sits ~1.8 pts above the 35B
but now rank-orders broadly with it, and the gap is stable (+0.9 to +2.4). A stable
offset is correctable (stricter pass threshold, or subtract a calibration constant);
an anti-correlation is not. So qwen3-8b is a **viable judge with calibration** — the
opposite of what the confounded run suggested. gemma/selene/14b were only tested under
the wrong rubric; re-test them the same way before ranking, but the 8B alone may now
suffice as a cheap independent-enough judge (it is the same family as the producer, so
a cross-family option still has value for de-biasing DPO labels).

## Status / next
1. Bug 1 fixed + tested (wiggum detection tests pass; 2 pre-existing threshold-test failures
   are unrelated WIP).
2. Bug 2 (code truncation) identified, design pending.
3. Judge-replacement question DEFERRED until the eval pipeline grades on correct rubrics and
   full content — only then is a judge comparison meaningful.
4. Independent: the tok/s regression = 35B+8B VRAM co-residency -> CPU offload (35B alone did
   8 evals in 74 s). Fix proposed in start-vram-fix.md (kept separate; needs an independent
   judge decision, which this experiment did not settle).

## Caveats
n=8, medium complexity, Q4 quants. Directional. The methodological lesson stands regardless:
a judge comparison is only valid once the rubric and the visible content are correct.

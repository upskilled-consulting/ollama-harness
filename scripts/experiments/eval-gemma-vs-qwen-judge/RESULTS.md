# Results: Gemma-4-E4B vs Qwen3-8B as Wiggum evaluator

Pilot, n=8 (medium-complexity outputs from data/eval/benchmark_*.md), anchored to the
35B (sole-resident) as the strong reference judge. Same fixed files scored by each judge
via `wiggum.evaluate()` (single round, temp 0).

| judge       | mean | range    | corr vs 35B | MAE vs 35B |
|-------------|------|----------|-------------|------------|
| 35B anchor  | 5.05 | 2.2–6.4  | —           | —          |
| qwen3-8b    | 8.00 | 7.7–8.6  | **-0.62**   | 2.95       |
| gemma-e4b   | 8.16 | 7.2–8.6  | **-0.21**   | 3.11       |

qwen3-8b vs gemma-e4b correlation: **0.31** (fairly independent).

## Findings
1. **Neither 8B-class judge is a good proxy for the strong judge.** Both run ~3 points
   more lenient than the 35B (mean ~8 vs 5) and **do not even rank-order outputs the
   same way** — correlation with the anchor is negative/near-zero. The 8B *anti*-correlates.
2. **Both small judges miss failing outputs.** `coding_systems_medium_001`: the 35B
   scored it **2.2** (the required code was largely absent); qwen3-8b said **8.6**, gemma **8.2**.
   A lenient small judge cannot tell a near-failure from an excellent answer.
3. **Gemma is not meaningfully better or worse than qwen3-8b as a judge** — similar
   leniency, marginally less anti-correlated, marginally worse MAE. It does add
   *diversity* (0.31 corr), but two judges that both miss the same failure don't fix leniency.

## Decision
- **Do not** swap qwen3-8b -> gemma-e4b expecting better judging; it is a lateral move.
- The VRAM/tok-s fix must NOT depend on a small judge being trustworthy. Prefer: run the
  **35B as the judge** for DPO-label generation (accurate, and fast as sole resident —
  this batch was 74 s / 8 files once Gemma was unloaded), keeping a small judge only for
  cheap in-loop gating if at all.
- **Implication for `data/rl_dataset/wiggum_dpo.jsonl`:** its preference labels were
  produced by the lenient 8B judge, which here could not separate a 2.2 from an 8.6.
  Those labels are likely noisy — worth regenerating with the 35B.

## Caveats
n=8, all medium complexity — directional, not definitive. Scale to ~30 files across
difficulty levels before finalizing. The 35B-as-anchor is an assumption, but the
missing-code case (35B=2.2, both small=8+) strongly indicates the 35B is the correct one.

## Harness fixes this experiment surfaced (all in harness/)
Gemma scored 0 until three Qwen-specific assumptions were fixed — the eval stack was
implicitly Qwen-tuned:
1. `inference.py` — enforce `response_format=json_object` for the **llamacpp** backend,
   not just vLLM (a llama.cpp judge that emits any preamble silently scored 0).
2. `wiggum.py` — eval `num_predict` 512 -> 1024 (512 truncated the full rubric JSON for
   verbose models).
3. `inference.py` — apply `enable_thinking=False` to **gemma** too, not only qwen/qwq
   (Gemma is a thinking model; it spent all tokens reasoning and emitted empty content).

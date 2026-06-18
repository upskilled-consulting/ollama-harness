# Experiment: Gemma-4-E4B vs Qwen3-8B as Wiggum evaluator

**Question.** Is `gemma-4-E4B` a good-enough — and usefully *diverse* — judge to replace
`qwen3-8b` as the Wiggum evaluator? Replacing it would also free the VRAM that is
currently forcing CPU offload on the 35B producer (the W18->W20 tok/s regression).

**Method.** Score a *fixed* batch of existing outputs with each candidate judge and
compare both against an anchor judge (the 35B). Scoring fixed files — not re-running
the producer — is what isolates the evaluator; re-generation would confound producer
and judge. Tool: `harness-engineering/eval_compare_evaluators.py`.

**Decision rule.** Prefer Gemma if it either (a) tracks the 35B anchor at least as
closely as Qwen3-8B (correlation / mean |delta|), OR (b) independently catches real
issues the Qwen judge misses (diversity payoff — it is a different model family, so it
should not share Qwen's blind spots; producer is Qwen, so a Qwen judge self-grades).

## VRAM reality
16 GB cannot hold 35B + 8B + E4B. Serve **one small judge at a time**; the 35B anchor
pass and each candidate pass run sequentially.

## Steps
1. Free VRAM held by the current evaluator:
   - stop the `llama8b` server (port 8082) from the running `start.py`.
2. Serve Gemma as a **text** judge (no vision tower needed -> omit `--mmproj`):
   ```
   llama.cpp\build\bin\llama-server.exe -m models\gemma-4-E4B-it-UD-Q4_K_XL.gguf ^
     --port 8082 -ngl 99 --ctx-size 8192 --parallel 1
   ```
3. Add a routing entry so the harness can address it (append to HARNESS_ENDPOINTS in .env):
   ```
   "gemma-e4b": {"url": "http://localhost:8082/v1", "model_id": "gemma-4-E4B-it-UD-Q4_K_XL.gguf", "backend": "llamacpp"}
   ```
4. Run the comparison over a fixed batch (single round, no revision):
   ```
   python eval_compare_evaluators.py --evaluators qwen3-8b gemma-e4b \
     --files <15-20 outputs from data/eval/*.md and harness-engineering/eval-*.md>
   ```
   For the anchor, repeat with the 35B served and `--evaluators qwen3.6-35b`.
5. Compare: per-file score deltas, correlation of each candidate with the 35B anchor,
   and a manual read of where Gemma and Qwen disagree on the *same* output.

## Why this matters beyond speed
`data/rl_dataset/wiggum_dpo.jsonl` is built from the evaluator's accept/reject signal.
Swapping the judge changes the *labels* on the DPO/SFT preference data — so judge choice
propagates into fine-tuning signal quality. Measure before standardizing.

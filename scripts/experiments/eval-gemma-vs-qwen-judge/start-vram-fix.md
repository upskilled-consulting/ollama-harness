# Proposed VRAM / tok-s fix (review before applying)

**Problem (measured).** On 16 GB, the 35B producer (12.74 GB weights) and the 8B
evaluator (4.36 GB) cannot both be `-ngl 99` resident — combined weights exceed the
card before any KV cache — so llama.cpp offloads layers to CPU. That is the W18->W20
regression: the 35B's own generation fell from ~106 tok/s to single digits. With the
8B unloaded, the 35B did 8 evals in 74 s (sole resident, no offload).

**Why use the 35B as the evaluator.** The pilot showed neither 8B-class judge tracks
the strong judge (both ~3 pts lenient; qwen3-8b *anti*-correlates; both missed a
near-failing output the 35B scored 2.2). So the cheap judge is also the *wrong* judge.
Using the 35B for both produce and evaluate removes the second resident model entirely:
one model, no contention, accurate scoring. Uses **no new llama-server flags**.

Tradeoff: each eval is now a 35B call (~9 s here) instead of an 8B call, but there is
no offload tax, so end-to-end is faster and the labels are trustworthy.

## Change 1 — start.py: make the 8B opt-in (no longer auto-resident)

```diff
     parser = argparse.ArgumentParser(description="Start harness services")
-    parser.add_argument("services", nargs="*", default=list(SERVICES))
+    # llama8b is opt-in: on a 16 GB card it cannot be GPU-resident alongside the
+    # 35B (12.7 GB) without forcing CPU offload that craters tok/s. Start it
+    # explicitly (`python start.py llama8b`) only when you have headroom.
+    parser.add_argument("services", nargs="*",
+                        default=[s for s in SERVICES if s != "llama8b"])
     parser.add_argument("--no-llama", action="store_true", help="skip llama-server")
```

## Change 2 — .env: route the evaluator to the 35B

```diff
-HARNESS_EVALUATOR_MODEL=qwen3-8b
+HARNESS_EVALUATOR_MODEL=qwen3.6-35b
```

## Verify after applying
1. `python start.py` -> only the 35B llama-server starts (8B does not).
2. Watch the 35B load log: `offloaded NN/NN layers to GPU` should be full (no CPU spill).
3. Run a task and confirm producer tok/s is back to triple digits.
4. If you still want a fast in-loop gate, start the 8B explicitly *and* drop its `-ngl`
   so it runs on CPU/partial, leaving the 35B's VRAM intact — but treat its scores as a
   coarse gate, not as DPO-label truth (regenerate those with the 35B).

## NOT included (deliberately)
- `--slot-save-path` (prompt-cache persistence) and a 35B `--reasoning-budget` cap are
  worthwhile but add/flip llama-server flags; given commit 760a789 ("strip unsupported
  llama flags"), confirm your build supports them before adding.

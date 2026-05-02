"""
finetune_annotate.py — Fine-tune a model to produce Nanda Annotated Abstracts.

Pipeline:
  1. Fetch arxiv abstracts for all papers in annotated-abstracts.csv
  2. Build instruction pairs  (abstract → 8-section annotation)
  3. QLoRA fine-tune Qwen2.5-7B-Instruct via trl SFTTrainer
  4. Merge LoRA adapters and save full model
  5. Print GGUF conversion and Ollama registration commands

Requirements:
    pip install transformers peft trl datasets accelerate bitsandbytes requests

Usage:
    python finetune_annotate.py                          # full run
    python finetune_annotate.py --fetch-only             # just build dataset, no training
    python finetune_annotate.py --model Qwen2.5-7B-Instruct --epochs 3
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

HERE         = Path(__file__).parent.parent  # repo root
ANN_CSV      = HERE / "data" / "annotated-abstracts.csv"
DATASET_OUT  = HERE / "data" / "finetune_dataset.jsonl"
MODEL_OUT    = HERE / "finetune_output"
METRICS_OUT  = HERE / "data" / "finetune_metrics.jsonl"

DEFAULT_MODEL  = "Qwen/Qwen2.5-7B-Instruct"
DEFAULT_EPOCHS = 3
ARXIV_API      = "https://export.arxiv.org/api/query"
RATE_LIMIT_S   = 3.0   # seconds between arxiv API requests

SYSTEM_PROMPT = """\
You are a research-paper analyst. Given a paper abstract, produce an annotated abstract \
using the Nanda framework with EXACTLY these eight bold section headers, in this order:

**Topic**
**Motivation**
**Contribution**
**Detail / Nuance**
**Evidence / Contribution 2**
**Weaker result**
**Narrow impact**
**Broad impact**

Rules:
- Each header must appear on its own line, bold, exactly as shown above.
- After each header write 1-2 sentences of plain prose synthesized from the paper. Be concise.
- Use only information from the provided text. Do not invent results.
- If a section is not clearly evidenced, write a brief inference grounded in what IS present.
- Output NOTHING before **Topic** and NOTHING after the **Broad impact** prose.

Section definitions:
  Topic                    — what subject area / problem this paper addresses
  Motivation               — why this problem matters; the gap or need being addressed
  Contribution             — the main new artifact, method, or claim ('We introduce/propose X')
  Detail / Nuance          — key technical specifics of how the contribution works
  Evidence / Contribution 2 — benchmark results or empirical evidence; secondary findings
  Weaker result            — limitations, conditions where the approach underperforms, or open problems
  Narrow impact            — specific, bounded applications or immediate takeaways
  Broad impact             — wider implications for the field or community (e.g. open-source release)\
"""


# ---------------------------------------------------------------------------
# Step 1 — fetch arxiv metadata
# ---------------------------------------------------------------------------

def arxiv_id_from_filename(filename: str) -> str:
    """Convert annotated-abstracts.csv filename to arxiv ID (2308-04079v1 → 2308.04079v1)."""
    # Replace first hyphen between YYMM and NNNNN with a dot
    return re.sub(r'^(\d{4})-(\d+)', r'\1.\2', str(filename).strip())


def fetch_arxiv_batch(ids: list[str]) -> dict[str, dict]:
    """Fetch title + abstract for a list of arxiv IDs. Returns {id: {title, abstract}}."""
    results = {}
    for arxiv_id in ids:
        try:
            resp = requests.get(
                ARXIV_API,
                params={"id_list": arxiv_id, "max_results": 1},
                timeout=15,
            )
            resp.raise_for_status()
            xml = resp.text

            # Skip the feed-level <title> and grab the entry's <title>
            entry_m   = re.search(r"<entry>(.*?)</entry>", xml, re.DOTALL)
            summary_m = re.search(r"<summary>(.*?)</summary>", xml, re.DOTALL)

            if entry_m and summary_m:
                entry_xml = entry_m.group(1)
                title_m   = re.search(r"<title>(.*?)</title>", entry_xml, re.DOTALL)
                if not title_m:
                    print(f"  [arxiv] {arxiv_id}: parse failed (no entry title)")
                    continue
                title    = re.sub(r"\s+", " ", title_m.group(1)).strip()
                abstract = re.sub(r"\s+", " ", summary_m.group(1)).strip()
                results[arxiv_id] = {"title": title, "abstract": abstract}
                print(f"  [arxiv] {arxiv_id}: {title[:60]}")
            else:
                print(f"  [arxiv] {arxiv_id}: parse failed")
        except Exception as e:
            print(f"  [arxiv] {arxiv_id}: error — {e}")

        time.sleep(RATE_LIMIT_S)

    return results


# ---------------------------------------------------------------------------
# Step 2 — build instruction pairs
# ---------------------------------------------------------------------------

def format_annotation(row: pd.Series, title: str) -> str:
    """Reconstruct the formatted 8-section annotation from CSV columns."""
    return (
        f"# Annotated Abstract: {title}\n\n"
        f"**Topic**\n{row['topic']}\n\n"
        f"**Motivation**\n{row['motivation']}\n\n"
        f"**Contribution**\n{row['contribution']}\n\n"
        f"**Detail / Nuance**\n{row['detail_nuance']}\n\n"
        f"**Evidence / Contribution 2**\n{row['evidence_contribution_2']}\n\n"
        f"**Weaker result**\n{row['weaker_result']}\n\n"
        f"**Narrow impact**\n{row['narrow_impact']}\n\n"
        f"**Broad impact**\n{row['broad_impact']}"
    )


def build_dataset(ann_df: pd.DataFrame, arxiv_meta: dict) -> list[dict]:
    """Build list of {system, user, assistant} instruction dicts."""
    examples = []
    skipped  = 0

    for _, row in ann_df.iterrows():
        arxiv_id = arxiv_id_from_filename(row["filename"])
        meta     = arxiv_meta.get(arxiv_id)
        if not meta:
            skipped += 1
            continue

        user_msg  = f"Paper abstract:\n\n{meta['abstract']}"
        assistant = format_annotation(row, meta["title"])

        examples.append({
            "system":    SYSTEM_PROMPT,
            "user":      user_msg,
            "assistant": assistant,
            "arxiv_id":  arxiv_id,
        })

    print(f"\nDataset: {len(examples)} examples built, {skipped} skipped (no arxiv match)")
    return examples


def save_dataset(examples: list[dict], path: Path):
    with open(path, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    print(f"Dataset saved -> {path}")


# ---------------------------------------------------------------------------
# Dashboard callback — per-step metrics to finetune_metrics.jsonl + stdout
# ---------------------------------------------------------------------------

class DashboardCallback:
    """
    trl TrainerCallback that emits per-step metrics to finetune_metrics.jsonl
    and as [EVENT] structured events to stdout (picked up by SSE stream if
    launched via server.py).

    Import deferred so this module loads without trl installed.
    """

    def __new__(cls, metrics_path: Path):
        try:
            from transformers import TrainerCallback

            class _Impl(TrainerCallback):
                def __init__(self, metrics_path):
                    self.metrics_path = metrics_path
                    self._start_time  = None
                    self._step_times  = []

                def _emit(self, record: dict):
                    record["wall_time"] = time.time()
                    line = json.dumps(record, ensure_ascii=False)
                    with open(self.metrics_path, "a", encoding="utf-8") as f:
                        f.write(line + "\n")
                    print(f"[EVENT]{line}", flush=True)

                def on_train_begin(self, args, state, control, **kwargs):
                    self._start_time = time.time()
                    self._emit({
                        "type":       "train_begin",
                        "max_steps":  state.max_steps,
                        "num_epochs": args.num_train_epochs,
                        "model":      args.output_dir,
                    })

                def on_log(self, args, state, control, logs=None, **kwargs):
                    if not logs:
                        return
                    now = time.time()
                    elapsed = now - self._start_time if self._start_time else 0
                    self._step_times.append(now)
                    # ETA from rolling average of last 10 step durations
                    eta_s = None
                    if len(self._step_times) >= 2:
                        recent = self._step_times[-10:]
                        secs_per_step = (recent[-1] - recent[0]) / max(len(recent) - 1, 1)
                        remaining = state.max_steps - state.global_step
                        eta_s = round(secs_per_step * remaining)
                    self._emit({
                        "type":                "metric",
                        "step":                state.global_step,
                        "max_steps":           state.max_steps,
                        "epoch":               round(state.epoch or 0, 4),
                        "loss":                logs.get("loss"),
                        "grad_norm":           logs.get("grad_norm"),
                        "learning_rate":       logs.get("learning_rate"),
                        "mean_token_accuracy": logs.get("mean_token_accuracy"),
                        "entropy":             logs.get("entropy"),
                        "elapsed_s":           round(elapsed),
                        "eta_s":               eta_s,
                    })

                def on_epoch_end(self, args, state, control, **kwargs):
                    self._emit({
                        "type":  "epoch_end",
                        "epoch": round(state.epoch or 0, 2),
                        "step":  state.global_step,
                    })

                def on_train_end(self, args, state, control, **kwargs):
                    elapsed = time.time() - self._start_time if self._start_time else 0
                    self._emit({
                        "type":      "train_end",
                        "step":      state.global_step,
                        "elapsed_s": round(elapsed),
                    })

            return _Impl(metrics_path)
        except ImportError:
            return object.__new__(object)


# ---------------------------------------------------------------------------
# Step 3 — QLoRA fine-tune
# ---------------------------------------------------------------------------

def finetune(examples: list[dict], base_model: str, epochs: int, output_dir: Path, resume: bool = False, save_steps: int = 100):
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, get_peft_model
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from trl import SFTConfig, SFTTrainer
    except ImportError as e:
        sys.exit(f"[error] missing dependency: {e}\n  pip install transformers peft trl datasets accelerate")

    ckpt_dir = output_dir / "checkpoints"

    # Auto-detect last checkpoint for resume
    resume_from = None
    if resume:
        import glob as _glob
        ckpts = sorted(_glob.glob(str(ckpt_dir / "checkpoint-*")))
        if ckpts:
            resume_from = ckpts[-1]
            print(f"[finetune] resuming from {resume_from}")
        else:
            print("[finetune] --resume requested but no checkpoints found; starting fresh")

    print(f"\n[finetune] base model : {base_model}")
    print(f"[finetune] examples   : {len(examples)}")
    print(f"[finetune] epochs     : {epochs}")
    print(f"[finetune] output     : {output_dir}")
    print(f"[finetune] save_steps : every {save_steps} steps")

    # Build HF Dataset with formatted chat strings
    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.model_max_length = 2048

    def format_chat(ex):
        messages = [
            {"role": "system",    "content": ex["system"]},
            {"role": "user",      "content": ex["user"]},
            {"role": "assistant", "content": ex["assistant"]},
        ]
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)

    texts = [format_chat(ex) for ex in examples]

    # Train/eval split
    split_idx = max(1, int(len(texts) * 0.9))
    train_ds  = Dataset.from_dict({"text": texts[:split_idx]})
    eval_ds   = Dataset.from_dict({"text": texts[split_idx:]})
    print(f"[finetune] train={len(train_ds)}  eval={len(eval_ds)}")

    # Load in bf16, explicitly move to CUDA
    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
    ).to("cuda")

    # LoRA config
    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model.config.use_cache = False        # must disable for training
    model = get_peft_model(model, lora_config)
    model.enable_input_require_grads()   # required for PEFT + gradient checkpointing
    model.print_trainable_parameters()

    # Training args — save_strategy="steps" with a frequent interval guards against
    # mid-epoch interruptions (OS updates, crashes).  save_total_limit=3 keeps disk
    # usage bounded.  eval_strategy stays epoch-based; load_best_model_at_end is
    # omitted because HF Trainer requires it to align with save_strategy.
    sft_config = SFTConfig(
        output_dir=str(ckpt_dir),
        num_train_epochs=epochs,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=1,
        learning_rate=2e-4,
        bf16=True,
        dataloader_num_workers=0,
        logging_steps=1,
        eval_strategy="epoch",
        save_strategy="steps",
        save_steps=save_steps,
        save_total_limit=3,
        report_to="none",
        dataset_text_field="text",
    )

    # Clear previous metrics only on fresh runs
    if not resume_from:
        METRICS_OUT.write_text("", encoding="utf-8")

    # EarlyStoppingCallback requires load_best_model_at_end=True, which we removed
    # to allow save_strategy="steps" + eval_strategy="epoch". Omit it entirely.

    trainer = SFTTrainer(
        model=model,
        args=sft_config,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        processing_class=tokenizer,
        callbacks=[DashboardCallback(METRICS_OUT)],
    )

    print("\n[finetune] training...")
    print(f"[finetune] metrics -> {METRICS_OUT}")
    trainer.train(resume_from_checkpoint=resume_from)

    # Merge LoRA weights and save
    merged_path = output_dir / "merged"
    print(f"\n[finetune] merging adapters → {merged_path}")
    merged_model = trainer.model.merge_and_unload()
    merged_model.save_pretrained(str(merged_path))
    tokenizer.save_pretrained(str(merged_path))
    print("[finetune] done.")

    return merged_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model",      default=DEFAULT_MODEL,  help="HF model ID to fine-tune")
    parser.add_argument("--epochs",     default=DEFAULT_EPOCHS, type=int)
    parser.add_argument("--fetch-only", action="store_true",    help="Only fetch arxiv data and build dataset, skip training")
    parser.add_argument("--skip-fetch", action="store_true",    help="Use existing finetune_dataset.jsonl, skip arxiv fetch")
    parser.add_argument("--dataset",    default=None,           help="Path to alternate JSONL dataset (e.g. finetune_dataset_v2.jsonl)")
    parser.add_argument("--patience",   default=1, type=int,   help="(unused — early stopping requires load_best_model_at_end)")
    parser.add_argument("--resume",     action="store_true",   help="Resume from the last checkpoint in finetune_output/checkpoints/")
    parser.add_argument("--save-steps", default=100, type=int, help="Save a checkpoint every N steps (default: 100)")
    args = parser.parse_args()

    ann_df = pd.read_csv(ANN_CSV)
    print(f"Loaded {len(ann_df)} annotations from {ANN_CSV.name}")

    # --- Fetch or load arxiv metadata ---
    if args.dataset:
        dataset_path = HERE / args.dataset
        print(f"Loading dataset from {dataset_path}")
        examples = [json.loads(l) for l in dataset_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    elif args.skip_fetch and DATASET_OUT.exists():
        print(f"Loading existing dataset from {DATASET_OUT}")
        examples = [json.loads(l) for l in DATASET_OUT.read_text(encoding="utf-8").splitlines() if l.strip()]
    else:
        arxiv_ids = [arxiv_id_from_filename(f) for f in ann_df["filename"]]
        print(f"\nFetching {len(arxiv_ids)} abstracts from arxiv API...")
        arxiv_meta = fetch_arxiv_batch(arxiv_ids)
        examples   = build_dataset(ann_df, arxiv_meta)
        save_dataset(examples, DATASET_OUT)

    if args.fetch_only:
        print("--fetch-only: skipping training.")
        return

    # --- Fine-tune ---
    merged_path = finetune(examples, args.model, args.epochs, MODEL_OUT,
                           resume=args.resume, save_steps=args.save_steps)

    # --- Post-training instructions ---
    gguf_path = HERE / "finetune_output" / "nanda-annotator-q4.gguf"
    print(f"""
=== Next steps: GGUF conversion + Ollama registration ===

1. Convert to GGUF:
   {sys.executable} llama.cpp/convert_hf_to_gguf.py {merged_path} --outfile {gguf_path} --outtype q8_0

2. Quantize to Q4_K_M (optional, smaller):
   llama.cpp/build/bin/llama-quantize {gguf_path.with_suffix('')}_q8.gguf {gguf_path} Q4_K_M

3. Create Modelfile:
   echo 'FROM {gguf_path}' > finetune_output/Modelfile

4. Register in Ollama:
   ollama create nanda-annotator -f finetune_output/Modelfile

5. Use in harness:
   /annotate /wiggum --producer nanda-annotator https://arxiv.org/abs/XXXX annotate-test/out.md
""")


if __name__ == "__main__":
    main()

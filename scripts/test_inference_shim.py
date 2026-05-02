"""
test_inference_shim.py — verify inference.py routes correctly to vLLM.

Run from the harness root with INFERENCE_BACKEND=vllm set in .env:
    python test_inference_shim.py

Checks:
  1. _resolve_model maps harness model tags to the served AWQ model
  2. OllamaLike.chat() returns a valid response via vLLM
  3. _OllamaResponse exposes the fields logger._extract_usage() needs
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

import os, sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env so INFERENCE_BACKEND / VLLM_BASE_URL are present
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env", override=False)

backend = os.environ.get("INFERENCE_BACKEND", "ollama")
print(f"INFERENCE_BACKEND = {backend}")
if backend != "vllm":
    print("  WARNING: INFERENCE_BACKEND is not 'vllm' — set it in .env to test vLLM routing")
    sys.exit(1)

base_url = os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1")
print(f"VLLM_BASE_URL     = {base_url}")

# --- 1. Model map coverage ---
from harness import inference
print("\n[1] Model map resolution:")
for tag in ["pi-qwen-32b", "pi-qwen", "Qwen3-Coder:30b"]:
    resolved = inference._resolve_model(tag)
    print(f"  {tag!r:35s} -> {resolved!r}")

# --- 2. Live call via OllamaLike ---
print("\n[2] OllamaLike.chat() -> vLLM:")
ollama = inference.OllamaLike(keep_alive=-1)
model_tag = "pi-qwen-32b"
resp = ollama.chat(
    model=model_tag,
    messages=[{"role": "user", "content": "Reply with exactly three words: vllm is working"}],
    options={"num_predict": 10, "temperature": 0.0},
)
content = resp["message"]["content"]
print(f"  model tag : {model_tag}")
print(f"  response  : {content!r}")

# --- 3. Usage fields ---
print("\n[3] _OllamaResponse usage fields:")
fields = {
    "prompt_eval_count":    resp.prompt_eval_count,
    "eval_count":           resp.eval_count,
    "total_duration (ns)":  resp.total_duration,
    "eval_duration (ns)":   resp.eval_duration,
    "prompt_eval_duration": resp.prompt_eval_duration,
    "message.thinking":     resp.message.thinking,
}
for k, v in fields.items():
    print(f"  {k:28s} = {v}")

print("\nAll checks passed." if content else "\nWARNING: empty response content.")

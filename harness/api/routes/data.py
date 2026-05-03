"""GET /api/finetune/metrics — fine-tune training metrics stream.
   GET /api/finetune/datasets  — dataset catalogue with counts + samples.
"""

import json

from fastapi import APIRouter

from harness.config import DATA_DIR, ROOT

router = APIRouter(tags=["data"])
_METRICS = DATA_DIR / "finetune_metrics.jsonl"

_DATASETS = [
    {"name": "SFT",          "path": ROOT / "scripts/hf_datasets/sft.jsonl",         "format": "sft"},
    {"name": "DPO",          "path": ROOT / "scripts/hf_datasets/dpo.jsonl",          "format": "dpo"},
    {"name": "Preference",   "path": ROOT / "scripts/hf_datasets/preference.jsonl",   "format": "preference"},
    {"name": "Reward",       "path": ROOT / "scripts/hf_datasets/reward.jsonl",       "format": "reward"},
    {"name": "Trajectory",   "path": ROOT / "scripts/hf_datasets/trajectory.jsonl",   "format": "trajectory"},
    {"name": "GRPO",         "path": ROOT / "data/rl_dataset/grpo.jsonl",             "format": "grpo"},
    {"name": "Wiggum DPO",   "path": ROOT / "data/rl_dataset/wiggum_dpo.jsonl",       "format": "preference"},
]

_SAMPLE_N = 20


def _read_jsonl(path, n=None):
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass
        if n and len(records) >= n:
            break
    return records


@router.get("/finetune/metrics")
async def finetune_metrics():
    return _read_jsonl(_METRICS)


@router.get("/finetune/datasets")
async def finetune_datasets():
    result = []
    for ds in _DATASETS:
        path = ds["path"]
        all_records = _read_jsonl(path)
        samples = all_records[:_SAMPLE_N]
        result.append({
            "name":    ds["name"],
            "format":  ds["format"],
            "count":   len(all_records),
            "fields":  list(samples[0].keys()) if samples else [],
            "samples": samples,
        })
    return result


@router.get("/finetune/rl")
async def finetune_rl():
    """All RL training data structured for the dashboard view."""
    preference = _read_jsonl(ROOT / "data/rl_dataset/wiggum_dpo.jsonl")
    # Sort by score gap descending so the clearest signal pairs are first
    preference.sort(key=lambda r: r.get("score_gap", 0), reverse=True)

    reward = _read_jsonl(ROOT / "scripts/hf_datasets/reward.jsonl")
    # Only records with dimension data or feedback — these are the informative ones
    reward = [r for r in reward if r.get("dimensions") or r.get("feedback") or r.get("issues")]
    reward.sort(key=lambda r: r.get("score", 0), reverse=True)

    grpo = _read_jsonl(ROOT / "data/rl_dataset/grpo.jsonl")

    dpo = _read_jsonl(ROOT / "scripts/hf_datasets/dpo.jsonl")

    return {
        "preference": preference,
        "reward":     reward,
        "grpo":       grpo,
        "dpo":        dpo,
    }

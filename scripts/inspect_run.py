"""
inspect_run.py — pretty-print the last N runs from runs.jsonl

Usage:
    python inspect_run.py          # last run
    python inspect_run.py 3        # last 3 runs
    python inspect_run.py --all    # all runs, summary table
"""

import json
import sys


def fmt_stage(stage, vals):
    return f"    {stage:<16}  in={vals['input']:>5}  out={vals['output']:>5}  calls={vals['calls']}  ms={vals['total_ms']:.0f}"


def print_run(d, idx=None):
    label = f"Run {idx}" if idx is not None else "Run"
    print(f"\n{'='*60}")
    print(f" {label}: {d.get('timestamp', '?')[:19]}")
    print(f"  task:     {d.get('task', '')[:70]}")
    print(f"  producer: {d.get('producer_model', '?')}  evaluator: {d.get('evaluator_model', '?')}")
    print(f"  final:    {d.get('final', '?')}  duration: {d.get('run_duration_s', '?')}s")
    print(f"  tokens:   in={d.get('input_tokens', 0)}  out={d.get('output_tokens', 0)}")
    stages = d.get('tokens_by_stage', {})
    if stages:
        print("  by stage:")
        for s, v in stages.items():
            print(fmt_stage(s, v))
    print(f"  wiggum:   rounds={d.get('wiggum_rounds', 0)}  scores={d.get('wiggum_scores', [])}")
    dims = d.get('wiggum_dims', [])
    if dims:
        for i, dim in enumerate(dims):
            ds = "  ".join(f"{k[:3]}={v}" for k, v in dim.items())
            print(f"    round {i+1}: [{ds}]")
    print(f"  output:   {d.get('output_path', '?')}  ({d.get('output_bytes', '?')} bytes, {d.get('output_lines', '?')} lines)")


def summary_table(runs):
    print(f"\n{'#':<4} {'timestamp':<20} {'final':<6} {'dur(s)':<8} {'in_tok':<8} {'out_tok':<8} {'wig_rds':<8} {'scores'}")
    for i, d in enumerate(runs):
        ts = d.get('timestamp', '?')[:19]
        final = d.get('final', '?') or '?'
        dur = d.get('run_duration_s', '?')
        tin = d.get('input_tokens', 0)
        tout = d.get('output_tokens', 0)
        wr = d.get('wiggum_rounds', 0)
        ws = d.get('wiggum_scores', [])
        print(f"{i+1:<4} {ts:<20} {final:<6} {str(dur):<8} {tin:<8} {tout:<8} {wr:<8} {ws}")


def main():
    with open('runs.jsonl') as f:
        runs = [json.loads(l) for l in f if l.strip()]

    args = sys.argv[1:]

    if '--all' in args:
        summary_table(runs)
        return

    n = int(args[0]) if args else 1
    for i, d in enumerate(runs[-n:]):
        print_run(d, idx=len(runs) - n + i + 1)


if __name__ == '__main__':
    main()

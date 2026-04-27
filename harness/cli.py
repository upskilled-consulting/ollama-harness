"""
harness/cli.py — op command dispatcher.

Maps slash-commands and flags to agent/skill/server invocations.
Replaces the monolithic arg-parsing block at the bottom of the old op.py.
"""

from __future__ import annotations
import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="op",
        description="Harness agentic research CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("task", nargs="?",         help="Task string or /skill invocation")
    parser.add_argument("--producer", "-p",        help="Override producer model")
    parser.add_argument("--evaluator", "-e",       help="Override evaluator model")
    parser.add_argument("--no-wiggum",             action="store_true")
    parser.add_argument("--no-memory",             action="store_true")
    parser.add_argument("--orchestrate",           action="store_true")
    parser.add_argument("--from-env",              action="store_true", help="Read task from AGENT_TASK env var")
    parser.add_argument("--serve",                 action="store_true", help="Start the API server")
    parser.add_argument("--port",                  type=int, default=None)
    args, remainder = parser.parse_known_args()

    if args.serve:
        _serve(args.port)
        return

    if args.from_env:
        import os
        task = os.environ.get("AGENT_TASK", "").strip()
        if not task:
            print("Error: AGENT_TASK environment variable is empty", file=sys.stderr)
            sys.exit(1)
        args.task = task

    if not args.task:
        parser.print_help()
        sys.exit(1)

    _run_task(args, remainder)


def _run_task(args: argparse.Namespace, remainder: list[str]) -> None:
    from harness.config import settings

    producer = args.producer or settings.producer_model

    if args.orchestrate:
        from harness import orchestrator
        orchestrator.orchestrate(args.task, producer_model=producer)
    else:
        from harness import agent
        agent.run(
            task=args.task,
            producer_model=producer,
            evaluator_model=args.evaluator or settings.evaluator_model,
            no_wiggum=args.no_wiggum,
            no_memory=args.no_memory,
        )


def _serve(port: int | None) -> None:
    from harness.config import settings
    import uvicorn
    uvicorn.run(
        "harness.api.main:app",
        host=settings.host,
        port=port or settings.port,
        reload=True,
    )

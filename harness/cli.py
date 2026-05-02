"""
harness/cli.py — oh command dispatcher.

Usage:
  oh                    interactive REPL
  oh <task>             run a single task (no quotes needed)
  oh -h / --help        show help
  oh --serve            start the API server
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pyfiglet
from rich import box
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from harness import harness_console as _hc

console = _hc._console

_LOGO_FONT  = "isometric1"
_ACCENT     = "bold cyan"
_PROMPT_STR = "oh >  "

_SKILLS = [
    # Research
    ("research <topic>",                    "Multi-round web search + synthesis"),
    ("summarize <url|path>",                "Fetch and compress a URL or local file"),
    ("/lit-review <topic>",                 "Fetch papers, annotate, synthesize into review"),
    ("/annotate <url|path>",                "Annotate a paper or document (wiggum eval)"),
    # Browser / navigation
    ("/browser <url> <goal>",               "LLM-guided web navigation + content extraction"),
    ("/sitemap <url> [goal]",               "Crawl a domain, rank pages by goal"),
    # Site generation
    ("/design <url> [save to file.md]",     "Extract design system tokens from a live URL"),
    ("/build-page <design.md> from <dir/>", "Generate themed HTML page from .md content files"),
    ("/site <url> from <dir/>",             "Design + build in one command"),
    # Media
    ("/transcribe <url|path>",              "Transcribe YouTube video or local audio"),
    # Memory / project
    ("/recall <topic>",                     "Surface relevant observations from memory"),
    ("/orientation",                        "Summarise project state + recent activity"),
    ("/re-orient",                          "Rebuild orientation cache from GitHub state"),
    ("/suggest",                            "Recommend next research tasks"),
    ("/debug [filter]",                     "Diagnose recent FAIL/ERROR runs"),
    # Collaboration
    ("/email <contact> <goal>",             "Draft and send emails via Gmail"),
    ("/sync-wiki",                          "Sync lit-review corpus to GitHub wiki"),
    ("/panel",                              "Enable 3-persona wiggum review panel"),
]

_FLAGS = [
    ("--no-wiggum",      "Skip quality evaluation loop"),
    ("--headed",         "Show browser window (browser/design tasks)"),
    ("--keep-browser",   "Leave browser open after task"),
    ("--reuse-browser",  "Reconnect to existing browser session"),
    ("-h / --help",      "Show this help"),
    ("exit / quit",      "Leave the REPL"),
]

_OP_FLAGS = {"--no-wiggum", "--headed", "--keep-browser", "--reuse-browser"}


def _logo() -> str:
    return pyfiglet.figlet_format("oh", font=_LOGO_FONT)


def _show_splash():
    logo_text = Text(_logo(), style=_ACCENT)
    subtitle = Text(
        "  agentic research · browser navigation · synthesis · eval\n",
        style="italic dim",
    )
    combined = Text()
    combined.append_text(logo_text)
    combined.append_text(subtitle)

    console.print()
    console.print(Panel(combined, border_style="cyan", box=box.DOUBLE_EDGE, padding=(0, 2)))

    try:
        from harness import inference as _inf
        from harness.agent import MODEL as _PRODUCER
        ep_names = list(_inf._ENDPOINTS) if _inf._ENDPOINTS else []
        ep_str = "  ".join(ep_names) if ep_names else "—"
        active_marker = f"  [dim](active: {_PRODUCER})[/dim]" if _PRODUCER in ep_names else ""
        console.print(f"  [dim]models:[/dim] [cyan]{ep_str}[/cyan]{active_marker}")
    except Exception:
        pass

    console.print(
        "  [dim]type[/dim] [cyan]-h[/cyan] [dim]for help,[/dim] "
        "[cyan]exit[/cyan] [dim]to quit[/dim]\n"
    )


def _show_help():
    console.print()
    console.print(Rule("[bold cyan]oh — ollama-harness agent CLI[/bold cyan]", style="cyan"))
    console.print()
    console.print("[bold]USAGE[/bold]")
    console.print("  [cyan]oh[/cyan]                    interactive REPL")
    console.print("  [cyan]oh[/cyan] [italic]<task>[/italic]             run a single task (no quotes needed)")
    console.print("  [cyan]oh[/cyan] [cyan]-h[/cyan]                  show this help")
    console.print()
    console.print("[bold]SKILLS[/bold]")
    for cmd, desc in _SKILLS:
        console.print(f"  [cyan]{cmd:<30}[/cyan] [dim]{desc}[/dim]")
    console.print()
    try:
        from harness import plugin_loader as _pl
        _pl.load_all()
        _pcmds = _pl.get_commands()
        if _pcmds:
            console.print("[bold]PLUGINS[/bold]")
            for _pk, _pc in sorted(_pcmds.items()):
                _pdesc = _pc["definition"].get("description", "")
                console.print(f"  [cyan]/{_pk:<29}[/cyan] [dim]{_pdesc}[/dim]")
            console.print()
    except Exception:
        pass
    console.print("[bold]FLAGS[/bold]")
    for flag, desc in _FLAGS:
        console.print(f"  [cyan]{flag:<20}[/cyan] [dim]{desc}[/dim]")
    console.print()
    console.print("[bold]EXAMPLES[/bold]")
    console.print("  [dim]$[/dim] oh research best practices for cost management in AI agents, save to ~/Desktop/out.md")
    console.print("  [dim]$[/dim] oh /browser go to docs.anthropic.com and find the pricing page")
    console.print("  [dim]$[/dim] oh /sitemap stripe.com find integration guides")
    console.print()


_TASK_VERBS = {
    "research", "summarize", "summarise", "find", "fetch", "explain", "compare",
    "analyze", "analyse", "review", "generate", "write", "create", "build",
    "list", "show", "get", "search", "look", "check", "translate", "convert",
    "extract", "annotate", "transcribe", "survey", "evaluate", "run", "save",
}

def _looks_like_task(text: str) -> bool:
    """Return True if the input should be routed through the full agent pipeline."""
    if text.startswith("/"):
        return True
    words = text.lower().split()
    if len(words) >= 5:
        return True
    if words and words[0] in _TASK_VERBS:
        return True
    import re
    if re.search(r"https?://|\.md\b|\.py\b|\.txt\b|save to\b", text, re.IGNORECASE):
        return True
    return False


def _chat(text: str) -> None:
    """Lightweight single-turn response for conversational inputs."""
    from harness import inference as _inf
    from harness.agent import MODEL as _PRODUCER
    model = _PRODUCER
    _hc.install()
    _inf._on_inf_start = lambda label: _hc.start_spinner(label)
    _inf._on_inf_end   = _hc.stop_spinner
    _inf._on_cot       = _hc.show_cot
    try:
        resp  = _inf.chat(model, [{"role": "user", "content": text}],
                          system="You are oh, a helpful CLI assistant. Be brief and direct.")
        reply = resp.message.content if hasattr(resp, "message") else str(resp)
        console.print(f"\n  {reply}\n")
    except Exception as e:
        console.print(f"\n  [yellow]{e}[/yellow]\n")
    finally:
        _hc.stop_spinner()
        _hc.uninstall()
        _inf._on_inf_start = None
        _inf._on_inf_end   = None
        _inf._on_cot       = None


def _run(task: str, extra_args: list[str] | None = None):
    from harness import inference as _inf
    from harness.agent import run as _agent_run

    no_wiggum = bool(extra_args and "--no-wiggum" in extra_args)
    if extra_args:
        if "--headed"        in extra_args: os.environ["HARNESS_HEADED"]        = "1"
        if "--keep-browser"  in extra_args: os.environ["HARNESS_KEEP_BROWSER"]  = "1"
        if "--reuse-browser" in extra_args: os.environ["HARNESS_REUSE_BROWSER"] = "1"

    console.print()
    console.print(Panel(
        f"[bold white]{task}[/bold white]",
        border_style="cyan",
        box=box.ROUNDED,
        padding=(0, 2),
    ))

    _hc.install()
    _inf._on_inf_start = lambda label: _hc.start_spinner(label)
    _inf._on_inf_end   = _hc.stop_spinner
    _inf._on_cot       = _hc.show_cot

    t0 = time.monotonic()
    try:
        _agent_run(task, use_wiggum=not no_wiggum)
    except SystemExit:
        pass
    except KeyboardInterrupt:
        _hc.stop_spinner()
        _hc._console.print("\n  [yellow]interrupted[/yellow]")
    finally:
        _hc.stop_spinner()
        _hc.uninstall()
        _inf._on_inf_start = None
        _inf._on_inf_end   = None
        _inf._on_cot       = None

    elapsed = time.monotonic() - t0
    console.print(f"\n  [dim]* done[/dim]  [cyan]{elapsed:.1f}s[/cyan]\n")


def _repl(extra_args: list[str]):
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.styles import Style

    history_path = Path.home() / ".op_history"
    session = PromptSession(
        history=FileHistory(str(history_path)),
        style=Style.from_dict({"prompt": "ansicyan bold"}),
    )

    _show_splash()

    while True:
        try:
            task = session.prompt(_PROMPT_STR)
        except KeyboardInterrupt:
            console.print("[dim]  (ctrl-c — type exit to quit)[/dim]")
            continue
        except EOFError:
            console.print("[dim]  bye[/dim]")
            break

        task = task.strip()
        if not task:
            continue
        if task.lower() in ("exit", "quit", "q", ":q"):
            console.print("[dim]  bye[/dim]")
            break
        if task.lower() in ("-h", "--help", "help"):
            _show_help()
            continue

        if _looks_like_task(task):
            _run(task, extra_args=extra_args)
        else:
            _chat(task)


def _serve(port: int | None = None):
    import uvicorn

    from harness.config import settings
    uvicorn.run(
        "harness.api.main:app",
        host=settings.host,
        port=port or settings.port,
        reload=True,
        reload_dirs=[str(Path(__file__).parent)],
    )


def main() -> None:
    raw = sys.argv[1:]

    if not raw:
        _repl(extra_args=[])
        return

    if raw[0] in ("-h", "--help", "help"):
        _show_help()
        return

    if raw[0] == "--serve":
        port = int(raw[1]) if len(raw) > 1 and raw[1].isdigit() else None
        _serve(port)
        return

    flags = [a for a in raw if a in _OP_FLAGS]
    words = [a for a in raw if a not in _OP_FLAGS]
    task  = " ".join(words).strip()

    if not task:
        _repl(extra_args=flags)
        return

    _run(task, extra_args=flags)

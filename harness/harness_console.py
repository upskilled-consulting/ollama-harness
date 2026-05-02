"""
harness_console.py — retro-techy display layer for the op CLI.

Provides:
  install()         replace sys.stdout with a [tag]-colorizing wrapper
  uninstall()       restore sys.stdout
  start_spinner()   animated inference indicator (background thread)
  stop_spinner()    clear spinner and return
  show_cot()        render a chain-of-thought panel
"""

from __future__ import annotations

import io
import os
import re
import sys
import threading
import time

from rich.console import Console
from rich.panel import Panel
from rich import box as _box

# Capture the real terminal stdout AT IMPORT TIME — before install() swaps it.
_ORIG: io.TextIOBase = sys.stdout
_is_tty: bool = getattr(sys.stdout, "isatty", lambda: False)()

# Enable ANSI + UTF-8 on Windows.
if sys.platform == "win32":
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        # ENABLE_PROCESSED_OUTPUT | ENABLE_WRAP_AT_EOL_OUTPUT | ENABLE_VIRTUAL_TERMINAL_PROCESSING
        k32.SetConsoleMode(k32.GetStdHandle(-11), 7)
        # Set output codepage to UTF-8 (65001) so Unicode characters don't crash cp1252
        k32.SetConsoleOutputCP(65001)
    except Exception:
        pass
    # Reconfigure stdout/stderr to UTF-8 so print() doesn't encode through cp1252
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Rich console wired to the real terminal.
# legacy_windows=False: force ANSI mode even on old Windows terminals; avoids
# UnicodeEncodeError on cp1252 when printing non-Latin characters via Rich.
_console = Console(file=sys.stdout, highlight=False, markup=True,
                   force_terminal=True if _is_tty else None,
                   legacy_windows=False)

# ── Tag registry ─────────────────────────────────────────────────────────────
# Each entry: (icon, label-style, rest-style)
# rest-style="" means pass content unstyled so Rich can render naturally.
_TAGS: dict[str, tuple[str, str, str]] = {
    "agent":          ("◈", "bold bright_cyan",   ""),
    "inference":      ("◦", "dim cyan",            "dim"),
    "skill:sitemap":  ("◈", "bright_green",        ""),
    "skill:browser":  ("◈", "bright_green",        ""),
    "skill:annotate": ("◈", "bright_green",        ""),
    "skill:email":    ("◈", "bright_green",        ""),
    "skill:panel":    ("◈", "bright_green",        ""),
    "skill":          ("◈", "green",               ""),
    "sitemap":        ("◦", "green",               "dim"),
    "browser":        ("◦", "green",               "dim"),
    "plan":           ("▸", "cyan",                ""),
    "extract":        ("▸", "cyan",                ""),
    "navigate":       ("▸", "dim cyan",            "dim"),
    "decide":         ("▸", "dim cyan",            "dim"),
    "completeness":   ("◦", "dim cyan",            "dim"),
    "error":          ("✗", "bold red",            "red"),
    "warn":           ("⚠", "yellow",              ""),
    "log":            ("◦", "dim",                 "dim"),
    "propose":        ("◈", "bright_magenta",      ""),
    "proposal":       ("◦", "magenta",             ""),
    "eval":           ("◈", "bright_blue",         ""),
    "wiggum":         ("◈", "dim magenta",         "dim"),
    "research":       ("◦", "dim green",           "dim"),
    "hint":           ("→", "bright_yellow",       ""),
    "mode":           ("◦", "dim yellow",          "dim"),
    "loop":           ("◦", "dim",                 "dim"),
    "tsv":            ("◦", "dim",                 "dim"),
    "discard":        ("✗", "dim red",             "dim"),
    "keep":           ("✓", "bright_green",        ""),
}

# ── Spinner ───────────────────────────────────────────────────────────────────

_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_CYAN   = "\033[36m"
_DIM    = "\033[2m"
_RST    = "\033[0m"
_CLR    = "\r\033[K"

_active_spinner: "_Spinner | None" = None
_spin_lock = threading.Lock()


class _Spinner(threading.Thread):
    def __init__(self, label: str):
        super().__init__(daemon=True)
        self._label = label
        self._stop_event = threading.Event()

    def run(self):
        try:
            _ORIG.write("\n")
        except Exception:
            return
        i = 0
        while not self._stop_event.is_set():
            f = _FRAMES[i % len(_FRAMES)]
            try:
                _ORIG.write(f"{_CLR}  {_CYAN}{f}{_RST}  {_DIM}{self._label}{_RST}")
                _ORIG.flush()
            except Exception:
                break
            time.sleep(0.09)
            i += 1
        try:
            _ORIG.write(_CLR)
            _ORIG.flush()
        except Exception:
            pass

    def stop(self):
        self._stop_event.set()
        self.join(timeout=0.5)


def start_spinner(label: str = "generating…"):
    global _active_spinner
    if not _is_tty:
        return
    with _spin_lock:
        if _active_spinner and _active_spinner.is_alive():
            _active_spinner.stop()
        _active_spinner = _Spinner(label)
        _active_spinner.start()


def stop_spinner():
    global _active_spinner
    with _spin_lock:
        if _active_spinner:
            _active_spinner.stop()
            _active_spinner = None


# ── CoT panel ─────────────────────────────────────────────────────────────────

_COT_MAX = 380


def show_cot(thinking: str):
    """Render a collapsed chain-of-thought panel."""
    if not thinking or len(thinking.strip()) < 15:
        return
    text = thinking.strip()
    overflow = f"\n[dim]… +{len(text) - _COT_MAX:,} chars[/dim]" if len(text) > _COT_MAX else ""
    body = _esc(text[:_COT_MAX]) + overflow
    _console.print(
        Panel(
            f"[dim]{body}[/dim]",
            title="[dim cyan]⟨thinking⟩[/dim cyan]",
            border_style="dim blue",
            box=_box.ROUNDED,
            padding=(0, 1),
        )
    )


# ── Stdout interceptor ────────────────────────────────────────────────────────

def _esc(s: str) -> str:
    """Escape Rich markup characters in plain text."""
    return s.replace("[", "\\[")


def _emit(line: str):
    """Format and print one line to the real terminal."""
    with _spin_lock:
        # If spinner is running, clear its line before writing so they don't collide.
        if _active_spinner and _active_spinner.is_alive():
            _ORIG.write(_CLR)

    s = line.strip()
    if not s:
        _ORIG.write("\n")
        _ORIG.flush()
        return

    m = re.match(r"^(\s*)\[([a-zA-Z][a-zA-Z0-9:_-]*)\](.*)", line)
    if m:
        indent, raw_tag, rest = m.group(1), m.group(2).lower(), m.group(3).strip()
        entry = _TAGS.get(raw_tag) or _TAGS.get(raw_tag.split(":")[0])
        if entry:
            icon, lstyle, rstyle = entry
            label = f"[{lstyle}]{icon} {raw_tag}[/{lstyle}]"
            body  = (f"[{rstyle}]{_esc(rest)}[/{rstyle}]" if rstyle else _esc(rest))
            _console.print(f"{indent}  {label}  {body}", highlight=False)
            return

    # Unmatched line — pass through as-is.
    _ORIG.write(line + "\n")
    _ORIG.flush()


class _HarnessOutput(io.TextIOBase):
    """Wraps sys.stdout; colorizes [tag]-prefixed lines from harness internals."""

    def __init__(self):
        self._buf = ""

    def write(self, text: str) -> int:
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            _emit(line)
        return len(text)

    def flush(self):
        if self._buf:
            _emit(self._buf)
            self._buf = ""
        _ORIG.flush()

    def fileno(self):
        return _ORIG.fileno()

    def isatty(self):
        return getattr(_ORIG, "isatty", lambda: False)()

    @property
    def encoding(self):
        return getattr(_ORIG, "encoding", "utf-8")

    @property
    def errors(self):
        return getattr(_ORIG, "errors", "replace")


# ── Install / uninstall ───────────────────────────────────────────────────────

_installed = False


def install():
    global _installed
    if not _installed and getattr(_ORIG, "isatty", lambda: False)():
        sys.stdout = _HarnessOutput()
        _installed = True


def uninstall():
    global _installed
    if _installed:
        sys.stdout = _ORIG
        _installed = False

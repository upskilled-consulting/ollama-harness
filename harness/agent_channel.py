"""
harness/agent_channel.py — lightweight IPC for orchestrator ↔ subtask messaging (Pattern 3).

The parent orchestrator creates a temp directory (HARNESS_MSG_CHANNEL) before
spawning subtasks and passes its path + a per-subtask index (HARNESS_SUBTASK_IDX)
as environment variables.  Subtask agents call send_message() which atomically
writes a JSON file to the channel directory.  The orchestrator polls the channel
in a background thread and emits [EVENT] lines for each new message.

Message types
-------------
  "progress"  — intermediate finding or round-completion report (logged + forwarded)
  "blocker"   — subtask hit a recoverable issue (logged; parent continues)
  "finding"   — notable intermediate result worth surfacing before final synthesis
  "done"      — explicit early completion signal (rare; most subtasks just exit)
"""

from __future__ import annotations

import json
import os
import time

# ---------------------------------------------------------------------------
# Subtask-side API  (called from inside the subprocess)
# ---------------------------------------------------------------------------

def channel_path() -> str | None:
    """Return the channel directory path, or None if not running as a subtask."""
    return os.environ.get("HARNESS_MSG_CHANNEL") or None


def subtask_idx() -> int:
    """Return this subtask's index within the parent pool."""
    try:
        return int(os.environ.get("HARNESS_SUBTASK_IDX", "0"))
    except ValueError:
        return 0


def send_message(to: str, msg_type: str, content: str) -> str:
    """
    Write a message to the orchestrator's channel directory.
    No-ops silently when not running as a subtask (HARNESS_MSG_CHANNEL unset).

    Args:
        to:       Recipient — "parent" or a subtask index string e.g. "2"
        msg_type: One of "progress", "blocker", "finding", "done"
        content:  Human-readable message (keep under 300 chars for dashboard display)

    Returns:
        A short confirmation string (for tool-call result display).
    """
    ch = channel_path()
    if not ch or not os.path.isdir(ch):
        return "no channel configured"

    idx = subtask_idx()
    ts  = int(time.time() * 1000)
    msg = {
        "from_idx": idx,
        "to":       to,
        "type":     msg_type,
        "content":  content[:500],  # hard cap to prevent huge files
        "ts":       ts,
    }

    # Atomic write via rename to prevent partial reads by the watcher thread.
    fpath = os.path.join(ch, f"{idx}_{ts}.json")
    tmp   = fpath + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(msg, f)
        os.replace(tmp, fpath)
    except OSError:
        return "write failed"

    return f"sent:{msg_type}"


# ---------------------------------------------------------------------------
# Parent-side API  (called from inside the orchestrator)
# ---------------------------------------------------------------------------

def poll_messages(channel: str, seen: set[str]) -> list[dict]:
    """
    Return all complete (non-tmp) message files not already in `seen`.
    Updates `seen` in-place.  Returns messages sorted by ts ascending.
    """
    msgs: list[dict] = []
    try:
        for fname in os.listdir(channel):
            if fname.endswith(".tmp") or fname in seen:
                continue
            fpath = os.path.join(channel, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    msgs.append(json.load(f))
                seen.add(fname)
            except (OSError, json.JSONDecodeError):
                pass
    except OSError:
        pass
    return sorted(msgs, key=lambda m: m.get("ts", 0))

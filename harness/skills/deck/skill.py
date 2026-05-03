"""Task-string parser for the /deck skill."""
from __future__ import annotations

import os
import re


def parse_deck_task(task: str) -> dict:
    """
    Parse a /deck task string.

    Accepted forms:
      /deck --design <url|design.md> --content <url|dir|pdf> [--out <file.pptx>] [--title "..."]
      /deck design <url> content <dir> save to <file.pptx>

    Returns dict with keys: design_src, content_src, output_path, title
    """
    task = re.sub(r"^/deck\s*", "", task.strip(), flags=re.IGNORECASE).strip()

    # --title "..."  or  --title word
    title = ""
    title_m = (
        re.search(r'--title\s+"([^"]+)"', task, re.IGNORECASE) or
        re.search(r"--title\s+'([^']+)'", task, re.IGNORECASE) or
        re.search(r"--title\s+(\S+)",     task, re.IGNORECASE)
    )
    if title_m:
        title = title_m.group(1)
        task  = task[:title_m.start()] + task[title_m.end():]

    # --out / save to
    out_path = None
    out_m = re.search(r"(?:--out|save\s+to)\s+(\S+)", task, re.IGNORECASE)
    if out_m:
        out_path = os.path.expanduser(out_m.group(1))
        task     = task[:out_m.start()] + task[out_m.end():]

    # --design / design
    design_src = None
    design_m = re.search(r"(?:--design|design)\s+(\S+)", task, re.IGNORECASE)
    if design_m:
        design_src = design_m.group(1)
        task       = task[:design_m.start()] + task[design_m.end():]

    # --content / content / from
    content_src = None
    content_m = re.search(r"(?:--content|content|from)\s+(\S+)", task, re.IGNORECASE)
    if content_m:
        content_src = os.path.expanduser(content_m.group(1))
        task        = task[:content_m.start()] + task[content_m.end():]

    if not design_src and not content_src:
        raise ValueError(
            "Cannot parse /deck task — need at least --design and --content.\n"
            "Examples:\n"
            "  /deck --design https://stripe.com --content ~/Desktop/notes/ --out slides.pptx\n"
            "  /deck design https://vercel.com content ~/research/ save to deck.pptx\n"
            "  /deck --design https://notion.so --content report.pdf"
        )

    return {
        "design_src":  design_src,
        "content_src": content_src,
        "output_path": out_path,
        "title":       title,
    }

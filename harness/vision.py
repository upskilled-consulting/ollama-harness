"""
harness/vision.py — image-to-text preprocessing for the agent pipeline.

Routes image inputs through llama3.2-vision to extract structured descriptions,
which are injected as research context for the tool-capable text model.

The vision model does NOT do web search or file writing — it only reads images
and returns text. The tool-capable model handles all actions.

Usage (standalone):
    python -m harness.vision <image_path>
    python -m harness.vision <image_path> "<task description>"

Usage (as module):
    from harness.vision import extract_image_context
    description = extract_image_context(image_path, task)

Environment:
    Requires: llama3.2-vision pulled via `ollama pull llama3.2-vision`
"""

import base64
import os
import re
import sys

from harness import inference as ollama

VISION_MODEL = "llama3.2-vision"

EXTRACT_PROMPT = """I need to complete this task: {task}

Examine this image carefully and describe everything relevant to the task. Include:
- What type of content is shown (chart, screenshot, diagram, photo, document, etc.)
- All visible text, labels, headings, and annotations — transcribe them exactly
- Key data points, values, or metrics if this is a chart or table
- The overall structure and layout
- Any relationships, flows, or connections shown

Be specific and thorough. The description will be used by a separate model that cannot see the image."""

DESCRIBE_PROMPT = """Examine this image carefully and describe its contents in detail. Include:
- What type of content is shown
- All visible text, labels, and annotations — transcribe them exactly
- Key data points or values if this is a chart or table
- The overall structure and layout

Be specific and thorough."""


def extract_image_context(image_path: str, task: str = "") -> str:
    """
    Send image to llama3.2-vision and return a text description.

    If task is provided, the prompt is tailored to extract what the task needs.
    Returns the description string, or an error message on failure.
    """
    expanded = os.path.expanduser(image_path)

    if not os.path.exists(expanded):
        return f"[vision error] image not found: {expanded}"

    ext = os.path.splitext(expanded)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
        return f"[vision error] unsupported image format: {ext}"

    with open(expanded, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    prompt = EXTRACT_PROMPT.format(task=task) if task else DESCRIBE_PROMPT

    try:
        response = ollama.chat(
            model=VISION_MODEL,
            messages=[{
                "role": "user",
                "content": prompt,
                "images": [image_b64],
            }],
            options={"temperature": 0.0},
        )
        return response["message"]["content"].strip()
    except Exception as e:
        return f"[vision error] {e}"


def detect_image_paths(task: str) -> list[str]:
    """
    Find image file paths in a task string and return those that exist on disk.

    Matches absolute paths, home-relative paths (~), and bare filenames with
    image extensions.
    """
    pattern = r'(?:[~/\\][\w\-. /\\]*|[\w]:\\[\w\-. /\\]*|[\w\-./]+)\.(?:png|jpg|jpeg|gif|bmp|webp)'
    candidates = re.findall(pattern, task, re.IGNORECASE)
    found = []
    for c in candidates:
        expanded = os.path.expanduser(c.strip())
        if os.path.exists(expanded):
            found.append(expanded)
    return found


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m harness.vision <image_path> [task description]")
        sys.exit(1)

    path = sys.argv[1]
    task_desc = sys.argv[2] if len(sys.argv) > 2 else ""

    print(f"[vision] extracting context from: {path}")
    if task_desc:
        print(f"[vision] task: {task_desc}")
    print()

    result = extract_image_context(path, task_desc)
    print(result)

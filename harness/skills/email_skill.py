"""
email_skill.py — /email standalone skill.

Given a CSV of contacts + slide content and a stated goal, generates a
personalized email draft (JSON) per speaker and saves them to an output directory.

CSV expectations:
  Required : name, affiliation
  Preferred: markdown (pre-converted slide text), summary, topic_keywords
  Optional : content_url (fetched via MarkItDown if markdown is empty), emails

Usage (via agent.py):
    python agent.py "/email geo-week-talks.csv reach out about our geospatial AI platform save to outreach/"
"""

import csv
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from harness.inference import chat as _llm_chat
from harness.schema import make_id

_KEEP_ALIVE = int(os.environ.get("OLLAMA_KEEP_ALIVE", -1))

_EMAIL_SYSTEM = """\
You are a professional outreach specialist. Your job is to write a warm, specific, \
personalized email from a sender to a conference speaker.

Rules:
- Address the speaker by first name.
- Open by thanking them sincerely for their talk — reference the specific title or topic.
- In the second paragraph, connect their work to the sender's context naturally and briefly.
- In the third paragraph, mention the sender's platform or resource with a light touch — \
  frame it as potentially useful to the speaker or their community, not a sales pitch.
- Close warmly with a simple sign-off.
- Use plain professional prose. No bullet points, no em dashes, no formal titles.
- Output ONLY the email body text — no Subject line, no From/To headers.
- End with the sender's name exactly as given in the context.
"""

_EMAIL_PROMPT_TMPL = """\
Sender: {sender_name}{sender_company_line}
Goal: {goal}

Speaker profile:
  Name        : {name}
  Affiliation : {affiliation}
  Topic       : {keywords}
  Summary     : {summary}

Slide content excerpt:
{slide_excerpt}

Write the personalized email body from {sender_name} to {first_name}.
"""

_SUBJECT_SYSTEM = """\
You write concise, specific email subject lines. Output ONLY the subject line text — \
no quotes, no prefix like "Subject:". Keep it under 60 characters.
"""

_SUBJECT_PROMPT_TMPL = """\
Sender company: {sender_company}
Goal: {goal}
Speaker: {name} ({affiliation})
Topic keywords: {keywords}

Write a natural, specific subject line for a thank-you / introduction email \
from the sender to this conference speaker. Do not start with "Re:" or use \
the speaker's full name in the subject.
"""

_SLIDE_CHAR_LIMIT = 600   # chars of slide markdown fed to the model


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_url_markdown(url: str) -> str:
    """Fetch a URL and convert to markdown via MarkItDown. Returns empty string on failure."""
    try:
        from markitdown import MarkItDown
        md = MarkItDown(enable_plugins=False)
        result = md.convert_url(url)
        return (result.text_content or "")[:8000]
    except Exception as e:
        print(f"    [email] markitdown fetch failed for {url}: {e}")
        return ""


def _safe_filename(name: str) -> str:
    """Convert a speaker name to a safe filename."""
    clean = re.sub(r"[^\w\s-]", "", name).strip()
    return re.sub(r"\s+", "_", clean).lower()


def _parse_list_field(val: str) -> list[str]:
    """Parse a stringified Python list or comma-separated string."""
    if not val or val.strip() in ("[]", ""):
        return []
    try:
        parsed = json.loads(val.replace("'", '"'))
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
    except Exception:
        pass
    return [x.strip() for x in val.strip("[]").split(",") if x.strip()]


def _ollama_chat(model: str, messages: list[dict], num_predict: int = 512) -> tuple[str, int, int]:
    """Returns (text, prompt_tokens, completion_tokens)."""
    resp = _llm_chat(
        model=model,
        messages=messages,
        options={"num_predict": num_predict, "temperature": 0.7},
        keep_alive=_KEEP_ALIVE,
    )
    text = resp["message"]["content"].strip()
    # Strip Qwen3 think blocks
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    in_tok  = resp.get("prompt_eval_count", 0) or 0
    out_tok = resp.get("eval_count", 0) or 0
    return text, in_tok, out_tok


# ---------------------------------------------------------------------------
# Per-draft trace logger
# ---------------------------------------------------------------------------

def _log_draft_trace(
    name, affiliation, to_email, subject, body,
    subject_prompt, body_prompt,
    producer_model,
    subject_tokens_in, subject_tokens_out,
    body_tokens_in, body_tokens_out,
    duration_s, json_path, goal,
):
    """Append one runs.jsonl entry + messages.jsonl turns per email draft."""
    from harness.logger import LOG_PATH
    run_id = make_id()
    now    = datetime.now(UTC).isoformat()
    record = {
        "run_id":         run_id,
        "timestamp":      now,
        "task":           f"Email draft: {name} <{to_email}>",
        "producer_model": producer_model,
        "evaluator_model": None,
        "run_duration_s": duration_s,
        "input_tokens":   subject_tokens_in + body_tokens_in,
        "output_tokens":  subject_tokens_out + body_tokens_out,
        "tokens_by_stage": {
            "subject": {"input": subject_tokens_in, "output": subject_tokens_out, "calls": 1},
            "body":    {"input": body_tokens_in,    "output": body_tokens_out,    "calls": 1},
        },
        "tool_calls": [
            {"name": "subject_prompt", "query": subject_prompt, "result_chars": len(subject)},
            {"name": "body_prompt",    "query": body_prompt,    "result_chars": len(body)},
        ],
        "vision_images": [], "total_search_chars": 0, "quality_floor_hit": False,
        "files_read": [], "code_executions": 0, "injection_stripped": 0, "memory_hits": 0,
        "plan": None, "orchestrated": False, "subtask_count": 0, "synth_forced": False,
        "output_path":  json_path,
        "output_lines": len(body.splitlines()),
        "output_bytes": len(body.encode()),
        "count_check_retry": False,
        "wiggum_rounds": 0, "wiggum_scores": [], "wiggum_dims": [], "wiggum_eval_log": [],
        "final": "PASS",
        "task_type":   "email_draft",
        "email_to":    to_email,
        "email_name":  name,
        "email_affiliation": affiliation,
        "email_subject": subject,
        "email_body":    body,
        "email_goal":    goal,
    }
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    _write_messages(run_id, subject_prompt, subject, body_prompt, body, now)


def _write_messages(
    run_id: str,
    subject_prompt: str, subject: str,
    body_prompt: str, body: str,
    now: str = "",
) -> None:
    """Write LLM turn messages to messages.jsonl so the context-window inspector shows content."""
    from harness.schema import MESSAGES_PATH
    if not now:
        now = datetime.now(UTC).isoformat()
    _turns = [
        (0, "subject", _SUBJECT_SYSTEM, subject_prompt, subject),
        (2, "body",    _EMAIL_SYSTEM,   body_prompt,    body),
    ]
    with open(MESSAGES_PATH, "a", encoding="utf-8") as f:
        for base_seq, stage, system_text, prompt_text, response_text in _turns:
            for seq_off, role, content in [
                (0, "system",    system_text),
                (1, "user",      prompt_text),
                (2, "assistant", response_text),
            ]:
                entry = {
                    "run_id":    run_id,
                    "seq":       base_seq + seq_off,
                    "role":      role,
                    "stage":     stage,
                    "content":   content,
                    "chars":     len(content),
                    "timestamp": now,
                }
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

_SOURCE_EXTS = {".pdf", ".txt", ".md", ".docx", ".html", ".pptx"}


def _load_source(source: str) -> str:
    """Load content from a URL, local file, or treat as raw text."""
    if not source:
        return ""
    if source.startswith("http"):
        print(f"    [email] fetching URL: {source[:70]}")
        return _fetch_url_markdown(source)
    p = Path(source)
    if p.exists():
        suffix = p.suffix.lower()
        if suffix in _SOURCE_EXTS:
            try:
                from markitdown import MarkItDown
                result = MarkItDown(enable_plugins=False).convert(str(p))
                return (result.text_content or "")[:8000]
            except Exception:
                pass
        try:
            return p.read_text(encoding="utf-8")[:8000]
        except Exception as e:
            print(f"    [email] file read failed: {e}")
            return ""
    # Treat as raw inline text
    return source[:2000]


def generate_single_email(
    name: str,
    to_email: str,
    goal: str,
    affiliation: str = "",
    keywords: str = "",
    source: str = "",
    output_dir: str = "email_drafts/",
    producer_model: str = "qwen3-14b",
    sender_name: str = "",
    sender_email: str = "",
    sender_company: str = "",
    platform_url: str = "",
    run_id: str = "",
    log_trace: bool = True,
) -> dict | None:
    """
    Generate a single personalized email draft for one contact.

    source may be a URL, local file path, or raw text excerpt.
    Returns the result dict (with _tokens_in/_tokens_out) or None on failure.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    source_text = _load_source(source)
    slide_excerpt = source_text[:_SLIDE_CHAR_LIMIT] if source_text else "(no content provided)"

    first_name = name.split()[0] if name else "there"
    goal_full  = f"{goal} (platform: {platform_url})" if platform_url else goal
    sender_company_line = f" ({sender_company})" if sender_company else ""

    print(f"  [email] drafting for {name} <{to_email}>...")
    draft_start = time.monotonic()

    subject_prompt = _SUBJECT_PROMPT_TMPL.format(
        goal=goal_full,
        sender_company=sender_company or sender_name,
        name=name,
        affiliation=affiliation,
        keywords=keywords,
    )
    subject, s_in, s_out = _ollama_chat(
        producer_model,
        [{"role": "system", "content": _SUBJECT_SYSTEM},
         {"role": "user",   "content": subject_prompt}],
        num_predict=64,
    )

    body_prompt = _EMAIL_PROMPT_TMPL.format(
        goal=goal_full,
        sender_name=sender_name or "Nick",
        sender_company_line=sender_company_line,
        name=name,
        affiliation=affiliation,
        keywords=keywords,
        summary="",
        slide_excerpt=slide_excerpt,
        first_name=first_name,
    )
    body, b_in, b_out = _ollama_chat(
        producer_model,
        [{"role": "system", "content": _EMAIL_SYSTEM},
         {"role": "user",   "content": body_prompt}],
        num_predict=512,
    )

    draft_duration = round(time.monotonic() - draft_start, 1)

    record = {
        "name":          name,
        "affiliation":   affiliation,
        "to_email":      to_email,
        "email_found":   True,
        "sender_name":   sender_name,
        "sender_email":  sender_email,
        "subject":       subject,
        "body":          body,
        "generated_at":  datetime.now(UTC).isoformat(),
    }
    json_path = out_dir / f"{_safe_filename(name)}.json"
    json_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    record["json_path"] = str(json_path.resolve())

    if log_trace:
        _log_draft_trace(
            name=name, affiliation=affiliation, to_email=to_email,
            subject=subject, body=body,
            subject_prompt=subject_prompt, body_prompt=body_prompt,
            producer_model=producer_model,
            subject_tokens_in=s_in, subject_tokens_out=s_out,
            body_tokens_in=b_in,    body_tokens_out=b_out,
            duration_s=draft_duration,
            json_path=str(json_path.resolve()),
            goal=goal_full,
        )
    elif run_id:
        # Outer trace owns the run record — just write messages under its run_id
        _write_messages(run_id, subject_prompt, subject, body_prompt, body)

    print(f"    -> {json_path.name}  subject: {subject[:50]}")
    record["_tokens_in"]  = s_in + b_in
    record["_tokens_out"] = s_out + b_out
    record["_subject_tokens_in"]  = s_in
    record["_subject_tokens_out"] = s_out
    record["_body_tokens_in"]     = b_in
    record["_body_tokens_out"]    = b_out
    return record


def run_email_standalone(
    csv_path: str,
    goal: str,
    output_dir: str,
    producer_model: str,
    sender_name: str = "",
    sender_email: str = "",
    sender_company: str = "",
    platform_url: str = "",
    max_emails: int = 30,
    filter_keyword: str = "",
) -> list[dict]:
    """
    Generate personalized email JSON drafts for speakers in csv_path.

    Returns a list of result dicts:
      {name, affiliation, json_path, subject, body, to_email, generated_at}
    """
    csv_file = Path(csv_path)
    out_dir  = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not csv_file.exists():
        print(f"  [email] CSV not found: {csv_file}")
        return []

    # --- Load CSV ---
    with open(csv_file, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"  [email] loaded {len(rows)} rows from {csv_file.name}")

    # Optional keyword filter
    if filter_keyword:
        kw = filter_keyword.lower()
        rows = [r for r in rows if kw in (r.get("topic_keywords", "") + r.get("domain", "") + r.get("summary", "")).lower()]
        print(f"  [email] filtered to {len(rows)} rows matching '{filter_keyword}'")

    print(f"  [email] generating up to {max_emails} email draft(s) -> {out_dir}/")

    results: list[dict] = []
    total_in  = 0
    total_out = 0

    for i, row in enumerate(rows, 1):
        if len(results) >= max_emails:
            break

        name        = row.get("name", "").strip()
        affiliation = row.get("affiliation", "").strip()
        first_name  = name.split()[0] if name else "there"
        keywords    = ", ".join(_parse_list_field(row.get("topic_keywords", ""))) or row.get("domain", "")
        summary     = (row.get("summary", "") or "")[:400]

        # Try common column name variants for email address
        emails_raw = (
            row.get("emails", "")
            or row.get("emails_regex", "")
            or row.get("email", "")
            or row.get("contact_email", "")
            or row.get("speaker_email", "")
            or ""
        )
        all_emails = []
        if emails_raw and emails_raw.strip() not in ("[]", ""):
            all_emails = [e for e in _parse_list_field(emails_raw) if "@" in e]

        if all_emails:
            if len(all_emails) > 1:
                print(f"  [{i}/{len(rows)}] {name} has {len(all_emails)} addresses, using first: {all_emails[0]}")
            to_email = all_emails[0]
        else:
            to_email = ""
            print(f"  [{i}/{len(rows)}] {name} — no email found, draft will use placeholder")

        # Slide content — prefer pre-converted markdown, fallback to URL fetch
        slide_md = (row.get("markdown", "") or "").strip()
        if not slide_md and row.get("content_url", "").strip():
            print(f"    [{i}/{len(rows)}] fetching slides for {name}...")
            slide_md = _fetch_url_markdown(row["content_url"])
        slide_excerpt = slide_md[:_SLIDE_CHAR_LIMIT] if slide_md else "(no slide content available)"

        print(f"  [{i}/{len(rows)}] drafting email for {name} ({affiliation})...")
        draft_start = time.monotonic()

        # Build goal string — append platform URL if provided
        goal_full = goal
        if platform_url:
            goal_full = f"{goal} (platform: {platform_url})"

        sender_company_line = f" ({sender_company})" if sender_company else ""

        # --- Generate subject line ---
        subject_prompt = _SUBJECT_PROMPT_TMPL.format(
            goal=goal_full,
            sender_company=sender_company or sender_name,
            name=name,
            affiliation=affiliation,
            keywords=keywords,
        )
        subject, s_in, s_out = _ollama_chat(
            producer_model,
            [
                {"role": "system", "content": _SUBJECT_SYSTEM},
                {"role": "user",   "content": subject_prompt},
            ],
            num_predict=64,
        )
        total_in  += s_in
        total_out += s_out

        # --- Generate email body ---
        body_prompt = _EMAIL_PROMPT_TMPL.format(
            goal=goal_full,
            sender_name=sender_name or "Nick",
            sender_company_line=sender_company_line,
            name=name,
            affiliation=affiliation,
            keywords=keywords,
            summary=summary,
            slide_excerpt=slide_excerpt,
            first_name=first_name,
        )
        body, b_in, b_out = _ollama_chat(
            producer_model,
            [
                {"role": "system", "content": _EMAIL_SYSTEM},
                {"role": "user",   "content": body_prompt},
            ],
            num_predict=512,
        )
        total_in  += b_in
        total_out += b_out

        draft_duration = round(time.monotonic() - draft_start, 1)

        # --- Write per-contact JSON ---
        record = {
            "name":          name,
            "affiliation":   affiliation,
            "to_email":      to_email or "<email-not-found>",
            "email_found":   bool(to_email),
            "sender_name":   sender_name,
            "sender_email":  sender_email,
            "subject":       subject,
            "body":          body,
            "generated_at":  datetime.now(UTC).isoformat(),
        }
        json_filename = f"{_safe_filename(name)}.json"
        json_path     = out_dir / json_filename
        json_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        record["json_path"] = str(json_path.resolve())

        # --- Log individual draft trace to runs.jsonl ---
        _log_draft_trace(
            name=name, affiliation=affiliation, to_email=to_email,
            subject=subject, body=body,
            subject_prompt=subject_prompt, body_prompt=body_prompt,
            producer_model=producer_model,
            subject_tokens_in=s_in, subject_tokens_out=s_out,
            body_tokens_in=b_in,    body_tokens_out=b_out,
            duration_s=draft_duration,
            json_path=str(json_path.resolve()),
            goal=goal_full,
        )

        results.append(record)
        print(f"    -> {json_path.name}  subject: {subject[:50]}")

    # Write manifest
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    n_with_email = sum(1 for r in results if r.get("email_found"))
    print(f"\n  [email] {len(results)} drafts saved to {out_dir}/ "
          f"({n_with_email} with email, {len(results)-n_with_email} placeholder) — manifest: manifest.json")
    print(f"  [email] tokens — in: {total_in:,}  out: {total_out:,}  total: {total_in + total_out:,}")
    for r in results:
        r["_tokens_in"]  = total_in
        r["_tokens_out"] = total_out
    return results

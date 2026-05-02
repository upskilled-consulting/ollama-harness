"""
harness/api/routes/voice.py — /api/voice and /api/notes/save endpoints.

Flow:
  POST /api/voice        multipart audio blob → Whisper → LLM classify → JSON
  POST /api/notes/save   {note_text, timestamp?, filename?} → notes/<file>.md
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from harness.config import ROOT
from harness.inference import chat as _llm_chat

router = APIRouter()

NOTES_DIR = ROOT / "notes"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_ffmpeg() -> str:
    import shutil
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        raise RuntimeError("ffmpeg not found — install via winget or pip install imageio-ffmpeg")


_TS_RE = re.compile(r'^\[(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})\]\s*(.*)')


def _parse_whisper_segments(output: str) -> list[dict]:
    """Parse whisper.cpp stdout into segment dicts with start/end/text."""
    segments = []
    for line in output.splitlines():
        m = _TS_RE.match(line.strip())
        if m and m.group(3).strip():
            segments.append({"start": m.group(1), "end": m.group(2), "text": m.group(3).strip()})
    return segments


def _segments_to_plain(segments: list[dict]) -> str:
    return ' '.join(s["text"] for s in segments).strip()


def _segments_to_markdown(segments: list[dict]) -> str:
    lines = []
    for s in segments:
        start = s["start"][:8]   # drop milliseconds: 00:00:13.880 → 00:00:13
        end   = s["end"][:8]
        lines.append(f"[{start} → {end}]  {s['text']}")
    return '\n'.join(lines)


def _transcribe_blob(blob_path: str) -> tuple[list[dict], str]:
    """Convert audio blob → 16kHz WAV, transcribe with whisper.cpp.

    Returns (segments, wav_path).
      segments  — list of {"start", "end", "text"} dicts
      wav_path  — caller owns this file and must delete or keep it
    """
    import subprocess
    import tempfile

    from harness.config import WHISPER_CPP_CLI, WHISPER_CPP_MODEL

    ffmpeg = _get_ffmpeg()
    wav_fd, wav_path = tempfile.mkstemp(suffix=".wav")
    os.close(wav_fd)

    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", blob_path,
             "-ar", "16000", "-ac", "1", "-f", "wav", wav_path],
            capture_output=True, check=True,
        )
    except subprocess.CalledProcessError as e:
        os.unlink(wav_path)
        raise RuntimeError(f"ffmpeg conversion failed: {e.stderr.decode(errors='replace')[:200]}")

    if not WHISPER_CPP_CLI.exists():
        os.unlink(wav_path)
        raise RuntimeError(f"whisper-cli not found at {WHISPER_CPP_CLI} — set WHISPER_CPP_CLI env var")
    if not WHISPER_CPP_MODEL.exists():
        os.unlink(wav_path)
        raise RuntimeError(f"whisper model not found at {WHISPER_CPP_MODEL} — set WHISPER_CPP_MODEL env var")

    try:
        result = subprocess.run(
            [str(WHISPER_CPP_CLI), "-m", str(WHISPER_CPP_MODEL), "-f", wav_path, "-np"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300,
        )
        raw = result.stdout or result.stderr
    except subprocess.TimeoutExpired:
        os.unlink(wav_path)
        raise RuntimeError("whisper.cpp transcription timed out (300s)")

    segments = _parse_whisper_segments(raw)
    return segments, wav_path


def _save_note_wav(wav_src: str, dest: Path) -> None:
    """Copy the already-converted WAV to its permanent notes location."""
    import shutil
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(wav_src, dest)


_CLASSIFICATION_SYSTEM = """\
You are the voice interface for the Harness Engineering agentic research pipeline.

Your job is to interpret the user's spoken request and return a JSON object — nothing else, no markdown fences.

## Sender context (always available for email tasks)
Name: {sender_name}
Email: {sender_email}
Company: {sender_company}

## Classification rules

Classify as **"task"** when the user wants the agent to:
- Send or draft an email (any mention of "email", "reach out", "follow up", "write to")
- Search the web, fetch a URL, or find information
- Write, save, or generate a file
- Run an experiment, analysis, or pipeline operation
- Do anything that requires the agent to execute

Classify as **"answer"** when the user asks a question about:
- The harness itself, its models, experiments, or architecture
- Something answerable without web access

## Email task rules

When the user wants to send or draft an email, the task_string must start with `/email`.
Three forms — choose the right one:

**Form 1 — single contact, email address known:**
`/email <Full Name> <email@domain.com> "<context>" <goal>`

**Form 2 — single contact, email address NOT known:**
`/email <Full Name> "<company or role>" "<relationship context>" <goal>`

**Form 3 — batch CSV:**
`/email <filename.csv> <goal>`

Rules:
- Wrap multi-word context strings in double quotes in the task_string.
- Do NOT add "save to X.md" for /email tasks — set suggested_path to "email_drafts/".

## ASR correction

Correct common speech-to-text errors:
- "lang chain" → LangChain  |  "open a eye" → OpenAI  |  "hug in face" → Hugging Face
- "git hub" → GitHub  |  "pie torch" → PyTorch  |  "fast api" → FastAPI
- "lama" / "llama" → Llama  |  "geo week" → GeoWeek  |  "esri" → Esri

## Output path rule (non-email tasks)

Non-email agent tasks must end with "save to <path>.md".
If the user didn't specify a path, invent a sensible snake_case filename.

## Browser tasks

Set `uses_browser: true` when the task involves navigating to a URL or headed browsing.

## Response format

Return exactly this JSON, no other text:

{{
  "type": "task" | "answer",
  "corrected_transcript": "<ASR-corrected version>",
  "reasoning": "<one sentence>",
  "task_string": "<complete agent task string>",
  "suggested_path": "<relative path>",
  "uses_browser": true | false,
  "response": "<markdown answer — only for type=answer>"
}}"""


# ---------------------------------------------------------------------------
# POST /api/voice
# ---------------------------------------------------------------------------

@router.post("/voice")
async def api_voice(audio: UploadFile = File(...)):
    # Save blob to temp file
    suffix = Path(audio.filename or "audio.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await audio.read())
        tmp_path = tmp.name

    wav_path = None
    try:
        segments, wav_path = _transcribe_blob(tmp_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"transcription failed: {e}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    transcript = _segments_to_plain(segments)
    if not transcript:
        if wav_path:
            try:
                os.unlink(wav_path)
            except OSError:
                pass
        raise HTTPException(status_code=400, detail="transcript empty")

    # Note shortcut — "note: ..." or "note this is ..." bypasses LLM classification
    note_match = re.match(r"^note[s]?\s*[:,-]?\s*", transcript, re.IGNORECASE)
    if note_match:
        note_text  = transcript[note_match.end():].strip() or transcript
        ts         = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
        date_fmt   = ts[:10]
        wav_dest   = NOTES_DIR / f"op-note-{ts}.wav"
        md_dest    = NOTES_DIR / f"op-note-{ts}.md"
        saved_wav  = None
        saved_md   = None
        timed_body = _segments_to_markdown(segments)
        try:
            _save_note_wav(wav_path, wav_dest)
            saved_wav = str(wav_dest)
        except Exception as e:
            print(f"[voice/note] wav save failed (non-fatal): {e}")
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass
        try:
            NOTES_DIR.mkdir(parents=True, exist_ok=True)
            md_dest.write_text(
                f"# OP Note — {date_fmt}\n\n{timed_body}\n",
                encoding="utf-8",
            )
            saved_md = str(md_dest)
        except Exception as e:
            print(f"[voice/note] md save failed (non-fatal): {e}")
        return JSONResponse({
            "type":       "note",
            "transcript": transcript,
            "note_text":  note_text,
            "wav_path":   saved_wav,
            "md_path":    saved_md,
            "timestamp":  ts,
            "segments":   segments,
        })

    # LLM classification
    producer       = os.environ.get("HARNESS_PRODUCER_MODEL", "qwen3.6-35b")
    sender_name    = os.environ.get("SENDER_NAME", "")
    sender_email   = os.environ.get("SENDER_EMAIL", "")
    sender_company = os.environ.get("SENDER_COMPANY", "")

    system_msg = _CLASSIFICATION_SYSTEM.format(
        sender_name=sender_name,
        sender_email=sender_email,
        sender_company=sender_company,
    )

    try:
        resp = _llm_chat(
            model=producer,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user",   "content": transcript},
            ],
            options={"temperature": 0.2, "num_predict": 1024},
        )
        raw = resp["message"]["content"].strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {
            "type": "answer",
            "corrected_transcript": transcript,
            "reasoning": "",
            "response": raw,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM classification failed: {e}")

    try:
        os.unlink(wav_path)
    except OSError:
        pass

    parsed["transcript"] = transcript
    parsed["segments"]   = segments
    return JSONResponse(parsed)


# ---------------------------------------------------------------------------
# POST /api/notes/save
# ---------------------------------------------------------------------------

class NoteSaveRequest(BaseModel):
    note_text: str
    timestamp: str = ""
    filename:  str = ""


@router.post("/notes/save")
async def api_notes_save(body: NoteSaveRequest):
    note_text = body.note_text.strip()
    if not note_text:
        raise HTTPException(status_code=400, detail="note_text is empty")

    ts       = body.timestamp or datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
    filename = body.filename.strip() or f"op-note-{ts}.md"
    if not filename.endswith(".md"):
        filename += ".md"

    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = NOTES_DIR / filename
    date_fmt = ts[:10] if len(ts) >= 10 else ts
    content  = f"# OP Note — {date_fmt}\n\n{note_text}\n"
    try:
        out_path.write_text(content, encoding="utf-8")
        return {"saved": True, "path": str(out_path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

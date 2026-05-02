"""
youtube_transcribe.py — transcribe YouTube videos and direct media URLs.

YouTube watch URLs:
  1. youtube-transcript-api (no audio download, uses auto-captions)
  2. Fallback: pytubefix → whisper.cpp

Direct media URLs (mp4, mp3, wav, webm, etc.):
  ffmpeg extracts audio → whisper.cpp transcribes

whisper.cpp binary and model are resolved from WHISPER_CPP_CLI / WHISPER_CPP_MODEL
env vars (or config.py defaults).

Install:
    pip install -U pytubefix youtube-transcript-api imageio-ffmpeg
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

_YT_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch\?.*v=|shorts/)|youtu\.be/)[\w\-]+"
)
_MEDIA_EXTENSIONS = {".mp4", ".mp3", ".wav", ".webm", ".ogg", ".m4a", ".mkv", ".flv", ".avi"}


def is_youtube_url(url: str) -> bool:
    return bool(_YT_PATTERN.match(url))


def is_media_url(url: str) -> bool:
    return Path(url.split("?")[0]).suffix.lower() in _MEDIA_EXTENSIONS


def _get_ffmpeg() -> str:
    """Return path to ffmpeg binary — system install or imageio_ffmpeg fallback."""
    import shutil
    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        return sys_ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"  # will surface a clear error if missing


def _ensure_ffmpeg() -> None:
    """Inject imageio_ffmpeg binary dir into PATH so whisper's subprocess finds it."""
    import shutil
    if shutil.which("ffmpeg"):
        return
    try:
        import imageio_ffmpeg
        ffmpeg_dir = os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    except ImportError:
        pass


def _extract_video_id(url: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w\-]+)", url)
    return m.group(1) if m else None


_TS_RE = re.compile(r'^\[(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})\]\s*(.*)')


def _parse_whisper_segments(output: str) -> list[dict]:
    segments = []
    for line in output.splitlines():
        m = _TS_RE.match(line.strip())
        if m and m.group(3).strip():
            segments.append({"start": m.group(1), "end": m.group(2), "text": m.group(3).strip()})
    return segments


def _segments_to_timed_text(segments: list[dict]) -> str:
    """Format segments as '[HH:MM:SS → HH:MM:SS]  text' lines."""
    lines = []
    for s in segments:
        lines.append(f"[{s['start'][:8]} → {s['end'][:8]}]  {s['text']}")
    return '\n'.join(lines)


def _format_yt_captions(entries: list[dict]) -> str:
    """Format youtube-transcript-api entries with HH:MM:SS timestamps."""
    lines = []
    for e in entries:
        t = int(e.get("start", 0))
        ts = f"{t // 3600:02d}:{(t % 3600) // 60:02d}:{t % 60:02d}"
        lines.append(f"[{ts}]  {e['text']}")
    return '\n'.join(lines)


def _whisper_transcribe(audio_path: str) -> str:
    """Transcribe an audio file using the whisper.cpp CLI.

    Returns a timestamped transcript string:
      [HH:MM:SS → HH:MM:SS]  segment text
      ...
    """
    from harness.config import WHISPER_CPP_CLI, WHISPER_CPP_MODEL

    ffmpeg   = _get_ffmpeg()
    is_wav   = audio_path.lower().endswith(".wav")
    wav_path = audio_path if is_wav else audio_path + ".wav"

    if not is_wav:
        try:
            subprocess.run(
                [ffmpeg, "-y", "-i", audio_path,
                 "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav_path],
                check=True, capture_output=True,
            )
        except Exception as e:
            print(f"  [transcribe] ffmpeg pre-convert failed: {e}")
            return ""

    if not WHISPER_CPP_CLI.exists():
        print(f"  [transcribe] whisper-cli not found at {WHISPER_CPP_CLI}")
        return ""
    if not WHISPER_CPP_MODEL.exists():
        print(f"  [transcribe] whisper model not found at {WHISPER_CPP_MODEL}")
        return ""

    print(f"  [transcribe] whisper.cpp on {Path(wav_path).name}...")
    try:
        result = subprocess.run(
            [str(WHISPER_CPP_CLI), "-m", str(WHISPER_CPP_MODEL), "-f", wav_path, "-np"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=600,
        )
        raw = result.stdout or result.stderr
    except subprocess.TimeoutExpired:
        print("  [transcribe] whisper.cpp timed out")
        return ""
    except Exception as e:
        print(f"  [transcribe] failed: {e}")
        return ""
    finally:
        if not is_wav and os.path.exists(wav_path):
            os.unlink(wav_path)

    segments = _parse_whisper_segments(raw)
    text = _segments_to_timed_text(segments)
    if text:
        print(f"  [transcribe] {len(segments)} segments  {len(text)} chars")
    return text


def _ffmpeg_extract_audio(media_url: str, out_path: str) -> bool:
    """Download/convert a direct media URL to wav via ffmpeg. Returns True on success."""
    result = subprocess.run(
        [_get_ffmpeg(), "-i", media_url, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", "-vn", out_path, "-y"],
        capture_output=True,
        timeout=300,
    )
    return result.returncode == 0 and Path(out_path).exists()


def transcribe_youtube(url: str) -> str:
    """
    Transcribe a YouTube watch URL.
    Strategy B (transcript API) → fallback A (pytubefix + whisper).
    """
    video_id = _extract_video_id(url)

    # B: youtube-transcript-api — no audio download, uses auto-captions
    if video_id:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            print(f"  [youtube] fetching auto-captions for {video_id}...")
            entries = YouTubeTranscriptApi.get_transcript(video_id)
            text = _format_yt_captions(entries)
            if text:
                print(f"  [youtube] captions: {len(entries)} segments  {len(text)} chars")
                return f"[YouTube transcript — {url}]\n\n{text}"
        except Exception as e:
            print(f"  [youtube] transcript API failed ({e}), falling back to audio...")

    # A fallback: pytubefix downloads audio stream → whisper
    try:
        from pytubefix import YouTube
    except ImportError:
        print("  [youtube] pytubefix not installed (pip install pytubefix)")
        return ""

    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            print(f"  [youtube] fetching audio stream: {url[:70]}...")
            yt = YouTube(url)
            stream = yt.streams.filter(only_audio=True).order_by("abr").last()
            if not stream:
                print("  [youtube] no audio stream found")
                return ""
            audio_file = stream.download(output_path=tmp_dir, filename="audio")
        except Exception as e:
            print(f"  [youtube] stream fetch failed: {e}")
            return ""

        text = _whisper_transcribe(audio_file)
        if not text:
            return ""
        return f"[YouTube transcript — {url}]\n\n{text}"


def transcribe_media_url(url: str) -> str:
    """
    Transcribe a direct media URL (mp4, mp3, etc.) via ffmpeg + whisper.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_path = str(Path(tmp_dir) / "audio.wav")
        print(f"  [media] extracting audio: {url[:70]}...")
        if not _ffmpeg_extract_audio(url, out_path):
            print("  [media] ffmpeg failed")
            return ""
        text = _whisper_transcribe(out_path)
        if not text:
            return ""
        return f"[Media transcript — {url}]\n\n{text}"

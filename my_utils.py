from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

WORD_RE = re.compile(r"\b\w+\b")
LINE_RE = re.compile(r'^\[(\d{2}):(\d{2}):(\d{2})\s*→\s*(\d{2}):(\d{2}):(\d{2})\]\s*(.+)$')
BAD_ENDINGS = {"in", "of", "and", "to", "the", "a", "an", "for", "with", "on", "at", "by", "from"}


def ts_to_sec(h: str, m: str, s: str) -> int:
    return int(h) * 3600 + int(m) * 60 + int(s)


def clean_text(text: str) -> str:
    return (
        text.replace(" ", " ")
            .replace("“", '"')
            .replace("”", '"')
            .replace("’", "'")
            .strip()
    )


def word_count(text: str) -> int:
    return len(WORD_RE.findall(text))


def ends_badly(text: str) -> bool:
    words = [w.lower() for w in WORD_RE.findall(text)]
    return bool(words) and words[-1] in BAD_ENDINGS


def transcript_to_rows(transcript_path: str | Path, audio_path: str | Path, speaker_id: str = "me") -> list[dict]:
    rows = []
    for raw in Path(transcript_path).read_text(encoding="utf-8").splitlines():
        m = LINE_RE.match(raw.strip())
        if not m:
            continue
        sh, sm, ss, eh, em, es, text = m.groups()
        start, end = ts_to_sec(sh, sm, ss), ts_to_sec(eh, em, es)
        text = clean_text(text)
        if not text:
            continue
        rows.append({
            "audio_filepath": str(audio_path),
            "text": text,
            "start": start,
            "end": end,
            "duration": end - start,
            "speaker_id": speaker_id,
            "source_transcript": str(transcript_path),
        })
    return rows


def build_jsonl_dataset(
    transcripts_dir: str | Path,
    notes_dir: str | Path,
    out_dir: str | Path,
    speaker_id: str = "me",
) -> tuple[Path, Path, list[dict]]:
    transcripts_dir = Path(transcripts_dir)
    notes_dir = Path(notes_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict] = []
    for md in sorted(transcripts_dir.glob("*-transcript.md")):
        stem = md.name.replace("-transcript.md", "")
        audio_path = notes_dir / f"{stem}.wav"
        if audio_path.exists():
            all_rows.extend(transcript_to_rows(md, audio_path, speaker_id=speaker_id))

    jsonl_path = out_dir / "manifest.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in all_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    csv_path = out_dir / "manifest.csv"
    pd.DataFrame(all_rows).to_csv(csv_path, index=False)
    return jsonl_path, csv_path, all_rows


def load_manifest(jsonl_path: str | Path) -> pd.DataFrame:
    rows = []
    with Path(jsonl_path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return pd.DataFrame(rows)


def filter_training_df(
    df: pd.DataFrame,
    min_words: int = 4,
    min_dur: float = 1.5,
    max_dur: float = 10.0,
) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    df = df.copy()
    df["text"] = df["text"].astype(str).map(clean_text)
    df["word_count"] = df["text"].map(word_count)
    df["bad_end"] = df["text"].map(ends_badly)
    df = df[df["duration"].between(min_dur, max_dur)]
    df = df[df["word_count"] >= min_words]
    df = df[~df["bad_end"]]
    return df.drop(columns=["word_count", "bad_end"]).reset_index(drop=True)


def preview_rows(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    cols = [c for c in ["audio_filepath", "text", "start", "end", "duration", "speaker_id"] if c in df.columns]
    return df[cols].head(n)


def write_jsonl(df: pd.DataFrame, path: str | Path) -> None:
    with Path(path).open("w", encoding="utf-8") as f:
        for _, row in df.iterrows():
            f.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")

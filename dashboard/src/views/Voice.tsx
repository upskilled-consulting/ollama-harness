import { useState, useRef, useCallback, useEffect } from "react";
import { Mic, MicOff, Play, X, Copy, Save } from "lucide-react";
import { clsx } from "clsx";
import { useSubmitTask } from "@/hooks/useRuns";

type Status = "idle" | "recording" | "transcribing" | "done";
type ResultType = "task" | "answer" | "note" | null;

interface VoiceResult {
  type:                 ResultType;
  transcript:          string;
  corrected_transcript?: string;
  reasoning?:          string;
  task_string?:        string;
  suggested_path?:     string;
  uses_browser?:       boolean;
  response?:           string;
  note_text?:          string;
  timestamp?:          string;
  wav_path?:           string;
  transcript_path?:    string;
}

const SPACE_HOLD_MS = 900;

export function Voice() {
  const [mode,           setMode]           = useState<"note" | "task">("note");
  const [autoTranscribe, setAutoTranscribe] = useState(true);
  const [status,   setStatus]   = useState<Status>("idle");
  const [result,   setResult]   = useState<VoiceResult | null>(null);
  const [task,     setTask]     = useState("");
  const [noteText, setNoteText] = useState("");
  const [noteFile, setNoteFile] = useState("");
  const [msg,      setMsg]      = useState<{ ok: boolean; text: string } | null>(null);

  const recRef      = useRef<MediaRecorder | null>(null);
  const chunksRef   = useRef<Blob[]>([]);
  const canvasRef   = useRef<HTMLCanvasElement>(null);
  const animRef     = useRef<number>(0);
  const statusRef   = useRef<Status>("idle");
  const spaceDownAt = useRef<number>(0);
  const spaceTimer  = useRef<ReturnType<typeof setTimeout> | null>(null);
  const submit      = useSubmitTask();

  statusRef.current = status;

  // ---------------------------------------------------------------------------
  // Waveform visualiser
  // ---------------------------------------------------------------------------
  const startWaveform = useCallback((stream: MediaStream) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx    = canvas.getContext("2d")!;
    const audio  = new AudioContext();
    const src    = audio.createMediaStreamSource(stream);
    const anal   = audio.createAnalyser();
    anal.fftSize = 512;
    src.connect(anal);
    const buf = new Uint8Array(anal.frequencyBinCount);

    const draw = () => {
      animRef.current = requestAnimationFrame(draw);
      anal.getByteFrequencyData(buf);
      const W = canvas.width, H = canvas.height;
      ctx.clearRect(0, 0, W, H);
      ctx.shadowBlur = 6;
      ctx.shadowColor = "#4ade80";
      ctx.fillStyle   = "#4ade80";
      const barW = W / buf.length * 2.5;
      for (let i = 0; i < buf.length; i++) {
        const h = (buf[i] / 255) * H;
        ctx.fillRect(i * barW, H - h, barW - 1, h);
      }
    };
    draw();

    // Clean up AudioContext when recording stops
    return () => { cancelAnimationFrame(animRef.current); audio.close(); };
  }, []);

  // ---------------------------------------------------------------------------
  // Record / stop
  // ---------------------------------------------------------------------------
  const startRecording = useCallback(async () => {
    if (statusRef.current !== "idle") return;
    setMsg(null);
    setResult(null);
    setTask("");
    setNoteText("");
    setNoteFile("");

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setMsg({ ok: false, text: "Microphone access denied." });
      return;
    }

    const stopWave = startWaveform(stream);
    chunksRef.current = [];
    const rec = new MediaRecorder(stream);
    recRef.current = rec;

    rec.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
    rec.onstop = async () => {
      cancelAnimationFrame(animRef.current);
      stopWave?.();
      stream.getTracks().forEach(t => t.stop());
      // Clear waveform canvas
      const canvas = canvasRef.current;
      if (canvas) canvas.getContext("2d")!.clearRect(0, 0, canvas.width, canvas.height);

      setStatus("transcribing");
      const blob = new Blob(chunksRef.current, { type: "audio/webm" });
      const form = new FormData();
      form.append("audio", blob, "voice.webm");
      form.append("mode", mode);
      form.append("auto_transcribe", autoTranscribe ? "true" : "false");

      try {
        const resp = await fetch("/api/voice", { method: "POST", body: form });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          throw new Error(err.detail || resp.statusText);
        }
        const data: VoiceResult = await resp.json();
        setResult(data);
        if (data.type === "task")   setTask(data.task_string || data.corrected_transcript || data.transcript);
        if (data.type === "note")   setNoteText(data.note_text || data.transcript);
        setStatus("done");
      } catch (e) {
        setMsg({ ok: false, text: `Error: ${String(e)}` });
        setStatus("idle");
      }
    };

    rec.start();
    setStatus("recording");
  }, [startWaveform, mode, autoTranscribe]);

  const stopRecording = useCallback(() => {
    if (statusRef.current === "recording") recRef.current?.stop();
  }, []);

  // ---------------------------------------------------------------------------
  // Push-to-talk (hold Space ≥ 900 ms)
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const onDown = (e: KeyboardEvent) => {
      if (e.code !== "Space" || e.repeat) return;
      if (e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement) return;
      e.preventDefault();
      spaceDownAt.current = Date.now();
      if (statusRef.current === "idle") {
        spaceTimer.current = setTimeout(() => startRecording(), SPACE_HOLD_MS);
      }
    };
    const onUp = (e: KeyboardEvent) => {
      if (e.code !== "Space") return;
      if (spaceTimer.current) { clearTimeout(spaceTimer.current); spaceTimer.current = null; }
      if (statusRef.current === "recording") stopRecording();
    };
    window.addEventListener("keydown", onDown);
    window.addEventListener("keyup",   onUp);
    return () => { window.removeEventListener("keydown", onDown); window.removeEventListener("keyup", onUp); };
  }, [startRecording, stopRecording]);

  useEffect(() => () => { recRef.current?.stop(); }, []);

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------
  const handleRunTask = async () => {
    if (!task.trim()) return;
    setMsg(null);
    try {
      await submit.mutateAsync({ task: task.trim() });
      setMsg({ ok: true, text: "Task queued." });
      setStatus("idle");
      setResult(null);
    } catch (e) {
      setMsg({ ok: false, text: String(e) });
    }
  };

  const handleSaveNote = async () => {
    if (!noteText.trim()) return;
    setMsg(null);
    try {
      const resp = await fetch("/api/notes/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          note_text: noteText.trim(),
          timestamp: result?.timestamp || "",
          filename:  noteFile.trim() || "",
        }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || resp.statusText);
      setMsg({ ok: true, text: `Saved → ${data.path}` });
      setStatus("idle");
      setResult(null);
    } catch (e) {
      setMsg({ ok: false, text: String(e) });
    }
  };

  const discard = () => {
    setStatus("idle");
    setResult(null);
    setTask("");
    setNoteText("");
    setNoteFile("");
    setMsg(null);
  };

  // ---------------------------------------------------------------------------
  // Status label
  // ---------------------------------------------------------------------------
  const statusLabel = {
    idle:         `Click the mic or hold Space to record a ${mode}.`,
    recording:    "Recording… click the mic or release Space to stop.",
    transcribing: "Transcribing…",
    done:         null,
  }[status];

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  return (
    <div>
      <div className="view-header">
        <h1>Voice</h1>
        <p>{mode === "note" ? "Recording as note — hold Space or click mic" : "Recording as task — hold Space or click mic"}</p>
      </div>

      <div className="voice-wrap">
        {/* Mode toggle */}
        <div className="voice-mode-toggle" style={{ display: "flex", gap: 6, marginBottom: mode === "note" ? 10 : 20 }}>
          <button
            className={clsx("btn", mode === "note" ? "btn-primary" : "btn-ghost")}
            onClick={() => setMode("note")}
            disabled={status !== "idle"}
          >Note</button>
          <button
            className={clsx("btn", mode === "task" ? "btn-primary" : "btn-ghost")}
            onClick={() => setMode("task")}
            disabled={status !== "idle"}
          >Task</button>
        </div>
        {mode === "note" && (
          <label className="toggle-label" style={{ marginBottom: 20 }}>
            <input
              type="checkbox"
              checked={autoTranscribe}
              onChange={(e) => setAutoTranscribe(e.target.checked)}
              disabled={status !== "idle"}
            />
            Auto-transcribe to corpus
          </label>
        )}

        {/* Waveform canvas */}
        <canvas
          ref={canvasRef}
          width={300}
          height={32}
          className="voice-wave"
          style={{ display: status === "recording" ? "block" : "none" }}
        />

        {/* Mic FAB */}
        <button
          className={clsx("mic-btn", status === "recording" && "recording")}
          onClick={status === "recording" ? stopRecording : (status === "idle" ? startRecording : undefined)}
          disabled={status === "transcribing"}
          title={status === "recording" ? "Stop recording" : "Start recording"}
        >
          {status === "recording" ? <MicOff size={28} /> : <Mic size={28} />}
        </button>

        {statusLabel && <div className="voice-status">{statusLabel}</div>}

        {/* ── TASK panel ── */}
        {status === "done" && result?.type === "task" && (
          <div className="voice-task-card">
            {result.reasoning && (
              <p className="voice-reasoning">{result.reasoning}</p>
            )}
            <textarea
              className="voice-edit"
              value={task}
              onChange={(e) => setTask(e.target.value)}
              placeholder="Edit the task string before running…"
            />
            <div className="row-gap">
              <button
                className="btn btn-primary"
                onClick={() => void handleRunTask()}
                disabled={!task.trim() || submit.isPending}
              >
                <Play size={13} />
                {submit.isPending ? "Submitting…" : "Run task"}
              </button>
              <button className="btn btn-ghost" onClick={discard}>
                <X size={13} /> Discard
              </button>
            </div>
          </div>
        )}

        {/* ── ANSWER panel ── */}
        {status === "done" && result?.type === "answer" && (
          <div className="voice-task-card">
            <p className="voice-reasoning">{result.corrected_transcript}</p>
            <div className="voice-answer">{result.response}</div>
            <div className="row-gap">
              <button
                className="btn btn-ghost"
                onClick={() => navigator.clipboard.writeText(result.response || "")}
              >
                <Copy size={13} /> Copy
              </button>
              <button className="btn btn-ghost" onClick={discard}>
                <X size={13} /> Dismiss
              </button>
            </div>
          </div>
        )}

        {/* ── NOTE panel ── */}
        {status === "done" && result?.type === "note" && (
          <div className="voice-task-card">
            <p className="voice-reasoning">Review note — edit before saving.</p>
            <textarea
              className="voice-edit"
              value={noteText}
              onChange={(e) => setNoteText(e.target.value)}
              placeholder="Note content…"
            />
            <input
              className="voice-filename"
              value={noteFile}
              onChange={(e) => setNoteFile(e.target.value)}
              placeholder="Filename (optional, e.g. meeting-notes.md)"
            />
            <div className="row-gap">
              <button
                className="btn btn-primary"
                onClick={() => void handleSaveNote()}
                disabled={!noteText.trim()}
              >
                <Save size={13} /> Save note
              </button>
              <button className="btn btn-ghost" onClick={discard}>
                <X size={13} /> Discard
              </button>
            </div>
          </div>
        )}

        {/* Status / error messages */}
        {msg && (
          <span className={clsx("status-msg", msg.ok ? "status-ok" : "status-err")}>
            {msg.text}
          </span>
        )}
      </div>
    </div>
  );
}

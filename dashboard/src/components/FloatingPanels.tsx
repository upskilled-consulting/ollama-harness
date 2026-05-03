import { useState, useRef, useEffect, type KeyboardEvent } from "react";
import { TerminalSquare, Mic, X, RotateCcw } from "lucide-react";
import { Voice } from "@/views/Voice";
import { useSubmitTask } from "@/hooks/useRuns";
import { useQueryClient } from "@tanstack/react-query";
import type { RunRecord } from "@/types";

// ── Terminal panel ─────────────────────────────────────────────────────────────

type HistoryEntry =
  | { kind: "input";  text: string }
  | { kind: "output"; text: string; runId?: string; status?: string }
  | { kind: "error";  text: string };

const OH_BANNER =
`      ___           ___
     /\\  \\         /\\__\\
    /::\\  \\       /:/  /
   /:/\\:\\  \\     /:/__/
  /:/  \\:\\  \\   /::\\  \\ ___
 /:/__/ \\:\\__\\ /:/\\:\\  /\\__\\
 \\:\\  \\ /:/  / \\/__\\:\\/:/  /
  \\:\\  /:/  /       \\::/  /
   \\:\\/:/  /        /:/  /
    \\::/  /        /:/  /
     \\/__/         \\/__/    `;

const OH_WELCOME: HistoryEntry[] = [
  { kind: "output", text: OH_BANNER },
  { kind: "output", text: "ollama-harness agent CLI  —  type a task or /skill" },
  { kind: "output", text: 'type "help" for available skills' },
];

function TerminalPanel({ onClose }: { onClose: () => void }) {
  const [input,   setInput]   = useState("");
  const [history, setHistory] = useState<HistoryEntry[]>(OH_WELCOME);
  const [histIdx, setHistIdx] = useState(-1);
  const inputRef  = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const submit    = useSubmitTask();
  const qc        = useQueryClient();

  // Keep an input history for ↑/↓ navigation
  const inputHistory = useRef<string[]>([]);

  // Scroll to bottom on new entries
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [history]);

  // Watch live runs to update pending status badges
  useEffect(() => {
    const unsub = qc.getQueryCache().subscribe((event) => {
      if (event.query.queryKey[0] !== "runs") return;
      const data = event.query.state.data as { active: RunRecord[]; recent: RunRecord[] } | undefined;
      if (!data) return;
      const all = [...(data.active ?? []), ...(data.recent ?? [])];
      setHistory((prev) =>
        prev.map((e) => {
          if (e.kind !== "output" || !e.runId || e.status) return e;
          const run = all.find((r) => r.run_id === e.runId);
          if (run?.final) return { ...e, status: run.final };
          return e;
        })
      );
    });
    return unsub;
  }, [qc]);

  const push = (entry: HistoryEntry) => setHistory((h) => [...h, entry]);

  const handleSubmit = () => {
    const cmd = input.trim();
    if (!cmd) return;

    push({ kind: "input", text: cmd });
    inputHistory.current = [cmd, ...inputHistory.current.slice(0, 49)];
    setInput("");
    setHistIdx(-1);

    // clear
    if (cmd === "clear" || cmd === "cls") {
      setHistory(OH_WELCOME);
      return;
    }

    // help
    if (cmd === "help") {
      push({ kind: "output", text: [
        "SKILLS",
        "  /lit-review <topic>     fetch papers, annotate, synthesize",
        "  /browser <url> <goal>   LLM-guided web navigation",
        "  /design <url>           extract design system tokens",
        "  /deck --design <url> --content <src>  generate .pptx",
        "  /email <contact> <goal> draft and send via Gmail",
        "  /recall <topic>         surface observations from memory",
        "  /introspect             generate live capabilities doc",
        "  /orientation            summarise project state",
        "  /debug [filter]         diagnose recent FAIL/ERROR runs",
        "",
        "BUILT-INS",
        "  clear   reset terminal",
        "  help    show this message",
        "",
        "Anything else is submitted as a free-form task.",
      ].join("\n") });
      return;
    }

    // Everything else → submit as a harness task
    submit.mutate(
      { task: cmd },
      {
        onSuccess: (data) => {
          const runId = (data as { run_id?: string })?.run_id;
          push({ kind: "output", text: "→ queued", runId, status: undefined });
        },
        onError: (err) => {
          push({ kind: "error", text: `error: ${String(err)}` });
        },
      }
    );
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") { handleSubmit(); return; }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      const next = Math.min(histIdx + 1, inputHistory.current.length - 1);
      setHistIdx(next);
      setInput(inputHistory.current[next] ?? "");
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      const next = histIdx - 1;
      setHistIdx(next);
      setInput(next < 0 ? "" : inputHistory.current[next] ?? "");
    }
  };

  const prompt = "oh >";

  return (
    <div style={{
      width: 520, height: 420,
      background: "#0a0c12", border: "1px solid var(--border)", borderRadius: 12,
      display: "flex", flexDirection: "column", overflow: "hidden",
      boxShadow: "0 24px 48px rgba(0,0,0,0.6)",
    }}>
      {/* title bar */}
      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "8px 12px", borderBottom: "1px solid var(--border)",
        background: "#0d0f18",
      }}>
        <span style={{ fontSize: 11, color: "var(--dim)", fontFamily: "var(--font-mono)", flex: 1 }}>
          oh — ollama-harness
        </span>
        <button onClick={() => setHistory([])} style={{ background: "none", border: "none", color: "var(--dim)", cursor: "pointer", padding: 2 }}>
          <RotateCcw size={13} />
        </button>
        <button onClick={onClose} style={{ background: "none", border: "none", color: "var(--dim)", cursor: "pointer", padding: 2 }}>
          <X size={14} />
        </button>
      </div>

      {/* history */}
      <div ref={scrollRef} style={{
        flex: 1, overflowY: "auto", padding: "10px 14px",
        display: "flex", flexDirection: "column", gap: 2,
        fontFamily: "var(--font-mono)", fontSize: 12, lineHeight: 1.7,
      }}>
        {history.map((e, i) => {
          if (e.kind === "input") return (
            <div key={i} style={{ color: "var(--accent)" }}>
              <span style={{ color: "var(--dim)", userSelect: "none" }}>{prompt} </span>{e.text}
            </div>
          );
          if (e.kind === "error") return (
            <div key={i} style={{ color: "var(--fail)" }}>{e.text}</div>
          );
          // output
          const statusColor = e.status === "PASS" ? "var(--pass)" : e.status === "FAIL" || e.status === "ERROR" ? "var(--fail)" : "var(--warn)";
          return (
            <div key={i} style={{ color: "var(--dim)", whiteSpace: "pre-wrap" }}>
              {e.text}
              {e.runId && (
                <span style={{ marginLeft: 8, color: statusColor, fontSize: 10 }}>
                  [{e.status ?? "running…"}]
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* input */}
      <div style={{
        display: "flex", alignItems: "center", gap: 6,
        padding: "8px 12px", borderTop: "1px solid var(--border)",
        background: "#0d0f18",
      }}>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--dim)", whiteSpace: "nowrap", userSelect: "none" }}>
          {prompt}
        </span>
        <input
          ref={inputRef}
          autoFocus
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          spellCheck={false}
          style={{
            flex: 1, background: "none", border: "none", outline: "none",
            fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text)",
            caretColor: "var(--accent)",
          }}
        />
      </div>
    </div>
  );
}

// ── Voice panel ────────────────────────────────────────────────────────────────

function VoicePanel({ onClose }: { onClose: () => void }) {
  return (
    <div style={{
      width: 420,
      background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 12,
      display: "flex", flexDirection: "column", overflow: "hidden",
      boxShadow: "0 24px 48px rgba(0,0,0,0.6)",
      maxHeight: "80vh", overflowY: "auto",
    }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "10px 14px", borderBottom: "1px solid var(--border)",
        background: "var(--surface)",
      }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text)" }}>Voice</span>
        <button onClick={onClose} style={{ background: "none", border: "none", color: "var(--dim)", cursor: "pointer" }}>
          <X size={14} />
        </button>
      </div>
      <Voice />
    </div>
  );
}

// ── FAB button ─────────────────────────────────────────────────────────────────

function Fab({ icon, active, tooltip, onClick }: {
  icon: React.ReactNode; active: boolean; tooltip: string; onClick: () => void;
}) {
  return (
    <div style={{ position: "relative" }}>
      <button
        onClick={onClick}
        title={tooltip}
        style={{
          width: 44, height: 44, borderRadius: 12,
          background: active ? "rgba(129,140,248,0.2)" : "var(--surface)",
          border: `1px solid ${active ? "var(--accent)" : "var(--border)"}`,
          color: active ? "var(--accent)" : "var(--dim)",
          cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
          boxShadow: "0 4px 12px rgba(0,0,0,0.4)",
          transition: "background 0.15s, border-color 0.15s, color 0.15s",
        }}
      >
        {icon}
      </button>
    </div>
  );
}

// ── Root export ────────────────────────────────────────────────────────────────

export function FloatingPanels() {
  const [open, setOpen] = useState<"terminal" | "voice" | null>(null);

  const toggle = (panel: "terminal" | "voice") =>
    setOpen((cur) => (cur === panel ? null : panel));

  return (
    <div style={{
      position: "fixed", bottom: 24, right: 24,
      display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 10,
      zIndex: 500,
    }}>
      {/* panels — rendered above their respective FAB */}
      {open === "terminal" && (
        <TerminalPanel onClose={() => setOpen(null)} />
      )}
      {open === "voice" && (
        <VoicePanel onClose={() => setOpen(null)} />
      )}

      {/* FAB stack */}
      <Fab
        icon={<TerminalSquare size={18} />}
        active={open === "terminal"}
        tooltip="Terminal"
        onClick={() => toggle("terminal")}
      />
      <Fab
        icon={<Mic size={18} />}
        active={open === "voice"}
        tooltip="Voice"
        onClick={() => toggle("voice")}
      />
    </div>
  );
}

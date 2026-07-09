import { useState, useEffect, type CSSProperties } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAutoresearch } from "@/hooks/useRuns";
import type { AutoresearchRecord, FeedbackRecord } from "@/types";

// ---------------------------------------------------------------------------
// RLHF panel (reused pattern from Runs view)
// ---------------------------------------------------------------------------

const AR_RUN_ID = "autoresearch";

function expNodeId(rec: AutoresearchRecord) {
  return `exp-${rec.experiment}-${rec.timestamp.slice(0, 19)}`;
}

function RlhfPanel({ nodeId }: { nodeId: string }) {
  const [rating,     setRating]     = useState<1 | -1 | null>(null);
  const [comment,    setComment]    = useState("");
  const [saved,      setSaved]      = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const qc = useQueryClient();

  const { data: feedbackList } = useQuery({
    queryKey: ["feedback", AR_RUN_ID],
    queryFn:  () => fetch(`/api/feedback/${AR_RUN_ID}`).then((r) => r.json() as Promise<FeedbackRecord[]>),
    staleTime: 10_000,
  });

  useEffect(() => {
    const existing = [...(feedbackList ?? [])].reverse().find((f) => f.node_id === nodeId);
    if (existing) { setRating(existing.rating as 1 | -1); setComment(existing.comment ?? ""); setSaved(true); }
    else          { setRating(null); setComment(""); setSaved(false); }
  }, [feedbackList, nodeId]);

  const submit = async () => {
    if (rating === null) return;
    setSubmitting(true);
    try {
      await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: AR_RUN_ID, node_id: nodeId, rating, comment }),
      });
      setSaved(true);
      void qc.invalidateQueries({ queryKey: ["feedback", AR_RUN_ID] });
    } finally { setSubmitting(false); }
  };

  const thumb = (active: boolean, color: string): CSSProperties => ({
    background: active ? `${color}20` : "none",
    border: `1px solid ${active ? color : "var(--border)"}`,
    color: active ? color : "var(--dim)",
    borderRadius: 6, padding: "3px 10px", cursor: "pointer", fontSize: 13, lineHeight: 1,
  });

  return (
    <div style={{ paddingTop: 10, borderTop: "1px solid var(--border)" }}>
      <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--dim)", marginBottom: 7 }}>
        Rate this proposal
      </div>
      <div style={{ display: "flex", gap: 6, marginBottom: 7, alignItems: "center" }}>
        <button style={thumb(rating === 1, "#34d399")} onClick={() => { setRating(1); setSaved(false); }} title="Good proposal">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M7 10v12M15 5.88L14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"/>
          </svg>
        </button>
        <button style={thumb(rating === -1, "#f87171")} onClick={() => { setRating(-1); setSaved(false); }} title="Bad proposal">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M17 14V2M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z"/>
          </svg>
        </button>
        {saved && <span style={{ fontSize: 10, color: "var(--pass)", marginLeft: 2 }}>✓ saved</span>}
      </div>
      <textarea
        value={comment} onChange={(e) => { setComment(e.target.value); setSaved(false); }}
        placeholder="Add a comment…" rows={2}
        style={{
          width: "100%", background: "var(--bg)", border: "1px solid var(--border)",
          borderRadius: 5, color: "var(--text)", fontSize: 11, padding: "5px 8px",
          resize: "vertical", fontFamily: "inherit", marginBottom: 6, outline: "none",
          boxSizing: "border-box",
        }}
      />
      <button onClick={submit} disabled={rating === null || submitting}
        style={{
          background: rating !== null ? "rgba(129,140,248,0.12)" : "none",
          border: "1px solid var(--accent)",
          color: rating !== null ? "var(--accent)" : "var(--dim)",
          borderRadius: 5, padding: "4px 0",
          cursor: rating !== null ? "pointer" : "not-allowed",
          fontSize: 11, width: "100%",
        }}>
        {submitting ? "Saving…" : saved ? "✓ Feedback saved" : "Submit feedback"}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

const STATUS_CFG: Record<string, { label: string; color: string; bg: string }> = {
  baseline: { label: "BASELINE", color: "#94a3b8", bg: "rgba(148,163,184,0.12)" },
  keep:     { label: "KEEP",     color: "#22c55e", bg: "rgba(34,197,94,0.12)"   },
  discard:  { label: "DISCARD",  color: "#f87171", bg: "rgba(248,113,113,0.12)" },
};

function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_CFG[status] ?? { label: status.toUpperCase(), color: "var(--dim)", bg: "var(--surface2)" };
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, letterSpacing: "0.06em",
      padding: "2px 7px", borderRadius: 4,
      color: cfg.color, background: cfg.bg,
      fontFamily: "var(--font-mono, monospace)",
    }}>
      {cfg.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// KPI card
// ---------------------------------------------------------------------------

function KpiCard({ label, value, color, sub }: { label: string; value: string | number; color?: string; sub?: string }) {
  return (
    <div className="kpi-card" style={{ minWidth: 120 }}>
      <div className="kpi-value" style={color ? { color } : undefined}>{value}</div>
      <div className="kpi-label">{label}</div>
      {sub && <div style={{ fontSize: 10, color: "var(--dim)", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Mini delta pill
// ---------------------------------------------------------------------------

function DeltaPill({ delta }: { delta: number }) {
  const positive = delta > 0;
  const zero     = Math.abs(delta) < 0.001;
  const color    = zero ? "var(--dim)" : positive ? "#22c55e" : "#f87171";
  return (
    <span className="mono" style={{ fontSize: 11, color }}>
      {zero ? "±0.000" : `${positive ? "+" : ""}${delta.toFixed(3)}`}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Experiment row
// ---------------------------------------------------------------------------

function ExpRow({ rec, selected, onSelect }: {
  rec: AutoresearchRecord;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <div
      onClick={onSelect}
      style={{
        display: "grid",
        gridTemplateColumns: "48px 80px 64px 80px 64px 90px 1fr",
        gap: 12, alignItems: "center",
        padding: "8px 12px", borderRadius: 6, cursor: "pointer",
        background: selected ? "var(--surface2, rgba(255,255,255,0.07))" : "transparent",
        borderLeft: selected ? "2px solid var(--accent, #6366f1)" : "2px solid transparent",
      }}
      className="hover-row"
    >
      <span className="mono" style={{ fontSize: 12 }}>#{rec.experiment}</span>
      <StatusBadge status={rec.status} />
      <span className="mono" style={{ fontSize: 12 }}>{rec.score.toFixed(3)}</span>
      <DeltaPill delta={rec.delta} />
      <span className="mono" style={{ fontSize: 11, color: rec.consecutive_discards >= 4 ? "#f59e0b" : "var(--dim)" }}>
        {rec.consecutive_discards}
        {rec.kimi_fired && <span title="Kimi unblock fired" style={{ marginLeft: 4 }}>🤖</span>}
      </span>
      <span style={{ fontSize: 11, color: "var(--dim)" }}>{rec.tasks.join("+") || "—"}</span>
      <span style={{ fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
            title={rec.description}>
        {rec.description}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail panel
// ---------------------------------------------------------------------------

function InstructionBlock({ label, text }: { label: string; text: string }) {
  if (!text) return null;
  return (
    <div>
      <div style={{ fontSize: 10, color: "var(--dim)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>
        {label}
      </div>
      <pre style={{
        background: "var(--surface2, rgba(255,255,255,0.05))",
        borderRadius: 6, padding: "10px 12px",
        fontSize: 11, lineHeight: 1.6,
        whiteSpace: "pre-wrap", wordBreak: "break-word",
        margin: 0, maxHeight: 200, overflowY: "auto",
        fontFamily: "var(--font-mono, monospace)",
      }}>
        {text}
      </pre>
    </div>
  );
}

function ThinkingBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  if (!text) return null;
  const words = text.split(/\s+/).length;
  return (
    <div>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          display: "flex", alignItems: "center", gap: 6,
          background: "none", border: "none", cursor: "pointer",
          padding: "4px 0", width: "100%", textAlign: "left",
        }}
      >
        <span style={{ fontSize: 10, color: "var(--dim)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
          CoT reasoning
        </span>
        <span style={{ fontSize: 10, color: "var(--dim)" }}>({words} words)</span>
        <span style={{ fontSize: 11, color: "var(--dim)", marginLeft: "auto" }}>{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <pre style={{
          background: "rgba(99,102,241,0.06)",
          border: "1px solid rgba(99,102,241,0.15)",
          borderRadius: 6, padding: "10px 12px",
          fontSize: 11, lineHeight: 1.6,
          whiteSpace: "pre-wrap", wordBreak: "break-word",
          margin: "6px 0 0", maxHeight: 340, overflowY: "auto",
          fontFamily: "var(--font-mono, monospace)",
          color: "var(--dim)",
        }}>
          {text}
        </pre>
      )}
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
      <span style={{ fontSize: 10, color: "var(--dim)", minWidth: 72, paddingTop: 2, textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {label}
      </span>
      <span style={{ fontSize: 12, flex: 1 }}>{value}</span>
    </div>
  );
}

function ExpDetail({ rec, onClose }: { rec: AutoresearchRecord; onClose: () => void }) {
  const deltaColor = rec.delta > 0 ? "#22c55e" : rec.delta < 0 ? "#f87171" : "var(--dim)";
  return (
    <div style={{
      position: "sticky", top: 16,
      background: "var(--surface, #1a1a2e)", border: "1px solid var(--border, rgba(255,255,255,0.1))",
      borderRadius: 10, padding: 20, minWidth: 300, maxWidth: 380,
      display: "flex", flexDirection: "column", gap: 16,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span className="mono" style={{ fontSize: 13, fontWeight: 600 }}>Exp #{rec.experiment}</span>
          <StatusBadge status={rec.status} />
        </div>
        <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--dim)", fontSize: 16 }}>✕</button>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <DetailRow label="Time"   value={<span className="mono" style={{ fontSize: 11 }}>{rec.timestamp.slice(0, 19).replace("T", " ")}</span>} />
        <DetailRow label="Score"  value={<span className="mono">{rec.score.toFixed(3)}</span>} />
        <DetailRow label="Delta"  value={<span className="mono" style={{ color: deltaColor }}>{rec.delta > 0 ? "+" : ""}{rec.delta.toFixed(3)}</span>} />
        <DetailRow label="Tasks"  value={rec.tasks.join(", ") || "—"} />
        <DetailRow label="Discards" value={
          <span className="mono" style={{ color: rec.consecutive_discards >= 4 ? "#f59e0b" : undefined }}>
            {rec.consecutive_discards} consecutive
          </span>
        } />
        {rec.kimi_fired && <DetailRow label="Kimi" value={<span style={{ color: "#f59e0b" }}>Unblock fired this experiment</span>} />}
      </div>

      <div>
        <div style={{ fontSize: 10, color: "var(--dim)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>DESCRIPTION</div>
        <div style={{
          background: "var(--surface2, rgba(255,255,255,0.05))", borderRadius: 6,
          padding: "8px 10px", fontSize: 12, lineHeight: 1.5,
          borderLeft: "3px solid var(--accent, #6366f1)",
        }}>
          {rec.description}
        </div>
      </div>

      <InstructionBlock label="SYNTH_INSTRUCTION"       text={rec.synth} />
      <InstructionBlock label="SYNTH_INSTRUCTION_COUNT" text={rec.synth_count} />
      <InstructionBlock label="SYNTH_INSTRUCTION_PROSE" text={rec.synth_prose} />
      <ThinkingBlock text={rec.thinking} />
      <RlhfPanel nodeId={expNodeId(rec)} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Score sparkline (SVG)
// ---------------------------------------------------------------------------

function Sparkline({ records }: { records: AutoresearchRecord[] }) {
  const pts = records.filter((r) => r.status !== "baseline");
  if (pts.length < 2) return null;
  const scores = pts.map((r) => r.score);
  const min = Math.min(...scores);
  const max = Math.max(...scores);
  const range = max - min || 1;
  const W = 240, H = 40, pad = 4;

  const points = pts.map((r, i) => {
    const x = pad + (i / (pts.length - 1)) * (W - pad * 2);
    const y = H - pad - ((r.score - min) / range) * (H - pad * 2);
    return `${x},${y}`;
  }).join(" ");

  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ fontSize: 10, color: "var(--dim)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>
        Score trend (non-baseline)
      </div>
      <svg width={W} height={H} style={{ display: "block" }}>
        <polyline points={points} fill="none" stroke="var(--accent, #6366f1)" strokeWidth={1.5} strokeLinejoin="round" />
        {pts.map((r, i) => {
          const x = pad + (i / (pts.length - 1)) * (W - pad * 2);
          const y = H - pad - ((r.score - min) / range) * (H - pad * 2);
          const color = r.status === "keep" ? "#22c55e" : "#f87171";
          return <circle key={i} cx={x} cy={y} r={3} fill={color} />;
        })}
      </svg>
      <div style={{ display: "flex", gap: 12, marginTop: 4 }}>
        <span style={{ fontSize: 10, color: "var(--dim)" }}>min {min.toFixed(3)}</span>
        <span style={{ fontSize: 10, color: "var(--dim)" }}>max {max.toFixed(3)}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Column headers
// ---------------------------------------------------------------------------

const COLS = ["#", "Status", "Score", "Δ Score", "Discards", "Tasks", "Description"];
const COL_WIDTHS = "48px 80px 64px 80px 64px 90px 1fr";

// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------

export function Autoresearch() {
  const [selected, setSelected] = useState<AutoresearchRecord | null>(null);
  const { data, isLoading, error } = useAutoresearch();

  const records = data?.records ?? [];
  const summary = data?.summary;

  return (
    <div>
      <div className="view-header">
        <h1>Autoresearch</h1>
        <p>Real-time supervision of the synthesis instruction optimizer · polls every 5 s</p>
      </div>

      {/* Summary KPIs */}
      {summary && (
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 24 }}>
          <KpiCard label="Experiments"  value={summary.total_experiments} />
          <KpiCard label="Keeps"        value={summary.keeps}    color="#22c55e" />
          <KpiCard label="Discards"     value={summary.discards} color="#f87171" />
          <KpiCard label="Keep rate"    value={`${(summary.keep_rate * 100).toFixed(0)}%`} />
          <KpiCard label="Baseline"     value={summary.baseline_score?.toFixed(3) ?? "—"} />
          <KpiCard label="Best score"   value={summary.best_score?.toFixed(3) ?? "—"} color="#22c55e" />
          <KpiCard label="Avg Δ"        value={`${summary.avg_delta >= 0 ? "+" : ""}${summary.avg_delta.toFixed(3)}`}
                   color={summary.avg_delta >= 0 ? "#22c55e" : "#f87171"} />
          <KpiCard label="Kimi fires"   value={summary.kimi_fires} color={summary.kimi_fires > 0 ? "#f59e0b" : undefined} />
          <KpiCard label="Max consec. disc." value={summary.max_consecutive_discards}
                   color={summary.max_consecutive_discards >= 6 ? "#f59e0b" : undefined} />
        </div>
      )}

      {/* Sparkline */}
      {records.length > 1 && <Sparkline records={records} />}

      {/* Table + detail split */}
      <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          {/* Column headers */}
          <div style={{
            display: "grid",
            gridTemplateColumns: COL_WIDTHS,
            gap: 12, padding: "4px 12px 8px",
            borderBottom: "1px solid var(--border, rgba(255,255,255,0.08))",
          }}>
            {COLS.map((h) => (
              <span key={h} style={{ fontSize: 10, color: "var(--dim)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                {h}
              </span>
            ))}
          </div>

          {isLoading ? (
            <div className="loading">Loading autoresearch data…</div>
          ) : error ? (
            <div className="page-error">Could not load autoresearch data. Is the server running?</div>
          ) : records.length === 0 ? (
            <div style={{ padding: "48px 12px", color: "var(--dim)", textAlign: "center" }}>
              <div style={{ fontSize: 32, marginBottom: 12 }}>🔬</div>
              <div style={{ fontSize: 14, marginBottom: 6 }}>No autoresearch experiments yet</div>
              <div style={{ fontSize: 12 }}>
                Run <code style={{ fontFamily: "monospace" }}>python harness/autoresearch.py --mode auto</code> to start.
              </div>
            </div>
          ) : (
            <div>
              {[...records].reverse().map((rec) => (
                <ExpRow
                  key={`${rec.experiment}-${rec.timestamp}`}
                  rec={rec}
                  selected={selected?.experiment === rec.experiment && selected?.timestamp === rec.timestamp}
                  onSelect={() => setSelected(
                    (selected?.experiment === rec.experiment && selected?.timestamp === rec.timestamp) ? null : rec
                  )}
                />
              ))}
            </div>
          )}
        </div>

        {selected && (
          <ExpDetail rec={selected} onClose={() => setSelected(null)} />
        )}
      </div>
    </div>
  );
}

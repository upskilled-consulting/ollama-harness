import { useState } from "react";
import { useSecurityEvents, useSecuritySummary } from "@/hooks/useRuns";
import type { SecurityEvent } from "@/types";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SEVERITY_CFG: Record<string, { label: string; color: string; bg: string }> = {
  block: { label: "BLOCK", color: "#ef4444", bg: "rgba(239,68,68,0.12)" },
  warn:  { label: "WARN",  color: "#f59e0b", bg: "rgba(245,158,11,0.12)" },
  info:  { label: "INFO",  color: "#6366f1", bg: "rgba(99,102,241,0.12)" },
};

const LAYER_LABELS: Record<string, string> = {
  python_scanner:   "Python scanner",
  file_sandbox:     "File sandbox",
  output_sandbox:   "Output sandbox",
  injection_scanner:"Injection scanner",
  cdp_guard:        "CDP guard",
  scratch_guard:    "Scratch guard",
};

const TYPE_LABELS: Record<string, string> = {
  python_blocked:      "Python blocked",
  file_blocked:        "File blocked",
  output_blocked:      "Output blocked",
  injection_detected:  "Injection detected",
  cdp_blocked:         "CDP blocked",
  scratch_blocked:     "Scratch blocked",
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SeverityBadge({ severity }: { severity: string }) {
  const cfg = SEVERITY_CFG[severity] ?? { label: severity.toUpperCase(), color: "var(--dim)", bg: "var(--surface2)" };
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

function KpiCard({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div className="kpi-card" style={{ minWidth: 110 }}>
      <div className="kpi-value" style={color ? { color } : undefined}>{value}</div>
      <div className="kpi-label">{label}</div>
    </div>
  );
}

function FilterChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        fontSize: 11, padding: "3px 10px", borderRadius: 20, border: "none", cursor: "pointer",
        background: active ? "var(--accent, #6366f1)" : "var(--surface2, rgba(255,255,255,0.07))",
        color: active ? "#fff" : "var(--dim)",
        fontWeight: active ? 600 : 400,
        transition: "background 0.15s, color 0.15s",
      }}
    >
      {label}
    </button>
  );
}

function EventRow({ event, selected, onSelect }: { event: SecurityEvent; selected: boolean; onSelect: () => void }) {
  return (
    <div
      onClick={onSelect}
      style={{
        display: "grid",
        gridTemplateColumns: "140px 60px 140px 1fr 1fr",
        gap: 12, alignItems: "center",
        padding: "8px 12px", borderRadius: 6, cursor: "pointer",
        background: selected ? "var(--surface2, rgba(255,255,255,0.07))" : "transparent",
        borderLeft: selected ? "2px solid var(--accent, #6366f1)" : "2px solid transparent",
      }}
      className="hover-row"
    >
      <span className="mono" style={{ fontSize: 11, color: "var(--dim)" }}>
        {event.timestamp.slice(0, 19).replace("T", " ")}
      </span>
      <SeverityBadge severity={event.severity} />
      <span style={{ fontSize: 11, color: "var(--dim)" }}>
        {LAYER_LABELS[event.layer] ?? event.layer}
      </span>
      <span className="mono" style={{ fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
            title={event.resource}>
        {event.resource}
      </span>
      <span style={{ fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--dim)" }}
            title={event.reason}>
        {event.reason}
      </span>
    </div>
  );
}

function EventDetail({ event, onClose }: { event: SecurityEvent; onClose: () => void }) {
  const sev = SEVERITY_CFG[event.severity] ?? { label: event.severity, color: "var(--dim)", bg: "transparent" };
  return (
    <div style={{
      position: "sticky", top: 16,
      background: "var(--surface, #1a1a2e)", border: "1px solid var(--border, rgba(255,255,255,0.1))",
      borderRadius: 10, padding: 20, minWidth: 280, maxWidth: 340,
      display: "flex", flexDirection: "column", gap: 14,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <SeverityBadge severity={event.severity} />
        <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--dim)", fontSize: 16 }}>✕</button>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <DetailRow label="Event ID" value={<span className="mono" style={{ fontSize: 11 }}>{event.event_id}</span>} />
        <DetailRow label="Time" value={event.timestamp.slice(0, 19).replace("T", " ")} />
        <DetailRow label="Type" value={TYPE_LABELS[event.event_type] ?? event.event_type} />
        <DetailRow label="Layer" value={LAYER_LABELS[event.layer] ?? event.layer} />
        {event.caller && <DetailRow label="Caller" value={<span className="mono" style={{ fontSize: 11 }}>{event.caller}</span>} />}
        {event.run_id && (
          <DetailRow label="Run ID" value={
            <span className="mono" style={{ fontSize: 11, color: "var(--accent, #818cf8)" }}>
              {event.run_id}
            </span>
          } />
        )}
      </div>

      <div>
        <div className="section-title" style={{ fontSize: 10, marginBottom: 6 }}>REASON</div>
        <div style={{
          background: "var(--surface2, rgba(255,255,255,0.05))", borderRadius: 6, padding: "8px 10px",
          fontSize: 12, lineHeight: 1.5, wordBreak: "break-all",
          borderLeft: `3px solid ${sev.color}`,
        }}>
          {event.reason}
        </div>
      </div>

      <div>
        <div className="section-title" style={{ fontSize: 10, marginBottom: 6 }}>RESOURCE</div>
        <pre style={{
          background: "var(--surface2, rgba(255,255,255,0.05))", borderRadius: 6,
          padding: "8px 10px", fontSize: 11, overflowX: "auto", whiteSpace: "pre-wrap",
          wordBreak: "break-all", margin: 0, maxHeight: 200, overflowY: "auto",
        }}>
          {event.resource}
        </pre>
      </div>
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
      <span style={{ fontSize: 10, color: "var(--dim)", minWidth: 60, paddingTop: 2, textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {label}
      </span>
      <span style={{ fontSize: 12, flex: 1 }}>{value}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------

export function Security() {
  const [search,    setSearch]    = useState("");
  const [severity,  setSeverity]  = useState("");
  const [eventType, setEventType] = useState("");
  const [layer,     setLayer]     = useState("");
  const [selected,  setSelected]  = useState<SecurityEvent | null>(null);

  const { data: summary } = useSecuritySummary();
  const { data, isLoading, error } = useSecurityEvents({
    search: search || undefined,
    severity:   severity   || undefined,
    event_type: eventType  || undefined,
    layer:      layer      || undefined,
  });

  const events  = data?.events ?? [];
  const total   = data?.total  ?? 0;

  const severities  = ["block", "warn", "info"];
  const eventTypes  = Object.keys(TYPE_LABELS);
  const layers      = Object.keys(LAYER_LABELS);

  return (
    <div>
      <div className="view-header">
        <h1>Security</h1>
        <p>Audit log of all security checks · blocks, injection detections, sandbox violations</p>
      </div>

      {/* KPI row */}
      {summary && (
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 24 }}>
          <KpiCard label="Total events" value={summary.total} />
          <KpiCard label="Blocked" value={summary.by_severity["block"] ?? 0} color="#ef4444" />
          <KpiCard label="Warnings" value={summary.by_severity["warn"]  ?? 0} color="#f59e0b" />
          {Object.entries(summary.by_type).map(([k, v]) => (
            <KpiCard key={k} label={TYPE_LABELS[k] ?? k} value={v} />
          ))}
        </div>
      )}

      {/* Filters */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 18 }}>
        <input
          type="text" placeholder="Search resource or reason…"
          value={search} onChange={(e) => setSearch(e.target.value)}
          style={{
            background: "var(--surface2, rgba(255,255,255,0.07))", border: "1px solid var(--border, rgba(255,255,255,0.1))",
            borderRadius: 8, padding: "7px 12px", color: "inherit", fontSize: 13, outline: "none",
            width: "100%", maxWidth: 460,
          }}
        />
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          <span style={{ fontSize: 11, color: "var(--dim)", marginRight: 2 }}>Severity:</span>
          <FilterChip label="All" active={!severity} onClick={() => setSeverity("")} />
          {severities.map((s) => (
            <FilterChip key={s} label={s} active={severity === s} onClick={() => setSeverity(severity === s ? "" : s)} />
          ))}
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          <span style={{ fontSize: 11, color: "var(--dim)", marginRight: 2 }}>Type:</span>
          <FilterChip label="All" active={!eventType} onClick={() => setEventType("")} />
          {eventTypes.map((t) => (
            <FilterChip key={t} label={TYPE_LABELS[t]} active={eventType === t} onClick={() => setEventType(eventType === t ? "" : t)} />
          ))}
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          <span style={{ fontSize: 11, color: "var(--dim)", marginRight: 2 }}>Layer:</span>
          <FilterChip label="All" active={!layer} onClick={() => setLayer("")} />
          {layers.map((l) => (
            <FilterChip key={l} label={LAYER_LABELS[l]} active={layer === l} onClick={() => setLayer(layer === l ? "" : l)} />
          ))}
        </div>
      </div>

      {/* Event list + detail panel */}
      <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          {/* Column headers */}
          <div style={{
            display: "grid",
            gridTemplateColumns: "140px 60px 140px 1fr 1fr",
            gap: 12, padding: "4px 12px 8px",
            borderBottom: "1px solid var(--border, rgba(255,255,255,0.08))",
          }}>
            {["Time", "Severity", "Layer", "Resource", "Reason"].map((h) => (
              <span key={h} style={{ fontSize: 10, color: "var(--dim)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                {h}
              </span>
            ))}
          </div>

          {isLoading ? (
            <div className="loading">Loading security events…</div>
          ) : error ? (
            <div className="page-error">Could not load security events. Is the server running?</div>
          ) : events.length === 0 ? (
            <div style={{ padding: "48px 12px", color: "var(--dim)", textAlign: "center" }}>
              <div style={{ fontSize: 32, marginBottom: 12 }}>🔒</div>
              <div style={{ fontSize: 14, marginBottom: 6 }}>No security events recorded yet</div>
              <div style={{ fontSize: 12 }}>Events are logged automatically when security checks trigger.</div>
            </div>
          ) : (
            <div>
              <div style={{ fontSize: 11, color: "var(--dim)", padding: "6px 12px" }}>
                {total} event{total !== 1 ? "s" : ""}{total > events.length ? ` (showing ${events.length})` : ""}
              </div>
              {events.map((e) => (
                <EventRow
                  key={e.event_id}
                  event={e}
                  selected={selected?.event_id === e.event_id}
                  onSelect={() => setSelected(selected?.event_id === e.event_id ? null : e)}
                />
              ))}
            </div>
          )}
        </div>

        {selected && (
          <EventDetail event={selected} onClose={() => setSelected(null)} />
        )}
      </div>
    </div>
  );
}

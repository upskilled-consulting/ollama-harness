import { useSessions } from "@/hooks/useRuns";
import type { Session } from "@/types";

function fmt(iso?: string | null): string {
  if (!iso) return "—";
  return iso.slice(0, 16).replace("T", " ");
}

function dur(s?: number | null): string {
  if (s == null) return "—";
  if (s < 60)   return `${Math.round(s)}s`;
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return `${m}m ${sec}s`;
}

function tok(n?: number): string {
  if (!n) return "—";
  return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : `${(n / 1000).toFixed(0)}k`;
}

function SessionRow({ s }: { s: Session }) {
  const id = s.session_id.slice(-8);
  const isActive = !s.ended_at;
  return (
    <tr>
      <td>
        <span className="mono dim" title={s.session_id}>{id}</span>
        {isActive && <span className="badge running" style={{ marginLeft: 6 }}>active</span>}
      </td>
      <td className="mono">{fmt(s.started_at)}</td>
      <td className="mono">{fmt(s.ended_at)}</td>
      <td className="mono">{dur(s.duration_s)}</td>
      <td className="mono" style={{ textAlign: "right" }}>{s.runs ?? 0}</td>
      <td className="mono" style={{ textAlign: "right" }}>{s.artifacts ?? 0}</td>
      <td className="mono dim" style={{ textAlign: "right" }}>{tok(s.total_input_tokens)}</td>
      <td className="mono dim" style={{ textAlign: "right" }}>{tok(s.total_output_tokens)}</td>
    </tr>
  );
}

export function Sessions() {
  const { data, isLoading, error } = useSessions();

  if (isLoading) return <div className="loading">Loading…</div>;
  if (error)     return <div className="page-error">Could not load sessions.</div>;

  const sessions = data ?? [];
  const totalRuns = sessions.reduce((acc, s) => acc + (s.runs ?? 0), 0);
  const totalArtifacts = sessions.reduce((acc, s) => acc + (s.artifacts ?? 0), 0);
  const totalTokIn = sessions.reduce((acc, s) => acc + (s.total_input_tokens ?? 0), 0);
  const totalTokOut = sessions.reduce((acc, s) => acc + (s.total_output_tokens ?? 0), 0);

  return (
    <div>
      <div className="view-header">
        <h1>Sessions</h1>
        <p>{sessions.length} sessions · {totalRuns} runs · {totalArtifacts} artifacts</p>
      </div>

      <div className="kpi-row" style={{ marginBottom: 24 }}>
        <div className="kpi-card">
          <div className="kpi-label">Sessions</div>
          <div className="kpi-value">{sessions.length}</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Total runs</div>
          <div className="kpi-value">{totalRuns}</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Total input tok</div>
          <div className="kpi-value">{tok(totalTokIn)}</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Total output tok</div>
          <div className="kpi-value">{tok(totalTokOut)}</div>
        </div>
      </div>

      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        <table className="runs-table" style={{ width: "100%" }}>
          <thead>
            <tr>
              <th>Session ID</th>
              <th>Started</th>
              <th>Ended</th>
              <th>Duration</th>
              <th style={{ textAlign: "right" }}>Runs</th>
              <th style={{ textAlign: "right" }}>Artifacts</th>
              <th style={{ textAlign: "right" }}>In tok</th>
              <th style={{ textAlign: "right" }}>Out tok</th>
            </tr>
          </thead>
          <tbody>
            {sessions.length === 0
              ? <tr><td colSpan={8} style={{ color: "var(--dim)", textAlign: "center", padding: 32 }}>No sessions found.</td></tr>
              : sessions.map((s) => <SessionRow key={s.session_id} s={s} />)
            }
          </tbody>
        </table>
      </div>
    </div>
  );
}

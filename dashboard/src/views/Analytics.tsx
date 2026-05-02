import {
  BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, Legend,
} from "recharts";
import { ScoreTrend } from "@/components/ScoreTrend";
import { useCuration, useDashboardData } from "@/hooks/useRuns";

export function Analytics() {
  const { data, isLoading, error } = useDashboardData();
  const { data: curation } = useCuration();

  if (isLoading) return <div className="loading">Loading…</div>;
  if (error)     return <div className="error">Failed to load analytics.</div>;
  if (!data)     return null;

  const tokenData = data.recent_runs.slice(0, 20).map((r, i) => ({
    i,
    in:  r.input_tokens  ?? 0,
    out: r.output_tokens ?? 0,
  }));

  const durationData = data.recent_runs.slice(0, 20).map((r, i) => ({
    i,
    s: Math.round(r.run_duration_s ?? 0),
  }));

  return (
    <div>
      <div className="view-header">
        <h1>Analytics</h1>
        <p>Run performance over time</p>
      </div>

      <div className="section">
        <div className="section-title">Score trend</div>
        <div className="card">
          <ScoreTrend data={data.score_trend} />
        </div>
      </div>

      <div className="chart-grid-2">
        <div className="card">
          <div className="card-title">Token usage — last 20 runs</div>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={tokenData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
              <XAxis dataKey="i" hide />
              <YAxis width={42} />
              <Tooltip />
              <Legend iconSize={10} />
              <Bar dataKey="in"  fill="#818cf8" name="input"  radius={[2,2,0,0]} />
              <Bar dataKey="out" fill="#34d399" name="output" radius={[2,2,0,0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <div className="card-title">Run duration (s) — last 20 runs</div>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={durationData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
              <XAxis dataKey="i" hide />
              <YAxis width={42} />
              <Tooltip formatter={(v: number) => `${v}s`} />
              <Bar dataKey="s" fill="#f59e0b" name="seconds" radius={[2,2,0,0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="card">
        <div className="card-title">Lifetime token totals</div>
        <div style={{ display: "flex", gap: 40, paddingTop: 8 }}>
          <div>
            <div style={{ color: "var(--dim)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em" }}>Total input</div>
            <div style={{ fontWeight: 700, fontSize: 22, fontFamily: "var(--font-mono)" }}>
              {data.cost.total_input_tokens.toLocaleString()}
            </div>
          </div>
          <div>
            <div style={{ color: "var(--dim)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em" }}>Total output</div>
            <div style={{ fontWeight: 700, fontSize: 22, fontFamily: "var(--font-mono)" }}>
              {data.cost.total_output_tokens.toLocaleString()}
            </div>
          </div>
        </div>
      </div>

      {curation && curation.length > 0 && (() => {
        const passed = curation.filter((c) => c.passed).length;
        const meanScore = curation.reduce((a, c) => a + (c.mean ?? 0), 0) / curation.length;
        const chartData = curation.slice(0, 40).map((c, i) => ({ i, score: c.mean ?? 0 }));
        return (
          <div className="section">
            <div className="section-title">Paper curation</div>
            <div className="kpi-row" style={{ marginBottom: 16 }}>
              <div className="kpi-card">
                <div className="kpi-label">Papers scored</div>
                <div className="kpi-value">{curation.length}</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-label">Passed</div>
                <div className="kpi-value">{passed}</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-label">Pass rate</div>
                <div className="kpi-value">{curation.length ? `${Math.round(passed / curation.length * 100)}%` : "—"}</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-label">Mean score</div>
                <div className="kpi-value">{meanScore.toFixed(2)}</div>
              </div>
            </div>
            <div className="card">
              <div className="card-title">Curation scores — last 40 papers</div>
              <ResponsiveContainer width="100%" height={160}>
                <BarChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <XAxis dataKey="i" hide />
                  <YAxis domain={[0, 5]} width={28} />
                  <Tooltip formatter={(v: number) => v.toFixed(2)} />
                  <Bar dataKey="score" fill="#818cf8" name="score" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        );
      })()}
    </div>
  );
}

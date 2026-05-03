import {
  BarChart, Bar, LineChart, Line, AreaChart, Area,
  XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, CartesianGrid,
} from "recharts";
import { ScoreTrend } from "@/components/ScoreTrend";
import { useAnalytics, useCuration, useDashboardData } from "@/hooks/useRuns";

function shortDate(d: string) {
  const dt = new Date(d + "T00:00:00");
  return dt.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function Analytics() {
  const { data,     isLoading, error } = useDashboardData();
  const { data: ag, isLoading: agLoading } = useAnalytics();
  const { data: curation } = useCuration();

  if (isLoading) return <div className="loading">Loading…</div>;
  if (error)     return <div className="page-error">Failed to load analytics.</div>;
  if (!data)     return null;

  const daily  = (ag?.daily ?? []).filter((d) => d.date !== "unknown");
  const last30 = daily.slice(-30);

  const volumeData = last30.map((d) => ({
    date: shortDate(d.date), pass: d.pass, fail: d.fail, error: d.error,
  }));

  const passRateData = last30
    .filter((d) => d.total > 0)
    .map((d) => ({ date: shortDate(d.date), rate: Math.round((d.pass / d.total) * 100) }));

  const tokenData = last30.map((d) => ({
    date: shortDate(d.date),
    in:   Math.round(d.input_tokens  / 1000),
    out:  Math.round(d.output_tokens / 1000),
  }));

  const scoreDist = ag?.score_distribution ?? [];
  const taskTypes = ag?.task_types ?? [];

  const tick   = { fill: "var(--dim)", fontSize: 11 };
  const grid   = "rgba(255,255,255,0.05)";
  const tip    = { background: "var(--surface)", border: "1px solid var(--border)", fontSize: 12 };

  return (
    <div>
      <div className="view-header">
        <h1>Analytics</h1>
        <p>Run performance over time</p>
      </div>

      <div className="section">
        <div className="section-title">Score trend — all runs</div>
        <div className="card"><ScoreTrend data={data.score_trend} /></div>
      </div>

      {agLoading ? (
        <div className="loading" style={{ marginTop: 24 }}>Loading daily data…</div>
      ) : (
        <>
          <div className="chart-grid-2">
            <div className="card">
              <div className="card-title">Daily run volume — last 30 days</div>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={volumeData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid vertical={false} stroke={grid} />
                  <XAxis dataKey="date" tick={tick} interval="preserveStartEnd" />
                  <YAxis width={32} tick={tick} allowDecimals={false} />
                  <Tooltip contentStyle={tip} />
                  <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="pass"  stackId="a" fill="#34d399" name="pass"  />
                  <Bar dataKey="fail"  stackId="a" fill="#f87171" name="fail"  />
                  <Bar dataKey="error" stackId="a" fill="#fb923c" name="error" radius={[2,2,0,0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="card">
              <div className="card-title">Daily pass rate % — last 30 days</div>
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={passRateData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid vertical={false} stroke={grid} />
                  <XAxis dataKey="date" tick={tick} interval="preserveStartEnd" />
                  <YAxis domain={[0, 100]} width={36} tick={tick} unit="%" />
                  <Tooltip formatter={(v: number) => `${v}%`} contentStyle={tip} />
                  <Line type="monotone" dataKey="rate" stroke="#818cf8" strokeWidth={2} dot={false} name="pass rate" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="chart-grid-2">
            <div className="card">
              <div className="card-title">Daily token spend (k) — last 30 days</div>
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={tokenData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid vertical={false} stroke={grid} />
                  <XAxis dataKey="date" tick={tick} interval="preserveStartEnd" />
                  <YAxis width={36} tick={tick} unit="k" />
                  <Tooltip formatter={(v: number) => `${v}k`} contentStyle={tip} />
                  <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }} />
                  <Area type="monotone" dataKey="in"  stackId="1" stroke="#818cf8" fill="rgba(129,140,248,0.25)" name="input"  />
                  <Area type="monotone" dataKey="out" stackId="1" stroke="#34d399" fill="rgba(52,211,153,0.25)"  name="output" />
                </AreaChart>
              </ResponsiveContainer>
            </div>

            <div className="card">
              <div className="card-title">Score distribution — all runs</div>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={scoreDist} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid vertical={false} stroke={grid} />
                  <XAxis dataKey="score" tick={tick} />
                  <YAxis width={32} tick={tick} allowDecimals={false} />
                  <Tooltip contentStyle={tip} />
                  <Bar dataKey="count" fill="#818cf8" name="runs" radius={[2,2,0,0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {taskTypes.length > 0 && (
            <div className="card" style={{ marginTop: 0 }}>
              <div className="card-title">Task types</div>
              <div style={{ display: "flex", gap: 32, flexWrap: "wrap", paddingTop: 8 }}>
                {taskTypes.map(({ type, count }) => (
                  <div key={type}>
                    <div style={{ color: "var(--dim)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em" }}>{type}</div>
                    <div style={{ fontWeight: 700, fontSize: 20, fontFamily: "var(--font-mono)" }}>{count}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

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
        const passed    = curation.filter((c) => c.passed).length;
        const meanScore = curation.reduce((a, c) => a + (c.mean ?? 0), 0) / curation.length;
        const chartData = curation.slice(0, 40).map((c, i) => ({ i, score: c.mean ?? 0 }));
        return (
          <div className="section">
            <div className="section-title">Paper curation</div>
            <div className="kpi-row" style={{ marginBottom: 16 }}>
              <div className="kpi-card"><div className="kpi-label">Papers scored</div><div className="kpi-value">{curation.length}</div></div>
              <div className="kpi-card"><div className="kpi-label">Passed</div><div className="kpi-value">{passed}</div></div>
              <div className="kpi-card"><div className="kpi-label">Pass rate</div><div className="kpi-value">{`${Math.round(passed / curation.length * 100)}%`}</div></div>
              <div className="kpi-card"><div className="kpi-label">Mean score</div><div className="kpi-value">{meanScore.toFixed(2)}</div></div>
            </div>
            <div className="card">
              <div className="card-title">Curation scores — last 40 papers</div>
              <ResponsiveContainer width="100%" height={160}>
                <BarChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <XAxis dataKey="i" hide />
                  <YAxis domain={[0, 5]} width={28} tick={tick} />
                  <Tooltip formatter={(v: number) => v.toFixed(2)} contentStyle={tip} />
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

import { KpiCards }   from "@/components/KpiCards";
import { ScoreTrend } from "@/components/ScoreTrend";
import { useDashboardData } from "@/hooks/useRuns";

export function Home() {
  const { data, isLoading, error } = useDashboardData();

  if (isLoading) return <div className="loading">Loading…</div>;
  if (error)     return <div className="page-error">Failed to load dashboard data.</div>;
  if (!data)     return null;

  return (
    <div>
      <div className="view-header">
        <h1>Dashboard</h1>
        <p>Self-improving agentic research swarm</p>
      </div>

      <KpiCards kpi={data.kpi} />

      <div className="section">
        <div className="section-title">Score trend</div>
        <div className="card">
          <ScoreTrend data={data.score_trend} />
        </div>
      </div>
    </div>
  );
}

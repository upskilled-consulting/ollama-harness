import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useDashboardData, useLiveRuns } from "@/hooks/useRuns";
import { KpiCards } from "@/components/KpiCards";
import { ScoreTrend } from "@/components/ScoreTrend";
import { RunsTable } from "@/components/RunsTable";

const qc = new QueryClient();

function Dashboard() {
  useLiveRuns();
  const { data, isLoading, error } = useDashboardData();

  if (isLoading) return <div className="loading">Loading…</div>;
  if (error)     return <div className="error">Failed to load: {String(error)}</div>;
  if (!data)     return null;

  return (
    <main>
      <header>
        <h1>Harness</h1>
        <span className="subtitle">Self-improving agentic research swarm</span>
      </header>

      <section className="section">
        <KpiCards kpi={data.kpi} />
      </section>

      <section className="section">
        <h2>Score Trend</h2>
        <ScoreTrend data={data.score_trend} />
      </section>

      <section className="section">
        <h2>Recent Runs</h2>
        <RunsTable runs={data.recent_runs} />
      </section>
    </main>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <Dashboard />
    </QueryClientProvider>
  );
}

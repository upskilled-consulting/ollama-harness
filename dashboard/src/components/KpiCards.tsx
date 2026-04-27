import type { Kpi } from "@/types";

interface Props { kpi: Kpi }

function Card({ label, value }: { label: string; value: string }) {
  return (
    <div className="kpi-card">
      <div className="kpi-value">{value}</div>
      <div className="kpi-label">{label}</div>
    </div>
  );
}

export function KpiCards({ kpi }: Props) {
  return (
    <div className="kpi-grid">
      <Card label="Total Runs"     value={String(kpi.total_runs)} />
      <Card label="Pass Rate"      value={`${(kpi.pass_rate * 100).toFixed(1)}%`} />
      <Card label="Mean Score"     value={kpi.mean_score.toFixed(2)} />
      <Card label="Mean Duration"  value={`${kpi.mean_duration_s.toFixed(0)}s`} />
    </div>
  );
}

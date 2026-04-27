import { clsx } from "clsx";
import type { RunRecord } from "@/types";

interface Props { runs: RunRecord[] }

function Score({ scores }: { scores: number[] }) {
  const last = scores.at(-1);
  if (last == null) return <span className="dim">—</span>;
  return (
    <span className={clsx("score", last >= 8 ? "pass" : last >= 6 ? "warn" : "fail")}>
      {last.toFixed(1)}
    </span>
  );
}

function Final({ final }: { final: RunRecord["final"] }) {
  if (!final) return <span className="badge running">running</span>;
  return <span className={clsx("badge", final.toLowerCase())}>{final}</span>;
}

export function RunsTable({ runs }: Props) {
  return (
    <table className="runs-table">
      <thead>
        <tr>
          <th>Task</th>
          <th>Model</th>
          <th>Score</th>
          <th>Rounds</th>
          <th>Duration</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((r) => (
          <tr key={r.run_id}>
            <td className="task-cell" title={r.task}>{r.task.slice(0, 60)}{r.task.length > 60 ? "…" : ""}</td>
            <td className="mono">{r.producer_model}</td>
            <td><Score scores={r.wiggum_scores} /></td>
            <td>{r.wiggum_rounds}</td>
            <td>{r.run_duration_s ? `${r.run_duration_s.toFixed(0)}s` : "—"}</td>
            <td><Final final={r.final} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

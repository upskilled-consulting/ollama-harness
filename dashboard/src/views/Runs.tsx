import React, { useState } from "react";
import { clsx } from "clsx";
import { ChevronRight } from "lucide-react";
import { useAllRuns } from "@/hooks/useRuns";
import type { RunRecord, WiggumDim } from "@/types";

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

function DimBars({ dim }: { dim: WiggumDim }) {
  const keys: (keyof WiggumDim)[] = ["relevance", "completeness", "depth", "specificity", "structure"];
  return (
    <>
      {keys.map((k) => (
        <div key={k} className="dim-row">
          <span className="dim-label">{k}</span>
          <div className="dim-bar-wrap">
            <div className="dim-bar-fill" style={{ width: `${Math.min(100, ((dim[k] ?? 0) / 10) * 100)}%` }} />
          </div>
          <span className="dim-value">{dim[k]}</span>
        </div>
      ))}
    </>
  );
}

function RunDetail({ run }: { run: RunRecord }) {
  const lastDim = run.wiggum_dims?.at(-1);
  return (
    <div className="run-detail">
      <div className="detail-card">
        <div className="detail-card-title">Task</div>
        <div className="task-full">{run.task}</div>
      </div>

      {lastDim && (
        <div className="detail-card">
          <div className="detail-card-title">Wiggum dims</div>
          <DimBars dim={lastDim} />
        </div>
      )}

      <div className="detail-card">
        <div className="detail-card-title">Scores</div>
        <div>
          {run.wiggum_scores.length > 0
            ? run.wiggum_scores.map((s, i) => <span key={i} className="score-pill">{s.toFixed(1)}</span>)
            : <span className="dim">none</span>}
        </div>
      </div>

      <div className="detail-card">
        <div className="detail-card-title">Stats</div>
        <div style={{ fontSize: 12, lineHeight: 2 }}>
          <div><span className="dim">in: </span>{run.input_tokens?.toLocaleString() ?? "—"}</div>
          <div><span className="dim">out: </span>{run.output_tokens?.toLocaleString() ?? "—"}</div>
          <div><span className="dim">bytes: </span>{run.output_bytes?.toLocaleString() ?? "—"}</div>
          <div><span className="dim">rounds: </span>{run.wiggum_rounds ?? "—"}</div>
          <div><span className="dim">memory: </span>{run.memory_hits ?? "—"}</div>
        </div>
      </div>

      {run.wiggum_issues && run.wiggum_issues.length > 0 && (
        <div className="detail-card">
          <div className="detail-card-title">Issues</div>
          <div className="issues-scroll">
            {run.wiggum_issues.map((iss, i) => (
              <div key={i} className="issue-item">{iss}</div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function Runs() {
  const { data: runs = [], isLoading, error } = useAllRuns();
  const [expanded, setExpanded] = useState<string | null>(null);

  if (isLoading) return <div className="loading">Loading…</div>;
  if (error)     return <div className="error">Failed to load runs.</div>;

  return (
    <div>
      <div className="view-header">
        <h1>Runs</h1>
        <p>{runs.length} recent runs</p>
      </div>

      <table className="runs-table">
        <thead>
          <tr>
            <th style={{ width: 28 }} />
            <th>Task</th>
            <th>Model</th>
            <th>Score</th>
            <th>Rounds</th>
            <th>Duration</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {runs.length === 0 && (
            <tr><td colSpan={7} className="empty-state">No runs yet.</td></tr>
          )}
          {runs.map((r) => {
            const isOpen = expanded === r.run_id;
            return (
              <React.Fragment key={r.run_id}>
                <tr
                  className="run-row"
                  onClick={() => setExpanded(isOpen ? null : r.run_id)}
                >
                  <td>
                    <ChevronRight
                      size={13}
                      style={{
                        color: "var(--dim)",
                        transition: "transform 0.18s",
                        transform: isOpen ? "rotate(90deg)" : "rotate(0deg)",
                        display: "block",
                      }}
                    />
                  </td>
                  <td className="task-cell" title={r.task}>
                    {r.task.slice(0, 60)}{r.task.length > 60 ? "…" : ""}
                  </td>
                  <td className="mono">{r.producer_model}</td>
                  <td><Score scores={r.wiggum_scores} /></td>
                  <td>{r.wiggum_rounds}</td>
                  <td>{r.run_duration_s ? `${r.run_duration_s.toFixed(0)}s` : "—"}</td>
                  <td><Final final={r.final} /></td>
                </tr>
                {isOpen && (
                  <tr className="detail-row">
                    <td colSpan={7}>
                      <RunDetail run={r} />
                    </td>
                  </tr>
                )}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

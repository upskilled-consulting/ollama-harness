import { useState, useMemo } from "react";
import { clsx } from "clsx";
import { ChevronRight } from "lucide-react";
import { useAllRuns } from "@/hooks/useRuns";
import type { RunRecord, WiggumDim } from "@/types";

// ── helpers ───────────────────────────────────────────────────────────────────
const DIM_COLORS: Record<string, string> = {
  relevance:    "#4f8ef7",
  completeness: "#3fb950",
  depth:        "#a78bfa",
  specificity:  "#22d3ee",
  structure:    "#fb923c",
  grounded:     "#f0b429",
};

function fmtTs(ts: string | undefined) {
  if (!ts) return "—";
  const d = new Date(ts);
  const mo = d.toLocaleString("en-US", { month: "short" });
  const dy = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${mo} ${dy}  ${hh}:${mm}`;
}

function scoreColor(s: number) {
  return s >= 8 ? "var(--pass)" : s >= 6 ? "var(--warn)" : "var(--fail)";
}

// ── sub-components ────────────────────────────────────────────────────────────
function DimBars({ dim }: { dim: WiggumDim }) {
  const keys = Object.keys(dim).filter((k) => typeof dim[k] === "number");
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      {keys.map((k) => {
        const val   = dim[k] ?? 0;
        const color = DIM_COLORS[k] ?? "#4f8ef7";
        const pct   = Math.min(100, (val / 10) * 100);
        return (
          <div key={k} style={{ display: "flex", alignItems: "center", gap: 7 }}>
            <span style={{ fontSize: 10, color: "var(--dim)", minWidth: 88, textTransform: "capitalize" }}>{k}</span>
            <div style={{ flex: 1, height: 5, background: "rgba(255,255,255,0.07)", borderRadius: 3, overflow: "hidden" }}>
              <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 3, transition: "width 0.3s" }} />
            </div>
            <span style={{ fontSize: 10, color, fontFamily: "var(--font-mono)", minWidth: 20, textAlign: "right" }}>{val}</span>
          </div>
        );
      })}
    </div>
  );
}

function ScorePills({ scores }: { scores: number[] }) {
  if (scores.length === 0) return <span style={{ color: "var(--dim)", fontSize: 11 }}>no scores</span>;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
      {scores.map((s, i) => (
        <span key={i} style={{
          display: "inline-flex", alignItems: "center", gap: 3,
          padding: "2px 8px", borderRadius: 10, fontSize: 11, fontWeight: 700,
          fontFamily: "var(--font-mono)",
          background: `${scoreColor(s)}18`,
          color: scoreColor(s),
          border: `1px solid ${scoreColor(s)}40`,
        }}>
          r{i + 1} · {s.toFixed(1)}
        </span>
      ))}
    </div>
  );
}

function StatLine({ label, value }: { label: string; value: string | number | undefined | null }) {
  if (value == null || value === "" || value === "—") return null;
  return (
    <div style={{ display: "flex", gap: 8, fontSize: 11, lineHeight: 1.8 }}>
      <span style={{ color: "var(--dim)", minWidth: 80 }}>{label}</span>
      <span style={{ color: "var(--text)", fontFamily: "var(--font-mono)" }}>{value}</span>
    </div>
  );
}

function RunDetail({ run }: { run: RunRecord }) {
  const lastDim  = run.wiggum_dims?.at(-1);
  const lastEval = run.wiggum_eval_log?.at(-1);
  const scores   = run.wiggum_scores ?? [];
  const issues   = run.wiggum_issues ?? lastEval?.issues ?? [];
  const feedback = lastEval?.feedback;
  const thinking = lastEval?.thinking;

  return (
    <div style={{
      padding: "14px 16px 16px",
      background: "var(--bg)",
      borderTop: "1px solid var(--border)",
      display: "flex",
      flexDirection: "column",
      gap: 12,
    }}>
      {/* Task full text */}
      <div style={{
        fontSize: 12, lineHeight: 1.6, color: "var(--text)",
        padding: "10px 12px",
        background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 7,
        wordBreak: "break-word",
      }}>
        {run.task}
      </div>

      {/* Detail grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))", gap: 10 }}>

        {/* Scores */}
        <Section title={`Scores (${scores.length} rounds)`}>
          <ScorePills scores={scores} />
        </Section>

        {/* Dimensions */}
        {lastDim && (
          <Section title="Eval dimensions">
            <DimBars dim={lastDim} />
          </Section>
        )}

        {/* Stats */}
        <Section title="Stats">
          <StatLine label="model"     value={run.producer_model} />
          <StatLine label="evaluator" value={run.evaluator_model} />
          <StatLine label="duration"  value={run.run_duration_s != null ? `${run.run_duration_s.toFixed(1)}s` : null} />
          <StatLine label="tokens in" value={run.input_tokens ? run.input_tokens.toLocaleString() : null} />
          <StatLine label="tokens out" value={run.output_tokens ? run.output_tokens.toLocaleString() : null} />
          <StatLine label="output"    value={run.output_bytes != null ? `${(run.output_bytes / 1024).toFixed(1)} KB · ${run.output_lines ?? "?"} lines` : null} />
          <StatLine label="memory"    value={run.memory_hits != null && run.memory_hits > 0 ? `${run.memory_hits} hits` : null} />
          <StatLine label="leverage"  value={run.leverage != null ? `${run.leverage.toFixed(1)}×` : null} />
          <StatLine label="tac hours" value={run.tac_hours != null ? `${run.tac_hours.toFixed(2)} h` : null} />
        </Section>

        {/* Issues + feedback */}
        {(issues.length > 0 || feedback || thinking) && (
          <Section title={`Evaluator${issues.length > 0 ? ` · ${issues.length} issue${issues.length > 1 ? "s" : ""}` : ""}`}>
            {issues.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 3, marginBottom: feedback || thinking ? 8 : 0 }}>
                {issues.map((iss, i) => (
                  <div key={i} style={{
                    fontSize: 11, color: "var(--dim)", lineHeight: 1.45,
                    padding: "3px 0 3px 10px", wordBreak: "break-word",
                    borderLeft: "2px solid var(--warn)",
                  }}>{iss}</div>
                ))}
              </div>
            )}
            {feedback && (
              <div style={{ fontSize: 11, color: "var(--dim)", lineHeight: 1.5, wordBreak: "break-word", marginBottom: thinking ? 8 : 0 }}>
                {feedback}
              </div>
            )}
            {thinking && (
              <>
                <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--dim)", marginBottom: 4, marginTop: 4 }}>Reasoning</div>
                <div style={{ fontSize: 10, color: "var(--dim)", lineHeight: 1.6, wordBreak: "break-word", maxHeight: 120, overflowY: "auto", padding: "5px 8px", background: "rgba(0,0,0,0.2)", borderRadius: 4, borderLeft: "2px solid rgba(227,179,65,0.4)" }}>
                  {thinking}
                </div>
              </>
            )}
          </Section>
        )}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{
      background: "var(--surface)", border: "1px solid var(--border)",
      borderRadius: 8, padding: "10px 12px",
    }}>
      <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--dim)", marginBottom: 8 }}>
        {title}
      </div>
      {children}
    </div>
  );
}

// ── filter bar ────────────────────────────────────────────────────────────────
type StatusFilter = "all" | "pass" | "fail" | "error" | "running";

function FilterBar({
  search, onSearch, status, onStatus, total, shown,
}: {
  search: string; onSearch: (v: string) => void;
  status: StatusFilter; onStatus: (v: StatusFilter) => void;
  total: number; shown: number;
}) {
  const statuses: StatusFilter[] = ["all", "pass", "fail", "error", "running"];
  return (
    <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 14, flexWrap: "wrap" }}>
      <input
        type="search"
        placeholder="Filter by task…"
        value={search}
        onChange={(e) => onSearch(e.target.value)}
        style={{
          flex: 1, minWidth: 180,
          background: "var(--surface)", border: "1px solid var(--border)",
          borderRadius: 6, color: "var(--text)", fontSize: 12,
          padding: "6px 10px", outline: "none",
        }}
      />
      <div style={{ display: "flex", gap: 4 }}>
        {statuses.map((s) => (
          <button key={s} onClick={() => onStatus(s)} style={{
            padding: "4px 10px", borderRadius: 6, fontSize: 11, fontWeight: 600,
            cursor: "pointer", textTransform: "uppercase", letterSpacing: "0.04em",
            border: status === s ? "1px solid var(--accent)" : "1px solid var(--border)",
            background: status === s ? "rgba(129,140,248,0.15)" : "none",
            color: status === s ? "var(--accent)" : "var(--dim)",
          }}>{s}</button>
        ))}
      </div>
      <span style={{ fontSize: 11, color: "var(--dim)", whiteSpace: "nowrap" }}>
        {shown === total ? `${total} runs` : `${shown} / ${total}`}
      </span>
    </div>
  );
}

// ── main view ─────────────────────────────────────────────────────────────────
export function Runs() {
  const { data: runs = [], isLoading, error } = useAllRuns();
  const [expanded, setExpanded]   = useState<string | null>(null);
  const [search,   setSearch]     = useState("");
  const [status,   setStatus]     = useState<StatusFilter>("all");

  const filtered = useMemo(() => {
    return runs.filter((r) => {
      if (status !== "all") {
        const f = r.final?.toLowerCase() ?? "running";
        if (f !== status) return false;
      }
      if (search) {
        const q = search.toLowerCase();
        if (!r.task.toLowerCase().includes(q) && !(r.producer_model ?? "").toLowerCase().includes(q)) return false;
      }
      return true;
    });
  }, [runs, search, status]);

  if (isLoading) return <div className="loading">Loading…</div>;
  if (error)     return <div className="page-error">Failed to load runs.</div>;

  return (
    <div>
      <div className="view-header">
        <h1>Runs</h1>
      </div>

      <FilterBar
        search={search} onSearch={setSearch}
        status={status} onStatus={setStatus}
        total={runs.length} shown={filtered.length}
      />

      <table className="runs-table">
        <thead>
          <tr>
            <th style={{ width: 30 }} />
            <th style={{ width: 108 }}>Time</th>
            <th>Task</th>
            <th style={{ width: 112 }}>Model</th>
            <th style={{ width: 58, textAlign: "right" }}>Score</th>
            <th style={{ width: 72, textAlign: "right" }}>Duration</th>
            <th style={{ width: 78 }}>Status</th>
          </tr>
        </thead>
        <tbody>
          {filtered.length === 0 && (
            <tr><td colSpan={7} className="empty-state">No runs match.</td></tr>
          )}
          {filtered.map((r) => {
            const isOpen = expanded === r.run_id;
            const score  = r.wiggum_scores?.at(-1);
            return (
              <RunRows
                key={r.run_id}
                run={r}
                score={score}
                isOpen={isOpen}
                onToggle={() => setExpanded(isOpen ? null : r.run_id)}
              />
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function RunRows({ run, score, isOpen, onToggle }: {
  run: RunRecord; score: number | undefined; isOpen: boolean; onToggle: () => void;
}) {
  return (
    <>
      <tr className="run-row" onClick={onToggle}>
        <td>
          <ChevronRight size={13} style={{
            color: "var(--dim)", display: "block",
            transition: "transform 0.18s",
            transform: isOpen ? "rotate(90deg)" : "rotate(0deg)",
          }} />
        </td>
        <td style={{ fontSize: 11, color: "var(--dim)", whiteSpace: "nowrap", fontFamily: "var(--font-mono)" }}>
          {fmtTs(run.timestamp)}
        </td>
        <td className="task-cell" title={run.task}>
          {run.task.slice(0, 72)}{run.task.length > 72 ? "…" : ""}
        </td>
        <td className="mono" style={{ fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{run.producer_model}</td>
        <td style={{ textAlign: "right", fontFamily: "var(--font-mono)", fontWeight: 700, fontSize: 12 }}>
          {score != null
            ? <span style={{ color: scoreColor(score) }}>{score.toFixed(1)}</span>
            : <span style={{ color: "var(--dim)" }}>—</span>}
        </td>
        <td style={{ textAlign: "right", color: "var(--dim)", fontSize: 11, fontFamily: "var(--font-mono)" }}>
          {run.run_duration_s != null ? `${run.run_duration_s.toFixed(0)}s` : "—"}
        </td>
        <td>
          {run.final
            ? <span className={clsx("badge", run.final.toLowerCase())}>{run.final}</span>
            : <span className="badge running">running</span>}
        </td>
      </tr>
      {isOpen && (
        <tr className="detail-row">
          <td colSpan={7}>
            <RunDetail run={run} />
          </td>
        </tr>
      )}
    </>
  );
}

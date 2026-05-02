import { useState } from "react";
import { clsx } from "clsx";
import { useAllRuns } from "@/hooks/useRuns";
import type { RunRecord, WiggumDim, ToolCall, WiggumEvalEntry, Plan, StageTokens } from "@/types";

// ── DAG constants ─────────────────────────────────────────────────────────────
const NW   = 162;
const NH   = 64;
const HGAP = 60;
const VGAP = 12;
const PAD  = 28;

type NodeType = "task" | "memory" | "plan" | "search" | "synthesis" | "eval" | "output";

const NODE_CFG: Record<NodeType, { color: string; label: string }> = {
  task:      { color: "#4f8ef7", label: "TASK"      },
  memory:    { color: "#a78bfa", label: "MEMORY"    },
  plan:      { color: "#38bdf8", label: "PLAN"      },
  search:    { color: "#fb923c", label: "SEARCH"    },
  synthesis: { color: "#22d3ee", label: "SYNTHESIS" },
  eval:      { color: "#e3b341", label: "EVAL"      },
  output:    { color: "#3fb950", label: "OUTPUT"    },
};

// ── Node data model ───────────────────────────────────────────────────────────
interface DagNode {
  id:     string;
  type:   NodeType;
  col:    number;
  row:    number;
  x:      number;
  y:      number;
  title:  string;
  sub:    string;
  color:  string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data:   any;
}

interface DagEdge { from: DagNode; to: DagNode }

const trunc = (s: string | null | undefined, n: number) =>
  !s ? "" : s.length > n ? s.slice(0, n - 1) + "…" : s;

// ── Build columns from run record ─────────────────────────────────────────────
function buildColumns(run: RunRecord): DagNode[][] {
  const cols: DagNode[][] = [];

  // TASK
  cols.push([{
    id: "task", type: "task", col: 0, row: 0, x: 0, y: 0,
    title: trunc(run.task, 22),
    sub:   trunc(run.producer_model, 28),
    color: NODE_CFG.task.color,
    data:  run,
  }]);

  // MEMORY
  cols.push([{
    id: "memory", type: "memory", col: 0, row: 0, x: 0, y: 0,
    title: `${run.memory_hits ?? 0} memory hit${run.memory_hits === 1 ? "" : "s"}`,
    sub:   trunc(run.memory_context_titles?.[0] ?? "no prior context", 28),
    color: NODE_CFG.memory.color,
    data:  { hits: run.memory_hits, titles: run.memory_context_titles ?? [] },
  }]);

  // PLAN (if present)
  if (run.plan) {
    const queries = run.plan.search_queries ?? run.plan.queries ?? [];
    cols.push([{
      id: "plan", type: "plan", col: 0, row: 0, x: 0, y: 0,
      title: `${queries.length} quer${queries.length === 1 ? "y" : "ies"} planned`,
      sub:   trunc(queries[0] ?? "", 28),
      color: NODE_CFG.plan.color,
      data:  run.plan,
    }]);
  }

  // SEARCH — executed tool_calls (minus pure execution tools), with fallback to
  // plan.search_queries for older runs that logged a plan but not tool_calls.
  const EXEC_TOOLS = new Set(["run_python", "run_code", "execute_python", "execute_code"]);
  const tcSearches = (run.tool_calls ?? []).filter((tc) => !EXEC_TOOLS.has(tc.name));

  const planQueries: string[] = run.plan
    ? (run.plan.search_queries ?? run.plan.queries ?? [])
    : [];

  if (tcSearches.length > 0) {
    // Executed searches — show tool name + result chars
    cols.push(tcSearches.map((tc, i) => ({
      id:    `search-${i}`,
      type:  "search" as NodeType,
      col: 0, row: 0, x: 0, y: 0,
      title: trunc(tc.query ?? tc.name, 22),
      sub:   `${tc.name} · ${(tc.result_chars ?? 0).toLocaleString()}c`,
      color: NODE_CFG.search.color,
      data:  tc,
    })));
  } else if (planQueries.length > 0) {
    // Fallback: plan had queries but tool_calls weren't logged (older runs)
    cols.push(planQueries.map((q, i) => ({
      id:    `search-${i}`,
      type:  "search" as NodeType,
      col: 0, row: 0, x: 0, y: 0,
      title: trunc(q, 22),
      sub:   "planned query",
      color: NODE_CFG.search.color,
      data:  { name: "web_search", query: q, result_chars: null },
    })));
  }

  // SYNTHESIS
  const synth = run.tokens_by_stage?.synth;
  cols.push([{
    id: "synthesis", type: "synthesis", col: 0, row: 0, x: 0, y: 0,
    title: "Synthesis",
    sub:   run.output_bytes
      ? `${(run.output_bytes / 1024).toFixed(1)} KB`
      : synth?.output ? `${synth.output} out-tok` : "—",
    color: NODE_CFG.synthesis.color,
    data:  { synth, output_bytes: run.output_bytes, synth_cot: run.synth_cot },
  }]);

  // EVAL (one per wiggum_eval_log entry, or fallback to scores)
  const evalLog = run.wiggum_eval_log ?? [];
  if (evalLog.length > 0) {
    const total = evalLog.length;
    cols.push(evalLog.map((entry, i) => ({
      id: `eval-${i}`, type: "eval" as NodeType, col: 0, row: 0, x: 0, y: 0,
      title: `Round ${entry.round}/${total} · ${entry.score?.toFixed(1) ?? "?"}`,
      sub:   entry.issues?.[0] ? trunc(entry.issues[0], 28) : "no issues",
      color: NODE_CFG.eval.color,
      data:  entry,
    })));
  } else if ((run.wiggum_scores ?? []).length > 0) {
    const scores = run.wiggum_scores ?? [];
    const total  = scores.length;
    cols.push(scores.map((score, i) => ({
      id: `eval-${i}`, type: "eval" as NodeType, col: 0, row: 0, x: 0, y: 0,
      title: `Round ${i + 1}/${total} · ${score.toFixed(1)}`,
      sub:   (run.wiggum_issues ?? []).length > 0 ? `${run.wiggum_issues!.length} issue(s)` : "no issues",
      color: NODE_CFG.eval.color,
      data:  { round: i + 1, score, dims: run.wiggum_dims?.[i], issues: run.wiggum_issues ?? [] },
    })));
  }

  // OUTPUT
  const outColor = run.final === "PASS" ? "#3fb950" : run.final === "FAIL" ? "#f85149" : "#8b949e";
  cols.push([{
    id: "output", type: "output", col: 0, row: 0, x: 0, y: 0,
    title: run.final ?? "running",
    sub:   run.output_path ? trunc(run.output_path.replace(/.*[/\\]/, ""), 28) : "—",
    color: outColor,
    data:  run,
  }]);

  return cols;
}

function layoutColumns(cols: DagNode[][]): { nodes: DagNode[]; width: number; height: number } {
  const maxRows = Math.max(...cols.map((c) => c.length), 1);
  const svgW    = PAD * 2 + cols.length * NW + Math.max(0, cols.length - 1) * HGAP;
  const svgH    = PAD * 2 + maxRows * NH + Math.max(0, maxRows - 1) * VGAP;
  const nodes: DagNode[] = [];

  cols.forEach((col, ci) => {
    const colH   = col.length * NH + Math.max(0, col.length - 1) * VGAP;
    const startY = PAD + (svgH - PAD * 2 - colH) / 2;
    const x      = PAD + ci * (NW + HGAP);
    col.forEach((node, ri) => {
      nodes.push({ ...node, col: ci, row: ri, x, y: startY + ri * (NH + VGAP) });
    });
  });

  return { nodes, width: svgW, height: svgH };
}

function buildEdges(cols: DagNode[][], laid: DagNode[]): DagEdge[] {
  const edges: DagEdge[] = [];
  for (let ci = 0; ci < cols.length - 1; ci++) {
    const froms = laid.filter((n) => n.col === ci);
    const tos   = laid.filter((n) => n.col === ci + 1);
    for (const from of froms)
      for (const to of tos)
        edges.push({ from, to });
  }
  return edges;
}

// ── SVG components ────────────────────────────────────────────────────────────
function SvgEdge({ edge }: { edge: DagEdge }) {
  const x1   = edge.from.x + NW;
  const y1   = edge.from.y + NH / 2;
  const x2   = edge.to.x;
  const y2   = edge.to.y + NH / 2;
  const midX = (x1 + x2) / 2;
  return (
    <path
      d={`M${x1},${y1} C${midX},${y1} ${midX},${y2} ${x2},${y2}`}
      fill="none"
      stroke={edge.from.color}
      strokeWidth={1.5}
      strokeDasharray="5 3"
      opacity={0.4}
    />
  );
}

function SvgNode({ node, selected, onClick }: { node: DagNode; selected: boolean; onClick: () => void }) {
  const cfg = NODE_CFG[node.type];
  return (
    <g transform={`translate(${node.x},${node.y})`} onClick={onClick} style={{ cursor: "pointer" }}>
      <rect
        width={NW} height={NH} rx={5}
        fill={selected ? "rgba(255,255,255,0.06)" : "#0d1018"}
        stroke={node.color}
        strokeWidth={selected ? 1.8 : 1}
      />
      <rect width={4} height={NH} rx={2} fill={node.color} />
      <text x={12} y={16} fill={node.color} fontSize={8} fontFamily="monospace" fontWeight="bold" letterSpacing="0.1em">
        {cfg.label}
      </text>
      <text x={12} y={34} fill="#e2e8f0" fontSize={11} fontWeight="bold" fontFamily="system-ui, sans-serif">
        {node.title}
      </text>
      <text x={12} y={52} fill="#64748b" fontSize={9} fontFamily="system-ui, sans-serif">
        {node.sub}
      </text>
      <rect width={NW} height={NH} rx={5} fill="transparent" />
    </g>
  );
}

// ── Node inspector content ────────────────────────────────────────────────────
function InspRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: "flex", gap: 8, padding: "4px 0", borderBottom: "1px solid rgba(42,45,58,.5)", fontSize: 12 }}>
      <span style={{ color: "var(--dim)", minWidth: 90, flexShrink: 0, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</span>
      <span style={{ color: "var(--text)", wordBreak: "break-word", flex: 1 }}>{value}</span>
    </div>
  );
}

function DimBars({ dims }: { dims: WiggumDim }) {
  const keys = Object.keys(dims).filter((k) => typeof dims[k] === "number");
  return (
    <div style={{ marginTop: 4 }}>
      {keys.map((k) => (
        <div key={k} className="dim-row">
          <span className="dim-label">{k}</span>
          <div className="dim-bar-wrap">
            <div className="dim-bar-fill" style={{ width: `${Math.min(100, ((dims[k] ?? 0) / 10) * 100)}%` }} />
          </div>
          <span className="dim-value">{dims[k]}</span>
        </div>
      ))}
    </div>
  );
}

function NodeInspectorBody({ node }: { node: DagNode }) {
  const d = node.data as Record<string, unknown>;

  if (node.type === "task") {
    const run = d as unknown as RunRecord;
    return (
      <>
        <div style={{ fontSize: 12, lineHeight: 1.6, marginBottom: 10, wordBreak: "break-word", color: "var(--text)" }}>{run.task}</div>
        <InspRow label="timestamp"  value={run.timestamp?.slice(0, 19).replace("T", " ")} />
        <InspRow label="model"      value={run.producer_model} />
        <InspRow label="evaluator"  value={run.evaluator_model} />
        <InspRow label="type"       value={run.task_type ?? "—"} />
        <InspRow label="duration"   value={run.run_duration_s ? `${run.run_duration_s.toFixed(1)}s` : "—"} />
      </>
    );
  }

  if (node.type === "memory") {
    const titles = (d.titles as string[]) ?? [];
    return (
      <>
        <InspRow label="hits" value={String(d.hits ?? 0)} />
        {titles.length > 0
          ? titles.map((t, i) => <InspRow key={i} label={`obs ${i + 1}`} value={t} />)
          : <InspRow label="status" value="no prior context" />}
      </>
    );
  }

  if (node.type === "plan") {
    const plan = d as Plan;
    const queries = plan.search_queries ?? plan.queries ?? [];
    return (
      <>
        {queries.map((q, i) => <InspRow key={i} label={`query ${i + 1}`} value={q} />)}
        {plan.notes && <InspRow label="notes" value={plan.notes} />}
        {(plan.known_facts ?? []).map((f, i) => <InspRow key={i} label={`known ${i + 1}`} value={f} />)}
        {(plan.knowledge_gaps ?? []).map((g, i) => <InspRow key={i} label={`gap ${i + 1}`} value={g} />)}
      </>
    );
  }

  if (node.type === "search") {
    const tc = d as unknown as ToolCall;
    return (
      <>
        <InspRow label="tool"   value={tc.name} />
        <div style={{ marginTop: 8, marginBottom: 8, padding: "10px 12px", background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 6, fontSize: 12, lineHeight: 1.6, wordBreak: "break-word", color: "var(--text)" }}>
          {tc.query ?? "—"}
        </div>
        <InspRow label="result" value={tc.result_chars != null ? `${tc.result_chars.toLocaleString()} chars` : "—"} />
      </>
    );
  }

  if (node.type === "synthesis") {
    const synth = d.synth as StageTokens | undefined;
    const cot   = d.synth_cot as string[] | undefined;
    return (
      <>
        <InspRow label="out tokens" value={synth?.output?.toLocaleString() ?? "—"} />
        <InspRow label="in tokens"  value={synth?.input?.toLocaleString() ?? "—"} />
        <InspRow label="time"       value={synth?.total_ms != null ? `${(synth.total_ms / 1000).toFixed(1)}s` : "—"} />
        <InspRow label="output"     value={d.output_bytes != null ? `${((d.output_bytes as number) / 1024).toFixed(1)} KB` : "—"} />
        {cot && cot.length > 0 && (
          <div style={{ marginTop: 8 }}>
            <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--dim)", marginBottom: 4 }}>Chain of thought</div>
            <div style={{ maxHeight: 140, overflowY: "auto", fontSize: 11, color: "var(--dim)", lineHeight: 1.5, wordBreak: "break-word" }}>
              {cot.slice(0, 3).join(" · ")}
            </div>
          </div>
        )}
      </>
    );
  }

  if (node.type === "eval") {
    const entry = d as unknown as WiggumEvalEntry;
    return (
      <>
        <InspRow label="round" value={String(entry.round)} />
        <InspRow label="score" value={entry.score?.toFixed(2) ?? "—"} />
        {entry.dims && <DimBars dims={entry.dims} />}
        {(entry.issues ?? []).length > 0 && (
          <div style={{ marginTop: 8 }}>
            <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--dim)", marginBottom: 4 }}>Issues</div>
            <div className="issues-scroll">
              {entry.issues!.map((iss, i) => <div key={i} className="issue-item">{iss}</div>)}
            </div>
          </div>
        )}
        {entry.feedback && (
          <div style={{ marginTop: 8 }}>
            <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--dim)", marginBottom: 4 }}>Feedback</div>
            <div style={{ fontSize: 11, color: "var(--dim)", lineHeight: 1.5, wordBreak: "break-word" }}>{entry.feedback}</div>
          </div>
        )}
      </>
    );
  }

  if (node.type === "output") {
    const run = d as unknown as RunRecord;
    const scores = run.wiggum_scores ?? [];
    return (
      <>
        <InspRow label="status" value={
          <span className={clsx("badge", (run.final ?? "error").toLowerCase())}>{run.final ?? "running"}</span>
        } />
        {run.output_path && <InspRow label="path"  value={run.output_path} />}
        {run.output_bytes != null && <InspRow label="size"  value={`${(run.output_bytes / 1024).toFixed(1)} KB · ${run.output_lines ?? "?"} lines`} />}
        {scores.length > 0 && (
          <InspRow label="scores" value={
            <>{scores.map((s, i) => <span key={i} className="score-pill">{s.toFixed(1)}</span>)}</>
          } />
        )}
      </>
    );
  }

  return null;
}

function NodeInspector({ node, onClose }: { node: DagNode; onClose: () => void }) {
  const cfg = NODE_CFG[node.type];
  return (
    <div style={{
      width: 300, flexShrink: 0, background: "var(--surface)", borderLeft: "1px solid var(--border)",
      display: "flex", flexDirection: "column", overflow: "hidden",
    }}>
      <div style={{
        padding: "10px 14px", borderBottom: "1px solid var(--border)",
        display: "flex", alignItems: "center", gap: 8, flexShrink: 0,
      }}>
        <span style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em", color: node.color, fontFamily: "monospace" }}>
          {cfg.label}
        </span>
        <span style={{ flex: 1, fontSize: 12, fontWeight: 600, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {node.title}
        </span>
        <button onClick={onClose} style={{ background: "none", border: "none", color: "var(--dim)", cursor: "pointer", fontSize: 16, lineHeight: 1, padding: "0 2px" }}>×</button>
      </div>
      <div style={{ padding: "10px 14px", overflowY: "auto", flex: 1 }}>
        <NodeInspectorBody node={node} />
      </div>
    </div>
  );
}

// ── DAG canvas ────────────────────────────────────────────────────────────────
function DagCanvas({ run, selectedNode, onSelectNode }: {
  run: RunRecord;
  selectedNode: DagNode | null;
  onSelectNode: (n: DagNode | null) => void;
}) {
  const cols         = buildColumns(run);
  const { nodes, width, height } = layoutColumns(cols);
  const edges        = buildEdges(cols, nodes);

  return (
    <div
      style={{ flex: 1, overflow: "auto", background: "var(--bg)", padding: 8 }}
      onClick={(e) => { if (e.target === e.currentTarget) onSelectNode(null); }}
    >
      <svg width={width} height={height} style={{ display: "block" }}>
        {edges.map((edge, i) => <SvgEdge key={i} edge={edge} />)}
        {nodes.map((node) => (
          <SvgNode
            key={node.id}
            node={node}
            selected={selectedNode?.id === node.id}
            onClick={() => onSelectNode(selectedNode?.id === node.id ? null : node)}
          />
        ))}
      </svg>
    </div>
  );
}

// ── Run list ──────────────────────────────────────────────────────────────────
function RunList({ runs, selected, onSelect }: {
  runs:     RunRecord[];
  selected: RunRecord | null;
  onSelect: (r: RunRecord) => void;
}) {
  return (
    <div style={{
      width: 230, flexShrink: 0,
      background: "var(--surface)", borderRight: "1px solid var(--border)",
      display: "flex", flexDirection: "column", overflow: "hidden",
    }}>
      <div style={{
        padding: "10px 12px", borderBottom: "1px solid var(--border)",
        fontSize: 10, fontWeight: 700, textTransform: "uppercase",
        letterSpacing: "0.08em", color: "var(--dim)", flexShrink: 0,
      }}>
        Runs ({runs.length})
      </div>
      <div style={{ overflowY: "auto", flex: 1 }}>
        {runs.length === 0 && (
          <div className="empty-state">No runs yet.</div>
        )}
        {runs.map((r) => {
          const score = r.wiggum_scores?.at(-1);
          const isSelected = selected?.run_id === r.run_id;
          return (
            <div
              key={r.run_id}
              onClick={() => onSelect(r)}
              style={{
                padding: "8px 12px",
                borderLeft: `3px solid ${isSelected ? "var(--accent)" : "transparent"}`,
                borderBottom: "1px solid rgba(42,45,58,.4)",
                background: isSelected ? "rgba(129,140,248,0.07)" : "none",
                cursor: "pointer",
                transition: "background 0.1s",
              }}
              onMouseEnter={(e) => { if (!isSelected) (e.currentTarget as HTMLDivElement).style.background = "rgba(255,255,255,0.025)"; }}
              onMouseLeave={(e) => { if (!isSelected) (e.currentTarget as HTMLDivElement).style.background = "none"; }}
            >
              <div style={{ fontSize: 9, color: "var(--dim)", marginBottom: 2 }}>
                {r.timestamp?.slice(0, 16).replace("T", " ")}
              </div>
              <div style={{ fontSize: 11, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginBottom: 4 }}>
                {r.task.slice(0, 44)}{r.task.length > 44 ? "…" : ""}
              </div>
              <div style={{ display: "flex", gap: 5, alignItems: "center" }}>
                {r.final && (
                  <span className={clsx("badge", r.final.toLowerCase())} style={{ fontSize: "0.6rem" }}>
                    {r.final}
                  </span>
                )}
                {score != null && (
                  <span style={{ fontSize: 10, color: score >= 8 ? "var(--pass)" : score >= 6 ? "var(--warn)" : "var(--fail)", fontWeight: 700, fontFamily: "var(--font-mono)" }}>
                    {score.toFixed(1)}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Explorer ──────────────────────────────────────────────────────────────────
export function Explorer() {
  const { data: runs = [], isLoading, error } = useAllRuns();
  const [selectedRun,  setSelectedRun]  = useState<RunRecord | null>(null);
  const [selectedNode, setSelectedNode] = useState<DagNode | null>(null);

  // Prefer a run with tool_calls or wiggum_scores over an empty shell
  const defaultRun = runs.find((r) => (r.tool_calls?.length ?? 0) > 0 || (r.wiggum_scores?.length ?? 0) > 0) ?? runs[0] ?? null;
  const activeRun  = selectedRun ?? defaultRun;

  const handleSelectRun = (r: RunRecord) => {
    setSelectedRun(r);
    setSelectedNode(null);
  };

  if (isLoading) return <div className="loading">Loading…</div>;
  if (error)     return <div className="error">Failed to load runs.</div>;

  return (
    <div style={{ margin: "-28px", height: "100vh", display: "flex", overflow: "hidden" }}>
      <RunList runs={runs} selected={activeRun} onSelect={handleSelectRun} />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {activeRun ? (
          <>
            <div style={{
              padding: "8px 14px", borderBottom: "1px solid var(--border)",
              fontSize: 11, color: "var(--dim)", background: "var(--surface)",
              flexShrink: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>
              <span style={{ color: "var(--accent)", fontWeight: 600 }}>{activeRun.run_id?.slice(0, 20) ?? "—"}</span>
              {" · "}
              {activeRun.task.slice(0, 80)}{activeRun.task.length > 80 ? "…" : ""}
            </div>
            <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
              <DagCanvas
                run={activeRun}
                selectedNode={selectedNode}
                onSelectNode={setSelectedNode}
              />
              {selectedNode && (
                <NodeInspector
                  node={selectedNode}
                  onClose={() => setSelectedNode(null)}
                />
              )}
            </div>
          </>
        ) : (
          <div className="empty-state" style={{ margin: "auto" }}>
            Select a run from the list to view its pipeline DAG.
          </div>
        )}
      </div>
    </div>
  );
}

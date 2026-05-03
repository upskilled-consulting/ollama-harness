import { useState, useMemo, useEffect, type ReactNode, type CSSProperties } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { useAllRuns } from "@/hooks/useRuns";
import { MdView } from "@/components/MdView";
import type { RunRecord, WiggumDim, ToolCall, WiggumEvalEntry, Plan, StageTokens, FeedbackRecord } from "@/types";

// ── shared helpers ─────────────────────────────────────────────────────────────

function fmtTs(ts: string | undefined) {
  if (!ts) return "—";
  const d  = new Date(ts);
  const mo = d.toLocaleString("en-US", { month: "short" });
  const dy = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${mo} ${dy}  ${hh}:${mm}`;
}

function scoreColor(s: number) {
  return s >= 8 ? "var(--pass)" : s >= 6 ? "var(--warn)" : "var(--fail)";
}

const trunc = (s: string | null | undefined, n: number) =>
  !s ? "" : s.length > n ? s.slice(0, n - 1) + "…" : s;

const DIM_COLORS: Record<string, string> = {
  relevance:    "#4f8ef7",
  completeness: "#3fb950",
  depth:        "#a78bfa",
  specificity:  "#22d3ee",
  structure:    "#fb923c",
  grounded:     "#f0b429",
};

// ── DAG constants ──────────────────────────────────────────────────────────────

const NW = 162, NH = 64, HGAP = 60, VGAP = 12, PAD = 28;

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

interface DagNode {
  id: string; type: NodeType; col: number; row: number;
  x: number;  y: number;      title: string; sub: string;
  color: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: any;
}
interface DagEdge { from: DagNode; to: DagNode }

// ── DAG builder ────────────────────────────────────────────────────────────────

function buildColumns(run: RunRecord): DagNode[][] {
  const cols: DagNode[][] = [];

  cols.push([{ id: "task", type: "task", col: 0, row: 0, x: 0, y: 0,
    title: trunc(run.task, 22), sub: trunc(run.producer_model, 28),
    color: NODE_CFG.task.color, data: run }]);

  cols.push([{ id: "memory", type: "memory", col: 0, row: 0, x: 0, y: 0,
    title: `${run.memory_hits ?? 0} memory hit${run.memory_hits === 1 ? "" : "s"}`,
    sub: trunc(run.memory_context_titles?.[0] ?? "no prior context", 28),
    color: NODE_CFG.memory.color,
    data: { hits: run.memory_hits, titles: run.memory_context_titles ?? [] } }]);

  if (run.plan) {
    const queries = run.plan.search_queries ?? run.plan.queries ?? [];
    cols.push([{ id: "plan", type: "plan", col: 0, row: 0, x: 0, y: 0,
      title: `${queries.length} quer${queries.length === 1 ? "y" : "ies"} planned`,
      sub: trunc(queries[0] ?? "", 28), color: NODE_CFG.plan.color, data: run.plan }]);
  }

  const EXEC_TOOLS  = new Set(["run_python", "run_code", "execute_python", "execute_code"]);
  const tcSearches  = (run.tool_calls ?? []).filter((tc) => !EXEC_TOOLS.has(tc.name));
  const planQueries = run.plan ? (run.plan.search_queries ?? run.plan.queries ?? []) : [];

  if (tcSearches.length > 0) {
    cols.push(tcSearches.map((tc, i) => ({
      id: `search-${i}`, type: "search" as NodeType, col: 0, row: 0, x: 0, y: 0,
      title: trunc(tc.query ?? tc.name, 22),
      sub: tc.result_chars != null ? `${tc.name} · ${(tc.result_chars / 1000).toFixed(1)}k` : tc.name,
      color: NODE_CFG.search.color, data: tc,
    })));
  } else if (planQueries.length > 0) {
    cols.push(planQueries.map((q, i) => ({
      id: `search-${i}`, type: "search" as NodeType, col: 0, row: 0, x: 0, y: 0,
      title: trunc(q, 22), sub: "planned query",
      color: NODE_CFG.search.color, data: { name: "web_search", query: q, result_chars: null },
    })));
  }

  const synth = run.tokens_by_stage?.synth;
  cols.push([{ id: "synthesis", type: "synthesis", col: 0, row: 0, x: 0, y: 0,
    title: "Synthesis",
    sub: run.output_bytes ? `${(run.output_bytes / 1024).toFixed(1)} KB` : synth?.output ? `${synth.output} out-tok` : "—",
    color: NODE_CFG.synthesis.color,
    data: { synth, output_bytes: run.output_bytes, synth_cot: run.synth_cot } }]);

  const evalLog = run.wiggum_eval_log ?? [];
  if (evalLog.length > 0) {
    cols.push(evalLog.map((entry, i) => ({
      id: `eval-${i}`, type: "eval" as NodeType, col: 0, row: 0, x: 0, y: 0,
      title: `Round ${entry.round}/${evalLog.length} · ${entry.score?.toFixed(1) ?? "?"}`,
      sub: entry.issues?.[0] ? trunc(entry.issues[0], 28) : "no issues",
      color: NODE_CFG.eval.color, data: entry,
    })));
  } else if ((run.wiggum_scores ?? []).length > 0) {
    const scores = run.wiggum_scores ?? [];
    cols.push(scores.map((score, i) => ({
      id: `eval-${i}`, type: "eval" as NodeType, col: 0, row: 0, x: 0, y: 0,
      title: `Round ${i + 1}/${scores.length} · ${score.toFixed(1)}`,
      sub: (run.wiggum_issues ?? []).length > 0 ? `${run.wiggum_issues!.length} issue(s)` : "no issues",
      color: NODE_CFG.eval.color,
      data: { round: i + 1, score, dims: run.wiggum_dims?.[i], issues: run.wiggum_issues ?? [] },
    })));
  }

  const outColor = run.final === "PASS" ? "#3fb950" : run.final === "FAIL" ? "#f85149" : "#8b949e";
  cols.push([{ id: "output", type: "output", col: 0, row: 0, x: 0, y: 0,
    title: run.final ?? "running",
    sub: run.output_path ? trunc(run.output_path.replace(/.*[/\\]/, ""), 28) : "—",
    color: outColor, data: run }]);

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
    col.forEach((node, ri) => nodes.push({ ...node, col: ci, row: ri, x, y: startY + ri * (NH + VGAP) }));
  });
  return { nodes, width: svgW, height: svgH };
}

function buildEdges(cols: DagNode[][], laid: DagNode[]): DagEdge[] {
  const edges: DagEdge[] = [];
  for (let ci = 0; ci < cols.length - 1; ci++) {
    const froms = laid.filter((n) => n.col === ci);
    const tos   = laid.filter((n) => n.col === ci + 1);
    for (const f of froms) for (const t of tos) edges.push({ from: f, to: t });
  }
  return edges;
}

// ── SVG components ─────────────────────────────────────────────────────────────

function SvgEdge({ edge }: { edge: DagEdge }) {
  const x1 = edge.from.x + NW, y1 = edge.from.y + NH / 2;
  const x2 = edge.to.x,        y2 = edge.to.y   + NH / 2;
  const mx = (x1 + x2) / 2;
  return <path d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`} fill="none"
    stroke={edge.from.color} strokeWidth={1.5} strokeDasharray="5 3" opacity={0.4} />;
}

function SvgNode({ node, selected, onClick }: { node: DagNode; selected: boolean; onClick: () => void }) {
  return (
    <g transform={`translate(${node.x},${node.y})`} onClick={onClick} style={{ cursor: "pointer" }}>
      <rect width={NW} height={NH} rx={5} fill={selected ? "rgba(255,255,255,0.06)" : "#0d1018"}
        stroke={node.color} strokeWidth={selected ? 1.8 : 1} />
      <rect width={4} height={NH} rx={2} fill={node.color} />
      <text x={12} y={16} fill={node.color} fontSize={8} fontFamily="monospace" fontWeight="bold" letterSpacing="0.1em">
        {NODE_CFG[node.type].label}
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

// ── Output preview ─────────────────────────────────────────────────────────────

function OutputPreview({ runId }: { runId: string }) {
  const [open, setOpen]       = useState(false);
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr]         = useState<string | null>(null);

  const toggle = async () => {
    if (open) { setOpen(false); return; }
    setOpen(true);
    if (content !== null) return;
    setLoading(true); setErr(null);
    try {
      const res = await fetch(`/api/runs/${runId}/content`);
      if (!res.ok) { throw new Error(await res.text()); }
      const data = await res.json() as { content: string };
      setContent(data.content);
    } catch (e) { setErr(String(e)); }
    finally { setLoading(false); }
  };

  return (
    <div style={{ marginTop: 8 }}>
      <button onClick={toggle} style={{ background: "none", border: "1px solid var(--border)", borderRadius: 4, color: "var(--dim)", cursor: "pointer", fontSize: 10, padding: "3px 8px", textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {open ? "▲ hide preview" : "▼ preview output"}
      </button>
      {open && (
        <div style={{ marginTop: 6, maxHeight: 380, overflowY: "auto", background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 5, padding: "10px 12px" }}>
          {loading && <div style={{ color: "var(--dim)", fontSize: 11 }}>Loading…</div>}
          {err     && <div style={{ color: "var(--fail)", fontSize: 11 }}>{err}</div>}
          {content && <MdView content={content} />}
        </div>
      )}
    </div>
  );
}

// ── Stage tokens ───────────────────────────────────────────────────────────────

function StageToks({ candidates, tokensByStage }: { candidates: string[]; tokensByStage?: Record<string, StageTokens> }) {
  if (!tokensByStage) return null;
  const st = candidates.map((k) => tokensByStage[k]).find(Boolean);
  if (!st || (!st.input && !st.output)) return null;
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--dim)", marginBottom: 3 }}>Tokens</div>
      <div style={{ display: "flex", gap: 14, fontSize: 11, fontFamily: "var(--font-mono)" }}>
        {st.input  != null && <span><span style={{ color: "var(--dim)" }}>in </span>{st.input.toLocaleString()}</span>}
        {st.output != null && <span><span style={{ color: "var(--dim)" }}>out </span>{st.output.toLocaleString()}</span>}
        {(st.calls ?? 0) > 1 && <span style={{ color: "var(--dim)" }}>×{st.calls}</span>}
        {st.total_ms != null && <span style={{ color: "var(--dim)" }}>{(st.total_ms / 1000).toFixed(1)}s</span>}
      </div>
    </div>
  );
}

function AllStageToks({ tokensByStage }: { tokensByStage?: Record<string, StageTokens> }) {
  if (!tokensByStage) return null;
  const entries = Object.entries(tokensByStage).filter(([, st]) => (st.input ?? 0) + (st.output ?? 0) > 0);
  if (entries.length === 0) return null;
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--dim)", marginBottom: 4 }}>Token breakdown</div>
      {entries.map(([name, st]) => (
        <div key={name} style={{ display: "flex", gap: 0, fontSize: 10, marginBottom: 2, fontFamily: "var(--font-mono)", alignItems: "baseline" }}>
          <span style={{ color: "var(--dim)", minWidth: 64 }}>{name}</span>
          <span style={{ color: "var(--text)", minWidth: 50 }}>{(st.input ?? 0).toLocaleString()}<span style={{ color: "var(--dim)" }}>↑</span></span>
          <span style={{ color: "var(--text)" }}>{(st.output ?? 0).toLocaleString()}<span style={{ color: "var(--dim)" }}>↓</span></span>
          {(st.calls ?? 0) > 1 && <span style={{ color: "var(--dim)", marginLeft: 6 }}>×{st.calls}</span>}
        </div>
      ))}
    </div>
  );
}

// ── Dim bars ───────────────────────────────────────────────────────────────────

function DimBars({ dims }: { dims: WiggumDim }) {
  const keys = Object.keys(dims).filter((k) => typeof dims[k] === "number");
  return (
    <div style={{ marginTop: 6 }}>
      {keys.map((k) => {
        const val = dims[k] ?? 0;
        const color = DIM_COLORS[k] ?? "#4f8ef7";
        return (
          <div key={k} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
            <span style={{ fontSize: 10, color: "var(--dim)", minWidth: 84, textTransform: "capitalize" }}>{k}</span>
            <div style={{ flex: 1, height: 5, background: "rgba(255,255,255,0.07)", borderRadius: 3, overflow: "hidden" }}>
              <div style={{ width: `${Math.min(100, (val / 10) * 100)}%`, height: "100%", background: color, borderRadius: 3, transition: "width 0.3s" }} />
            </div>
            <span style={{ fontSize: 10, color, fontFamily: "var(--font-mono)", minWidth: 22, textAlign: "right" }}>{val}</span>
          </div>
        );
      })}
    </div>
  );
}

// ── RLHF panel ─────────────────────────────────────────────────────────────────

function RlhfPanel({ runId, nodeId }: { runId: string; nodeId: string }) {
  const [rating, setRating]         = useState<1 | -1 | null>(null);
  const [comment, setComment]       = useState("");
  const [saved, setSaved]           = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const qc = useQueryClient();

  const { data: feedbackList } = useQuery({
    queryKey: ["feedback", runId],
    queryFn:  () => fetch(`/api/feedback/${runId}`).then((r) => r.json() as Promise<FeedbackRecord[]>),
    staleTime: 10_000,
  });

  useEffect(() => {
    const existing = [...(feedbackList ?? [])].reverse().find((f) => f.node_id === nodeId);
    if (existing) { setRating(existing.rating); setComment(existing.comment ?? ""); setSaved(true); }
    else          { setRating(null); setComment(""); setSaved(false); }
  }, [feedbackList, nodeId]);

  const submit = async () => {
    if (rating === null) return;
    setSubmitting(true);
    try {
      await fetch("/api/feedback", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId, node_id: nodeId, rating, comment }) });
      setSaved(true);
      void qc.invalidateQueries({ queryKey: ["feedback", runId] });
    } finally { setSubmitting(false); }
  };

  const thumb = (active: boolean, color: string): CSSProperties => ({
    background: active ? `${color}20` : "none", border: `1px solid ${active ? color : "var(--border)"}`,
    color: active ? color : "var(--dim)", borderRadius: 6, padding: "3px 10px", cursor: "pointer", fontSize: 13, lineHeight: 1,
  });

  return (
    <div style={{ marginTop: 16, paddingTop: 10, borderTop: "1px solid var(--border)" }}>
      <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--dim)", marginBottom: 7 }}>Rate this step</div>
      <div style={{ display: "flex", gap: 6, marginBottom: 7, alignItems: "center" }}>
        <button style={thumb(rating === 1,  "#34d399")} onClick={() => { setRating(1);  setSaved(false); }}>👍</button>
        <button style={thumb(rating === -1, "#f87171")} onClick={() => { setRating(-1); setSaved(false); }}>👎</button>
        {saved && <span style={{ fontSize: 10, color: "var(--pass)", marginLeft: 2 }}>✓ saved</span>}
      </div>
      <textarea value={comment} onChange={(e) => { setComment(e.target.value); setSaved(false); }}
        placeholder="Add a comment…" rows={2}
        style={{ width: "100%", background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 5, color: "var(--text)", fontSize: 11, padding: "5px 8px", resize: "vertical", fontFamily: "inherit", marginBottom: 6, outline: "none" }} />
      <button onClick={submit} disabled={rating === null || submitting}
        style={{ background: rating !== null ? "rgba(129,140,248,0.12)" : "none", border: "1px solid var(--accent)", color: rating !== null ? "var(--accent)" : "var(--dim)", borderRadius: 5, padding: "4px 0", cursor: rating !== null ? "pointer" : "not-allowed", fontSize: 11, width: "100%" }}>
        {submitting ? "Saving…" : saved ? "✓ Feedback saved" : "Submit feedback"}
      </button>
    </div>
  );
}

// ── Node inspector ─────────────────────────────────────────────────────────────

function InspRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div style={{ display: "flex", gap: 8, padding: "4px 0", borderBottom: "1px solid rgba(42,45,58,.5)", fontSize: 12 }}>
      <span style={{ color: "var(--dim)", minWidth: 90, flexShrink: 0, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</span>
      <span style={{ color: "var(--text)", wordBreak: "break-word", flex: 1 }}>{value}</span>
    </div>
  );
}

function NodeInspectorBody({ node, run }: { node: DagNode; run: RunRecord }) {
  const d   = node.data as Record<string, unknown>;
  const tbs = run.tokens_by_stage;

  if (node.type === "task") {
    const r = d as unknown as RunRecord;
    return (<>
      <div style={{ fontSize: 12, lineHeight: 1.6, marginBottom: 10, wordBreak: "break-word", color: "var(--text)" }}>{r.task}</div>
      <InspRow label="timestamp"   value={r.timestamp?.slice(0, 19).replace("T", " ")} />
      <InspRow label="model"       value={r.producer_model} />
      <InspRow label="evaluator"   value={r.evaluator_model} />
      <InspRow label="type"        value={r.task_type ?? "—"} />
      <InspRow label="duration"    value={r.run_duration_s ? `${r.run_duration_s.toFixed(1)}s` : "—"} />
      <InspRow label="tokens"      value={`${(r.input_tokens ?? 0).toLocaleString()} in · ${(r.output_tokens ?? 0).toLocaleString()} out`} />
      {r.orchestrated && <InspRow label="orchestrated" value={r.subtask_count != null ? `${r.subtask_count} subtasks` : "yes"} />}
    </>);
  }
  if (node.type === "memory") {
    const titles = (d.titles as string[]) ?? [];
    return (<>
      <InspRow label="hits" value={String(d.hits ?? 0)} />
      {titles.length > 0 ? titles.map((t, i) => <InspRow key={i} label={`obs ${i + 1}`} value={t} />) : <InspRow label="status" value="no prior context" />}
    </>);
  }
  if (node.type === "plan") {
    const plan    = d as Plan;
    const queries = plan.search_queries ?? plan.queries ?? [];
    return (<>
      {queries.map((q, i) => <InspRow key={i} label={`query ${i + 1}`} value={q} />)}
      {plan.notes && <InspRow label="notes" value={plan.notes} />}
      {(plan.known_facts ?? []).map((f, i) => <InspRow key={i} label={`known ${i + 1}`} value={f} />)}
      {(plan.knowledge_gaps ?? []).map((g, i) => <InspRow key={i} label={`gap ${i + 1}`} value={g} />)}
      <StageToks candidates={["plan", "planner", "plan_prior", "prior"]} tokensByStage={tbs} />
    </>);
  }
  if (node.type === "search") {
    const tc = d as unknown as ToolCall;
    return (<>
      <InspRow label="tool" value={tc.name} />
      <div style={{ marginTop: 8, marginBottom: 8, padding: "10px 12px", background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 6, fontSize: 12, lineHeight: 1.6, wordBreak: "break-word", color: "var(--text)" }}>{tc.query ?? "—"}</div>
      <InspRow label="result" value={tc.result_chars != null ? `${tc.result_chars.toLocaleString()} chars` : "—"} />
      <StageToks candidates={["search", "web_search", "fetch", "browse"]} tokensByStage={tbs} />
    </>);
  }
  if (node.type === "synthesis") {
    const synth = d.synth as StageTokens | undefined;
    const cot   = d.synth_cot as string[] | undefined;
    return (<>
      <InspRow label="out tokens" value={synth?.output?.toLocaleString() ?? "—"} />
      <InspRow label="in tokens"  value={synth?.input?.toLocaleString() ?? "—"} />
      <InspRow label="time"       value={synth?.total_ms != null ? `${(synth.total_ms / 1000).toFixed(1)}s` : "—"} />
      <InspRow label="output"     value={d.output_bytes != null ? `${((d.output_bytes as number) / 1024).toFixed(1)} KB` : "—"} />
      <AllStageToks tokensByStage={tbs} />
      {cot && cot.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--dim)", marginBottom: 4 }}>Chain of thought ({cot.length})</div>
          <div style={{ maxHeight: 160, overflowY: "auto", display: "flex", flexDirection: "column", gap: 5 }}>
            {cot.map((step, i) => (
              <div key={i} style={{ fontSize: 10, color: "var(--dim)", lineHeight: 1.5, wordBreak: "break-word", padding: "5px 8px", background: "rgba(0,0,0,0.2)", borderRadius: 4, borderLeft: "2px solid rgba(129,140,248,0.4)" }}>{step}</div>
            ))}
          </div>
        </div>
      )}
      <OutputPreview runId={run.run_id} />
    </>);
  }
  if (node.type === "eval") {
    const entry = d as unknown as WiggumEvalEntry;
    return (<>
      <InspRow label="round" value={String(entry.round)} />
      <InspRow label="score" value={entry.score?.toFixed(2) ?? "—"} />
      {entry.dims && <DimBars dims={entry.dims} />}
      <StageToks candidates={["eval", "wiggum", "annotate"]} tokensByStage={tbs} />
      {(entry.issues ?? []).length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--dim)", marginBottom: 4 }}>Issues</div>
          <div className="issues-scroll">{entry.issues!.map((iss, i) => <div key={i} className="issue-item">{iss}</div>)}</div>
        </div>
      )}
      {entry.feedback && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--dim)", marginBottom: 4 }}>Evaluator feedback</div>
          <div style={{ fontSize: 11, color: "var(--dim)", lineHeight: 1.5, wordBreak: "break-word" }}>{entry.feedback}</div>
        </div>
      )}
      {entry.thinking && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--dim)", marginBottom: 4 }}>Evaluator reasoning</div>
          <div style={{ maxHeight: 200, overflowY: "auto", fontSize: 10, color: "var(--dim)", lineHeight: 1.6, wordBreak: "break-word", padding: "6px 8px", background: "rgba(0,0,0,0.2)", borderRadius: 4, borderLeft: "2px solid rgba(227,179,65,0.4)" }}>{entry.thinking}</div>
        </div>
      )}
    </>);
  }
  if (node.type === "output") {
    const r      = d as unknown as RunRecord;
    const scores = r.wiggum_scores ?? [];
    return (<>
      <InspRow label="status" value={<span className={clsx("badge", (r.final ?? "error").toLowerCase())}>{r.final ?? "running"}</span>} />
      {r.output_path && <InspRow label="path"  value={r.output_path} />}
      {r.output_bytes != null && <InspRow label="size" value={`${(r.output_bytes / 1024).toFixed(1)} KB · ${r.output_lines ?? "?"} lines`} />}
      {scores.length > 0 && <InspRow label="scores" value={<>{scores.map((s, i) => <span key={i} className="score-pill">{s.toFixed(1)}</span>)}</>} />}
      <InspRow label="tokens" value={`${(r.input_tokens ?? 0).toLocaleString()} in · ${(r.output_tokens ?? 0).toLocaleString()} out`} />
      {r.leverage  != null && <InspRow label="leverage"  value={`${r.leverage.toFixed(1)}×`} />}
      {r.tac_hours != null && <InspRow label="tac hours" value={`${r.tac_hours.toFixed(2)} h`} />}
      <OutputPreview runId={r.run_id} />
    </>);
  }
  return null;
}

function NodeInspector({ node, run, onClose }: { node: DagNode; run: RunRecord; onClose: () => void }) {
  return (
    <div style={{ width: 340, flexShrink: 0, background: "var(--surface)", borderLeft: "1px solid var(--border)", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
        <span style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em", color: node.color, fontFamily: "monospace" }}>{NODE_CFG[node.type].label}</span>
        <span style={{ flex: 1, fontSize: 12, fontWeight: 600, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{node.title}</span>
        <button onClick={onClose} style={{ background: "none", border: "none", color: "var(--dim)", cursor: "pointer", fontSize: 16, lineHeight: 1, padding: "0 2px" }}>×</button>
      </div>
      <div style={{ padding: "10px 14px", overflowY: "auto", flex: 1 }}>
        <NodeInspectorBody node={node} run={run} />
        <RlhfPanel runId={run.run_id} nodeId={node.id} />
      </div>
    </div>
  );
}

// ── Run summary card ───────────────────────────────────────────────────────────

function Chip({ label, value }: { label: string; value: string | undefined | null }) {
  if (!value) return null;
  return (
    <span style={{ display: "inline-flex", gap: 5, fontSize: 11, padding: "2px 8px", borderRadius: 6, background: "rgba(255,255,255,0.04)", border: "1px solid var(--border)" }}>
      <span style={{ color: "var(--dim)" }}>{label}</span>
      <span style={{ color: "var(--text)", fontFamily: "var(--font-mono)" }}>{value}</span>
    </span>
  );
}

function RunSummaryCard({ run, onClose }: { run: RunRecord; onClose: () => void }) {
  const scores   = run.wiggum_scores ?? [];
  const lastDim  = run.wiggum_dims?.at(-1);
  const lastEval = run.wiggum_eval_log?.at(-1);
  const feedback = lastEval?.feedback;
  const issues   = run.wiggum_issues ?? lastEval?.issues ?? [];

  return (
    <div style={{
      flexShrink: 0, background: "var(--surface)", borderBottom: "1px solid var(--border)",
      padding: "14px 18px", display: "flex", flexDirection: "column", gap: 10,
    }}>
      {/* top row: status + task + close */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
        <span className={clsx("badge", (run.final ?? "running").toLowerCase())} style={{ flexShrink: 0, marginTop: 2 }}>
          {run.final ?? "running"}
        </span>
        <div style={{ flex: 1, fontSize: 13, lineHeight: 1.55, color: "var(--text)", wordBreak: "break-word" }}>
          {run.task}
        </div>
        <button onClick={onClose} style={{ background: "none", border: "none", color: "var(--dim)", cursor: "pointer", fontSize: 16, lineHeight: 1, flexShrink: 0, padding: "0 2px" }}>×</button>
      </div>

      {/* stats chips */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
        <Chip label="model"    value={run.producer_model} />
        <Chip label="type"     value={run.task_type} />
        <Chip label="duration" value={run.run_duration_s != null ? `${run.run_duration_s.toFixed(1)}s` : null} />
        <Chip label="in"       value={run.input_tokens ? run.input_tokens.toLocaleString() : null} />
        <Chip label="out"      value={run.output_tokens ? run.output_tokens.toLocaleString() : null} />
        <Chip label="output"   value={run.output_bytes != null ? `${(run.output_bytes / 1024).toFixed(1)} KB` : null} />
        {scores.map((s, i) => (
          <span key={i} style={{ display: "inline-flex", gap: 4, fontSize: 11, padding: "2px 8px", borderRadius: 6, fontWeight: 700, fontFamily: "var(--font-mono)", background: `${scoreColor(s)}15`, border: `1px solid ${scoreColor(s)}40`, color: scoreColor(s) }}>
            r{i + 1} · {s.toFixed(1)}
          </span>
        ))}
      </div>

      {/* dim bars */}
      {lastDim && <DimBars dims={lastDim} />}

      {/* issues */}
      {issues.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {issues.map((iss, i) => (
            <div key={i} style={{ fontSize: 11, color: "var(--dim)", lineHeight: 1.45, padding: "2px 0 2px 10px", borderLeft: "2px solid var(--warn)", wordBreak: "break-word" }}>{iss}</div>
          ))}
        </div>
      )}

      {/* evaluator feedback */}
      {feedback && (
        <div style={{ fontSize: 11, color: "var(--dim)", lineHeight: 1.5, fontStyle: "italic", wordBreak: "break-word" }}>{feedback}</div>
      )}
    </div>
  );
}

// ── DAG canvas ─────────────────────────────────────────────────────────────────

function DagCanvas({ run, selectedNode, onSelectNode }: { run: RunRecord; selectedNode: DagNode | null; onSelectNode: (n: DagNode | null) => void }) {
  const cols  = buildColumns(run);
  const { nodes, width, height } = layoutColumns(cols);
  const edges = buildEdges(cols, nodes);
  return (
    <div style={{ flex: 1, overflow: "auto", background: "var(--bg)", padding: 8 }}
      onClick={(e) => { if (e.target === e.currentTarget) onSelectNode(null); }}>
      <svg width={width} height={height} style={{ display: "block" }}>
        {edges.map((edge, i) => <SvgEdge key={i} edge={edge} />)}
        {nodes.map((node) => (
          <SvgNode key={node.id} node={node} selected={selectedNode?.id === node.id}
            onClick={() => onSelectNode(selectedNode?.id === node.id ? null : node)} />
        ))}
      </svg>
    </div>
  );
}

// ── Left panel: filter + list ──────────────────────────────────────────────────

type StatusFilter = "all" | "pass" | "fail" | "error" | "running";

function LeftPanel({ runs, selected, onSelect }: { runs: RunRecord[]; selected: RunRecord | null; onSelect: (r: RunRecord) => void }) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");

  const filtered = useMemo(() => runs.filter((r) => {
    if (status !== "all") {
      const f = r.final?.toLowerCase() ?? "running";
      if (f !== status) return false;
    }
    if (search) {
      const q = search.toLowerCase();
      if (!r.task.toLowerCase().includes(q) && !(r.producer_model ?? "").toLowerCase().includes(q)) return false;
    }
    return true;
  }), [runs, search, status]);

  const statuses: StatusFilter[] = ["all", "pass", "fail", "error", "running"];

  return (
    <div style={{ width: 260, flexShrink: 0, background: "var(--surface)", borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* filter bar */}
      <div style={{ padding: "10px 10px 8px", borderBottom: "1px solid var(--border)", display: "flex", flexDirection: "column", gap: 7, flexShrink: 0 }}>
        <input
          type="search" placeholder="Filter…" value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: "100%", background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)", fontSize: 11, padding: "5px 9px", outline: "none" }}
        />
        <div style={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
          {statuses.map((s) => (
            <button key={s} onClick={() => setStatus(s)} style={{
              padding: "2px 7px", borderRadius: 5, fontSize: 10, fontWeight: 600, cursor: "pointer",
              textTransform: "uppercase", letterSpacing: "0.04em",
              border: status === s ? "1px solid var(--accent)" : "1px solid var(--border)",
              background: status === s ? "rgba(129,140,248,0.15)" : "none",
              color: status === s ? "var(--accent)" : "var(--dim)",
            }}>{s}</button>
          ))}
        </div>
        <span style={{ fontSize: 10, color: "var(--dim)" }}>
          {filtered.length === runs.length ? `${runs.length} runs` : `${filtered.length} / ${runs.length}`}
        </span>
      </div>

      {/* run list */}
      <div style={{ overflowY: "auto", flex: 1 }}>
        {filtered.length === 0 && <div className="empty-state">No runs match.</div>}
        {filtered.map((r) => {
          const score      = r.wiggum_scores?.at(-1);
          const isSelected = selected?.run_id === r.run_id;
          return (
            <div key={r.run_id} onClick={() => onSelect(r)} style={{
              padding: "8px 12px", cursor: "pointer",
              borderLeft: `3px solid ${isSelected ? "var(--accent)" : "transparent"}`,
              borderBottom: "1px solid rgba(42,45,58,.4)",
              background: isSelected ? "rgba(129,140,248,0.07)" : "none",
              transition: "background 0.1s",
            }}
              onMouseEnter={(e) => { if (!isSelected) (e.currentTarget as HTMLDivElement).style.background = "rgba(255,255,255,0.025)"; }}
              onMouseLeave={(e) => { if (!isSelected) (e.currentTarget as HTMLDivElement).style.background = "none"; }}
            >
              <div style={{ fontSize: 9, color: "var(--dim)", marginBottom: 2, fontFamily: "var(--font-mono)" }}>
                {fmtTs(r.timestamp)}
              </div>
              <div style={{ fontSize: 11, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginBottom: 4 }}>
                {r.task.slice(0, 46)}{r.task.length > 46 ? "…" : ""}
              </div>
              <div style={{ display: "flex", gap: 5, alignItems: "center" }}>
                {r.final && <span className={clsx("badge", r.final.toLowerCase())} style={{ fontSize: "0.6rem" }}>{r.final}</span>}
                {score != null && (
                  <span style={{ fontSize: 10, fontWeight: 700, fontFamily: "var(--font-mono)", color: scoreColor(score) }}>{score.toFixed(1)}</span>
                )}
                {r.run_duration_s != null && (
                  <span style={{ fontSize: 10, color: "var(--dim)", marginLeft: "auto", fontFamily: "var(--font-mono)" }}>{r.run_duration_s.toFixed(0)}s</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Main view ──────────────────────────────────────────────────────────────────

export function Runs() {
  const { data: runs = [], isLoading, error } = useAllRuns();
  const [selectedRun,  setSelectedRun]  = useState<RunRecord | null>(null);
  const [selectedNode, setSelectedNode] = useState<DagNode | null>(null);

  const defaultRun = runs.find((r) => (r.tool_calls?.length ?? 0) > 0 || (r.wiggum_scores?.length ?? 0) > 0) ?? runs[0] ?? null;
  const activeRun  = selectedRun ?? defaultRun;

  const handleSelectRun = (r: RunRecord) => { setSelectedRun(r); setSelectedNode(null); };
  const handleDeselectRun = () => { setSelectedRun(null); setSelectedNode(null); };

  if (isLoading) return <div className="loading">Loading…</div>;
  if (error)     return <div className="page-error">Failed to load runs.</div>;

  return (
    <div style={{ margin: "-28px", height: "100vh", display: "flex", overflow: "hidden" }}>
      <LeftPanel runs={runs} selected={activeRun} onSelect={handleSelectRun} />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {activeRun ? (
          <>
            <RunSummaryCard run={activeRun} onClose={handleDeselectRun} />
            <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
              <DagCanvas run={activeRun} selectedNode={selectedNode} onSelectNode={setSelectedNode} />
              {selectedNode && (
                <NodeInspector node={selectedNode} run={activeRun} onClose={() => setSelectedNode(null)} />
              )}
            </div>
          </>
        ) : (
          <div className="empty-state" style={{ margin: "auto" }}>Select a run to view its pipeline.</div>
        )}
      </div>
    </div>
  );
}

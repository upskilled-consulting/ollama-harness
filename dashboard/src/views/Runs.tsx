import { useState, useEffect, useRef, type ReactNode, type CSSProperties } from "react";
import { Plus, Minus, RefreshCw, Brain, ChevronDown, ChevronRight } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { useLiveRun, usePagedRuns } from "@/hooks/useRuns";
import { MdView } from "@/components/MdView";
import type { RunRecord, WiggumDim, ToolCall, ToolCallUrl, WiggumEvalEntry, Plan, StageTokens, FeedbackRecord, RunMessage, LiveRun } from "@/types";

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

const NW = 140, NH = 58, HGAP = 44, VGAP = 10, PAD = 24;

type NodeType = "task" | "memory" | "plan" | "search" | "synthesis" | "eval" | "output"
             | "lr_fetch" | "lr_curate" | "lr_cluster" | "lr_synth" | "lr_out";

const NODE_CFG: Record<NodeType, { color: string; label: string }> = {
  task:       { color: "#4f8ef7", label: "TASK"      },
  memory:     { color: "#a78bfa", label: "MEMORY"    },
  plan:       { color: "#38bdf8", label: "PLAN"      },
  search:     { color: "#fb923c", label: "SEARCH"    },
  synthesis:  { color: "#22d3ee", label: "SYNTHESIS" },
  eval:       { color: "#e3b341", label: "EVAL"      },
  output:     { color: "#3fb950", label: "OUTPUT"    },
  lr_fetch:   { color: "#38bdf8", label: "FETCH"     },
  lr_curate:  { color: "#a78bfa", label: "CURATE"    },
  lr_cluster: { color: "#e879f9", label: "CLUSTER"   },
  lr_synth:   { color: "#22d3ee", label: "SYNTH"     },
  lr_out:     { color: "#3fb950", label: "OUTPUT"    },
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

type NodeStatus = "done" | "running" | "pending";

function SvgNode({ node, selected, onClick, status = "done" }: {
  node: DagNode; selected: boolean; onClick: () => void; status?: NodeStatus;
}) {
  const isPending = status === "pending";
  const isRunning = status === "running";
  return (
    <g transform={`translate(${node.x},${node.y})`} onClick={onClick} style={{ cursor: "pointer" }}>
      <rect width={NW} height={NH} rx={5}
        fill={isPending ? "#0a0c12" : selected ? "rgba(255,255,255,0.06)" : "#0d1018"}
        stroke={isPending ? "rgba(255,255,255,0.18)" : node.color}
        strokeWidth={selected || isRunning ? 1.8 : 1}
        strokeDasharray={isPending ? "4 3" : undefined}
        style={{ transition: "stroke 0.3s, fill 0.3s" }}
      />
      {/* Pulsing outer ring for running state */}
      {isRunning && (
        <rect width={NW} height={NH} rx={5} fill="none"
          stroke={node.color} strokeWidth={2.5} className="dag-pulse" />
      )}
      <rect width={4} height={NH} rx={2} fill={node.color} opacity={isPending ? 0.25 : 1} />
      <text x={12} y={16} fill={node.color} fontSize={8} fontFamily="monospace" fontWeight="bold"
        letterSpacing="0.1em" opacity={isPending ? 0.35 : 1}>
        {NODE_CFG[node.type].label}
      </text>
      <text x={12} y={34} fill="#e2e8f0" fontSize={11} fontWeight="bold"
        fontFamily="system-ui, sans-serif" opacity={isPending ? 0.35 : 1}>
        {node.title}
      </text>
      <text x={12} y={52} fill="#64748b" fontSize={9} fontFamily="system-ui, sans-serif"
        opacity={isPending ? 0.35 : 1}>
        {node.sub}
      </text>
      {/* Spinning dots for running state */}
      {isRunning && (
        <g transform={`translate(${NW - 22}, ${NH / 2 - 3})`}>
          {([0, 1, 2] as const).map((i) => (
            <circle key={i} cx={i * 6} cy={0} r={2} fill={node.color}
              className={`dag-dot-${i}`} />
          ))}
        </g>
      )}
      {/* Checkmark for done state */}
      {status === "done" && !selected && (
        <g transform={`translate(${NW - 16}, 5)`}>
          <circle cx={5} cy={5} r={5} fill={node.color} fillOpacity={0.15} />
          <path d="M2.5 5 L4.5 7 L7.5 3" stroke={node.color} strokeWidth={1.2}
            fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </g>
      )}
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

// ── Dim notes + bars (each note aligned with its bar on the same row) ─────────

// Six distinct teal shades, darkest→lightest, assigned by score rank.
const TEAL_PALETTE = ["#0d4f56", "#0b7285", "#0891b2", "#06b6d4", "#22d3ee", "#67e8f9"];

// Try to extract a leading "dimname: body" prefix from an issue string.
function parseDimNote(s: string): [string, string] {
  const m = s.match(/^([a-z_]+):\s*(.*)/is);
  return m ? [m[1].toLowerCase(), m[2].trim()] : ["", s];
}

function DimNotesBars({
  dims, issues, feedback,
}: { dims: WiggumDim; issues: string[]; feedback?: string }) {
  // Build dim → note body map from issues that start with a dim name
  const noteMap: Record<string, string> = {};
  const unmatched: string[] = [];
  for (const iss of issues) {
    const [dim] = parseDimNote(iss);
    if (dim && dims[dim as keyof WiggumDim] !== undefined) {
      noteMap[dim] = iss.charAt(0).toUpperCase() + iss.slice(1);
    } else {
      unmatched.push(iss);
    }
  }

  const entries = Object.entries(dims)
    .filter(([, v]) => typeof v === "number")
    .sort(([, a], [, b]) => (b as number) - (a as number));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {entries.map(([key, rawVal], i) => {
        const v     = rawVal as number;
        const color = TEAL_PALETTE[Math.min(i, TEAL_PALETTE.length - 1)];
        const pct   = Math.min(100, (v / 10) * 100);
        const note  = noteMap[key];
        return (
          <div key={key} style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {/* Note — left, flex 1, left-bordered in the dim's teal */}
            <div style={{
              flex: 1, minWidth: 0, fontSize: 11, color: "var(--dim)", lineHeight: 1.45,
              padding: "2px 0 2px 8px", borderLeft: `2px solid ${color}70`,
              wordBreak: "break-word",
            }}>
              {note ?? <span style={{ color: "rgba(255,255,255,0.18)", fontStyle: "italic" }}>—</span>}
            </div>

            {/* Bar section: [score] [bar] [label] — fixed width, right side */}
            <div style={{ width: 210, flexShrink: 0, display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{
                fontSize: 11, color, fontFamily: "var(--font-mono)", fontWeight: 700,
                width: 16, textAlign: "right", flexShrink: 0,
              }}>{v}</span>
              <div style={{ flex: 1, height: 9, background: "rgba(255,255,255,0.06)", borderRadius: 3, overflow: "hidden" }}>
                <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 3, transition: "width 0.3s" }} />
              </div>
              <span style={{
                fontSize: 11, color: "var(--text)", textTransform: "capitalize",
                width: 88, flexShrink: 0, textAlign: "left",
              }}>{key}</span>
            </div>
          </div>
        );
      })}

      {/* Unmatched issues (no leading dim prefix) */}
      {unmatched.map((iss, i) => (
        <div key={`u${i}`} style={{ fontSize: 11, color: "var(--dim)", lineHeight: 1.45, padding: "2px 0 2px 8px", borderLeft: "2px solid var(--warn)", wordBreak: "break-word" }}>
          {iss}
        </div>
      ))}

      {feedback && (
        <div style={{ fontSize: 11, color: "var(--dim)", lineHeight: 1.5, fontStyle: "italic", wordBreak: "break-word", marginTop: 4 }}>
          {feedback}
        </div>
      )}
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
        <button style={thumb(rating === 1,  "#34d399")} onClick={() => { setRating(1);  setSaved(false); }} title="Positive">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M7 10v12M15 5.88L14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"/>
          </svg>
        </button>
        <button style={thumb(rating === -1, "#f87171")} onClick={() => { setRating(-1); setSaved(false); }} title="Negative">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M17 14V2M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z"/>
          </svg>
        </button>
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
    const [previewOpen, setPreviewOpen] = useState(false);
    return (<>
      <InspRow label="tool" value={tc.name} />
      {/* Query */}
      <div style={{ marginTop: 8, marginBottom: 8, padding: "10px 12px", background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 6, fontSize: 12, lineHeight: 1.6, wordBreak: "break-word", color: "var(--text)" }}>
        {tc.query ?? "—"}
      </div>
      {/* Error banner */}
      {tc.error && (
        <div style={{ padding: "7px 10px", borderRadius: 5, background: "rgba(248,81,73,0.1)", border: "1px solid rgba(248,81,73,0.3)", color: "#f85149", fontSize: 11, marginBottom: 8, wordBreak: "break-word" }}>
          {tc.error}
        </div>
      )}
      <InspRow label="hits" value={tc.urls ? String(tc.urls.length) : "—"} />
      <InspRow label="chars" value={tc.result_chars != null ? tc.result_chars.toLocaleString() : "—"} />
      {/* URL list */}
      {tc.urls && tc.urls.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--dim)", marginBottom: 5 }}>Sources</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 5, maxHeight: 220, overflowY: "auto" }}>
            {(tc.urls as ToolCallUrl[]).map((u, i) => (
              <div key={i} style={{ padding: "6px 8px", background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 5 }}>
                <div style={{ fontSize: 11, color: "var(--text)", fontWeight: 600, marginBottom: 2, wordBreak: "break-word" }}>{u.title || "(no title)"}</div>
                <div style={{ fontSize: 10, color: "#4f8ef7", wordBreak: "break-all", marginBottom: u.body ? 3 : 0 }}>{u.href}</div>
                {u.body && <div style={{ fontSize: 10, color: "var(--dim)", lineHeight: 1.45, wordBreak: "break-word" }}>{u.body}</div>}
              </div>
            ))}
          </div>
        </div>
      )}
      {/* Result preview toggle */}
      {tc.result_preview && (
        <div style={{ marginTop: 10 }}>
          <button
            onClick={() => setPreviewOpen((o) => !o)}
            style={{ background: "none", border: "1px solid var(--border)", borderRadius: 4, color: "var(--dim)", cursor: "pointer", fontSize: 10, padding: "3px 10px", textTransform: "uppercase", letterSpacing: "0.05em" }}
          >
            {previewOpen ? "▲ hide preview" : "▼ preview results"}
          </button>
          {previewOpen && (
            <div style={{ marginTop: 6, maxHeight: 380, overflowY: "auto", background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 5, padding: "10px 12px" }}>
              <MdView content={tc.result_preview} />
            </div>
          )}
        </div>
      )}
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

  const hasWiggum = scores.length > 0 || (lastDim != null) || issues.length > 0 || !!feedback;
  const [cardHeight, setCardHeight] = useState(() => hasWiggum ? 320 : 120);
  useEffect(() => { setCardHeight(hasWiggum ? 320 : 120); }, [run.run_id]);

  const startDrag = (e: React.MouseEvent) => {
    e.preventDefault();
    const startY = e.clientY;
    const startH = cardHeight;
    const onMove = (ev: MouseEvent) =>
      setCardHeight(Math.max(120, Math.min(640, startH + ev.clientY - startY)));
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  return (
    <div style={{
      flexShrink: 0, background: "var(--surface)", borderBottom: "1px solid var(--border)",
      display: "flex", flexDirection: "column",
      height: cardHeight, overflow: "hidden", position: "relative",
    }}>
      <div style={{ padding: "14px 18px", display: "flex", flexDirection: "column", gap: 10, overflowY: "auto", flex: 1 }}>
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
        {run.leverage != null && <Chip label="leverage" value={`${run.leverage.toFixed(1)}×`} />}
        {scores.map((s, i) => (
          <span key={i} style={{ display: "inline-flex", gap: 4, fontSize: 11, padding: "2px 8px", borderRadius: 6, fontWeight: 700, fontFamily: "var(--font-mono)", background: `${scoreColor(s)}15`, border: `1px solid ${scoreColor(s)}40`, color: scoreColor(s) }}>
            r{i + 1} · {s.toFixed(1)}
          </span>
        ))}
      </div>

      {/* per-dim notes aligned with bars */}
      {(lastDim || issues.length > 0 || feedback) && (
        <DimNotesBars
          dims={lastDim ?? {} as WiggumDim}
          issues={issues}
          feedback={feedback}
        />
      )}
    </div>

    {/* drag handle */}
    <div
      onMouseDown={startDrag}
      title="Drag to resize"
      style={{
        height: 10, flexShrink: 0, cursor: "ns-resize",
        background: "var(--surface)",
        borderTop: "1px solid var(--border)",
        display: "flex", alignItems: "center", justifyContent: "center",
        transition: "background 0.15s",
      }}
      onMouseEnter={e => (e.currentTarget.style.background = "rgba(129,140,248,0.12)")}
      onMouseLeave={e => (e.currentTarget.style.background = "var(--surface)")}
    >
      <div style={{ width: 32, height: 2, borderRadius: 2, background: "var(--border)" }} />
    </div>
  </div>
  );
}

// ── Lit-review view ────────────────────────────────────────────────────────────

const LR_COLORS = {
  fetch:      "#38bdf8",
  curate:     "#a78bfa",
  cluster:    "#e879f9",
  synthesize: "#22d3ee",
};

function fmtMs(ms: number | undefined) {
  if (!ms) return "—";
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)}m`;
  if (ms >= 1_000)  return `${(ms / 1_000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

function buildLrColumns(run: RunRecord): DagNode[][] {
  const tbs        = run.tokens_by_stage ?? {};
  const curateSt   = tbs.curate     as StageTokens | undefined;
  const clusterSt  = tbs.cluster    as StageTokens | undefined;
  const synthSt    = tbs.synthesize as StageTokens | undefined;
  const papers     = (run.tool_calls ?? []).filter((tc) => tc.name === "arxiv_fetch");
  const totalFetched = curateSt?.calls ?? papers.length;
  const passRate   = totalFetched > 0 ? Math.round(papers.length / totalFetched * 100) : 0;
  const outColor   = run.final === "PASS" ? "#3fb950" : run.final === "FAIL" ? "#f85149" : "#8b949e";

  const clusterMap = new Map<number, { name: string; papers: typeof papers }>();
  for (const p of papers) {
    const idx  = p.cluster_idx ?? -1;
    const name = p.cluster_name || (idx >= 0 ? `Cluster ${idx + 1}` : "Unclustered");
    if (!clusterMap.has(idx)) clusterMap.set(idx, { name, papers: [] });
    clusterMap.get(idx)!.papers.push(p);
  }
  const clusterList = [...clusterMap.entries()].sort((a, b) => a[0] - b[0]);
  const hasClusterData = clusterList.some(([idx]) => idx >= 0);
  const clusterCount   = hasClusterData
    ? clusterList.length
    : (synthSt?.calls != null && synthSt.calls > 1 ? synthSt.calls - 1 : null);

  return [
    [{
      id: "lr_fetch", type: "lr_fetch" as NodeType, col: 0, row: 0, x: 0, y: 0,
      title: `${totalFetched} papers`,
      sub: trunc(run.task.replace(/^\s*\/lit-review\s*/i, ""), 28),
      color: LR_COLORS.fetch,
      data: { totalFetched, curateSt, task: run.task },
    }],
    [{
      id: "lr_curate", type: "lr_curate" as NodeType, col: 0, row: 0, x: 0, y: 0,
      title: `${papers.length} / ${totalFetched}`,
      sub: `${passRate}% pass  ${fmtMs(curateSt?.total_ms)}`,
      color: LR_COLORS.curate,
      data: { papers, curateSt, passRate },
    }],
    hasClusterData
      ? clusterList.map(([idx, cl]) => ({
          id: `lr_cluster_${idx}`, type: "lr_cluster" as NodeType, col: 0, row: 0, x: 0, y: 0,
          title: trunc(cl.name, 22),
          sub: `${cl.papers.length} paper${cl.papers.length !== 1 ? "s" : ""}`,
          color: LR_COLORS.cluster,
          data: { ...cl, clusterSt, idx },
        }))
      : [{
          id: "lr_cluster_0", type: "lr_cluster" as NodeType, col: 0, row: 0, x: 0, y: 0,
          title: clusterCount != null ? `${clusterCount} groups` : "Cluster",
          sub: fmtMs(clusterSt?.total_ms),
          color: LR_COLORS.cluster,
          data: { name: "Cluster", papers, clusterSt, idx: -1 },
        }],
    [{
      id: "lr_synth", type: "lr_synth" as NodeType, col: 0, row: 0, x: 0, y: 0,
      title: synthSt?.output != null ? `${synthSt.output} tok` : "Synthesize",
      sub: fmtMs(synthSt?.total_ms),
      color: LR_COLORS.synthesize,
      data: { synthSt },
    }],
    [{
      id: "lr_out", type: "lr_out" as NodeType, col: 0, row: 0, x: 0, y: 0,
      title: run.final ?? "running",
      sub: run.output_bytes ? `${(run.output_bytes / 1024).toFixed(1)} KB` : "—",
      color: outColor,
      data: { run },
    }],
  ];
}

function LrKV({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", gap: 10, marginBottom: 4, alignItems: "flex-start" }}>
      {label && (
        <span style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em",
          color: "var(--dim)", minWidth: 88, flexShrink: 0, paddingTop: 1 }}>{label}</span>
      )}
      <span style={{ fontSize: 10, color: "var(--text)", lineHeight: 1.5 }}>{value}</span>
    </div>
  );
}

function LrNodeDetail({ node, run }: { node: DagNode; run: RunRecord }) {
  const d = node.data;
  if (node.type === "lr_fetch") return (
    <>
      <LrKV label="Query"   value={run.task.replace(/^\s*\/lit-review\s*/i, "").slice(0, 120) || run.task} />
      <LrKV label="Fetched" value={`${d.totalFetched} papers`} />
    </>
  );
  if (node.type === "lr_curate") return (
    <>
      <LrKV label="Passed" value={`${d.papers.length} / ${d.curateSt?.calls ?? d.papers.length} (${d.passRate}%)`} />
      <LrKV label="Time"   value={fmtMs(d.curateSt?.total_ms)} />
    </>
  );
  if (node.type === "lr_cluster") {
    const ps = d.papers as ToolCall[];
    return (
      <>
        <LrKV label="Cluster" value={d.name} />
        <LrKV label="Papers"  value={`${ps.length}`} />
        {ps.slice(0, 6).map((p, i) => (
          <LrKV key={i} label={i === 0 ? "Titles" : ""} value={trunc(p.query ?? p.urls?.[0]?.title ?? "", 90)} />
        ))}
        {ps.length > 6 && <LrKV label="" value={`+${ps.length - 6} more`} />}
      </>
    );
  }
  if (node.type === "lr_synth") return (
    <>
      <LrKV label="Output tok" value={d.synthSt?.output != null ? `${d.synthSt.output}` : "—"} />
      <LrKV label="Time"       value={fmtMs(d.synthSt?.total_ms)} />
    </>
  );
  if (node.type === "lr_out") return (
    <>
      <LrKV label="Status" value={d.run.final ?? "—"} />
      <LrKV label="File"   value={d.run.output_path?.replace(/.*[/\\]/, "") ?? "—"} />
      <LrKV label="Size"   value={d.run.output_bytes ? `${(d.run.output_bytes / 1024).toFixed(1)} KB` : "—"} />
    </>
  );
  return null;
}

function PaperCard({ tc }: { tc: ToolCall }) {
  const href    = tc.urls?.[0]?.href ?? "";
  const title   = tc.query ?? tc.urls?.[0]?.title ?? "Untitled";
  const preview = tc.result_preview ?? "";
  const arxivId = href.replace(/.*\/abs\//, "").replace(/v\d+$/, "");
  return (
    <div style={{ padding: "10px 12px", borderRadius: 7, background: "var(--surface)", border: "1px solid var(--border)", display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text)", lineHeight: 1.4 }}>{title}</div>
      {href && (
        <a href={href} target="_blank" rel="noreferrer"
          style={{ fontSize: 9, color: LR_COLORS.fetch, fontFamily: "var(--font-mono)", textDecoration: "none", opacity: 0.85 }}>
          arXiv:{arxivId}
        </a>
      )}
      {preview && (
        <div style={{ fontSize: 10, color: "var(--dim)", lineHeight: 1.5 }}>
          {preview.length > 200 ? preview.slice(0, 200) + "…" : preview}
        </div>
      )}
    </div>
  );
}

function LitReviewDag({ run }: { run: RunRecord }) {
  const [sel, setSel] = useState<DagNode | null>(null);
  const cols  = buildLrColumns(run);
  const { nodes, width, height } = layoutColumns(cols);
  const edges = buildEdges(cols, nodes);

  useEffect(() => { setSel(null); }, [run.run_id]);

  const allPapers  = (run.tool_calls ?? []).filter((tc) => tc.name === "arxiv_fetch");
  const showPapers = sel?.type === "lr_cluster" ? (sel.data.papers as ToolCall[]) : allPapers;
  const gridLabel  = sel?.type === "lr_cluster"
    ? `${sel.data.name} — ${showPapers.length} paper${showPapers.length !== 1 ? "s" : ""}`
    : `Papers — ${allPapers.length} annotated`;

  const durMin = run.run_duration_s ? Math.floor(run.run_duration_s / 60) : 0;
  const durSec = run.run_duration_s ? Math.floor(run.run_duration_s % 60) : 0;

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--bg)" }}>
      {/* DAG canvas */}
      <div
        style={{ flexShrink: 0, overflow: "auto", maxHeight: 320, background: "var(--surface)", borderBottom: "1px solid var(--border)", position: "relative" }}
        onClick={(e) => { if (e.target === e.currentTarget) setSel(null); }}
      >
        <svg width={width} height={height} style={{ display: "block" }}>
          {edges.map((edge, i) => <SvgEdge key={i} edge={edge} />)}
          {nodes.map((node) => (
            <SvgNode
              key={node.id}
              node={node}
              selected={sel?.id === node.id}
              onClick={() => setSel(sel?.id === node.id ? null : node)}
            />
          ))}
        </svg>
        {run.run_duration_s != null && (
          <span style={{ position: "absolute", bottom: 6, right: 10, fontSize: 10, color: "var(--dim)", fontFamily: "var(--font-mono)", pointerEvents: "none" }}>
            {durMin}m {durSec}s
          </span>
        )}
      </div>

      {/* Selected node detail */}
      {sel && (
        <div style={{ flexShrink: 0, padding: "10px 20px 8px", borderBottom: "1px solid var(--border)", background: "var(--surface)" }}>
          <div style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em", color: sel.color, marginBottom: 6 }}>
            {sel.title}
          </div>
          <LrNodeDetail node={sel} run={run} />
        </div>
      )}

      {/* Paper grid */}
      <div style={{ flex: 1, overflowY: "auto", padding: "14px 20px" }}>
        <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.09em", color: "var(--dim)", marginBottom: 10 }}>
          {gridLabel}
        </div>
        {showPapers.length === 0 ? (
          <div style={{ fontSize: 12, color: "var(--dim)", fontStyle: "italic" }}>No paper metadata recorded. Rerun with the updated harness to populate this view.</div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 8 }}>
            {showPapers.map((tc, i) => <PaperCard key={i} tc={tc} />)}
          </div>
        )}
      </div>
    </div>
  );
}

// ── DAG canvas ─────────────────────────────────────────────────────────────────

function DagCanvas({ run, selectedNode, onSelectNode }: { run: RunRecord; selectedNode: DagNode | null; onSelectNode: (n: DagNode | null) => void }) {
  const [scale, setScale] = useState(1);
  const cols  = buildColumns(run);
  const { nodes, width, height } = layoutColumns(cols);
  const edges = buildEdges(cols, nodes);

  const zoomBtn: CSSProperties = {
    width: 28, height: 28, borderRadius: 6,
    background: "var(--surface)", border: "1px solid var(--border)",
    color: "var(--dim)", cursor: "pointer",
    display: "flex", alignItems: "center", justifyContent: "center",
    boxShadow: "0 2px 6px rgba(0,0,0,0.3)",
    transition: "background 0.12s, color 0.12s",
  };

  return (
    <div style={{ flex: 1, overflow: "auto", background: "var(--bg)", padding: 8, position: "relative" }}
      onClick={(e) => { if (e.target === e.currentTarget) onSelectNode(null); }}>
      {/* Zoom controls */}
      <div style={{
        position: "absolute", top: 10, right: 10,
        display: "flex", flexDirection: "column", gap: 4, zIndex: 10,
      }}>
        <button
          style={zoomBtn}
          title="Zoom in"
          onClick={(e) => { e.stopPropagation(); setScale((s) => Math.min(2, +(s + 0.25).toFixed(2))); }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "rgba(129,140,248,0.15)"; (e.currentTarget as HTMLButtonElement).style.color = "var(--accent)"; }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "var(--surface)"; (e.currentTarget as HTMLButtonElement).style.color = "var(--dim)"; }}
        ><Plus size={14} /></button>
        <button
          style={zoomBtn}
          title="Zoom out"
          onClick={(e) => { e.stopPropagation(); setScale((s) => Math.max(0.25, +(s - 0.25).toFixed(2))); }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "rgba(129,140,248,0.15)"; (e.currentTarget as HTMLButtonElement).style.color = "var(--accent)"; }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "var(--surface)"; (e.currentTarget as HTMLButtonElement).style.color = "var(--dim)"; }}
        ><Minus size={14} /></button>
      </div>
      <div style={{ transform: `scale(${scale})`, transformOrigin: "top left", display: "inline-block" }}>
        <svg width={width} height={height} style={{ display: "block" }}>
          {edges.map((edge, i) => <SvgEdge key={i} edge={edge} />)}
          {nodes.map((node) => (
            <SvgNode key={node.id} node={node} selected={selectedNode?.id === node.id}
              onClick={() => onSelectNode(selectedNode?.id === node.id ? null : node)} />
          ))}
        </svg>
      </div>
    </div>
  );
}

// ── Live DAG ───────────────────────────────────────────────────────────────────

const LIVE_STAGE_ORDER = ["memory", "plan", "search", "synth", "eval"] as const;

const LIVE_STAGE_LABELS: Record<string, { running: string; done: string; pending: string }> = {
  memory:  { running: "retrieving…",  done: "memory",    pending: "memory"    },
  plan:    { running: "planning…",    done: "plan",      pending: "plan"      },
  search:  { running: "searching…",   done: "search",    pending: "search"    },
  synth:   { running: "synthesizing…",done: "synthesis", pending: "synthesis" },
  eval:    { running: "evaluating…",  done: "eval",      pending: "eval"      },
};

const LIVE_STAGE_TO_TYPE: Record<string, NodeType> = {
  memory: "memory",
  plan:   "plan",
  search: "search",
  synth:  "synthesis",
  eval:   "eval",
};

function liveNodeStatus(stage: string, liveRun: LiveRun): NodeStatus {
  if (stage === liveRun.current_stage) return "running";
  if (liveRun.stages_seen.includes(stage)) return "done";
  return "pending";
}

function buildLiveColumns(liveRun: LiveRun): { cols: DagNode[][]; statusMap: Record<string, NodeStatus> } {
  const statusMap: Record<string, NodeStatus> = {};
  const cols: DagNode[][] = [];

  // TASK — always done
  statusMap["task"] = "done";
  cols.push([{ id: "task", type: "task", col: 0, row: 0, x: 0, y: 0,
    title: trunc(liveRun.task, 22), sub: "in progress",
    color: NODE_CFG.task.color, data: {} }]);

  // Middle stages
  for (const stage of LIVE_STAGE_ORDER) {
    const st  = liveNodeStatus(stage, liveRun);
    const lbl = LIVE_STAGE_LABELS[stage];
    const typ = LIVE_STAGE_TO_TYPE[stage];
    statusMap[stage] = st;
    cols.push([{ id: stage, type: typ, col: 0, row: 0, x: 0, y: 0,
      title: lbl[st], sub: st === "running" ? "active" : st === "done" ? "done" : "queued",
      color: NODE_CFG[typ].color, data: {} }]);
  }

  // OUTPUT — always pending while run is live
  statusMap["output"] = "pending";
  cols.push([{ id: "output", type: "output", col: 0, row: 0, x: 0, y: 0,
    title: "output", sub: "pending",
    color: "#8b949e", data: {} }]);

  return { cols, statusMap };
}

function LiveDagCanvas({ liveRun }: { liveRun: LiveRun }) {
  const { cols, statusMap } = buildLiveColumns(liveRun);
  const { nodes, width, height } = layoutColumns(cols);
  const edges = buildEdges(cols, nodes);
  return (
    <div style={{ flex: 1, overflow: "auto", background: "var(--bg)", padding: 8 }}>
      <svg width={width} height={height} style={{ display: "block" }}>
        {edges.map((edge, i) => <SvgEdge key={i} edge={edge} />)}
        {nodes.map((node) => (
          <SvgNode key={node.id} node={node} selected={false} onClick={() => undefined}
            status={statusMap[node.id] ?? "pending"} />
        ))}
      </svg>
    </div>
  );
}

// ── Live thinking ──────────────────────────────────────────────────────────────

type ThinkingEvent = { stage: string; text: string; chars: number };

function useLiveThinking(itemId: string | undefined): ThinkingEvent[] {
  const [events, setEvents] = useState<ThinkingEvent[]>([]);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!itemId) { setEvents([]); return; }
    setEvents([]);
    const es = new EventSource(`/api/tasks/${itemId}/stream`);
    esRef.current = es;
    es.onmessage = (e: MessageEvent<string>) => {
      const raw = e.data;
      if (!raw.startsWith("[EVENT]")) return;
      try {
        const ev = JSON.parse(raw.slice(7)) as { type: string; data: Record<string, unknown> };
        if (ev.type === "thinking") {
          setEvents((prev) => [...prev, {
            stage: (ev.data.stage as string) ?? "",
            text:  (ev.data.text  as string) ?? "",
            chars: (ev.data.chars as number) ?? 0,
          }]);
        }
      } catch { /* ignore */ }
    };
    return () => { es.close(); esRef.current = null; };
  }, [itemId]);

  return events;
}

const THINKING_STAGE_LABEL: Record<string, string> = {
  plan:      "Planner reasoning",
  synth:     "Synthesis reasoning",
  tool:      "Tool-loop reasoning",
  eval:      "Evaluator reasoning",
  cluster:   "Cluster reasoning",
  synthesize:"Synthesize reasoning",
  annotate:  "Annotation reasoning",
};

function LiveThinkingCard({ ev }: { ev: ThinkingEvent }) {
  const [open, setOpen] = useState(false);
  const label = THINKING_STAGE_LABEL[ev.stage] ?? `${ev.stage} reasoning`;
  return (
    <div style={{ marginBottom: 4, borderRadius: 7, border: "1px solid rgba(167,139,250,0.25)", background: "rgba(167,139,250,0.04)", overflow: "hidden" }}>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{ width: "100%", display: "flex", alignItems: "center", gap: 7, padding: "7px 11px", background: "none", border: "none", cursor: "pointer", textAlign: "left" }}
      >
        {open ? <ChevronDown size={12} color="#a78bfa" /> : <ChevronRight size={12} color="#a78bfa" />}
        <span style={{ fontSize: 11, color: "#a78bfa", fontWeight: 600 }}>{label}</span>
        <span style={{ fontSize: 10, color: "var(--dim)", fontFamily: "var(--font-mono)", marginLeft: "auto" }}>{ev.chars.toLocaleString()} chars</span>
      </button>
      {open && (
        <pre style={{ margin: 0, padding: "0 12px 10px 30px", fontSize: 10, lineHeight: 1.65, color: "rgba(167,139,250,0.75)", whiteSpace: "pre-wrap", wordBreak: "break-word", fontFamily: "var(--font-mono)", maxHeight: 380, overflowY: "auto" }}>
          {ev.text}
        </pre>
      )}
    </div>
  );
}

function LiveThinkingPanel({ events }: { events: ThinkingEvent[] }) {
  const bottomRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [events.length]);
  return (
    <div style={{ width: 320, flexShrink: 0, borderLeft: "1px solid rgba(167,139,250,0.2)", background: "rgba(167,139,250,0.02)", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <div style={{ padding: "8px 12px 7px", borderBottom: "1px solid rgba(167,139,250,0.15)", display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
        <Brain size={12} color="#a78bfa" />
        <span style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.07em", color: "#a78bfa" }}>Reasoning traces</span>
        <span style={{ fontSize: 9, color: "var(--dim)", fontFamily: "var(--font-mono)", marginLeft: "auto" }}>{events.length}</span>
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: "8px 10px" }}>
        {events.length === 0 && (
          <div style={{ fontSize: 11, color: "var(--dim)", textAlign: "center", paddingTop: 24, fontStyle: "italic" }}>
            Waiting for reasoning traces…
          </div>
        )}
        {events.map((ev, i) => <LiveThinkingCard key={i} ev={ev} />)}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

// ── Elapsed ticker ─────────────────────────────────────────────────────────────

function useElapsed(startedAt: string) {
  const [elapsed, setElapsed] = useState(0);
  const ref = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    const t0 = new Date(startedAt).getTime();
    const tick = () => setElapsed(Math.floor((Date.now() - t0) / 1000));
    tick();
    ref.current = setInterval(tick, 1000);
    return () => { if (ref.current) clearInterval(ref.current); };
  }, [startedAt]);
  return elapsed;
}

// ── Left panel: filter + list ──────────────────────────────────────────────────

type StatusFilter = "all" | "pass" | "fail" | "error" | "running";

function LiveRunCard({ liveRun, isSelected, onSelect }: { liveRun: LiveRun; isSelected: boolean; onSelect: () => void }) {
  const elapsed = useElapsed(liveRun.started_at);
  const stageLbl = LIVE_STAGE_LABELS[liveRun.current_stage]?.running ?? liveRun.current_stage;
  return (
    <div onClick={onSelect} style={{
      padding: "8px 12px", cursor: "pointer",
      borderLeft: `3px solid ${isSelected ? "#22d3ee" : "#22d3ee55"}`,
      borderBottom: "1px solid rgba(34,211,238,0.15)",
      background: isSelected ? "rgba(34,211,238,0.07)" : "rgba(34,211,238,0.03)",
      transition: "background 0.1s",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 3 }}>
        <span className="live-dot" style={{ width: 6, height: 6, borderRadius: "50%", background: "#22d3ee", display: "inline-block", flexShrink: 0 }} />
        <span style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: "#22d3ee", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em" }}>live</span>
        <span style={{ fontSize: 9, color: "var(--dim)", fontFamily: "var(--font-mono)", marginLeft: "auto" }}>{elapsed}s</span>
      </div>
      <div style={{ fontSize: 11, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginBottom: 3 }}>
        {liveRun.task.slice(0, 46)}{liveRun.task.length > 46 ? "…" : ""}
      </div>
      <div style={{ fontSize: 9, color: "#22d3ee99", fontFamily: "var(--font-mono)" }}>{stageLbl}</div>
    </div>
  );
}

function SyncButton() {
  const qc = useQueryClient();
  const [spinning, setSpinning] = useState(false);

  const handleSync = () => {
    setSpinning(true);
    void qc.invalidateQueries({ queryKey: ["paged_runs"] });
    setTimeout(() => setSpinning(false), 600);
  };

  return (
    <button
      onClick={handleSync}
      title="Refresh runs"
      style={{
        background: "none", border: "none", cursor: "pointer",
        color: "var(--dim)", display: "flex", alignItems: "center",
        padding: "2px 4px", borderRadius: 4, transition: "color 0.15s",
      }}
      onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.color = "var(--accent)"; }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.color = "var(--dim)"; }}
    >
      <RefreshCw size={12} style={{ transition: "transform 0.6s", transform: spinning ? "rotate(360deg)" : "none" }} />
    </button>
  );
}

function LeftPanel({ runs, selected, onSelect, liveRun, liveSelected, onSelectLive,
  total, page, pages, onPage, search, onSearch, status, onStatus }: {
  runs: RunRecord[]; selected: RunRecord | null; onSelect: (r: RunRecord) => void;
  liveRun: LiveRun | null; liveSelected: boolean; onSelectLive: () => void;
  total: number; page: number; pages: number; onPage: (p: number) => void;
  search: string; onSearch: (s: string) => void;
  status: StatusFilter; onStatus: (s: StatusFilter) => void;
}) {
  const filtered = runs;

  const statuses: StatusFilter[] = ["all", "pass", "fail", "error", "running"];

  return (
    <div style={{ width: 260, flexShrink: 0, background: "var(--surface)", borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* filter bar */}
      <div style={{ padding: "10px 10px 8px", borderBottom: "1px solid var(--border)", display: "flex", flexDirection: "column", gap: 7, flexShrink: 0 }}>
        <input
          type="search" placeholder="Filter…" value={search}
          onChange={(e) => onSearch(e.target.value)}
          style={{ width: "100%", background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)", fontSize: 11, padding: "5px 9px", outline: "none" }}
        />
        <div style={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
          {statuses.map((s) => (
            <button key={s} onClick={() => onStatus(s)} style={{
              padding: "2px 7px", borderRadius: 5, fontSize: 10, fontWeight: 600, cursor: "pointer",
              textTransform: "uppercase", letterSpacing: "0.04em",
              border: status === s ? "1px solid var(--accent)" : "1px solid var(--border)",
              background: status === s ? "rgba(129,140,248,0.15)" : "none",
              color: status === s ? "var(--accent)" : "var(--dim)",
            }}>{s}</button>
          ))}
        </div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontSize: 10, color: "var(--dim)" }}>
            {runs.length} on page
            {total > runs.length && <span style={{ color: "var(--accent)", marginLeft: 4 }}>{total} total</span>}
          </span>
          <SyncButton />
        </div>
      </div>

      {/* run list */}
      <div style={{ overflowY: "auto", flex: 1 }}>
        {liveRun && <LiveRunCard liveRun={liveRun} isSelected={liveSelected} onSelect={onSelectLive} />}
        {filtered.length === 0 && !liveRun && <div className="empty-state">No runs match.</div>}
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
                {r.leverage != null && (
                  <span style={{ fontSize: 10, color: "var(--dim)", fontFamily: "var(--font-mono)" }}>{r.leverage.toFixed(0)}×</span>
                )}
                {r.run_duration_s != null && (
                  <span style={{ fontSize: 10, color: "var(--dim)", marginLeft: "auto", fontFamily: "var(--font-mono)" }}>{r.run_duration_s.toFixed(0)}s</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* pagination controls */}
      {pages > 1 && (
        <div style={{
          flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "6px 10px", borderTop: "1px solid var(--border)", background: "var(--surface)",
        }}>
          <button
            onClick={() => onPage(page - 1)} disabled={page <= 1}
            style={{
              background: "none", border: "1px solid var(--border)", borderRadius: 5,
              color: page <= 1 ? "var(--border)" : "var(--dim)", cursor: page <= 1 ? "default" : "pointer",
              fontSize: 11, padding: "2px 8px",
            }}
          >‹</button>
          <span style={{ fontSize: 10, color: "var(--dim)", fontFamily: "var(--font-mono)" }}>
            {page} / {pages}
          </span>
          <button
            onClick={() => onPage(page + 1)} disabled={page >= pages}
            style={{
              background: "none", border: "1px solid var(--border)", borderRadius: 5,
              color: page >= pages ? "var(--border)" : "var(--dim)", cursor: page >= pages ? "default" : "pointer",
              fontSize: 11, padding: "2px 8px",
            }}
          >›</button>
        </div>
      )}
    </div>
  );
}

// ── LLM message viewer ────────────────────────────────────────────────────────

const ROLE_COLORS: Record<string, string> = {
  user:      "#4f8ef7",
  assistant: "#22d3ee",
  system:    "#a78bfa",
  tool:      "#fb923c",
};

function MsgCard({ msg, defaultUserOpen = true }: { msg: RunMessage; defaultUserOpen?: boolean }) {
  const [userOpen, setUserOpen] = useState(defaultUserOpen);
  const color = ROLE_COLORS[msg.role] ?? "#8b949e";
  const isUser = msg.role === "user";

  return (
    <div style={{ border: `1px solid ${color}25`, borderLeft: `3px solid ${color}`, borderRadius: 6, overflow: "hidden" }}>
      <div
        style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 10px", background: `${color}10`, cursor: isUser ? "pointer" : "default" }}
        onClick={isUser ? () => setUserOpen((o) => !o) : undefined}
      >
        <span style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color, fontFamily: "monospace" }}>{msg.role}</span>
        {msg.chars != null && <span style={{ fontSize: 9, color: "var(--dim)", fontFamily: "var(--font-mono)", marginLeft: "auto" }}>{msg.chars.toLocaleString()} chars</span>}
        {msg.truncated && <span style={{ fontSize: 9, color: "var(--warn)" }}>truncated</span>}
        {isUser && <span style={{ fontSize: 9, color: "var(--dim)" }}>{userOpen ? "▲" : "▼"}</span>}
      </div>
      {(!isUser || userOpen) && msg.content && (
        msg.role === "assistant"
          ? <div style={{ padding: "8px 10px", fontSize: 11, overflowY: "auto", maxHeight: 320, background: "rgba(0,0,0,0.15)" }}><MdView content={msg.content} /></div>
          : <pre style={{ margin: 0, padding: "8px 10px", fontSize: 11, lineHeight: 1.6, color: "var(--text)", whiteSpace: "pre-wrap", wordBreak: "break-word", overflowY: "auto", maxHeight: 320, background: "rgba(0,0,0,0.15)", fontFamily: "var(--font-mono)" }}>{msg.content}</pre>
      )}
      {typeof msg.cot === "string" && msg.cot.length > 0 && (
        <details style={{ borderTop: `1px solid ${color}20` }}>
          <summary style={{ padding: "4px 10px", fontSize: 9, color: "var(--dim)", cursor: "pointer", textTransform: "uppercase", letterSpacing: "0.06em" }}>
            chain of thought ({msg.cot.length.toLocaleString()} chars)
          </summary>
          <pre style={{ margin: 0, padding: "8px 10px", fontSize: 10, lineHeight: 1.6, color: "var(--dim)", whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: 240, overflowY: "auto", background: "rgba(0,0,0,0.1)", fontFamily: "var(--font-mono)" }}>
            {msg.cot}
          </pre>
        </details>
      )}
    </div>
  );
}

// Group sequential (user, assistant) pairs into rounds.
// A "round" boundary occurs each time role resets to "user" after an "assistant".
function groupIntoRounds(messages: RunMessage[]): RunMessage[][] {
  const rounds: RunMessage[][] = [];
  let current: RunMessage[] = [];
  for (const msg of messages) {
    if (msg.role === "user" && current.some((m) => m.role === "assistant")) {
      rounds.push(current);
      current = [];
    }
    current.push(msg);
  }
  if (current.length > 0) rounds.push(current);
  return rounds;
}

function MessageViewer({ runId, stage, label }: { runId: string; stage: string; label?: string }) {
  const [open, setOpen] = useState(false);

  const { data: messages, isLoading, error } = useQuery({
    queryKey:  ["messages", runId, stage],
    queryFn:   () => fetch(`/api/runs/${runId}/messages?stage=${encodeURIComponent(stage)}`)
                       .then((r) => r.json() as Promise<RunMessage[]>),
    enabled:   open,
    staleTime: 60_000,
  });

  const btnLabel = label ?? "view input / output";
  const rounds   = messages ? groupIntoRounds(messages) : [];
  const multiRound = rounds.length > 1;

  return (
    <div style={{ marginTop: 10 }}>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{ background: "none", border: "1px solid var(--border)", borderRadius: 4, color: "var(--dim)", cursor: "pointer", fontSize: 10, padding: "3px 10px", textTransform: "uppercase", letterSpacing: "0.05em" }}
      >
        {open ? "▲ hide" : `▼ ${btnLabel}`}
        {messages && multiRound && !open && <span style={{ marginLeft: 6, color: "var(--accent)", fontFamily: "var(--font-mono)" }}>{rounds.length} rounds</span>}
      </button>

      {open && (
        <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: multiRound ? 12 : 8 }}>
          {isLoading && <div style={{ fontSize: 11, color: "var(--dim)" }}>Loading…</div>}
          {error     && <div style={{ fontSize: 11, color: "var(--fail)" }}>Failed to load messages.</div>}
          {messages && messages.length === 0 && (
            <div style={{ fontSize: 11, color: "var(--dim)", fontStyle: "italic" }}>
              No messages recorded for this stage yet — they'll appear after the next run.
            </div>
          )}
          {rounds.map((round, ri) => (
            <div key={ri}>
              {multiRound && (
                <div style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.09em", color: "var(--dim)", marginBottom: 5, paddingLeft: 2 }}>
                  Round {ri + 1} / {rounds.length}
                </div>
              )}
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {round.map((msg) => (
                  // User prompts collapsed by default when there are multiple rounds — they're
                  // repetitive boilerplate (same rubric template, different content each time).
                  <MsgCard key={msg.seq} msg={msg} defaultUserOpen={!multiRound || msg.role !== "user"} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Context window treemap ─────────────────────────────────────────────────────

type ViewMode = "dag" | "context" | "subtasks";

function inferContextLimit(model: string | undefined): number {
  if (!model) return 32768;
  const m = model.toLowerCase();
  if (m.includes("128k") || m.includes("72b") || m.includes("70b")) return 131072;
  if (m.includes("32k")) return 32768;
  return 32768;
}

const STAGE_CFG: Record<string, { color: string; label: string; context?: boolean }> = {
  search_query:        { color: "#fb923c", label: "Search" },
  synth:               { color: "#22d3ee", label: "Synthesis" },
  synth_count:         { color: "#0e8899", label: "Synth count" },
  tool_loop:           { color: "#4f8ef7", label: "Tool loop" },
  wiggum_eval:         { color: "#e3b341", label: "Eval" },
  wiggum_revise:       { color: "#9c7a08", label: "Revise" },
  planner:             { color: "#38bdf8", label: "Planner" },
  memory:              { color: "#a78bfa", label: "Memory" },
  compress_knowledge:  { color: "#3fb950", label: "Compress" },
  other:               { color: "#6b7280", label: "Other" },
  // lit-review pipeline stages
  fetch:               { color: "#38bdf8", label: "Fetch"       },
  enrich:              { color: "#818cf8", label: "Enrich"       },
  curate:              { color: "#a78bfa", label: "Curate"       },
  annotate:            { color: "#c084fc", label: "Annotate"     },
  cluster:             { color: "#e879f9", label: "Cluster"      },
  synthesize:          { color: "#22d3ee", label: "Synthesize"   },
  render:              { color: "#3fb950", label: "Render"       },
  // context injection stages (no LLM call — estimated chars/4 tokens)
  system_prompt:       { color: "#f472b6", label: "Sys prompt",  context: true },
  research_context:    { color: "#34d399", label: "Research ctx", context: true },
  memory_context:      { color: "#c084fc", label: "Memory ctx",  context: true },
  skill_context:       { color: "#fbbf24", label: "Skill ctx",   context: true },
  vision_context:      { color: "#60a5fa", label: "Vision ctx",  context: true },
  file_context:        { color: "#a3e635", label: "File ctx",    context: true },
};

function ContextTreemap({ run }: { run: RunRecord }) {
  const [selected, setSelected] = useState<string | null>(null);

  const tbs = run.tokens_by_stage;
  if (!tbs) {
    return <div style={{ padding: 24, color: "var(--dim)", fontSize: 12 }}>No token breakdown recorded for this run.</div>;
  }

  const entries = Object.entries(tbs)
    .filter(([, st]) => (st.input ?? 0) > 0)
    .sort(([, a], [, b]) => (b.input ?? 0) - (a.input ?? 0));

  if (entries.length === 0) {
    return <div style={{ padding: 24, color: "var(--dim)", fontSize: 12 }}>No input token data recorded for this run.</div>;
  }

  const limit      = inferContextLimit(run.producer_model);
  const totalInput = run.input_tokens ?? entries.reduce((s, [, st]) => s + (st.input ?? 0), 0);
  const fillPct    = Math.min(100, (totalInput / limit) * 100);
  const fillColor  = fillPct > 90 ? "var(--fail)" : fillPct > 70 ? "var(--warn)" : "var(--accent)";

  const selSt  = selected ? tbs[selected]  : null;
  const selCfg = selected ? (STAGE_CFG[selected] ?? { color: "#8b949e", label: selected }) : null;

  return (
    <div style={{ padding: "16px 18px", overflowY: "auto", flex: 1 }}>
      {/* fill gauge */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--dim)", marginBottom: 5, textTransform: "uppercase", letterSpacing: "0.06em" }}>
          <span>Context window fill</span>
          <span style={{ fontFamily: "var(--font-mono)", color: fillColor }}>
            {totalInput.toLocaleString()} / {limit.toLocaleString()} tok · {fillPct.toFixed(1)}%
          </span>
        </div>
        <div style={{ height: 7, background: "rgba(255,255,255,0.06)", borderRadius: 4, overflow: "hidden" }}>
          <div style={{ width: `${fillPct}%`, height: "100%", borderRadius: 4, background: fillColor, transition: "width 0.4s" }} />
        </div>
        <div style={{ fontSize: 9, color: "rgba(255,255,255,0.2)", marginTop: 3, fontFamily: "var(--font-mono)" }}>
          model: {run.producer_model ?? "unknown"} · inferred limit: {limit.toLocaleString()} tok
        </div>
      </div>

      {/* treemap box */}
      <div
        style={{ height: 148, background: "rgba(0,0,0,0.28)", borderRadius: 7, border: "1px solid var(--border)", overflow: "hidden", display: "flex", cursor: "default" }}
        onClick={() => setSelected(null)}
      >
        {entries.map(([stage, st]) => {
          const pct        = ((st.input ?? 0) / limit) * 100;
          const cfg        = STAGE_CFG[stage] ?? { color: "#8b949e", label: stage };
          const isSelected = selected === stage;
          const isCtx      = st.context === true;
          return (
            <div
              key={stage}
              onClick={(e) => { e.stopPropagation(); setSelected(isSelected ? null : stage); }}
              style={{
                width: `${pct}%`, height: "100%", flexShrink: 0,
                background: isCtx ? `${cfg.color}40` : cfg.color,
                opacity: selected && !isSelected ? 0.35 : 0.82,
                outline: isSelected ? "2px solid rgba(255,255,255,0.8)" : "none",
                outlineOffset: -2,
                display: "flex", flexDirection: "column", justifyContent: "flex-end",
                padding: "5px 6px", overflow: "hidden", cursor: "pointer",
                borderRight: isCtx ? `1px dashed ${cfg.color}80` : "1px solid rgba(0,0,0,0.22)",
                transition: "opacity 0.15s",
                boxSizing: "border-box",
              }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.opacity = "1"; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.opacity = selected && !isSelected ? "0.35" : "0.82"; }}
            >
              {pct > 4 && (
                <div style={{ fontSize: 9, color: isCtx ? cfg.color : "rgba(255,255,255,0.95)", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {cfg.label}
                </div>
              )}
              {pct > 7 && (
                <div style={{ fontSize: 8, color: isCtx ? `${cfg.color}bb` : "rgba(255,255,255,0.6)", fontFamily: "var(--font-mono)", marginTop: 1 }}>
                  {(st.input ?? 0).toLocaleString()}
                </div>
              )}
            </div>
          );
        })}
        {fillPct < 92 && (
          <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", minWidth: 0 }}>
            <span style={{ fontSize: 10, color: "rgba(255,255,255,0.1)", textTransform: "uppercase", letterSpacing: "0.12em" }}>unused</span>
          </div>
        )}
      </div>

      {/* selected stage detail */}
      {selected && selSt && selCfg && (() => {
        const isCtxStage = selSt.context === true;
        const detailRows: [string, string | null][] = isCtxStage ? [
          ["Est. tokens",  (selSt.input ?? 0).toLocaleString()],
          ["% of window",  `${((selSt.input ?? 0) / limit * 100).toFixed(2)}%`],
        ] : [
          ["Input tokens",   (selSt.input ?? 0).toLocaleString()],
          ["Output tokens",  (selSt.output ?? 0).toLocaleString()],
          ["LLM calls",      String(selSt.calls ?? 1)],
          ["% of window",    `${((selSt.input ?? 0) / limit * 100).toFixed(2)}%`],
          ["Total time",     selSt.total_ms   != null ? `${(selSt.total_ms   / 1000).toFixed(2)}s` : null],
          ["Prompt time",    selSt.prompt_ms  != null ? `${(selSt.prompt_ms  / 1000).toFixed(2)}s` : null],
          ["Eval time",      selSt.eval_ms    != null ? `${(selSt.eval_ms    / 1000).toFixed(2)}s` : null],
          ["Thinking chars", selSt.thinking_chars ? selSt.thinking_chars.toLocaleString() : null],
        ];
        return (
          <div style={{ marginTop: 12, padding: "11px 14px", background: "var(--surface)", border: `1px solid ${selCfg.color}35`, borderLeft: `3px solid ${selCfg.color}`, borderRadius: 7 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 9 }}>
              <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: selCfg.color }}>
                {selCfg.label}
              </div>
              {isCtxStage && (
                <span style={{ fontSize: 9, color: selCfg.color, border: `1px dashed ${selCfg.color}60`, borderRadius: 3, padding: "1px 5px", letterSpacing: "0.06em" }}>
                  context injection · estimated tokens
                </span>
              )}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "7px 20px" }}>
              {detailRows.filter(([, v]) => v !== null).map(([label, value]) => (
                <div key={label}>
                  <div style={{ fontSize: 9, color: "var(--dim)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 2 }}>{label}</div>
                  <div style={{ fontSize: 12, color: "var(--text)", fontFamily: "var(--font-mono)" }}>{value}</div>
                </div>
              ))}
            </div>
            <MessageViewer runId={run.run_id} stage={selected} label={isCtxStage ? "view content" : undefined} />
          </div>
        );
      })()}

      {/* legend */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "5px 14px", marginTop: 13 }}>
        {entries.map(([stage, st]) => {
          const cfg = STAGE_CFG[stage] ?? { color: "#8b949e", label: stage };
          const pct = ((st.input ?? 0) / limit) * 100;
          return (
            <div key={stage} onClick={() => setSelected(selected === stage ? null : stage)}
              style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10, cursor: "pointer", opacity: selected && selected !== stage ? 0.45 : 1, transition: "opacity 0.15s" }}>
              <div style={{ width: 8, height: 8, borderRadius: 2, background: st.context ? `${cfg.color}40` : cfg.color, border: st.context ? `1px dashed ${cfg.color}` : "none", flexShrink: 0 }} />
              <span style={{ color: "var(--dim)" }}>{cfg.label}{st.context ? " ~" : ""}</span>
              <span style={{ color: "var(--text)", fontFamily: "var(--font-mono)" }}>{pct.toFixed(1)}%</span>
            </div>
          );
        })}
        <div style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10 }}>
          <div style={{ width: 8, height: 8, borderRadius: 2, background: "rgba(255,255,255,0.06)", border: "1px solid var(--border)", flexShrink: 0 }} />
          <span style={{ color: "var(--dim)" }}>unused</span>
          <span style={{ color: "var(--text)", fontFamily: "var(--font-mono)" }}>{Math.max(0, 100 - fillPct).toFixed(1)}%</span>
        </div>
      </div>
    </div>
  );
}

// ── Lit-review compute breakdown ──────────────────────────────────────────────

const LR_STAGE_ORDER = ["fetch", "enrich", "curate", "annotate", "cluster", "synthesize", "render"];

const CURATE_JUDGES = 5; // fixed number of personas in curator.py

function CurationFunnel({ attempted, passed }: { attempted: number; passed: number }) {
  const filtered   = attempted - passed;
  const passPct    = attempted > 0 ? (passed   / attempted) * 100 : 0;
  const filterPct  = attempted > 0 ? (filtered / attempted) * 100 : 0;
  const rows: { label: string; count: number; pct: number; color: string }[] = [
    { label: "Passed",   count: passed,   pct: passPct,   color: "#3fb950" },
    { label: "Filtered", count: filtered, pct: filterPct, color: "#f85149" },
  ];
  return (
    <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid rgba(255,255,255,0.07)" }}>
      <div style={{ fontSize: 9, color: "var(--dim)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 8 }}>
        Paper curation &middot; {attempted} papers &times; {CURATE_JUDGES} judges
      </div>
      {rows.map(({ label, count, pct, color }) => (
        <div key={label} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
          <span style={{ fontSize: 9, color, fontFamily: "var(--font-mono)", fontWeight: 700, width: 48, flexShrink: 0 }}>{label}</span>
          <div style={{ flex: 1, height: 6, background: "rgba(255,255,255,0.07)", borderRadius: 3, overflow: "hidden" }}>
            <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 3, transition: "width 0.4s" }} />
          </div>
          <span style={{ fontSize: 10, color: "var(--text)", fontFamily: "var(--font-mono)", width: 52, textAlign: "right", flexShrink: 0 }}>
            {count} <span style={{ color: "var(--dim)", fontSize: 9 }}>({pct.toFixed(0)}%)</span>
          </span>
        </div>
      ))}
    </div>
  );
}

function LitReviewCompute({ run }: { run: RunRecord }) {
  const [selected, setSelected] = useState<string | null>(null);

  const tbs = run.tokens_by_stage;
  if (!tbs) return <div style={{ padding: 24, color: "var(--dim)", fontSize: 12 }}>No compute data recorded for this run.</div>;

  const entries = Object.entries(tbs)
    .filter(([stage]) => LR_STAGE_ORDER.includes(stage))
    .sort(([a], [b]) => LR_STAGE_ORDER.indexOf(a) - LR_STAGE_ORDER.indexOf(b));

  if (entries.length === 0) return <div style={{ padding: 24, color: "var(--dim)", fontSize: 12 }}>No stage data recorded for this run.</div>;

  const totalMs     = entries.reduce((s, [, st]) => s + (st.total_ms ?? 0), 0);
  const totalInput  = entries.reduce((s, [, st]) => s + (st.input  ?? 0), 0);
  const totalOutput = entries.reduce((s, [, st]) => s + (st.output ?? 0), 0);
  const totalCalls  = entries.reduce((s, [, st]) => s + (st.calls  ?? 0), 0);

  // Curation funnel data
  const curateCalls    = (tbs.curate as StageTokens | undefined)?.calls ?? 0;
  const papersAttempted = curateCalls > 0 ? Math.round(curateCalls / CURATE_JUDGES) : 0;
  const papersPassed    = (run.tool_calls ?? []).filter((tc) => tc.name === "arxiv_fetch" || (tc.urls?.length ?? 0) > 0).length;

  const selSt  = selected ? tbs[selected] as StageTokens : null;
  const selCfg = selected ? (STAGE_CFG[selected] ?? { color: "#8b949e", label: selected }) : null;

  const colGrid = "110px 44px 80px 80px 80px 68px";

  return (
    <div style={{ padding: "16px 18px", overflowY: "auto", flex: 1 }}>
      {/* Header */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--dim)", marginBottom: 5, textTransform: "uppercase", letterSpacing: "0.06em" }}>
          <span>Multi-stage compute</span>
          <span style={{ fontFamily: "var(--font-mono)", color: "var(--text)" }}>
            {totalCalls} calls &middot; {fmtMs(totalMs)}
          </span>
        </div>
        {/* Time-proportional bar */}
        <div style={{ height: 7, background: "rgba(255,255,255,0.06)", borderRadius: 4, overflow: "hidden", display: "flex" }}>
          {entries.map(([stage, st]) => {
            const pct = totalMs > 0 ? ((st.total_ms ?? 0) / totalMs) * 100 : 0;
            const cfg = STAGE_CFG[stage] ?? { color: "#8b949e", label: stage };
            return <div key={stage} style={{ width: `${pct}%`, height: "100%", background: cfg.color, flexShrink: 0, transition: "width 0.4s" }} />;
          })}
        </div>
        <div style={{ fontSize: 9, color: "rgba(255,255,255,0.2)", marginTop: 3, fontFamily: "var(--font-mono)" }}>
          proportional by wall time &middot; {totalInput.toLocaleString()} in + {totalOutput.toLocaleString()} out tok
        </div>
      </div>

      {/* Table */}
      <div style={{ display: "flex", flexDirection: "column", gap: 1, marginBottom: 12 }}>
        <div style={{ display: "grid", gridTemplateColumns: colGrid, gap: "0 8px", padding: "3px 8px", fontSize: 9, color: "var(--dim)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
          <span>Stage</span><span>Calls</span><span>Input tok</span><span>Output tok</span><span>Avg in/call</span><span>Time</span>
        </div>
        {entries.map(([stage, st]) => {
          const cfg    = STAGE_CFG[stage] ?? { color: "#8b949e", label: stage };
          const calls  = st.calls ?? 1;
          const avgIn  = calls > 0 ? Math.round((st.input ?? 0) / calls) : 0;
          const isSel  = selected === stage;
          return (
            <div key={stage} onClick={() => setSelected(isSel ? null : stage)} style={{
              display: "grid", gridTemplateColumns: colGrid, gap: "0 8px",
              padding: "6px 8px", borderRadius: 5, cursor: "pointer",
              background: isSel ? `${cfg.color}15` : "transparent",
              border:     isSel ? `1px solid ${cfg.color}30` : "1px solid transparent",
              transition: "background 0.1s",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                <div style={{ width: 7, height: 7, borderRadius: 2, background: cfg.color, flexShrink: 0 }} />
                <span style={{ fontSize: 11, color: cfg.color, fontWeight: 600 }}>{cfg.label}</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                <span style={{ fontSize: 11, color: "var(--text)", fontFamily: "var(--font-mono)" }}>{calls}</span>
                {stage === "curate" && papersAttempted > 0 && (
                  <span style={{ fontSize: 8, color: "var(--dim)", fontFamily: "var(--font-mono)" }}>{papersAttempted}&times;{CURATE_JUDGES}</span>
                )}
              </div>
              <span style={{ fontSize: 11, color: "var(--text)", fontFamily: "var(--font-mono)" }}>{(st.input ?? 0).toLocaleString()}</span>
              <span style={{ fontSize: 11, color: "var(--text)", fontFamily: "var(--font-mono)" }}>{(st.output ?? 0).toLocaleString()}</span>
              <span style={{ fontSize: 11, color: "var(--dim)",  fontFamily: "var(--font-mono)" }}>{avgIn.toLocaleString()}</span>
              <span style={{ fontSize: 11, color: "var(--text)", fontFamily: "var(--font-mono)" }}>{fmtMs(st.total_ms)}</span>
            </div>
          );
        })}
        <div style={{ display: "grid", gridTemplateColumns: colGrid, gap: "0 8px", padding: "6px 8px 4px", borderTop: "1px solid var(--border)", marginTop: 2 }}>
          <span style={{ fontSize: 10, fontWeight: 700, color: "var(--dim)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Total</span>
          <span style={{ fontSize: 11, color: "var(--text)", fontFamily: "var(--font-mono)" }}>{totalCalls}</span>
          <span style={{ fontSize: 11, color: "var(--text)", fontFamily: "var(--font-mono)" }}>{totalInput.toLocaleString()}</span>
          <span style={{ fontSize: 11, color: "var(--text)", fontFamily: "var(--font-mono)" }}>{totalOutput.toLocaleString()}</span>
          <span style={{ fontSize: 11, color: "var(--dim)",  fontFamily: "var(--font-mono)" }}>—</span>
          <span style={{ fontSize: 11, color: "var(--text)", fontFamily: "var(--font-mono)" }}>{fmtMs(totalMs)}</span>
        </div>
      </div>

      {/* Selected stage detail */}
      {selected && selSt && selCfg && (() => {
        const calls = selSt.calls ?? 1;
        const rows: [string, string | null][] = [
          ["Input tokens",   (selSt.input  ?? 0).toLocaleString()],
          ["Output tokens",  (selSt.output ?? 0).toLocaleString()],
          ["Calls",          String(calls)],
          ["Avg in / call",  calls > 0 ? Math.round((selSt.input ?? 0) / calls).toLocaleString() : "—"],
          ["Total time",     fmtMs(selSt.total_ms)],
          ["Prompt time",    selSt.prompt_ms   != null ? fmtMs(selSt.prompt_ms)   : null],
          ["Eval time",      selSt.eval_ms     != null ? fmtMs(selSt.eval_ms)     : null],
          ["Thinking chars", selSt.thinking_chars ? selSt.thinking_chars.toLocaleString() : null],
        ];
        return (
          <div style={{ padding: "11px 14px", background: "var(--surface)", border: `1px solid ${selCfg.color}35`, borderLeft: `3px solid ${selCfg.color}`, borderRadius: 7 }}>
            <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: selCfg.color, marginBottom: 9 }}>
              {selCfg.label} &middot; {calls} call{calls !== 1 ? "s" : ""}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "7px 20px" }}>
              {rows.filter(([, v]) => v !== null).map(([label, value]) => (
                <div key={label}>
                  <div style={{ fontSize: 9, color: "var(--dim)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 2 }}>{label}</div>
                  <div style={{ fontSize: 12, color: "var(--text)", fontFamily: "var(--font-mono)" }}>{value}</div>
                </div>
              ))}
            </div>
            {selected === "curate" && papersAttempted > 0 && (
              <CurationFunnel attempted={papersAttempted} passed={papersPassed} />
            )}
            <MessageViewer runId={run.run_id} stage={selected} />
          </div>
        );
      })()}
    </div>
  );
}

// ── Subtasks pane ─────────────────────────────────────────────────────────────

function SubtasksPane({ run, onSelectRun }: { run: RunRecord; onSelectRun: (r: RunRecord) => void }) {
  const { data: children, isLoading, error } = useQuery({
    queryKey:  ["run_children", run.run_id],
    queryFn:   () => fetch(`/api/runs/${run.run_id}/children`).then((r) => r.json() as Promise<RunRecord[]>),
    staleTime: 30_000,
  });

  if (isLoading) return <div style={{ padding: 24, color: "var(--dim)", fontSize: 12 }}>Loading subtask runs…</div>;
  if (error)     return <div style={{ padding: 24, color: "var(--fail)", fontSize: 12 }}>Failed to load subtask runs.</div>;

  if (!children || children.length === 0) {
    const hint = run.subtask_count != null ? ` Expected ${run.subtask_count} subtask(s) — records may not yet be indexed.` : "";
    return <div style={{ padding: 24, color: "var(--dim)", fontSize: 12 }}>No child runs found.{hint}</div>;
  }

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "14px 18px", display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--dim)", marginBottom: 4 }}>
        {children.length} subtask run{children.length !== 1 ? "s" : ""}
      </div>
      {children.map((child) => {
        const score = child.wiggum_scores?.at(-1);
        return (
          <div
            key={child.run_id}
            onClick={() => onSelectRun(child)}
            style={{
              padding: "10px 14px", borderRadius: 7, cursor: "pointer",
              border: "1px solid var(--border)", background: "var(--surface)",
              display: "flex", flexDirection: "column", gap: 6,
              transition: "border-color 0.12s, background 0.12s",
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.borderColor = "var(--accent)"; (e.currentTarget as HTMLDivElement).style.background = "rgba(129,140,248,0.06)"; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.borderColor = "var(--border)"; (e.currentTarget as HTMLDivElement).style.background = "var(--surface)"; }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
              {child.final && <span className={clsx("badge", child.final.toLowerCase())} style={{ fontSize: "0.6rem" }}>{child.final}</span>}
              {score != null && (
                <span style={{ fontSize: 11, fontWeight: 700, fontFamily: "var(--font-mono)", color: scoreColor(score) }}>{score.toFixed(1)}</span>
              )}
              <span style={{ fontSize: 9, color: "var(--dim)", fontFamily: "var(--font-mono)", marginLeft: "auto" }}>
                {child.run_duration_s != null ? `${child.run_duration_s.toFixed(0)}s` : ""}
              </span>
            </div>
            <div style={{ fontSize: 11, color: "var(--text)", lineHeight: 1.45, wordBreak: "break-word" }}>
              {trunc(child.task, 120)}
            </div>
            <div style={{ display: "flex", gap: 10, fontSize: 10, color: "var(--dim)", fontFamily: "var(--font-mono)" }}>
              <span>{fmtTs(child.timestamp)}</span>
              {child.input_tokens  != null && <span>{child.input_tokens.toLocaleString()} in</span>}
              {child.output_tokens != null && <span>{child.output_tokens.toLocaleString()} out</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Main view ──────────────────────────────────────────────────────────────────

export function Runs() {
  const [page,   setPage]   = useState(1);
  const [status, setStatus] = useState<StatusFilter>("all");
  const [search, setSearch] = useState("");

  const apiStatus = status === "all" ? "" : status;
  const { data: paged, isLoading, error } = usePagedRuns(page, 25, apiStatus, search);
  const runs  = paged?.runs  ?? [];
  const total = paged?.total ?? 0;
  const pages = paged?.pages ?? 1;

  const { data: liveRun = null }              = useLiveRun();
  const liveThinking                          = useLiveThinking(liveRun?.item_id);
  const [selectedRun,  setSelectedRun]  = useState<RunRecord | null>(null);
  const [selectedNode, setSelectedNode] = useState<DagNode | null>(null);

  const handleStatus = (s: StatusFilter) => { setStatus(s); setPage(1); setSelectedRun(null); setSelectedNode(null); };
  const handleSearch = (s: string)       => { setSearch(s); setPage(1); setSelectedRun(null); setSelectedNode(null); };
  const [viewMode,     setViewMode]     = useState<ViewMode>("dag");
  const [liveSelected, setLiveSelected] = useState(false);

  // Auto-select the live run when one starts; deselect when it finishes
  const prevLive = useRef<string | null>(null);
  useEffect(() => {
    if (liveRun && prevLive.current !== liveRun.run_id) {
      setLiveSelected(true);
      setSelectedRun(null);
      prevLive.current = liveRun.run_id;
    }
    if (!liveRun && prevLive.current) {
      setLiveSelected(false);
      prevLive.current = null;
    }
  }, [liveRun]);

  const defaultRun = runs.find((r) => (r.tool_calls?.length ?? 0) > 0 || (r.wiggum_scores?.length ?? 0) > 0) ?? runs[0] ?? null;
  const activeRun  = liveSelected ? null : (selectedRun ?? defaultRun);

  const handleSelectRun = (r: RunRecord) => {
    setSelectedRun(r); setSelectedNode(null); setLiveSelected(false);
    if (!r.orchestrated && viewMode === "subtasks") setViewMode("dag");
  };
  const handleDeselectRun = () => { setSelectedRun(null); setSelectedNode(null); };
  const handleViewMode = (m: ViewMode) => { setViewMode(m); if (m !== "dag") setSelectedNode(null); };
  const handleSelectLive = () => { setLiveSelected(true); setSelectedRun(null); setSelectedNode(null); };

  if (isLoading && !paged) return <div className="loading">Loading…</div>;
  if (error)               return <div className="page-error">Failed to load runs.</div>;

  return (
    <div style={{ margin: "-28px", height: "100vh", display: "flex", overflow: "hidden" }}>
      <LeftPanel runs={runs} selected={activeRun} onSelect={handleSelectRun}
        liveRun={liveRun} liveSelected={liveSelected} onSelectLive={handleSelectLive}
        total={total} page={page} pages={pages}
        onPage={(p) => { setPage(p); setSelectedRun(null); setSelectedNode(null); }}
        search={search} onSearch={handleSearch}
        status={status} onStatus={handleStatus} />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {liveSelected && liveRun ? (
          <>
            {/* Live run header */}
            <div style={{ padding: "10px 16px", background: "var(--surface)", borderBottom: "1px solid rgba(34,211,238,0.2)", display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
              <span className="live-dot" style={{ width: 8, height: 8, borderRadius: "50%", background: "#22d3ee", display: "inline-block" }} />
              <span style={{ fontSize: 12, color: "#22d3ee", fontWeight: 700, fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: "0.06em" }}>running</span>
              <span style={{ fontSize: 12, color: "var(--text)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{liveRun.task}</span>
            </div>

            {/* Live DAG + reasoning traces */}
            <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
              <LiveDagCanvas liveRun={liveRun} />
              {liveRun.item_id && <LiveThinkingPanel events={liveThinking} />}
            </div>
          </>
        ) : activeRun ? (
          <>
            <RunSummaryCard run={activeRun} onClose={handleDeselectRun} />

            {/* view mode tabs */}
            <div style={{ display: "flex", borderBottom: "1px solid var(--border)", background: "var(--surface)", flexShrink: 0 }}>
              {(["dag", "context", ...(activeRun.orchestrated ? ["subtasks"] : [])] as ViewMode[]).map((m) => (
                <button key={m} onClick={() => handleViewMode(m)} style={{
                  padding: "6px 16px", fontSize: 10, fontWeight: 700, cursor: "pointer",
                  textTransform: "uppercase", letterSpacing: "0.07em",
                  background: "none", border: "none",
                  borderBottom: viewMode === m ? "2px solid var(--accent)" : "2px solid transparent",
                  color: viewMode === m ? "var(--accent)" : "var(--dim)",
                  marginBottom: -1, transition: "color 0.15s",
                }}>
                  {m === "dag"
                    ? (activeRun.task_type === "lit-review" ? "Overview" : "Pipeline DAG")
                    : m === "context"
                      ? (activeRun.task_type === "lit-review" ? "Compute" : "Context window")
                      : `Subtasks${activeRun.subtask_count != null ? ` (${activeRun.subtask_count})` : ""}`}
                </button>
              ))}
            </div>

            <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
              {viewMode === "dag" ? (
                activeRun.task_type === "lit-review" ? (
                  <LitReviewDag run={activeRun} />
                ) : (
                  <>
                    <DagCanvas run={activeRun} selectedNode={selectedNode} onSelectNode={setSelectedNode} />
                    {selectedNode && (
                      <NodeInspector node={selectedNode} run={activeRun} onClose={() => setSelectedNode(null)} />
                    )}
                  </>
                )
              ) : viewMode === "subtasks" ? (
                <SubtasksPane run={activeRun} onSelectRun={handleSelectRun} />
              ) : (
                activeRun.task_type === "lit-review"
                  ? <LitReviewCompute run={activeRun} />
                  : <ContextTreemap   run={activeRun} />
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

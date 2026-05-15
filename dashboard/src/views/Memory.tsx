import { useState, useCallback, useRef, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useMemories, useMemory, useMemoryGraph, useMemoryPruneCandidates } from "@/hooks/useRuns";
import { api } from "@/api/client";
import type { MemoryRow, MemoryGraphNode } from "@/types";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const QUALITY_COLOR: Record<number, string> = {
  [-3]: "#ef4444", [-2]: "#f97316", [-1]: "#eab308",
  0:    "var(--dim)",
  1:    "#86efac",  2:    "#34d399",  3:    "#10b981",
};

const CLUSTER_COLORS = [
  "#6366f1","#0ea5e9","#10b981","#f59e0b",
  "#ec4899","#8b5cf6","#14b8a6","#f97316",
];

type Tab = "memories" | "review" | "graph";

// ---------------------------------------------------------------------------
// Quality badge
// ---------------------------------------------------------------------------

function QualityBadge({ q }: { q: number }) {
  const color = QUALITY_COLOR[Math.max(-3, Math.min(3, q))] ?? "var(--dim)";
  const label = q > 0 ? `+${q}` : String(q);
  return (
    <span style={{
      fontSize: 10, padding: "1px 5px", borderRadius: 4,
      background: color + "22", color, fontWeight: 600, fontFamily: "var(--font-mono, monospace)",
    }}>
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Memory list row
// ---------------------------------------------------------------------------

function MemoryItem({ mem, selected, onClick }: { mem: MemoryRow; selected: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        textAlign: "left", border: "none", cursor: "pointer", width: "100%",
        padding: "10px 12px", borderRadius: 8,
        background: selected ? "var(--accent-faint, rgba(99,102,241,0.12))" : "transparent",
        borderLeft: selected ? "2px solid var(--accent, #6366f1)" : "2px solid transparent",
        marginBottom: 2,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 3 }}>
        <span style={{
          fontSize: 11, fontWeight: 600,
          color: selected ? "var(--accent, #818cf8)" : "inherit",
          flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {mem.title}
        </span>
        <QualityBadge q={mem.quality} />
      </div>
      <div style={{ display: "flex", gap: 8, fontSize: 10, color: "var(--dim)" }}>
        <span>{mem.timestamp.slice(0, 10)}</span>
        {mem.task_type && <span style={{ color: "#6366f1" }}>{mem.task_type}</span>}
        {mem.final_score !== undefined && mem.final_score !== null && (
          <span>{mem.final_score.toFixed(1)}/10</span>
        )}
        {mem.facts_count > 0 && <span>{mem.facts_count} facts</span>}
      </div>
      {mem.tags.length > 0 && (
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 4 }}>
          {mem.tags.slice(0, 4).map((t) => (
            <span key={t} style={{
              fontSize: 9, padding: "1px 5px", borderRadius: 10,
              background: "rgba(99,102,241,0.15)", color: "#818cf8",
            }}>{t}</span>
          ))}
        </div>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Detail pane
// ---------------------------------------------------------------------------

function DetailPane({ memId, onDeleted }: { memId: number; onDeleted: () => void }) {
  const qc = useQueryClient();
  const { data: mem, isLoading } = useMemory(memId);

  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft,   setTitleDraft]   = useState("");
  const [tagDraft,     setTagDraft]     = useState("");
  const [saving,       setSaving]       = useState(false);
  const [confirmDel,   setConfirmDel]   = useState(false);
  const [msg,          setMsg]          = useState("");

  const invalidate = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ["memory", memId] });
    void qc.invalidateQueries({ queryKey: ["memories"] });
    void qc.invalidateQueries({ queryKey: ["memory_prune"] });
  }, [qc, memId]);

  const flash = (m: string) => { setMsg(m); setTimeout(() => setMsg(""), 2500); };

  const sendFeedback = async (rating: number) => {
    setSaving(true);
    try {
      await api.memory_feedback(memId, rating);
      invalidate();
      flash(rating > 0 ? "Upvoted." : "Downvoted.");
    } finally { setSaving(false); }
  };

  const saveTitle = async () => {
    setSaving(true);
    try {
      await api.memory_update(memId, { title: titleDraft });
      invalidate();
      setEditingTitle(false);
      flash("Saved.");
    } finally { setSaving(false); }
  };

  const addTag = async () => {
    if (!tagDraft.trim() || !mem) return;
    const newTags = [...(mem.tags || []), tagDraft.trim()];
    setSaving(true);
    try {
      await api.memory_update(memId, { tags: newTags });
      invalidate();
      setTagDraft("");
    } finally { setSaving(false); }
  };

  const removeTag = async (tag: string) => {
    if (!mem) return;
    const newTags = mem.tags.filter((t) => t !== tag);
    await api.memory_update(memId, { tags: newTags });
    invalidate();
  };

  const hardDelete = async () => {
    setSaving(true);
    try {
      await api.memory_delete(memId);
      void qc.invalidateQueries({ queryKey: ["memories"] });
      void qc.invalidateQueries({ queryKey: ["memory_prune"] });
      onDeleted();
    } finally { setSaving(false); }
  };

  if (isLoading) return <div className="loading">Loading…</div>;
  if (!mem) return null;

  return (
    <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "flex-start", gap: 10,
        paddingBottom: 12, borderBottom: "1px solid var(--border, rgba(255,255,255,0.08))",
      }}>
        <div style={{ flex: 1 }}>
          {editingTitle ? (
            <div style={{ display: "flex", gap: 6 }}>
              <input
                value={titleDraft}
                onChange={(e) => setTitleDraft(e.target.value)}
                style={{
                  flex: 1, background: "var(--surface2)", border: "1px solid var(--accent, #6366f1)",
                  borderRadius: 6, padding: "4px 8px", fontSize: 14, color: "inherit",
                  fontFamily: "inherit", outline: "none",
                }}
                onKeyDown={(e) => { if (e.key === "Enter") void saveTitle(); if (e.key === "Escape") setEditingTitle(false); }}
                autoFocus
              />
              <button onClick={() => void saveTitle()} disabled={saving} style={btn("#10b981")}>Save</button>
              <button onClick={() => setEditingTitle(false)} style={btn("var(--dim)")}>Cancel</button>
            </div>
          ) : (
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 15, fontWeight: 600 }}>{mem.title}</span>
              <button onClick={() => { setTitleDraft(mem.title); setEditingTitle(true); }} style={btn("var(--dim)", true)}>edit</button>
            </div>
          )}
          <div style={{ display: "flex", gap: 10, fontSize: 11, color: "var(--dim)", marginTop: 4 }}>
            <span>{mem.timestamp.slice(0, 16).replace("T", " ")}</span>
            {mem.task_type && <span>{mem.task_type}</span>}
            {mem.final && <span style={{ color: mem.final === "PASS" ? "#10b981" : "#ef4444" }}>{mem.final}</span>}
            {mem.final_score != null && <span>{mem.final_score.toFixed(1)}/10</span>}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {msg && <span style={{ fontSize: 11, color: "#10b981" }}>{msg}</span>}
          <QualityBadge q={mem.quality} />
        </div>
      </div>

      {/* RLHF */}
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <span style={{ fontSize: 11, color: "var(--dim)" }}>Quality signal:</span>
        <button onClick={() => void sendFeedback(1)} disabled={saving} style={btn("#10b981", true)}>👍 upvote</button>
        <button onClick={() => void sendFeedback(-1)} disabled={saving} style={btn("#ef4444", true)}>👎 downvote</button>
        <span style={{ fontSize: 11, color: "var(--dim)" }}>(current: {mem.quality > 0 ? "+" : ""}{mem.quality})</span>
      </div>

      {/* Provenance */}
      {mem.run_id && (
        <div className="card" style={{ padding: "8px 12px" }}>
          <span style={{ fontSize: 10, color: "var(--dim)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Provenance</span>
          <div style={{ fontSize: 12, marginTop: 4 }}>
            Run: <span className="mono" style={{ color: "var(--accent, #818cf8)", fontSize: 11 }}>{mem.run_id}</span>
          </div>
          {mem.output_path && (
            <div style={{ fontSize: 11, color: "var(--dim)", marginTop: 2, wordBreak: "break-all" }}>{mem.output_path}</div>
          )}
        </div>
      )}

      {/* Task */}
      <div>
        <div style={{ fontSize: 10, color: "var(--dim)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>Task</div>
        <div style={{ fontSize: 12, lineHeight: 1.6 }}>{mem.task}</div>
      </div>

      {/* Narrative */}
      <div>
        <div style={{ fontSize: 10, color: "var(--dim)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>Narrative</div>
        <div style={{
          fontSize: 12, lineHeight: 1.7,
          background: "var(--surface2, rgba(255,255,255,0.04))",
          borderRadius: 8, padding: 12,
          borderLeft: "3px solid var(--accent, #6366f1)",
        }}>{mem.narrative}</div>
      </div>

      {/* Facts */}
      {mem.facts.length > 0 && (
        <div>
          <div style={{ fontSize: 10, color: "var(--dim)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>Facts</div>
          <ul style={{ margin: 0, padding: "0 0 0 16px", display: "flex", flexDirection: "column", gap: 4 }}>
            {mem.facts.map((f, i) => (
              <li key={i} style={{ fontSize: 12, lineHeight: 1.6 }}>{f}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Tags */}
      <div>
        <div style={{ fontSize: 10, color: "var(--dim)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>Tags</div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          {mem.tags.map((t) => (
            <span key={t} style={{
              fontSize: 11, padding: "2px 8px", borderRadius: 12,
              background: "rgba(99,102,241,0.15)", color: "#818cf8",
              display: "flex", alignItems: "center", gap: 4,
            }}>
              {t}
              <button
                onClick={() => void removeTag(t)}
                style={{ background: "none", border: "none", cursor: "pointer", padding: 0, color: "inherit", fontSize: 10, lineHeight: 1 }}
              >×</button>
            </span>
          ))}
          <div style={{ display: "flex", gap: 4 }}>
            <input
              value={tagDraft}
              onChange={(e) => setTagDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") void addTag(); }}
              placeholder="add tag…"
              style={{
                fontSize: 11, padding: "2px 8px", borderRadius: 12, width: 100,
                background: "var(--surface2)", border: "1px solid rgba(255,255,255,0.1)",
                color: "inherit", outline: "none", fontFamily: "inherit",
              }}
            />
            {tagDraft && <button onClick={() => void addTag()} style={btn("#6366f1", true)}>+</button>}
          </div>
        </div>
      </div>

      {/* Delete */}
      <div style={{ marginTop: "auto", paddingTop: 12, borderTop: "1px solid var(--border, rgba(255,255,255,0.08))" }}>
        {!confirmDel ? (
          <button onClick={() => setConfirmDel(true)} style={btn("#ef4444", true)}>Delete permanently…</button>
        ) : (
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ fontSize: 12, color: "#ef4444" }}>Permanently delete this memory?</span>
            <button onClick={() => void hardDelete()} disabled={saving} style={btn("#ef4444")}>Delete</button>
            <button onClick={() => setConfirmDel(false)} style={btn("var(--dim)")}>Cancel</button>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Review tab (prune candidates)
// ---------------------------------------------------------------------------

function ReviewPane() {
  const qc = useQueryClient();
  const { data, isLoading } = useMemoryPruneCandidates();
  const [deleting, setDeleting] = useState<Set<number>>(new Set());
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const candidates = data?.candidates ?? [];

  const dismiss = async (id: number, hard: boolean) => {
    setDeleting((s) => new Set(s).add(id));
    try {
      if (hard) {
        await api.memory_delete(id);
      } else {
        await api.memory_update(id, { quality: 0 });
      }
      void qc.invalidateQueries({ queryKey: ["memory_prune"] });
      void qc.invalidateQueries({ queryKey: ["memories"] });
      if (selectedId === id) setSelectedId(null);
    } finally {
      setDeleting((s) => { const n = new Set(s); n.delete(id); return n; });
    }
  };

  if (isLoading) return <div className="loading">Loading…</div>;

  if (candidates.length === 0) {
    return (
      <div style={{ textAlign: "center", padding: "60px 0", color: "var(--dim)" }}>
        <div style={{ fontSize: 32, marginBottom: 12 }}>✓</div>
        <div style={{ fontSize: 14 }}>No memories flagged for review.</div>
        <div style={{ fontSize: 12, marginTop: 6 }}>Memories with quality ≤ −2 appear here.</div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>
      <div style={{ width: 320, flexShrink: 0 }}>
        <div style={{ fontSize: 12, color: "var(--dim)", marginBottom: 10 }}>
          {candidates.length} memor{candidates.length !== 1 ? "ies" : "y"} need review
        </div>
        {candidates.map((c) => (
          <div key={c.id} style={{
            padding: "10px 12px", borderRadius: 8, marginBottom: 4,
            background: selectedId === c.id ? "var(--accent-faint, rgba(99,102,241,0.12))" : "var(--surface2, rgba(255,255,255,0.04))",
            cursor: "pointer",
          }} onClick={() => setSelectedId(selectedId === c.id ? null : c.id)}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
              <span style={{ fontSize: 12, fontWeight: 600, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.title}</span>
              <QualityBadge q={c.quality} />
            </div>
            <div style={{ fontSize: 10, color: "var(--dim)", marginBottom: 8 }}>
              {c.timestamp.slice(0, 10)} · score {c.final_score?.toFixed(1) ?? "n/a"}
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              <button
                onClick={(e) => { e.stopPropagation(); void dismiss(c.id, false); }}
                disabled={deleting.has(c.id)}
                style={btn("#6366f1", true)}
              >Reset quality</button>
              <button
                onClick={(e) => { e.stopPropagation(); void dismiss(c.id, true); }}
                disabled={deleting.has(c.id)}
                style={btn("#ef4444", true)}
              >Delete</button>
            </div>
          </div>
        ))}
      </div>
      {selectedId && (
        <DetailPane memId={selectedId} onDeleted={() => setSelectedId(null)} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Graph tab (UMAP ontology)
// ---------------------------------------------------------------------------

function GraphPane() {
  const { data: graph, isLoading } = useMemoryGraph();
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoveredId, setHoveredId] = useState<number | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const dragging = useRef(false);
  const lastPos = useRef({ x: 0, y: 0 });

  const W = 700, H = 500;

  const nodes = graph?.nodes ?? [];
  const clusters = graph?.clusters ?? [];

  // Normalize UMAP coords to SVG viewport
  const xs = nodes.map((n) => n.x);
  const ys = nodes.map((n) => n.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const rangeX = (maxX - minX) || 1, rangeY = (maxY - minY) || 1;
  const pad = 40;

  const toSvg = (n: MemoryGraphNode) => ({
    x: pad + ((n.x - minX) / rangeX) * (W - 2 * pad),
    y: pad + ((n.y - minY) / rangeY) * (H - 2 * pad),
  });

  const onMouseDown = (e: React.MouseEvent) => {
    dragging.current = true;
    lastPos.current = { x: e.clientX, y: e.clientY };
  };
  const onMouseMove = (e: React.MouseEvent) => {
    if (!dragging.current) return;
    setPan((p) => ({ x: p.x + e.clientX - lastPos.current.x, y: p.y + e.clientY - lastPos.current.y }));
    lastPos.current = { x: e.clientX, y: e.clientY };
  };
  const onMouseUp = () => { dragging.current = false; };
  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    setZoom((z) => Math.max(0.3, Math.min(4, z * (e.deltaY < 0 ? 1.12 : 0.9))));
  };

  if (isLoading) return <div className="loading">Loading graph…</div>;
  if (graph?.error) return (
    <div style={{ textAlign: "center", padding: "60px 0", color: "var(--dim)" }}>
      <div style={{ fontSize: 13, marginBottom: 8 }}>{graph.error}</div>
      {graph.error.includes("umap-learn") && (
        <code style={{ fontSize: 11 }}>pip install umap-learn scikit-learn</code>
      )}
    </div>
  );
  if (nodes.length === 0) return (
    <div style={{ textAlign: "center", padding: "60px 0", color: "var(--dim)" }}>
      <div style={{ fontSize: 13 }}>Not enough memories for ontology visualization.</div>
      <div style={{ fontSize: 11, marginTop: 6 }}>Run at least 5 tasks to populate this graph.</div>
    </div>
  );

  const hoveredNode = nodes.find((n) => n.id === hoveredId) ?? null;

  return (
    <div>
      {/* Cluster legend */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        {clusters.map((c) => (
          <div key={c.id} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11 }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%", background: c.color }} />
            <span style={{ color: "var(--dim)" }}>{c.label}</span>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", gap: 20 }}>
        {/* SVG canvas */}
        <div style={{ position: "relative", borderRadius: 12, overflow: "hidden", background: "var(--surface2, rgba(255,255,255,0.03))", border: "1px solid var(--border, rgba(255,255,255,0.07))" }}>
          <svg
            ref={svgRef}
            width={W} height={H}
            style={{ cursor: dragging.current ? "grabbing" : "grab", display: "block" }}
            onMouseDown={onMouseDown}
            onMouseMove={onMouseMove}
            onMouseUp={onMouseUp}
            onMouseLeave={onMouseUp}
            onWheel={onWheel}
          >
            <g transform={`translate(${pan.x},${pan.y}) scale(${zoom})`}>
              {nodes.map((n) => {
                const { x, y } = toSvg(n);
                const color = CLUSTER_COLORS[n.cluster % CLUSTER_COLORS.length];
                const isHov = n.id === hoveredId;
                const isSel = n.id === selectedId;
                const r = 5 + Math.max(0, n.quality) * 1.5;
                return (
                  <g key={n.id}
                    onMouseEnter={() => setHoveredId(n.id)}
                    onMouseLeave={() => setHoveredId(null)}
                    onClick={() => setSelectedId(n.id === selectedId ? null : n.id)}
                    style={{ cursor: "pointer" }}
                  >
                    <circle
                      cx={x} cy={y} r={isSel ? r + 3 : r}
                      fill={color}
                      fillOpacity={isHov || isSel ? 0.9 : 0.6}
                      stroke={isSel ? "#fff" : "none"}
                      strokeWidth={1.5}
                    />
                    {(isHov || isSel) && (
                      <text x={x} y={y - r - 4} textAnchor="middle" fill="#e2e8f0" fontSize={9} style={{ pointerEvents: "none" }}>
                        {n.label.slice(0, 28)}{n.label.length > 28 ? "…" : ""}
                      </text>
                    )}
                  </g>
                );
              })}
            </g>
          </svg>
          <div style={{ position: "absolute", bottom: 8, right: 10, fontSize: 10, color: "var(--dim)", userSelect: "none" }}>
            scroll to zoom · drag to pan · click to select
          </div>
        </div>

        {/* Detail panel for selected node */}
        {selectedId ? (
          <div style={{ width: 320, flexShrink: 0 }}>
            <DetailPane memId={selectedId} onDeleted={() => setSelectedId(null)} />
          </div>
        ) : hoveredNode ? (
          <div style={{ width: 320, flexShrink: 0, padding: 16, background: "var(--surface2, rgba(255,255,255,0.04))", borderRadius: 10 }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>{hoveredNode.label}</div>
            <div style={{ fontSize: 11, color: "var(--dim)", display: "flex", gap: 8 }}>
              {hoveredNode.task_type && <span>{hoveredNode.task_type}</span>}
              <span>quality: {hoveredNode.quality > 0 ? "+" : ""}{hoveredNode.quality}</span>
            </div>
            <div style={{ fontSize: 11, color: "var(--dim)", marginTop: 6 }}>Click to open detail</div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Filters + search
// ---------------------------------------------------------------------------

const QUALITY_OPTS: { label: string; min: number; max: number }[] = [
  { label: "All",       min: -3, max: 3 },
  { label: "Positive",  min:  1, max: 3 },
  { label: "Neutral",   min:  0, max: 0 },
  { label: "Negative",  min: -3, max: -1 },
];

// ---------------------------------------------------------------------------
// Root view
// ---------------------------------------------------------------------------

export function Memory() {
  const [tab,        setTab]        = useState<Tab>("memories");
  const [search,     setSearch]     = useState("");
  const [taskType,   setTaskType]   = useState("");
  const [qualFilter, setQualFilter] = useState(0); // index into QUALITY_OPTS
  const [page,       setPage]       = useState(1);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [debouncedSearch, setDebouncedSearch] = useState("");

  const qf = QUALITY_OPTS[qualFilter];
  const { data, isLoading } = useMemories({
    search:      debouncedSearch,
    task_type:   taskType,
    quality_min: qf.min,
    quality_max: qf.max,
    page,
    per_page:    25,
  });

  const memories    = data?.memories ?? [];
  const total       = data?.total ?? 0;
  const pages       = data?.pages ?? 1;
  const { data: pruneData } = useMemoryPruneCandidates();
  const pruneCount  = pruneData?.candidates.length ?? 0;

  const onSearch = (v: string) => {
    setSearch(v);
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => { setDebouncedSearch(v); setPage(1); }, 300);
  };

  useEffect(() => () => { if (searchTimer.current) clearTimeout(searchTimer.current); }, []);

  return (
    <div>
      <div className="view-header">
        <h1>Memory</h1>
        <p>Semantic observation store · RLHF quality signals · Ontology graph</p>
      </div>

      {/* Tab bar */}
      <div style={{ display: "flex", gap: 4, marginBottom: 20 }}>
        {(["memories", "review", "graph"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              padding: "6px 16px", borderRadius: 8, border: "none", cursor: "pointer", fontSize: 13,
              background: tab === t ? "var(--accent-faint, rgba(99,102,241,0.15))" : "transparent",
              color: tab === t ? "var(--accent, #818cf8)" : "var(--dim)",
              fontWeight: tab === t ? 600 : 400,
            }}
          >
            {t === "review" ? (
              <>Review{pruneCount > 0 && <span style={{ marginLeft: 6, fontSize: 10, background: "#ef4444", color: "#fff", borderRadius: 10, padding: "1px 5px" }}>{pruneCount}</span>}</>
            ) : t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === "review" && <ReviewPane />}
      {tab === "graph" && <GraphPane />}

      {tab === "memories" && (
        <>
          {/* Search + filters */}
          <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 16, flexWrap: "wrap" }}>
            <input
              value={search}
              onChange={(e) => onSearch(e.target.value)}
              placeholder="Search memories…"
              style={{
                flex: 1, minWidth: 200, maxWidth: 360,
                padding: "7px 12px", borderRadius: 8, fontSize: 13,
                background: "var(--surface2, rgba(255,255,255,0.06))",
                border: "1px solid var(--border, rgba(255,255,255,0.08))",
                color: "inherit", outline: "none", fontFamily: "inherit",
              }}
            />
            {/* Quality filter chips */}
            <div style={{ display: "flex", gap: 4 }}>
              {QUALITY_OPTS.map((o, i) => (
                <button key={o.label} onClick={() => { setQualFilter(i); setPage(1); }} style={{
                  fontSize: 11, padding: "4px 10px", borderRadius: 20, border: "none", cursor: "pointer",
                  background: qualFilter === i ? "var(--accent, #6366f1)" : "var(--surface2, rgba(255,255,255,0.07))",
                  color: qualFilter === i ? "#fff" : "var(--dim)", fontWeight: qualFilter === i ? 600 : 400,
                }}>{o.label}</button>
              ))}
            </div>
            {taskType && (
              <button onClick={() => { setTaskType(""); setPage(1); }} style={{
                fontSize: 11, padding: "4px 10px", borderRadius: 20, border: "none", cursor: "pointer",
                background: "#6366f122", color: "#818cf8",
              }}>{taskType} ×</button>
            )}
            <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--dim)" }}>
              {total} memor{total !== 1 ? "ies" : "y"}
            </span>
          </div>

          {isLoading && <div className="loading">Loading…</div>}

          {!isLoading && memories.length === 0 && (
            <div style={{ textAlign: "center", padding: "60px 0", color: "var(--dim)" }}>
              <div style={{ fontSize: 14, marginBottom: 8 }}>No memories yet.</div>
              <div style={{ fontSize: 12 }}>Memories are stored automatically after PASS runs.</div>
            </div>
          )}

          {!isLoading && memories.length > 0 && (
            <div style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>
              {/* List */}
              <div style={{
                width: 320, flexShrink: 0,
                borderRight: "1px solid var(--border, rgba(255,255,255,0.08))",
                paddingRight: 16,
              }}>
                {memories.map((m) => (
                  <MemoryItem
                    key={m.id}
                    mem={m}
                    selected={selectedId === m.id}
                    onClick={() => {
                      setSelectedId(m.id === selectedId ? null : m.id);
                      if (m.task_type && !taskType) setTaskType("");
                    }}
                  />
                ))}

                {/* Pagination */}
                {pages > 1 && (
                  <div style={{ display: "flex", gap: 4, marginTop: 12, justifyContent: "center" }}>
                    <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1} style={btn("var(--dim)", true)}>‹</button>
                    <span style={{ fontSize: 12, color: "var(--dim)", padding: "4px 8px" }}>{page} / {pages}</span>
                    <button onClick={() => setPage((p) => Math.min(pages, p + 1))} disabled={page === pages} style={btn("var(--dim)", true)}>›</button>
                  </div>
                )}
              </div>

              {/* Detail */}
              {selectedId ? (
                <DetailPane memId={selectedId} onDeleted={() => setSelectedId(null)} />
              ) : (
                <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--dim)", fontSize: 13 }}>
                  Select a memory to view details
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Style helpers
// ---------------------------------------------------------------------------

function btn(color: string, small = false): React.CSSProperties {
  return {
    fontSize:   small ? 11 : 12,
    padding:    small ? "3px 8px" : "4px 12px",
    borderRadius: 6, border: "none", cursor: "pointer",
    background: color + "22", color, fontWeight: 600,
  };
}

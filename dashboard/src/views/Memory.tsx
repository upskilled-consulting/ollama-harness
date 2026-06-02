import { useState, useCallback, useRef, useEffect } from "react";
import { ThumbsUp, ThumbsDown, Hand, Crosshair, Maximize2, ZoomIn, X } from "lucide-react";
import { zoom as d3Zoom, zoomIdentity, brush as d3Brush, select as d3Select } from "d3";
import type { ZoomBehavior } from "d3";
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
        <button onClick={() => void sendFeedback(1)} disabled={saving} style={btn("#10b981", true)} title="Upvote"><ThumbsUp size={13} /> upvote</button>
        <button onClick={() => void sendFeedback(-1)} disabled={saving} style={btn("#ef4444", true)} title="Downvote"><ThumbsDown size={13} /> downvote</button>
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
// Graph tab — D3 zoom + brush interactive canvas
// ---------------------------------------------------------------------------

type GraphMode = "pan" | "select";

function GraphPane() {
  const { data: graph, isLoading, isError } = useMemoryGraph();
  const svgRef    = useRef<SVGSVGElement>(null);
  const gMainRef  = useRef<SVGGElement>(null);
  const gBrushRef = useRef<SVGGElement>(null);
  const zoomBehavior    = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const currentTransform = useRef(zoomIdentity);
  const pendingTransform = useRef<typeof zoomIdentity | null>(null);

  const [mode,           setMode]           = useState<GraphMode>("pan");
  const [selectedId,     setSelectedId]     = useState<number | null>(null);
  const [hoveredId,      setHoveredId]      = useState<number | null>(null);
  const [brushedIds,     setBrushedIds]     = useState<Set<number> | null>(null);
  const [hiddenClusters, setHiddenClusters] = useState<Set<number>>(new Set());
  const [zoomPct,        setZoomPct]        = useState(100);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; node: MemoryGraphNode } | null>(null);

  const W = 720, H = 520, PAD = 40;

  const nodes    = graph?.nodes    ?? [];
  const clusters = graph?.clusters ?? [];

  // UMAP → SVG pixel coords
  const xs = nodes.map((n) => n.x), ys = nodes.map((n) => n.y);
  const minX = xs.length ? Math.min(...xs) : 0, maxX = xs.length ? Math.max(...xs) : 1;
  const minY = ys.length ? Math.min(...ys) : 0, maxY = ys.length ? Math.max(...ys) : 1;
  const rX = (maxX - minX) || 1,  rY = (maxY - minY) || 1;
  const toSvg = (n: MemoryGraphNode) => ({
    x: PAD + ((n.x - minX) / rX) * (W - 2 * PAD),
    y: PAD + ((n.y - minY) / rY) * (H - 2 * PAD),
  });

  // ── D3 Zoom ────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!svgRef.current || !gMainRef.current) return;
    const svgEl = svgRef.current;
    const gEl   = gMainRef.current;

    if (mode !== "pan") {
      // Detach zoom events in select mode
      d3Select(svgEl)
        .on("mousedown.zoom", null).on("touchstart.zoom", null)
        .on("wheel.zoom",     null).on("dblclick.zoom",   null);
      return;
    }

    const z = d3Zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 12])
      .on("zoom", (ev) => {
        currentTransform.current = ev.transform;
        d3Select(gEl).attr("transform", String(ev.transform));
        setZoomPct(Math.round(ev.transform.k * 100));
      });

    zoomBehavior.current = z;
    d3Select(svgEl).call(z);
    return () => { d3Select(svgEl).on(".zoom", null); };
  }, [mode]);

  // Apply a pending zoom transform after mode switches to pan
  useEffect(() => {
    if (mode !== "pan" || !svgRef.current || !zoomBehavior.current || !pendingTransform.current) return;
    d3Select(svgRef.current).transition().duration(420)
      .call(zoomBehavior.current.transform, pendingTransform.current);
    pendingTransform.current = null;
  }, [mode]);

  // ── D3 Brush ───────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!gBrushRef.current) return;
    const gEl = gBrushRef.current;

    if (mode !== "select") {
      d3Select(gEl).on(".brush", null).selectAll("*").remove();
      return;
    }

    const b = d3Brush()
      .extent([[0, 0], [W, H]])
      .on("end", (ev) => {
        if (!ev.selection) { setBrushedIds(null); return; }
        const [[x0, y0], [x1, y1]] = ev.selection as [[number, number], [number, number]];
        const t = currentTransform.current;
        const ids = new Set(
          nodes
            .filter((n) => {
              if (hiddenClusters.has(n.cluster)) return false;
              const p = toSvg(n);
              return t.applyX(p.x) >= x0 && t.applyX(p.x) <= x1
                  && t.applyY(p.y) >= y0 && t.applyY(p.y) <= y1;
            })
            .map((n) => n.id)
        );
        setBrushedIds(ids.size ? ids : null);
      });

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    d3Select(gEl).call(b as any);
    return () => { d3Select(gEl).on(".brush", null).selectAll("*").remove(); };
  }, [mode, nodes, hiddenClusters]); // toSvg is derived from nodes — safe to omit

  // ── Helpers ────────────────────────────────────────────────────────────────
  const resetZoom = () => {
    if (!svgRef.current || !zoomBehavior.current) return;
    d3Select(svgRef.current).transition().duration(380)
      .call(zoomBehavior.current.transform, zoomIdentity);
  };

  const zoomToSelection = () => {
    if (!brushedIds?.size) return;
    const pts = nodes.filter((n) => brushedIds.has(n.id)).map(toSvg);
    const x0 = Math.min(...pts.map((p) => p.x)) - 30, x1 = Math.max(...pts.map((p) => p.x)) + 30;
    const y0 = Math.min(...pts.map((p) => p.y)) - 30, y1 = Math.max(...pts.map((p) => p.y)) + 30;
    const s  = Math.min(10, 0.88 * Math.min(W / (x1 - x0), H / (y1 - y0)));
    pendingTransform.current = zoomIdentity
      .translate(W / 2 - s * (x0 + x1) / 2, H / 2 - s * (y0 + y1) / 2)
      .scale(s);
    setBrushedIds(null);
    setMode("pan");
  };

  const toggleCluster = (id: number) =>
    setHiddenClusters((prev) => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });

  // ── Guard states ───────────────────────────────────────────────────────────
  if (isLoading) return <div className="loading">Loading graph…</div>;
  if (isError) return (
    <div style={{ textAlign: "center", padding: "60px 0", color: "var(--dim)" }}>
      <div style={{ fontSize: 13 }}>Graph unavailable — server may be busy.</div>
      <div style={{ fontSize: 11, marginTop: 6 }}>Switch away and back to retry.</div>
    </div>
  );
  if (graph?.error) return (
    <div style={{ textAlign: "center", padding: "60px 0", color: "var(--dim)" }}>
      <div style={{ fontSize: 13 }}>{graph.error}</div>
      {graph.error.includes("umap-learn") && <code style={{ fontSize: 11 }}>pip install umap-learn scikit-learn</code>}
    </div>
  );
  if (nodes.length === 0) return (
    <div style={{ textAlign: "center", padding: "60px 0", color: "var(--dim)" }}>
      <div style={{ fontSize: 13 }}>Not enough memories for ontology visualization.</div>
      <div style={{ fontSize: 11, marginTop: 6 }}>Run at least 5 tasks to populate this graph.</div>
    </div>
  );

  const visibleNodes = nodes.filter((n) => !hiddenClusters.has(n.cluster));
  const hoveredNode  = nodes.find((n) => n.id === hoveredId) ?? null;

  return (
    <div>
      {/* ── Toolbar ── */}
      <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 10 }}>
        <button title="Pan / Zoom" onClick={() => setMode("pan")} style={graphToolBtn(mode === "pan")}>
          <Hand size={12} /> Pan
        </button>
        <button title="Draw a box to select nodes" onClick={() => { setMode("select"); setBrushedIds(null); }} style={graphToolBtn(mode === "select")}>
          <Crosshair size={12} /> Select
        </button>
        <div style={{ width: 1, height: 14, background: "var(--border)", margin: "0 2px" }} />
        <button title="Fit all nodes" onClick={resetZoom} style={graphToolBtn(false)}>
          <Maximize2 size={12} /> Fit
        </button>
        {brushedIds && brushedIds.size > 0 && (
          <>
            <button onClick={zoomToSelection} style={graphToolBtn(false, "var(--accent)")}>
              <ZoomIn size={12} /> Zoom to {brushedIds.size}
            </button>
            <button onClick={() => setBrushedIds(null)} style={graphToolBtn(false, "#ef4444")}>
              <X size={12} />
            </button>
          </>
        )}
        <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--dim)", fontFamily: "var(--font-mono)" }}>
          {zoomPct}%
        </span>
      </div>

      {/* ── Cluster legend — click to toggle ── */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12, alignItems: "center" }}>
        {clusters.map((c) => {
          const hidden = hiddenClusters.has(c.id);
          return (
            <button key={c.id} onClick={() => toggleCluster(c.id)} style={{
              display: "flex", alignItems: "center", gap: 4, fontSize: 11,
              border: "1px solid " + (hidden ? "transparent" : c.color + "44"),
              cursor: "pointer", padding: "2px 8px", borderRadius: 10,
              background: hidden ? "rgba(255,255,255,0.03)" : c.color + "18",
              color: hidden ? "var(--dim)" : c.color,
              opacity: hidden ? 0.45 : 1, transition: "opacity 0.15s",
            }}>
              <div style={{ width: 6, height: 6, borderRadius: "50%", background: hidden ? "var(--dim)" : c.color }} />
              {c.label}
            </button>
          );
        })}
        {hiddenClusters.size > 0 && (
          <button onClick={() => setHiddenClusters(new Set())} style={{
            fontSize: 10, border: "none", cursor: "pointer",
            padding: "2px 6px", borderRadius: 6, background: "none", color: "var(--dim)",
          }}>show all</button>
        )}
      </div>

      <div style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>
        {/* ── SVG canvas ── */}
        <div style={{ position: "relative", borderRadius: 12, overflow: "hidden", flexShrink: 0, background: "var(--surface2)", border: "1px solid var(--border)" }}>
          <svg
            ref={svgRef}
            width={W} height={H}
            style={{ display: "block", cursor: mode === "select" ? "crosshair" : "grab" }}
          >
            {/* Nodes — inside zoom transform group */}
            <g ref={gMainRef}>
              {visibleNodes.map((n) => {
                const { x, y } = toSvg(n);
                const color   = CLUSTER_COLORS[n.cluster % CLUSTER_COLORS.length];
                const isHov   = n.id === hoveredId;
                const isSel   = n.id === selectedId;
                const isBrush = brushedIds?.has(n.id) ?? false;
                const r       = 5 + Math.max(0, n.quality) * 1.5;
                const fOpacity = brushedIds
                  ? (isBrush ? 1 : 0.12)
                  : (isHov || isSel ? 0.92 : 0.65);
                return (
                  <g key={n.id} style={{ cursor: "pointer" }}
                    onMouseEnter={(e) => {
                      setHoveredId(n.id);
                      const rect = svgRef.current!.getBoundingClientRect();
                      setTooltip({ x: e.clientX - rect.left + 14, y: e.clientY - rect.top - 8, node: n });
                    }}
                    onMouseMove={(e) => {
                      const rect = svgRef.current!.getBoundingClientRect();
                      setTooltip((t) => t ? { ...t, x: e.clientX - rect.left + 14, y: e.clientY - rect.top - 8 } : null);
                    }}
                    onMouseLeave={() => { setHoveredId(null); setTooltip(null); }}
                    onClick={(e) => { e.stopPropagation(); setSelectedId(n.id === selectedId ? null : n.id); }}
                  >
                    <circle
                      cx={x} cy={y}
                      r={isSel ? r + 3 : r}
                      fill={color}
                      fillOpacity={fOpacity}
                      stroke={isSel ? "#fff" : isBrush ? color : "none"}
                      strokeWidth={isSel ? 2 : isBrush ? 1.5 : 0}
                      style={{ transition: "fill-opacity 0.12s, r 0.1s" }}
                    />
                    {(isHov || isSel) && (
                      <text x={x} y={y - r - 5} textAnchor="middle" fill="var(--text)"
                        fontSize={9} style={{ pointerEvents: "none", userSelect: "none" }}>
                        {n.label.length > 32 ? n.label.slice(0, 31) + "…" : n.label}
                      </text>
                    )}
                  </g>
                );
              })}
            </g>

            {/* Brush overlay — outside zoom group, screen-space coords */}
            <g ref={gBrushRef} style={{ pointerEvents: mode === "select" ? "all" : "none" }} />
          </svg>

          {/* Floating tooltip */}
          {tooltip && !selectedId && (
            <div style={{
              position: "absolute", left: tooltip.x, top: tooltip.y,
              pointerEvents: "none", zIndex: 20,
              background: "var(--surface)", border: "1px solid rgba(100,200,180,0.25)",
              borderRadius: 8, padding: "8px 12px", fontSize: 11, maxWidth: 210,
              boxShadow: "0 4px 18px rgba(0,0,0,0.45)",
            }}>
              <div style={{ fontWeight: 600, marginBottom: 3 }}>{tooltip.node.label}</div>
              <div style={{ color: "var(--dim)", display: "flex", gap: 8 }}>
                {tooltip.node.task_type && <span>{tooltip.node.task_type}</span>}
                <span>q: {tooltip.node.quality > 0 ? "+" : ""}{tooltip.node.quality}</span>
              </div>
              <div style={{ fontSize: 9, color: "var(--dim)", marginTop: 4, letterSpacing: "0.5px" }}>
                CLICK TO OPEN
              </div>
            </div>
          )}

          <div style={{ position: "absolute", bottom: 8, right: 10, fontSize: 9, color: "var(--dim)", userSelect: "none", letterSpacing: "0.4px" }}>
            {mode === "pan" ? "SCROLL → ZOOM · DRAG → PAN" : "DRAG → SELECT NODES"}
          </div>
        </div>

        {/* ── Right panel ── */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {selectedId ? (
            <DetailPane memId={selectedId} onDeleted={() => setSelectedId(null)} />
          ) : brushedIds && brushedIds.size > 0 ? (
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--accent)", marginBottom: 10, letterSpacing: "0.5px" }}>
                {brushedIds.size} NODE{brushedIds.size !== 1 ? "S" : ""} SELECTED
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 3, maxHeight: 420, overflowY: "auto" }}>
                {nodes.filter((n) => brushedIds.has(n.id)).map((n) => (
                  <button key={n.id} onClick={() => setSelectedId(n.id)} style={{
                    textAlign: "left", border: "1px solid var(--border)", cursor: "pointer",
                    padding: "7px 10px", borderRadius: 7, fontSize: 11,
                    background: "var(--surface2)", color: "var(--text)",
                    display: "flex", alignItems: "center", gap: 8,
                    transition: "background 0.1s",
                  }}>
                    <div style={{ width: 7, height: 7, borderRadius: "50%", flexShrink: 0, background: CLUSTER_COLORS[n.cluster % CLUSTER_COLORS.length] }} />
                    <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{n.label}</span>
                    <QualityBadge q={n.quality} />
                  </button>
                ))}
              </div>
            </div>
          ) : hoveredNode ? (
            <div style={{ padding: "4px 0" }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>{hoveredNode.label}</div>
              <div style={{ fontSize: 11, color: "var(--dim)", display: "flex", gap: 8, alignItems: "center" }}>
                {hoveredNode.task_type && <span>{hoveredNode.task_type}</span>}
                <QualityBadge q={hoveredNode.quality} />
              </div>
              <div style={{ fontSize: 10, color: "var(--dim)", marginTop: 8, letterSpacing: "0.4px" }}>CLICK NODE TO OPEN</div>
            </div>
          ) : (
            <div style={{ paddingTop: 40, color: "var(--dim)", fontSize: 12 }}>
              <div>Pan: drag or scroll</div>
              <div style={{ marginTop: 6 }}>Select: switch mode, drag a box</div>
              <div style={{ marginTop: 6 }}>Click cluster labels to hide/show</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function graphToolBtn(active: boolean, color?: string): React.CSSProperties {
  return {
    display: "inline-flex", alignItems: "center", gap: 4,
    fontSize: 11, padding: "4px 10px", borderRadius: 6, cursor: "pointer",
    border: "1px solid " + (active ? "var(--accent)" : "var(--border)"),
    background: active ? "rgba(100,200,180,0.1)" : "transparent",
    color: color ?? (active ? "var(--accent)" : "var(--dim)"),
    fontWeight: active ? 600 : 400, fontFamily: "var(--font-mono)",
    transition: "all 0.12s",
  };
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
    display: "inline-flex", alignItems: "center", gap: 5,
  };
}

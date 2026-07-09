import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Brain, Search } from "lucide-react";
import { api } from "@/api/client";
import type { ResearchHistoryItem } from "@/types";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SOURCE_LABELS: Record<string, string> = {
  search:   "search",
  research: "research",
  browser:  "browser",
};

const SOURCE_COLORS: Record<string, string> = {
  search:   "#6366f1",
  research: "#0ea5e9",
  browser:  "#10b981",
};

const TIME_OPTIONS = [
  { label: "Today",     since: () => startOfToday() },
  { label: "Yesterday", since: () => startOfToday() - 86400 },
  { label: "7 days",    since: () => Date.now() / 1000 - 86400 * 7 },
  { label: "All",       since: () => 0 },
];

function startOfToday(): number {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d.getTime() / 1000;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SourceBadge({ source }: { source: string }) {
  const color = SOURCE_COLORS[source] ?? "#888";
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, padding: "1px 6px", borderRadius: 4,
      background: color + "22", color, textTransform: "uppercase", letterSpacing: "0.05em",
      fontFamily: "var(--font-mono, monospace)",
    }}>
      {SOURCE_LABELS[source] ?? source}
    </span>
  );
}

function SimBar({ sim }: { sim: number }) {
  const pct = Math.round(sim * 100);
  const color = pct >= 80 ? "#10b981" : pct >= 50 ? "#f59e0b" : "#6b7280";
  return (
    <span style={{ display: "flex", alignItems: "center", gap: 4, minWidth: 56 }}>
      <span style={{
        height: 4, width: 40, borderRadius: 2,
        background: "var(--border, #333)", overflow: "hidden", display: "inline-block",
      }}>
        <span style={{ display: "block", height: "100%", width: `${pct}%`, background: color, borderRadius: 2 }} />
      </span>
      <span style={{ fontSize: 10, color: "var(--dim)", fontFamily: "var(--font-mono, monospace)" }}>
        {pct}
      </span>
    </span>
  );
}

function HistoryRow({
  item,
  checked,
  onCheck,
  onViewMemory,
}: {
  item:        ResearchHistoryItem;
  checked:     boolean;
  onCheck:     (id: string, v: boolean) => void;
  onViewMemory: (id: number) => void;
}) {
  const canIngest = item.source === "browser" && !item.in_memory;
  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 10, padding: "9px 12px",
      borderRadius: 8, borderBottom: "1px solid var(--border, #1e1e2e)",
      background: checked ? "var(--accent-faint, rgba(99,102,241,0.08))" : "transparent",
    }}>
      {canIngest && (
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onCheck(item.id, e.target.checked)}
          style={{ marginTop: 2, flexShrink: 0, accentColor: "#6366f1" }}
        />
      )}
      {!canIngest && <div style={{ width: 16, flexShrink: 0 }} />}

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <SourceBadge source={item.source} />
          <span style={{
            fontSize: 12, fontWeight: 600,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            maxWidth: 420,
          }}>
            {item.title}
          </span>
          {item.in_memory && item.memory_id != null && (
            <button
              onClick={() => onViewMemory(item.memory_id!)}
              title="View in Memory"
              style={{
                display: "flex", alignItems: "center", gap: 3,
                background: "#10b98122", color: "#10b981",
                border: "none", borderRadius: 4, padding: "1px 6px",
                fontSize: 10, fontWeight: 600, cursor: "pointer",
              }}
            >
              <Brain size={10} /> in memory
            </button>
          )}
          {item.url && (
            <a
              href={item.url}
              target="_blank"
              rel="noreferrer"
              style={{ color: "var(--dim)", display: "flex", alignItems: "center" }}
            >
              <ExternalLink size={11} />
            </a>
          )}
        </div>
        {item.snippet && (
          <div style={{ fontSize: 11, color: "var(--dim)", marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {item.snippet}
          </div>
        )}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        <SimBar sim={item.similarity} />
        <span style={{ fontSize: 10, color: "var(--dim)", whiteSpace: "nowrap" }}>
          {item.timestamp ? item.timestamp.slice(0, 16).replace("T", " ") : ""}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------

export function ResearchHistory() {
  const qc = useQueryClient();

  const [q, setQ]                     = useState("");
  const [debouncedQ, setDebouncedQ]   = useState("");
  const [source, setSource]           = useState("all");
  const [timeIdx, setTimeIdx]         = useState(3);
  const [selected, setSelected]       = useState<Set<string>>(new Set());
  const [ingestLog, setIngestLog]     = useState<string[]>([]);

  const since = TIME_OPTIONS[timeIdx].since();

  const { data: items = [], isFetching } = useQuery({
    queryKey: ["research-history", debouncedQ, since, source],
    queryFn:  () => api.research_history({ q: debouncedQ, since, source, limit: 100 }),
    staleTime: 30_000,
  });

  const ingestMut = useMutation({
    mutationFn: (urls: string[]) => api.research_history_ingest(urls),
    onSuccess: (data) => {
      const lines = data.results.map(
        (r) => `${r.status.padEnd(14)} ${r.url.slice(0, 70)}`
      );
      setIngestLog(lines);
      setSelected(new Set());
      qc.invalidateQueries({ queryKey: ["research-history"] });
      qc.invalidateQueries({ queryKey: ["memories"] });
    },
  });

  const handleSearch = (v: string) => {
    setQ(v);
    clearTimeout((handleSearch as any)._t);
    (handleSearch as any)._t = setTimeout(() => setDebouncedQ(v), 350);
  };

  const toggleSelect = (id: string, v: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      v ? next.add(id) : next.delete(id);
      return next;
    });
  };

  const browserUrls = useMemo(
    () => items.filter((i) => i.source === "browser" && !i.in_memory).map((i) => i.id),
    [items]
  );

  const allBrowserChecked = browserUrls.length > 0 && browserUrls.every((id) => selected.has(id));

  const toggleAllBrowser = () => {
    if (allBrowserChecked) {
      setSelected((prev) => {
        const next = new Set(prev);
        browserUrls.forEach((id) => next.delete(id));
        return next;
      });
    } else {
      setSelected((prev) => {
        const next = new Set(prev);
        browserUrls.forEach((id) => next.add(id));
        return next;
      });
    }
  };

  const selectedUrls = items
    .filter((i) => selected.has(i.id) && i.url)
    .map((i) => i.url as string);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", padding: "20px 24px", gap: 16 }}>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Search size={18} style={{ color: "var(--accent, #6366f1)" }} />
        <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Research History</h2>
        {isFetching && (
          <span style={{ fontSize: 11, color: "var(--dim)", marginLeft: 6 }}>loading...</span>
        )}
      </div>

      {/* Toolbar */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
        <input
          value={q}
          onChange={(e) => handleSearch(e.target.value)}
          placeholder="Search across searches, research, and browser history..."
          style={{
            flex: 1, minWidth: 240, padding: "6px 10px", borderRadius: 6,
            background: "var(--surface, #1e1e2e)", border: "1px solid var(--border, #333)",
            color: "inherit", fontSize: 13, outline: "none",
          }}
        />

        {/* Source filter */}
        <div style={{ display: "flex", borderRadius: 6, overflow: "hidden", border: "1px solid var(--border, #333)" }}>
          {(["all", "search", "research", "browser"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setSource(s)}
              style={{
                padding: "5px 10px", fontSize: 12, border: "none", cursor: "pointer",
                background: source === s ? "var(--accent, #6366f1)" : "var(--surface, #1e1e2e)",
                color: source === s ? "#fff" : "var(--dim)",
                fontWeight: source === s ? 700 : 400,
              }}
            >
              {s === "all" ? "All" : SOURCE_LABELS[s]}
            </button>
          ))}
        </div>

        {/* Time filter */}
        <div style={{ display: "flex", borderRadius: 6, overflow: "hidden", border: "1px solid var(--border, #333)" }}>
          {TIME_OPTIONS.map((opt, i) => (
            <button
              key={opt.label}
              onClick={() => setTimeIdx(i)}
              style={{
                padding: "5px 10px", fontSize: 12, border: "none", cursor: "pointer",
                background: timeIdx === i ? "#334155" : "var(--surface, #1e1e2e)",
                color: timeIdx === i ? "#e2e8f0" : "var(--dim)",
                fontWeight: timeIdx === i ? 700 : 400,
              }}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Results */}
      <div style={{
        flex: 1, overflowY: "auto", borderRadius: 8,
        border: "1px solid var(--border, #1e1e2e)",
        background: "var(--surface, #13131f)",
      }}>
        {items.length === 0 && !isFetching && (
          <div style={{ padding: 32, textAlign: "center", color: "var(--dim)", fontSize: 13 }}>
            No results. Try a different query or time range.
          </div>
        )}
        {items.map((item) => (
          <HistoryRow
            key={`${item.source}:${item.id}`}
            item={item}
            checked={selected.has(item.id)}
            onCheck={toggleSelect}
            onViewMemory={() => {}}
          />
        ))}
      </div>

      {/* Footer action bar */}
      {(selected.size > 0 || ingestLog.length > 0) && (
        <div style={{
          padding: "12px 16px", borderRadius: 8,
          border: "1px solid var(--border, #333)",
          background: "var(--surface, #1e1e2e)",
          display: "flex", flexDirection: "column", gap: 8,
        }}>
          {selected.size > 0 && (
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              {browserUrls.length > 1 && (
                <button
                  onClick={toggleAllBrowser}
                  style={{
                    fontSize: 12, padding: "4px 10px", borderRadius: 6, cursor: "pointer",
                    background: "transparent", border: "1px solid var(--border, #333)", color: "var(--dim)",
                  }}
                >
                  {allBrowserChecked ? "Deselect all" : "Select all browser"}
                </button>
              )}
              <span style={{ fontSize: 12, color: "var(--dim)", flex: 1 }}>
                {selected.size} URL{selected.size !== 1 ? "s" : ""} selected
              </span>
              <button
                onClick={() => ingestMut.mutate(selectedUrls)}
                disabled={ingestMut.isPending || selectedUrls.length === 0}
                style={{
                  padding: "6px 16px", borderRadius: 6, fontWeight: 700, fontSize: 13,
                  background: ingestMut.isPending ? "#334155" : "#6366f1",
                  color: "#fff", border: "none", cursor: ingestMut.isPending ? "not-allowed" : "pointer",
                }}
              >
                {ingestMut.isPending ? "Ingesting..." : `Ingest ${selectedUrls.length} URL${selectedUrls.length !== 1 ? "s" : ""}`}
              </button>
            </div>
          )}
          {ingestLog.length > 0 && (
            <div style={{
              fontFamily: "var(--font-mono, monospace)", fontSize: 11,
              color: "var(--dim)", maxHeight: 120, overflowY: "auto",
            }}>
              {ingestLog.map((line, i) => (
                <div key={i}>{line}</div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

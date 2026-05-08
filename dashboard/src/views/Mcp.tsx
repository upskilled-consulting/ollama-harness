import { useMcpLog, useMcpTools } from "@/hooks/useRuns";
import type { McpLogEntry, McpTool } from "@/types";

const EVENT_CLASS: Record<string, string> = {
  start: "mcp-event-start",
  done:  "mcp-event-done",
  fail:  "mcp-event-fail",
  line:  "mcp-event-line",
};

function McpRow({ entry }: { entry: McpLogEntry }) {
  return (
    <div className="mcp-entry">
      <span className="mcp-ts">{entry.ts?.slice(11, 19) ?? ""}</span>
      <span className="mcp-label" title={entry.label}>{entry.label}</span>
      <span className={EVENT_CLASS[entry.event] ?? "dim"}>{entry.event}</span>
      <span className="mcp-text" title={entry.text}>{entry.text}</span>
    </div>
  );
}

function ParamBadge({ name, required }: { name: string; required: boolean }) {
  return (
    <span
      className="mono"
      style={{
        fontSize: 11,
        padding: "2px 6px",
        borderRadius: 4,
        background: required ? "var(--accent-faint, rgba(99,102,241,0.12))" : "var(--surface2, rgba(255,255,255,0.06))",
        color: required ? "var(--accent, #818cf8)" : "var(--dim)",
        marginRight: 4,
      }}
      title={required ? "required" : "optional"}
    >
      {name}
    </span>
  );
}

function ToolCard({ tool }: { tool: McpTool }) {
  return (
    <div className="card" style={{ marginBottom: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6, flexWrap: "wrap" }}>
        <span className="mono" style={{ fontWeight: 600, fontSize: 13 }}>{tool.name}</span>
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {tool.parameters.map((p) => (
            <ParamBadge key={p.name} name={p.name} required={p.required} />
          ))}
        </div>
      </div>
      <p style={{ margin: 0, fontSize: 12, color: "var(--dim)", lineHeight: 1.5 }}>
        {tool.description}
      </p>
    </div>
  );
}

export function Mcp() {
  const { data: tools, isLoading: toolsLoading, error: toolsError } = useMcpTools();
  const { data, isLoading, error } = useMcpLog();

  const entries = data ?? [];

  return (
    <div>
      <div className="view-header">
        <h1>MCP</h1>
        <p>Registered tools · task execution log</p>
      </div>

      <div style={{ marginBottom: 28 }}>
        <div className="section-title" style={{ marginBottom: 10 }}>
          Tools ({toolsLoading ? "…" : (tools?.length ?? 0)})
        </div>
        {toolsLoading
          ? <div className="loading">Loading tools…</div>
          : toolsError
            ? <div className="page-error">Could not load tool manifest — is the server running? ({String(toolsError)})</div>
            : (tools ?? []).map((t) => <ToolCard key={t.name} tool={t} />)
        }
      </div>

      <div className="section-title" style={{ marginBottom: 10 }}>
        Task log · auto-refreshes every 5s
      </div>
      {isLoading
        ? <div className="loading">Loading…</div>
        : error
          ? <div className="page-error">Could not load MCP log. Is the server running?</div>
          : (
            <div className="mcp-log">
              <div className="mcp-log-header">{entries.length} entries</div>
              <div className="mcp-log-body">
                {entries.length === 0
                  ? <span style={{ color: "var(--dim)" }}>No MCP tasks logged yet.</span>
                  : entries.map((e, i) => <McpRow key={i} entry={e} />)
                }
              </div>
            </div>
          )
      }
    </div>
  );
}

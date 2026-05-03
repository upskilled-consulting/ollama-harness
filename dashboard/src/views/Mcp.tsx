import { useMcpLog } from "@/hooks/useRuns";
import type { McpLogEntry } from "@/types";

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

export function Mcp() {
  const { data, isLoading, error } = useMcpLog();

  if (isLoading) return <div className="loading">Loading…</div>;
  if (error)     return <div className="page-error">Could not load MCP log. Is the server running?</div>;

  const entries = data ?? [];

  return (
    <div>
      <div className="view-header">
        <h1>MCP</h1>
        <p>Parallel task execution log · auto-refreshes every 5s</p>
      </div>

      <div className="mcp-log">
        <div className="mcp-log-header">{entries.length} entries</div>
        <div className="mcp-log-body">
          {entries.length === 0
            ? <span style={{ color: "var(--dim)" }}>No MCP tasks logged yet.</span>
            : entries.map((e, i) => <McpRow key={i} entry={e} />)
          }
        </div>
      </div>
    </div>
  );
}

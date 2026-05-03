import { useState } from "react";
import { useArtifacts, useArtifactContent } from "@/hooks/useRuns";
import { MdView } from "@/components/MdView";
import type { Artifact } from "@/types";

function basename(path: string): string {
  return path.replace(/\\/g, "/").split("/").pop() ?? path;
}

function ext(path: string): string {
  const b = basename(path);
  const dot = b.lastIndexOf(".");
  return dot >= 0 ? b.slice(dot + 1).toLowerCase() : "";
}

function fmt(iso?: string): string {
  if (!iso) return "—";
  return iso.slice(0, 16).replace("T", " ");
}

function size(bytes?: number): string {
  if (bytes == null) return "—";
  if (bytes < 1024)  return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

const EXT_COLORS: Record<string, string> = {
  md:   "#818cf8",
  json: "#fb923c",
  csv:  "#34d399",
  txt:  "#94a3b8",
  py:   "#f59e0b",
  html: "#22d3ee",
};

const TEXT_EXTS = new Set(["md", "txt", "py", "json", "csv", "html", "js", "ts", "yaml", "toml"]);

function ArtifactPreview({ artifactId, fileExt }: { artifactId: string; fileExt: string }) {
  const { data, isLoading, error } = useArtifactContent(artifactId);

  if (isLoading) return (
    <div style={{ padding: "12px 16px", color: "var(--dim)", fontSize: 12 }}>Loading preview…</div>
  );
  if (error) return (
    <div style={{ padding: "12px 16px", color: "var(--fail)", fontSize: 12 }}>File not found on disk.</div>
  );
  if (!data) return null;

  return (
    <div style={{ padding: "8px 16px 16px" }}>
      <div style={{ fontSize: 11, color: "var(--dim)", marginBottom: 8, fontFamily: "var(--font-mono)", wordBreak: "break-all" }}>
        {data.path}
        {data.truncated && (
          <span style={{ marginLeft: 8, color: "var(--warn)" }}>
            (preview truncated — {size(data.bytes)} total)
          </span>
        )}
      </div>
      <div style={{
        background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 6,
        padding: "12px 14px", maxHeight: 420, overflowY: "auto",
        fontSize: 12, lineHeight: 1.6,
      }}>
        {fileExt === "md" ? (
          <MdView content={data.content} />
        ) : (
          <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word", fontFamily: "var(--font-mono)", color: "var(--text)" }}>
            {data.content}
          </pre>
        )}
      </div>
    </div>
  );
}

function ArtifactRow({ a }: { a: Artifact }) {
  const [expanded, setExpanded] = useState(false);
  const file     = basename(a.path);
  const fext     = ext(a.path);
  const color    = EXT_COLORS[fext] ?? "var(--dim)";
  const canPreview = TEXT_EXTS.has(fext);

  return (
    <>
      <tr
        style={{ cursor: canPreview ? "pointer" : "default" }}
        onClick={() => canPreview && setExpanded((x) => !x)}
      >
        <td>
          <span style={{ color, fontWeight: 600, fontFamily: "var(--font-mono)", fontSize: 12 }}>
            {file}
          </span>
        </td>
        <td><span className="badge">{a.type}</span></td>
        <td className="mono" style={{ textAlign: "right" }}>{size(a.bytes)}</td>
        <td className="mono" style={{ textAlign: "right" }}>{a.lines ?? "—"}</td>
        <td className="mono dim">{fmt(a.created_at)}</td>
        <td className="mono dim" title={a.run_id}>{a.run_id?.slice(-8) ?? "—"}</td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={6} style={{ padding: 0, background: "var(--surface-2, #12151f)" }}>
            <ArtifactPreview artifactId={a.artifact_id} fileExt={fext} />
          </td>
        </tr>
      )}
    </>
  );
}

export function Artifacts() {
  const { data, isLoading, error } = useArtifacts();
  const [filter, setFilter] = useState("");

  if (isLoading) return <div className="loading">Loading…</div>;
  if (error)     return <div className="page-error">Could not load artifacts.</div>;

  const artifacts = (data ?? []).filter((a) =>
    !filter || basename(a.path).toLowerCase().includes(filter.toLowerCase())
  );

  const totalBytes = (data ?? []).reduce((acc, a) => acc + (a.bytes ?? 0), 0);
  const byType: Record<string, number> = {};
  for (const a of data ?? []) byType[a.type] = (byType[a.type] ?? 0) + 1;

  return (
    <div>
      <div className="view-header">
        <h1>Artifacts</h1>
        <p>{(data ?? []).length} output files · {(totalBytes / 1024).toFixed(0)} KB total · click a text file to preview</p>
      </div>

      <div className="kpi-row" style={{ marginBottom: 24 }}>
        {Object.entries(byType).map(([type, count]) => (
          <div key={type} className="kpi-card">
            <div className="kpi-label">{type}</div>
            <div className="kpi-value">{count}</div>
          </div>
        ))}
      </div>

      <div style={{ marginBottom: 12 }}>
        <input
          className="task-input"
          style={{ maxWidth: 320 }}
          placeholder="Filter by filename…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>

      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        <table className="runs-table" style={{ width: "100%" }}>
          <thead>
            <tr>
              <th>File</th>
              <th>Type</th>
              <th style={{ textAlign: "right" }}>Size</th>
              <th style={{ textAlign: "right" }}>Lines</th>
              <th>Created</th>
              <th>Run</th>
            </tr>
          </thead>
          <tbody>
            {artifacts.length === 0
              ? <tr><td colSpan={6} style={{ color: "var(--dim)", textAlign: "center", padding: 32 }}>No artifacts found.</td></tr>
              : artifacts.map((a) => <ArtifactRow key={a.artifact_id} a={a} />)
            }
          </tbody>
        </table>
      </div>
    </div>
  );
}

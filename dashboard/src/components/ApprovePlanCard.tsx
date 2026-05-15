import { useState } from "react";
import { Brain } from "lucide-react";
import { api } from "@/api/client";

export function ApprovePlanCard({
  itemId,
  initialQueries,
  onApproved,
}: {
  itemId: string;
  initialQueries: string[];
  onApproved: () => void;
}) {
  const [text, setText]   = useState(initialQueries.join("\n"));
  const [busy, setBusy]   = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleApprove = async () => {
    setBusy(true);
    setError(null);
    try {
      const queries = text.split("\n").map((q) => q.trim()).filter(Boolean);
      await api.approve_plan(itemId, queries);
      onApproved();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="event-card" style={{
      borderLeft: "3px solid var(--accent, #6366f1)",
      background: "var(--bg-surface)",
      marginBottom: 8,
    }}>
      <div className="event-header" style={{ marginBottom: 8 }}>
        <span className="pulse-dot" />
        <Brain size={13} />
        <span style={{ fontWeight: 600 }}>Waiting for plan approval…</span>
      </div>
      <p style={{ fontSize: 11, color: "var(--dim)", margin: "0 0 6px" }}>
        Edit queries below (one per line), then approve to continue.
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={Math.max(3, initialQueries.length + 1)}
        style={{
          width: "100%",
          fontSize: 12,
          fontFamily: "var(--font-mono, monospace)",
          background: "var(--bg)",
          color: "var(--fg)",
          border: "1px solid var(--border)",
          borderRadius: 4,
          padding: "6px 8px",
          resize: "vertical",
          boxSizing: "border-box",
        }}
      />
      {error && <p style={{ color: "var(--error)", fontSize: 11, margin: "4px 0 0" }}>{error}</p>}
      <div style={{ marginTop: 8 }}>
        <button
          className="btn btn-primary"
          onClick={() => void handleApprove()}
          disabled={busy}
          style={{ padding: "4px 14px", fontSize: 12 }}
        >
          {busy ? "Approving…" : "Approve"}
        </button>
      </div>
    </div>
  );
}

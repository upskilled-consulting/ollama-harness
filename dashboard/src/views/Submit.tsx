import { useEffect, useRef, useState } from "react";
import { Play, Square, Search, Brain, Zap, Database } from "lucide-react";
import { clsx } from "clsx";
import { useCancelTask, useQueue, useRuns, useSubmitTask } from "@/hooks/useRuns";
import { MdView } from "@/components/MdView";
import { ApprovePlanCard } from "@/components/ApprovePlanCard";
import type { RunRecord } from "@/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type EventLine =
  | { kind: "log";       text: string }
  | { kind: "memory";    hits: number; titles: string[] }
  | { kind: "plan";      queries: string[]; complexity: string; task_type: string; notes?: string }
  | { kind: "plan_gate"; queries: string[] }
  | { kind: "search";    round: number; query: string; hits: number }
  | { kind: "synth";     stage: string; tokens_in?: number }
  | { kind: "wiggum";    round: number; score: number; passed: boolean };

function parseLine(raw: string): EventLine {
  if (raw.startsWith("[EVENT]")) {
    try {
      const ev = JSON.parse(raw.slice(7)) as { type: string; data: Record<string, unknown> };
      if (ev.type === "memory") {
        return {
          kind:   "memory",
          hits:   (ev.data.hits   as number)   ?? 0,
          titles: (ev.data.titles as string[]) ?? [],
        };
      }
      if (ev.type === "plan") {
        return {
          kind: "plan",
          queries:   (ev.data.queries   as string[]) ?? [],
          complexity:(ev.data.complexity as string)  ?? "",
          task_type: (ev.data.task_type  as string)  ?? "",
          notes:     ev.data.notes as string | undefined,
        };
      }
      if (ev.type === "search") {
        return {
          kind: "search",
          round: (ev.data.round as number) ?? 0,
          query: (ev.data.query as string) ?? "",
          hits:  (ev.data.hits  as number) ?? 0,
        };
      }
      if (ev.type === "synth") {
        return {
          kind: "synth",
          stage:     (ev.data.stage     as string)  ?? "",
          tokens_in: ev.data.tokens_in as number | undefined,
        };
      }
      if (ev.type === "wiggum") {
        return {
          kind: "wiggum",
          round:  (ev.data.round  as number)  ?? 0,
          score:  (ev.data.score  as number)  ?? 0,
          passed: (ev.data.passed as boolean) ?? false,
        };
      }
      if (ev.type === "plan_gate") {
        return { kind: "plan_gate", queries: (ev.data.queries as string[]) ?? [] };
      }
    } catch { /* fall through */ }
  }
  return { kind: "log", text: raw };
}

// ---------------------------------------------------------------------------
// Event card renderers
// ---------------------------------------------------------------------------

function MemoryCard({ e }: { e: Extract<EventLine, { kind: "memory" }> }) {
  return (
    <div className="event-card event-memory">
      <div className="event-header">
        <Database size={13} />
        <span>{e.hits > 0 ? `Memory: ${e.hits} hit${e.hits > 1 ? "s" : ""}` : "Memory: no history"}</span>
      </div>
      {e.titles.length > 0 && (
        <ul className="event-list">
          {e.titles.map((t, i) => <li key={i}>{t}</li>)}
        </ul>
      )}
    </div>
  );
}

function PlanCard({ e }: { e: Extract<EventLine, { kind: "plan" }> }) {
  return (
    <div className="event-card event-plan">
      <div className="event-header">
        <Brain size={13} />
        <span>Plan</span>
        {e.task_type && <span className="badge">{e.task_type}</span>}
        {e.complexity && <span className="badge dim">{e.complexity}</span>}
      </div>
      {e.queries.length > 0 && (
        <ul className="event-list">
          {e.queries.map((q, i) => <li key={i}>{q}</li>)}
        </ul>
      )}
      {e.notes && <p className="event-notes">{e.notes}</p>}
    </div>
  );
}

function SearchCard({ e }: { e: Extract<EventLine, { kind: "search" }> }) {
  return (
    <div className="event-card event-search">
      <div className="event-header">
        <Search size={13} />
        <span>Round {e.round}</span>
        <span className="dim" style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {e.query}
        </span>
        <span className="mono dim" style={{ fontSize: 11 }}>{e.hits} hits</span>
      </div>
    </div>
  );
}

function SynthCard({ e }: { e: Extract<EventLine, { kind: "synth" }> }) {
  return (
    <div className="event-card event-synth">
      <div className="event-header">
        <Zap size={13} />
        <span>Synthesis {e.stage === "start" ? "started" : "done"}</span>
        {e.tokens_in != null && (
          <span className="mono dim" style={{ fontSize: 11 }}>{e.tokens_in.toLocaleString()} ctx tokens</span>
        )}
      </div>
    </div>
  );
}

function WiggumCard({ e }: { e: Extract<EventLine, { kind: "wiggum" }> }) {
  const pct = Math.min(100, (e.score / 10) * 100);
  return (
    <div className="event-card event-wiggum">
      <div className="event-header">
        <span className={clsx("badge", e.passed ? "pass" : "error")}>
          Wiggum {e.passed ? "PASS" : "FAIL"}
        </span>
        <span className="mono" style={{ fontSize: 13, fontWeight: 600 }}>
          {e.score.toFixed(1)}
        </span>
        <span className="dim" style={{ fontSize: 11 }}>round {e.round}</span>
      </div>
      <div style={{ marginTop: 4, height: 4, background: "var(--bg-surface)", borderRadius: 2, overflow: "hidden" }}>
        <div style={{
          height: "100%", width: `${pct}%`,
          background: e.passed ? "var(--pass, #34d399)" : "var(--error, #f87171)",
          borderRadius: 2, transition: "width 0.4s",
        }} />
      </div>
    </div>
  );
}

function EventCard({ e }: { e: EventLine }) {
  if (e.kind === "memory") return <MemoryCard  e={e} />;
  if (e.kind === "plan")   return <PlanCard    e={e} />;
  if (e.kind === "search") return <SearchCard  e={e} />;
  if (e.kind === "synth")  return <SynthCard   e={e} />;
  if (e.kind === "wiggum") return <WiggumCard  e={e} />;
  return null; // log lines go into the pre block below
}

// ---------------------------------------------------------------------------
// Live log panel
// ---------------------------------------------------------------------------

function LiveLog({ itemId, onDone, onPlanGate }: {
  itemId: string;
  onDone: () => void;
  onPlanGate?: (queries: string[]) => void;
}) {
  const [events, setEvents]     = useState<EventLine[]>([]);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [done, setDone]         = useState(false);
  const logRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    const es = new EventSource(`/api/tasks/${itemId}/stream`);
    es.onmessage = (msg) => {
      const raw = msg.data as string;
      if (raw === "[DONE]") {
        setDone(true);
        es.close();
        onDone();
        return;
      }
      const parsed = parseLine(raw);
      if (parsed.kind === "plan_gate") {
        onPlanGate?.(parsed.queries);
        return; // don't push into event list — parent handles it
      }
      if (parsed.kind === "log") {
        setLogLines((prev) => [...prev, parsed.text]);
      } else {
        setEvents((prev) => [...prev, parsed]);
      }
    };
    es.onerror = () => { es.close(); setDone(true); onDone(); };
    return () => es.close();
  }, [itemId, onDone, onPlanGate]);

  // Auto-scroll log
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [logLines]);

  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        {!done && <span className="pulse-dot" />}
        <span className="section-title" style={{ margin: 0 }}>
          {done ? "Completed" : "Running"}
        </span>
      </div>

      {events.map((e, i) => <EventCard key={i} e={e} />)}

      {logLines.length > 0 && (
        <pre ref={logRef} style={{
          fontSize: 11,
          color: "var(--dim)",
          background: "var(--bg-surface)",
          borderRadius: 6,
          padding: "10px 12px",
          maxHeight: 240,
          overflow: "auto",
          whiteSpace: "pre-wrap",
          wordBreak: "break-all",
          lineHeight: 1.6,
          marginTop: 8,
        }}>
          {logLines.join("\n")}
        </pre>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Existing sub-components
// ---------------------------------------------------------------------------

function ActiveRuns() {
  const { data } = useRuns();
  const active = data?.active ?? [];
  if (active.length === 0) return null;
  return (
    <div className="section">
      <div className="section-title">Active ({active.length})</div>
      {active.map((r) => (
        <div key={r.run_id} className="active-run-card">
          <div className="active-run-header">
            <div className="pulse-dot" />
            <span className="active-run-id">{r.run_id.slice(0, 14)}</span>
            <span className="dim" style={{ fontSize: 11 }}>{r.producer_model}</span>
          </div>
          <div className="active-run-task">{r.task}</div>
        </div>
      ))}
    </div>
  );
}

function QueueTable() {
  const { data } = useQueue();
  const cancel = useCancelTask();
  const items = data?.items ?? [];
  if (items.length === 0) return <div className="empty-state">No pending tasks.</div>;
  return (
    <table className="runs-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Task</th>
          <th>Status</th>
          <th>Queued</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {items.map((item, i) => (
          <tr key={item.item_id}>
            <td className="dim mono">{i + 1}</td>
            <td className="task-cell">{item.task.slice(0, 80)}</td>
            <td>
              <span className={clsx("badge",
                item.status === "done"      ? "pass" :
                item.status === "error"     ? "error" :
                item.status === "cancelled" ? "error" : "running"
              )}>
                {item.status}
              </span>
            </td>
            <td className="dim mono" style={{ fontSize: 11 }}>
              {item.queued_at?.slice(11, 19) ?? "—"}
            </td>
            <td>
              {(item.status === "running" || item.status === "pending") && (
                <button
                  className="btn btn-ghost"
                  style={{ padding: "2px 6px", color: "var(--error)" }}
                  title="Terminate run"
                  onClick={() => void cancel.mutateAsync(item.item_id)}
                  disabled={cancel.isPending}
                >
                  <Square size={12} />
                </button>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ResultCard({ run }: { run: RunRecord }) {
  const score = run.wiggum_scores.at(-1);
  const isPass = run.final === "PASS";
  return (
    <div className="card" style={{ marginBottom: 24, borderLeft: `3px solid ${isPass ? "var(--pass, #34d399)" : "var(--error, #f87171)"}` }}>
      <div className="row-gap" style={{ marginBottom: 8 }}>
        <span className={clsx("badge", isPass ? "pass" : "error")}>{run.final}</span>
        {score != null && <span className="mono dim" style={{ fontSize: 12 }}>score {score.toFixed(2)}</span>}
        <span className="mono dim" style={{ fontSize: 12 }}>{run.run_duration_s?.toFixed(0)}s</span>
        {run.output_path && (
          <span className="mono dim" style={{ fontSize: 11, marginLeft: "auto" }}>{run.output_path}</span>
        )}
      </div>
      {run.final_content && (
        <div style={{ maxHeight: 480, overflow: "auto", marginTop: 8 }}>
          <MdView content={run.final_content} />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------

export function Submit() {
  const [task, setTask]         = useState("");
  const [model, setModel]       = useState("");
  const [noWiggum, setNoWiggum] = useState(false);
  const [usePlan, setUsePlan]   = useState(false);
  const [msg, setMsg]           = useState<{ ok: boolean; text: string } | null>(null);
  const [streamingId, setStreamingId]       = useState<string | null>(null);
  const [pendingTask, setPendingTask]       = useState<{ text: string; since: string } | null>(null);
  const [lastResult, setLastResult]         = useState<RunRecord | null>(null);
  const [pendingGate, setPendingGate]       = useState<{ queries: string[] } | null>(null);
  const submit = useSubmitTask();
  const { data: runsData } = useRuns();

  // Watch for the submitted task to appear in completed runs
  useEffect(() => {
    if (!pendingTask) return;
    const needle = pendingTask.text.slice(0, 60);
    const match = runsData?.recent.find(
      (r) => r.task.startsWith(needle) && r.timestamp >= pendingTask.since && r.final != null,
    );
    if (match) {
      setLastResult(match);
      setPendingTask(null);
    }
  }, [runsData, pendingTask]);

  const handleRun = async () => {
    if (!task.trim()) return;
    setMsg(null);
    setLastResult(null);
    setStreamingId(null);
    setPendingGate(null);
    try {
      const since = new Date().toISOString();
      const res = await submit.mutateAsync({
        task: task.trim(),
        producer_model: model.trim() || undefined,
        no_wiggum: noWiggum,
        use_plan: usePlan,
      });
      setStreamingId(res.item_id);
      setPendingTask({ text: task.trim(), since });
      setMsg({ ok: true, text: "Task running…" });
      setTask("");
    } catch (e) {
      setMsg({ ok: false, text: String(e) });
    }
  };

  const handleStreamDone = () => {
    setStreamingId(null);
    setPendingGate(null);
    if (msg?.ok) setMsg({ ok: true, text: "Task queued — waiting for result…" });
  };

  return (
    <div>
      <div className="view-header">
        <h1>Submit</h1>
        <p>Queue a research task</p>
      </div>

      <div className="card" style={{ marginBottom: 24, maxWidth: 680 }}>
        <div className="form-group">
          <label className="form-label">Task</label>
          <textarea
            className="task-input"
            placeholder="Research best practices for prompt injection defense and save to ~/Desktop/out.md"
            value={task}
            onChange={(e) => setTask(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && e.ctrlKey) void handleRun(); }}
          />
        </div>

        <div className="form-group row-gap" style={{ alignItems: "flex-end" }}>
          <div>
            <label className="form-label">Producer model</label>
            <input
              className="text-input"
              placeholder="default"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              style={{ width: 200 }}
            />
          </div>
          <label className="toggle-label" style={{ paddingBottom: 2 }}>
            <input type="checkbox" checked={noWiggum} onChange={(e) => setNoWiggum(e.target.checked)} />
            Skip wiggum
          </label>
          <label className="toggle-label" style={{ paddingBottom: 2 }}>
            <input type="checkbox" checked={usePlan} onChange={(e) => setUsePlan(e.target.checked)} />
            Review plan
          </label>
        </div>

        <div className="row-gap">
          <button
            className="btn btn-primary"
            onClick={() => void handleRun()}
            disabled={!task.trim() || submit.isPending}
          >
            <Play size={14} />
            {submit.isPending ? "Submitting…" : "Run now"}
          </button>
          {msg && (
            <span className={clsx("status-msg", msg.ok ? "status-ok" : "status-err")}>
              {(streamingId || pendingTask) && <span className="pulse-dot" style={{ marginRight: 6 }} />}
              {msg.text}
            </span>
          )}
        </div>

        <p style={{ fontSize: 11, color: "var(--dim)", marginTop: 10 }}>
          Ctrl+Enter to submit
        </p>
      </div>

      {streamingId && pendingGate && (
        <ApprovePlanCard
          itemId={streamingId}
          initialQueries={pendingGate.queries}
          onApproved={() => setPendingGate(null)}
        />
      )}

      {streamingId && (
        <LiveLog
          itemId={streamingId}
          onDone={handleStreamDone}
          onPlanGate={(queries) => setPendingGate({ queries })}
        />
      )}

      {lastResult && <ResultCard run={lastResult} />}

      <ActiveRuns />

      <div className="section">
        <div className="section-title">Queue</div>
        <QueueTable />
      </div>
    </div>
  );
}

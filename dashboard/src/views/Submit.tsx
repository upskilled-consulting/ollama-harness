import { useState } from "react";
import { Play, Square } from "lucide-react";
import { clsx } from "clsx";
import { useCancelTask, useQueue, useRuns, useSubmitTask } from "@/hooks/useRuns";

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

export function Submit() {
  const [task, setTask]         = useState("");
  const [model, setModel]       = useState("");
  const [noWiggum, setNoWiggum] = useState(false);
  const [msg, setMsg]           = useState<{ ok: boolean; text: string } | null>(null);
  const submit = useSubmitTask();

  const handleRun = async () => {
    if (!task.trim()) return;
    setMsg(null);
    try {
      await submit.mutateAsync({
        task: task.trim(),
        producer_model: model.trim() || undefined,
        no_wiggum: noWiggum,
      });
      setMsg({ ok: true, text: "Task queued." });
      setTask("");
    } catch (e) {
      setMsg({ ok: false, text: String(e) });
    }
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
              {msg.text}
            </span>
          )}
        </div>

        <p style={{ fontSize: 11, color: "var(--dim)", marginTop: 10 }}>
          Ctrl+Enter to submit
        </p>
      </div>

      <ActiveRuns />

      <div className="section">
        <div className="section-title">Queue</div>
        <QueueTable />
      </div>
    </div>
  );
}

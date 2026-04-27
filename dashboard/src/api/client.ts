import type { DashboardData, QueueItem, RunRecord } from "@/types";

const BASE = "/api";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  data:    ()                            => get<DashboardData>("/data"),
  runs:    ()                            => get<{ active: RunRecord[]; recent: RunRecord[] }>("/runs"),
  queue:   ()                            => get<{ pending: number; items: QueueItem[] }>("/queue"),
  submit:  (task: string, opts?: { producer_model?: string; no_wiggum?: boolean }) =>
    post<{ item_id: string }>("/tasks", { task, ...opts }),
};

export function createRunsSocket(onMessage: (run: RunRecord) => void): WebSocket {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${window.location.host}/ws/runs`);
  ws.onmessage = (e) => {
    try { onMessage(JSON.parse(e.data) as RunRecord); } catch { /* ignore */ }
  };
  return ws;
}

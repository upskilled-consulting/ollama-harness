import type { AnalyticsData, ArtifactContent, Artifact, CurationEntry, DashboardData, FeedbackRecord, GhCommit, GhCommitDetail, GhFileContent, GhIssue, GhPr, GhRepo, GhRun, GhTreeEntry, LiveRun, McpLogEntry, McpTool, PlanRecord, QueueItem, RunRecord, Session } from "@/types";

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
  data:      ()                             => get<DashboardData>("/data"),
  runs:      ()                             => get<{ active: RunRecord[]; recent: RunRecord[] }>("/runs"),
  all_runs:  ()                             => get<RunRecord[]>("/runs/all"),
  paged_runs: (page: number, per_page = 25) =>
    get<{ runs: RunRecord[]; total: number; page: number; per_page: number; pages: number }>(
      `/runs/paged?page=${page}&per_page=${per_page}`
    ),
  queue:     ()                             => get<{ pending: number; items: QueueItem[] }>("/queue"),
  mcp_log:   (limit = 200)                 => get<McpLogEntry[]>(`/mcp/log?limit=${limit}`),
  mcp_tools: ()                             => get<McpTool[]>("/mcp/tools"),
  sessions:  ()                             => get<Session[]>("/sessions"),
  artifacts: ()                             => get<Artifact[]>("/artifacts"),
  plans:     ()                             => get<PlanRecord[]>("/plans"),
  curation:  ()                             => get<CurationEntry[]>("/curation"),
  submit:    (task: string, opts?: { producer_model?: string; no_wiggum?: boolean; use_plan?: boolean }) =>
    post<{ item_id: string }>("/tasks", { task, ...opts }),
  approve_plan: (item_id: string, queries: string[]) =>
    post<{ ok: boolean }>(`/tasks/${item_id}/approve-plan`, { queries }),
  cancel:    (item_id: string) =>
    fetch(`${BASE}/tasks/${item_id}`, { method: "DELETE" }).then((r) => r.json()),
  feedback:        (run_id: string) => get<FeedbackRecord[]>(`/feedback/${run_id}`),
  submit_feedback: (body: { run_id: string; node_id: string; rating: number; comment: string }) =>
    post<FeedbackRecord>("/feedback", body),
  run_content:      (run_id: string) =>
    get<{ content: string; path: string; bytes: number }>(`/runs/${run_id}/content`),
  analytics:        () => get<AnalyticsData>("/analytics"),
  artifact_content: (artifact_id: string) =>
    get<ArtifactContent>(`/artifacts/${artifact_id}/content`),
  live_run: () =>
    fetch(`${BASE}/runs/live`).then((r) => r.ok ? r.json() as Promise<LiveRun | null> : Promise.resolve(null)).catch(() => null),
  github_repo:    () => get<GhRepo>("/github/repo"),
  github_prs:     () => get<GhPr[]>("/github/prs"),
  github_issues:  () => get<GhIssue[]>("/github/issues"),
  github_runs:    () => get<GhRun[]>("/github/runs"),
  github_commits:       () => get<GhCommit[]>("/github/commits"),
  github_commit_detail: (sha: string) => get<GhCommitDetail>(`/github/commits/${sha}/detail`),
  github_commit_tree:   (sha: string, path = "") =>
    get<GhTreeEntry[]>(`/github/commits/${sha}/tree${path ? `?path=${encodeURIComponent(path)}` : ""}`),
  github_commit_file:   (sha: string, path: string) =>
    get<GhFileContent>(`/github/commits/${sha}/file?path=${encodeURIComponent(path)}`),
  github_refresh: () =>
    fetch(`${BASE}/github/refresh`, { method: "POST" }).then((r) => r.json()),
};

export function createRunsSocket(onMessage: (run: RunRecord) => void): WebSocket {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${window.location.host}/ws/runs`);
  ws.onmessage = (e) => {
    try { onMessage(JSON.parse(e.data) as RunRecord); } catch { /* ignore */ }
  };
  ws.onerror = () => { /* suppress — onclose fires next and handles reconnect */ };
  return ws;
}

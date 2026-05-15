import type { AnalyticsData, ArtifactContent, Artifact, CurationEntry, DashboardData, FeedbackRecord, GhCommit, GhCommitDetail, GhFileContent, GhIssue, GhPr, GhRepo, GhRun, GhTreeEntry, LiveRun, McpLogEntry, McpTool, MemoryDetail, MemoryGraph, MemoryList, MemoryRow, PlanRecord, QueueItem, RunRecord, SecurityEvent, SecuritySummary, Session, SkillEntry, SystemConfig, SystemFileContent, SystemFileMeta } from "@/types";

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
  paged_runs: (page: number, per_page = 25, status = "", search = "") => {
    const p = new URLSearchParams({ page: String(page), per_page: String(per_page) });
    if (status) p.set("status", status);
    if (search) p.set("search", search);
    return get<{ runs: RunRecord[]; total: number; page: number; per_page: number; pages: number }>(
      `/runs/paged?${p.toString()}`
    );
  },
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
  gates: () => get<{ item_id: string; queries: string[] }[]>("/tasks/gates"),
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
  security_events: (params: { search?: string; severity?: string; event_type?: string; layer?: string; run_id?: string } = {}) => {
    const p = new URLSearchParams();
    if (params.search)     p.set("search",     params.search);
    if (params.severity)   p.set("severity",   params.severity);
    if (params.event_type) p.set("event_type", params.event_type);
    if (params.layer)      p.set("layer",      params.layer);
    if (params.run_id)     p.set("run_id",     params.run_id);
    const qs = p.toString();
    return get<{ events: SecurityEvent[]; total: number }>(`/security/events${qs ? `?${qs}` : ""}`);
  },
  security_summary: () => get<SecuritySummary>("/security/summary"),
  system_files:   () => get<SystemFileMeta[]>("/system/files"),
  system_file:    (key: string) => get<SystemFileContent>(`/system/files/${key}`),
  system_file_save: (key: string, content: string) =>
    fetch(`${BASE}/system/files/${key}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }).then((r) => r.json() as Promise<{ ok: boolean }>),
  system_config:  () => get<SystemConfig>("/system/config"),
  system_skills:  () => get<SkillEntry[]>("/system/skills"),
  memories: (params: { search?: string; task_type?: string; quality_min?: number; quality_max?: number; final?: string; page?: number; per_page?: number } = {}) => {
    const p = new URLSearchParams();
    if (params.search)                          p.set("search",      params.search);
    if (params.task_type)                       p.set("task_type",   params.task_type);
    if (params.quality_min !== undefined)       p.set("quality_min", String(params.quality_min));
    if (params.quality_max !== undefined)       p.set("quality_max", String(params.quality_max));
    if (params.final)                           p.set("final",       params.final);
    if (params.page !== undefined)              p.set("page",        String(params.page));
    if (params.per_page !== undefined)          p.set("per_page",    String(params.per_page));
    const qs = p.toString();
    return get<MemoryList>(`/memories${qs ? `?${qs}` : ""}`);
  },
  memory:          (id: number) => get<MemoryDetail>(`/memories/${id}`),
  memory_update:   (id: number, body: { title?: string; tags?: string[]; quality?: number }) =>
    fetch(`${BASE}/memories/${id}`, {
      method:  "PATCH",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(body),
    }).then((r) => r.json() as Promise<{ ok: boolean }>),
  memory_delete:   (id: number) =>
    fetch(`${BASE}/memories/${id}`, { method: "DELETE" }).then((r) => r.json() as Promise<{ ok: boolean }>),
  memory_feedback: (id: number, rating: number, comment = "") =>
    post<MemoryRow>(`/memories/${id}/feedback`, { rating, comment }),
  memory_prune_candidates: () => get<{ candidates: MemoryRow[] }>("/memories/prune-candidates"),
  memory_graph:    () => get<MemoryGraph>("/memories/graph"),
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

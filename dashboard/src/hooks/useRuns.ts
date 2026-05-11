import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, createRunsSocket } from "@/api/client";
import type { FeedbackRecord, LiveRun, RunRecord } from "@/types";

export function useGithub() {
  const POLL = 60_000;
  return {
    repo:    useQuery({ queryKey: ["gh_repo"],    queryFn: api.github_repo,    refetchInterval: POLL, retry: false }),
    prs:     useQuery({ queryKey: ["gh_prs"],     queryFn: api.github_prs,     refetchInterval: POLL, retry: false }),
    issues:  useQuery({ queryKey: ["gh_issues"],  queryFn: api.github_issues,  refetchInterval: POLL, retry: false }),
    runs:    useQuery({ queryKey: ["gh_runs"],     queryFn: api.github_runs,    refetchInterval: 30_000, retry: false }),
    commits: useQuery({ queryKey: ["gh_commits"], queryFn: api.github_commits, refetchInterval: POLL, retry: false }),
  };
}

export function useSessions() {
  return useQuery({ queryKey: ["sessions"], queryFn: api.sessions, staleTime: 30_000 });
}

export function useArtifacts() {
  return useQuery({ queryKey: ["artifacts"], queryFn: api.artifacts, staleTime: 30_000 });
}

export function useAllRuns() {
  return useQuery({ queryKey: ["all_runs"], queryFn: api.all_runs, staleTime: 10_000 });
}

export function usePagedRuns(page: number, perPage = 25, status = "", search = "") {
  return useQuery({
    queryKey:        ["paged_runs", page, perPage, status, search],
    queryFn:         () => api.paged_runs(page, perPage, status, search),
    staleTime:       15_000,
    placeholderData: (prev) => prev,
  });
}

export function useLiveRun() {
  return useQuery<LiveRun | null>({
    queryKey:       ["live_run"],
    queryFn:        api.live_run,
    refetchInterval: (query) => (query.state.data ? 2_000 : 10_000),
    staleTime:      0,
  });
}

export function usePlans() {
  return useQuery({ queryKey: ["plans"], queryFn: api.plans, staleTime: 30_000 });
}

export function useCuration() {
  return useQuery({ queryKey: ["curation"], queryFn: api.curation, staleTime: 60_000 });
}

export function useAnalytics() {
  return useQuery({ queryKey: ["analytics"], queryFn: api.analytics, staleTime: 30_000 });
}

export function useArtifactContent(artifactId: string | null) {
  return useQuery({
    queryKey: ["artifact_content", artifactId],
    queryFn:  () => api.artifact_content(artifactId!),
    enabled:  !!artifactId,
    staleTime: 60_000,
  });
}

export function useDashboardData() {
  return useQuery({ queryKey: ["data"], queryFn: api.data, refetchInterval: 10_000 });
}

export function useRuns() {
  return useQuery({ queryKey: ["runs"], queryFn: api.runs, refetchInterval: 5_000 });
}

export function useQueue() {
  return useQuery({ queryKey: ["queue"], queryFn: api.queue, refetchInterval: 3_000 });
}

export function useMcpLog() {
  return useQuery({ queryKey: ["mcp_log"], queryFn: () => api.mcp_log(), refetchInterval: 5_000 });
}

export function useMcpTools() {
  return useQuery({ queryKey: ["mcp_tools"], queryFn: api.mcp_tools, staleTime: Infinity });
}

export function useSubmitTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { task: string; producer_model?: string; no_wiggum?: boolean; use_plan?: boolean }) =>
      api.submit(args.task, { producer_model: args.producer_model, no_wiggum: args.no_wiggum, use_plan: args.use_plan }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["queue"] });
      void qc.invalidateQueries({ queryKey: ["runs"] });
    },
  });
}

export function useCancelTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (item_id: string) => api.cancel(item_id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["queue"] });
      void qc.invalidateQueries({ queryKey: ["runs"] });
    },
  });
}

export function useFeedback(runId: string | null) {
  return useQuery({
    queryKey: ["feedback", runId],
    queryFn:  () => (runId ? api.feedback(runId) : Promise.resolve([])),
    enabled:  !!runId,
    staleTime: 10_000,
  });
}

export function useSubmitFeedback() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { run_id: string; node_id: string; rating: number; comment: string }) =>
      api.submit_feedback(body),
    onSuccess: (_data: FeedbackRecord, vars) => {
      void qc.invalidateQueries({ queryKey: ["feedback", vars.run_id] });
    },
  });
}

export function useLiveRuns() {
  const qc = useQueryClient();
  const ws    = useRef<WebSocket | null>(null);
  const delay = useRef(3_000);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let active = true;

    function connect() {
      if (!active) return;

      const sock = createRunsSocket((run: RunRecord) => {
        delay.current = 3_000;
        qc.setQueryData<{ active: RunRecord[]; recent: RunRecord[] }>(["runs"], (prev) => {
          if (!prev) return { active: [], recent: [run] };
          const recent = [run, ...prev.recent.filter((r) => r.run_id !== run.run_id)].slice(0, 200);
          const nextActive = run.final
            ? prev.active.filter((r) => r.run_id !== run.run_id)
            : [run, ...prev.active];
          return { active: nextActive, recent };
        });
        void qc.invalidateQueries({ queryKey: ["data"] });
      });

      sock.onopen  = () => { delay.current = 3_000; };
      sock.onclose = () => {
        if (!active) return;
        timer.current = setTimeout(() => {
          delay.current = Math.min(delay.current * 2, 60_000);
          connect();
        }, delay.current);
      };

      ws.current = sock;
    }

    // Delay first attempt — survives React StrictMode double-invoke and avoids
    // a spurious "closed before established" error on cold start.
    timer.current = setTimeout(connect, 1_500);

    return () => {
      active = false;
      if (timer.current) clearTimeout(timer.current);
      ws.current?.close();
    };
  }, [qc]);
}

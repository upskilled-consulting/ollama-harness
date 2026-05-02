import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, createRunsSocket } from "@/api/client";
import type { RunRecord } from "@/types";

export function useSessions() {
  return useQuery({ queryKey: ["sessions"], queryFn: api.sessions, staleTime: 30_000 });
}

export function useArtifacts() {
  return useQuery({ queryKey: ["artifacts"], queryFn: api.artifacts, staleTime: 30_000 });
}

export function useAllRuns() {
  return useQuery({ queryKey: ["all_runs"], queryFn: api.all_runs, staleTime: 10_000 });
}

export function usePlans() {
  return useQuery({ queryKey: ["plans"], queryFn: api.plans, staleTime: 30_000 });
}

export function useCuration() {
  return useQuery({ queryKey: ["curation"], queryFn: api.curation, staleTime: 60_000 });
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

export function useSubmitTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { task: string; producer_model?: string; no_wiggum?: boolean }) =>
      api.submit(args.task, { producer_model: args.producer_model, no_wiggum: args.no_wiggum }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["queue"] });
      void qc.invalidateQueries({ queryKey: ["runs"] });
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

import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, createRunsSocket } from "@/api/client";
import type { RunRecord } from "@/types";

export function useDashboardData() {
  return useQuery({ queryKey: ["data"], queryFn: api.data, refetchInterval: 10_000 });
}

export function useQueue() {
  return useQuery({ queryKey: ["queue"], queryFn: api.queue, refetchInterval: 3_000 });
}

export function useLiveRuns() {
  const qc = useQueryClient();
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    ws.current = createRunsSocket((run: RunRecord) => {
      qc.setQueryData<{ active: RunRecord[]; recent: RunRecord[] }>(["runs"], (prev) => {
        if (!prev) return { active: [], recent: [run] };
        const recent = [run, ...prev.recent.filter((r) => r.run_id !== run.run_id)].slice(0, 50);
        const active = run.final ? prev.active.filter((r) => r.run_id !== run.run_id) : [run, ...prev.active];
        return { active, recent };
      });
      qc.invalidateQueries({ queryKey: ["data"] });
    });
    return () => ws.current?.close();
  }, [qc]);
}

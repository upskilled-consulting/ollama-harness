export interface WiggumDim {
  relevance:    number;
  completeness: number;
  depth:        number;
  specificity:  number;
  structure:    number;
}

export interface RunRecord {
  run_id:          string;
  timestamp:       string;
  task:            string;
  task_type:       string;
  producer_model:  string;
  evaluator_model: string;
  run_duration_s:  number;
  input_tokens:    number;
  output_tokens:   number;
  output_bytes:    number;
  wiggum_rounds:   number;
  wiggum_scores:   number[];
  wiggum_dims:     WiggumDim[];
  final:           "PASS" | "FAIL" | "ERROR" | null;
  memory_hits:     number;
  leverage?:       number;
  tac_hours?:      number;
}

export interface Kpi {
  total_runs:       number;
  pass_rate:        number;
  mean_score:       number;
  mean_duration_s:  number;
}

export interface ScoreTrendPoint {
  i:         number;
  score:     number;
  task_type: string;
}

export interface DashboardData {
  kpi:         Kpi;
  recent_runs: RunRecord[];
  score_trend: ScoreTrendPoint[];
  cost:        { total_input_tokens: number; total_output_tokens: number };
  claude_stats: Record<string, unknown>;
}

export interface QueueItem {
  item_id:   string;
  task:      string;
  status:    "pending" | "running" | "done" | "error";
  queued_at: string;
}

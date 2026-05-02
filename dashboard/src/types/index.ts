export interface WiggumDim {
  relevance:     number;
  completeness:  number;
  depth:         number;
  specificity:   number;
  structure:     number;
  grounded?:     number;
  [key: string]: number | undefined;
}

export interface ToolCall {
  name:          string;
  query?:        string;
  result_chars?: number;
}

export interface WiggumEvalEntry {
  round:     number;
  score:     number;
  dims?:     WiggumDim;
  issues?:   string[];
  feedback?: string;
  thinking?: string;
  content?:  string;
}

export interface Plan {
  task_type?:           string;
  complexity?:          string;
  search_queries?:      string[];
  queries?:             string[];
  known_facts?:         string[];
  knowledge_gaps?:      string[];
  prior_work_summary?:  string;
  notes?:               string;
  subtasks?:            string[];
}

export interface StageTokens {
  input?:          number;
  output?:         number;
  calls?:          number;
  total_ms?:       number;
  thinking_chars?: number;
}

export interface RunRecord {
  run_id:                 string;
  session_id?:            string;
  project_id?:            string;
  timestamp:              string;
  task:                   string;
  task_type?:             string;
  producer_model:         string;
  evaluator_model:        string;
  run_duration_s:         number;
  input_tokens:           number;
  output_tokens:          number;
  output_bytes?:          number | null;
  output_lines?:          number | null;
  output_path?:           string | null;
  wiggum_rounds:          number;
  wiggum_scores:          number[];
  wiggum_dims:            WiggumDim[];
  wiggum_issues?:         string[];
  wiggum_eval_log?:       WiggumEvalEntry[];
  tool_calls?:            ToolCall[];
  tokens_by_stage?:       Record<string, StageTokens>;
  memory_hits:            number;
  memory_context_titles?: string[];
  plan?:                  Plan | null;
  synth_cot?:             string[];
  total_search_chars?:    number;
  final:                  "PASS" | "FAIL" | "ERROR" | null;
  leverage?:              number;
  tac_hours?:             number;
}

export interface Kpi {
  total_runs:      number;
  pass_rate:       number;
  mean_score:      number;
  mean_duration_s: number;
}

export interface ScoreTrendPoint {
  i:         number;
  score:     number;
  task_type: string;
}

export interface DashboardData {
  kpi:          Kpi;
  recent_runs:  RunRecord[];
  score_trend:  ScoreTrendPoint[];
  cost:         { total_input_tokens: number; total_output_tokens: number };
  claude_stats: Record<string, unknown>;
}

export interface QueueItem {
  item_id:    string;
  task:       string;
  status:     "pending" | "running" | "done" | "error";
  queued_at?: string;
}

export interface McpLogEntry {
  ts:      string;
  task_id: string;
  label:   string;
  event:   string;
  text:    string;
}

export interface Session {
  session_id:           string;
  project_id?:          string;
  triggered_by?:        string;
  started_at:           string;
  ended_at?:            string | null;
  runs?:                number;
  artifacts?:           number;
  duration_s?:          number | null;
  total_input_tokens?:  number;
  total_output_tokens?: number;
  event?:               string;
}

export interface Artifact {
  artifact_id: string;
  run_id?:     string;
  session_id?: string;
  project_id?: string;
  type:        string;
  path:        string;
  bytes?:      number;
  lines?:      number;
  created_at:  string;
  event?:      string;
}

export interface PlanRecord {
  plan_id?:        string;
  run_id?:         string;
  session_id?:     string;
  task:            string;
  plan_type?:      string;
  task_type?:      string;
  complexity?:     string;
  subtasks?:       string[];
  known_facts?:    string[];
  knowledge_gaps?: string[];
  search_queries?: string[];
  created_at?:     string;
}

export interface CurationEntry {
  arxiv_id: string;
  title?:   string;
  mean?:    number;
  passed?:  boolean;
  tokens_in?: number;
  tokens_out?: number;
}

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
  eval_ms?:        number;
  prompt_ms?:      number;
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
  final_content?:         string | null;
  leverage?:              number;
  tac_hours?:             number;
  orchestrated?:          boolean;
  subtask_count?:         number;
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
  status:     "pending" | "running" | "done" | "error" | "cancelled";
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

export interface RunMessage {
  run_id:    string;
  seq:       number;
  role:      string;
  stage:     string | null;
  content:   string | null;
  cot:       string | null;
  chars:     number | null;
  truncated?: boolean;
  timestamp: string;
}

export interface LiveRun {
  run_id:        string;
  task:          string;
  started_at:    string;
  current_stage: string;
  stages_seen:   string[];
  elapsed_s:     number;
}

export interface FeedbackRecord {
  feedback_id: string;
  run_id:      string;
  node_id:     string;
  rating:      1 | -1;
  comment:     string;
  created_at:  string;
}

export interface CurationEntry {
  arxiv_id: string;
  title?:   string;
  mean?:    number;
  passed?:  boolean;
  tokens_in?: number;
  tokens_out?: number;
}

export interface AnalyticsDay {
  date:          string;
  total:         number;
  pass:          number;
  fail:          number;
  error:         number;
  mean_score:    number | null;
  input_tokens:  number;
  output_tokens: number;
}

export interface AnalyticsData {
  daily:              AnalyticsDay[];
  score_distribution: { score: number; count: number }[];
  task_types:         { type: string; count: number }[];
}

export interface ArtifactContent {
  content:   string;
  truncated: boolean;
  bytes:     number;
  path:      string;
}

export interface McpToolParam {
  name:     string;
  type:     string;
  required: boolean;
}

// ---------------------------------------------------------------------------
// GitHub panel
// ---------------------------------------------------------------------------

export interface GhRepoMeta {
  name:             string;
  owner:            { login: string };
  description:      string | null;
  url:              string;
  defaultBranchRef: { name: string } | null;
  isPrivate:        boolean;
  stargazerCount:   number;
  forkCount:        number;
  pushedAt:         string | null;
}

export interface GhRepo {
  branch:      string;
  dirty_files: number;
  ahead:       number;
  behind:      number;
  meta:        GhRepoMeta | null;
}

export interface GhPr {
  number:         number;
  title:          string;
  state:          string;
  author:         { login: string };
  createdAt:      string;
  headRefName:    string;
  isDraft:        boolean;
  reviewDecision: string | null;
}

export interface GhIssue {
  number:    number;
  title:     string;
  state:     string;
  author:    { login: string };
  createdAt: string;
  labels:    { name: string; color: string }[];
  assignees: { login: string }[];
}

export interface GhRun {
  databaseId: number;
  name:       string;
  status:     string;
  conclusion: string | null;
  createdAt:  string;
  headBranch: string;
  url:        string;
  event:      string;
}

export interface GhCommit {
  sha:     string;
  short:   string;
  message: string;
  author:  string;
  ago:     string;
  date?:   string;   // YYYY-MM-DD
}

export interface GhCommitDetail {
  sha:     string;
  message: string;
  stat:    string;
  files:   { status: string; file: string }[];
  diff:    string;
}

export interface GhTreeEntry {
  mode:   string;
  type:   "blob" | "tree";
  object: string;
  size:   number | null;
  name:   string;
}

export interface GhFileContent {
  path:      string;
  content:   string;
  binary:    boolean;
  truncated: boolean;
}

export interface McpTool {
  name:        string;
  description: string;
  parameters:  McpToolParam[];
}

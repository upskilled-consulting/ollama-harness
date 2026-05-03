import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from "recharts";
import { MdView } from "@/components/MdView";

// ── types ─────────────────────────────────────────────────────────────────────

interface TrainBegin  { type: "train_begin"; max_steps: number; num_epochs: number; model: string }
interface MetricRow   { type: "metric"; step: number; max_steps: number; epoch: number; loss: number | null; grad_norm: number | null; learning_rate: number | null; mean_token_accuracy: number | null; elapsed_s: number; eta_s: number | null }
interface TrainEnd    { type: "train_end"; step: number; elapsed_s: number }
type MetricRecord = TrainBegin | MetricRow | TrainEnd | { type: string };

interface PreferencePair {
  prompt: string; chosen: string; rejected: string;
  chosen_score: number; rejected_score: number; score_gap: number;
  chosen_round?: number; rejected_round?: number;
  task_type?: string; run_id?: string;
}

interface RewardRecord {
  prompt: string; response: string; score: number;
  dimensions?: Record<string, number>;
  issues?: string[]; feedback?: string;
  model?: string; task_type?: string; wiggum_rounds?: number;
}

interface GrpoRecord {
  prompt: string; task_type?: string;
  mean_reward: number; max_reward: number; min_reward: number; n_rollouts: number;
  completions: { content: string; reward: number; temp: number }[];
}

interface DpoRecord {
  prompt: string; chosen: string; rejected: string;
  chosen_score: number; rejected_score: number; score_delta: number;
  chosen_dims?: Record<string, number>; rejected_dims?: Record<string, number>;
  wiggum_feedback?: string; task_type?: string;
}

interface RlData {
  preference: PreferencePair[];
  reward:     RewardRecord[];
  grpo:       GrpoRecord[];
  dpo:        DpoRecord[];
}

// ── shared helpers ─────────────────────────────────────────────────────────────

function trunc(s: string, n = 180) { return s.length > n ? s.slice(0, n) + "…" : s; }

function fmtDuration(s: number) {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function downsample<T>(arr: T[], n: number): T[] {
  if (arr.length <= n) return arr;
  const step = arr.length / n;
  return Array.from({ length: n }, (_, i) => arr[Math.round(i * step)]);
}

function roundTicks(maxStep: number, n = 6): number[] {
  const raw = maxStep / n;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const interval = Math.ceil(raw / mag) * mag;
  const ticks: number[] = [];
  for (let t = interval; t < maxStep; t += interval) ticks.push(t);
  ticks.push(maxStep);
  return ticks;
}

const DIM_COLORS: Record<string, string> = {
  relevance: "#4f8ef7", completeness: "#3fb950", depth: "#a78bfa",
  specificity: "#22d3ee", structure: "#fb923c",
};

function scoreColor(s: number) {
  return s >= 8 ? "var(--pass)" : s >= 6 ? "var(--warn)" : "var(--fail)";
}

function ScoreBadge({ score }: { score: number }) {
  const c = scoreColor(score);
  return (
    <span style={{
      display: "inline-block", padding: "1px 7px", borderRadius: 8,
      fontSize: 11, fontWeight: 700, fontFamily: "var(--font-mono)",
      background: `${c}18`, color: c, border: `1px solid ${c}40`,
    }}>
      {score.toFixed(1)}
    </span>
  );
}

function DimBars({ dims }: { dims: Record<string, number> }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {Object.entries(dims).map(([k, v]) => {
        const color = DIM_COLORS[k] ?? "#4f8ef7";
        return (
          <div key={k} style={{ display: "flex", alignItems: "center", gap: 7 }}>
            <span style={{ fontSize: 10, color: "var(--dim)", minWidth: 90, textTransform: "capitalize" }}>{k}</span>
            <div style={{ flex: 1, height: 4, background: "rgba(255,255,255,0.07)", borderRadius: 2, overflow: "hidden" }}>
              <div style={{ width: `${(v / 10) * 100}%`, height: "100%", background: color, borderRadius: 2 }} />
            </div>
            <span style={{ fontSize: 10, color, fontFamily: "var(--font-mono)", minWidth: 18, textAlign: "right" }}>{v}</span>
          </div>
        );
      })}
    </div>
  );
}

function TabBar({ tabs, active, onChange }: { tabs: string[]; active: string; onChange: (t: string) => void }) {
  return (
    <div style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--border)", marginBottom: 18 }}>
      {tabs.map((t) => (
        <button key={t} onClick={() => onChange(t)} style={{
          background: "none", border: "none", borderBottom: t === active ? "2px solid var(--accent)" : "2px solid transparent",
          color: t === active ? "var(--accent)" : "var(--dim)", cursor: "pointer",
          fontSize: 12, fontWeight: 600, padding: "8px 14px", marginBottom: -1,
          textTransform: "uppercase", letterSpacing: "0.05em",
        }}>
          {t}
        </button>
      ))}
    </div>
  );
}

// ── training run tab ──────────────────────────────────────────────────────────

function KpiCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "12px 16px", minWidth: 120 }}>
      <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--dim)", marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, fontFamily: "var(--font-mono)", color: "var(--text)" }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: "var(--dim)", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function MetricChart({ data, dataKey, label, color, domain, tickFormatter, maxStep }: {
  data: object[]; dataKey: string; label: string; color: string;
  domain?: [number | "auto", number | "auto"];
  tickFormatter?: (v: number) => string;
  maxStep: number;
}) {
  const ticks = roundTicks(maxStep);
  return (
    <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "14px 16px" }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: "var(--dim)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 10 }}>{label}</div>
      <ResponsiveContainer width="100%" height={160}>
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <XAxis
            dataKey="step" type="number" domain={[0, maxStep]} ticks={ticks}
            tick={{ fontSize: 10, fill: "var(--dim)" }} tickLine={false} axisLine={false}
            tickFormatter={(v) => v >= 1000 ? `${v / 1000}k` : String(v)}
          />
          <YAxis
            domain={domain ?? ["auto", "auto"]}
            tick={{ fontSize: 10, fill: "var(--dim)" }} tickLine={false} axisLine={false} width={48}
            tickFormatter={tickFormatter ?? ((v) => String(v))}
          />
          <Tooltip
            contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, fontSize: 11 }}
            labelStyle={{ color: "var(--dim)" }} itemStyle={{ color }}
            formatter={(v: number) => [tickFormatter ? tickFormatter(v) : v.toFixed(4), label]}
            labelFormatter={(s) => `step ${s}`}
          />
          <Line type="monotone" dataKey={dataKey} stroke={color} dot={false} strokeWidth={1.5} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function TrainingTab() {
  const { data: raw = [], isLoading, error } = useQuery<MetricRecord[]>({
    queryKey: ["finetune-metrics"],
    queryFn:  () => fetch("/api/finetune/metrics").then((r) => r.json()),
    staleTime: 30_000,
  });

  const begin   = raw.find((r): r is TrainBegin => r.type === "train_begin") as TrainBegin | undefined;
  const end     = raw.find((r): r is TrainEnd   => r.type === "train_end")   as TrainEnd   | undefined;
  const metrics = (raw.filter((r): r is MetricRow => r.type === "metric") as MetricRow[]).filter((r) => r.loss !== null);
  const last    = metrics.at(-1);
  const maxSteps = begin?.max_steps ?? last?.max_steps ?? 0;
  const complete = !!end;
  const pct      = maxSteps > 0 ? Math.round((metrics.length / maxSteps) * 100) : 0;
  const modelName = begin?.model ? begin.model.split(/[\\/]/).at(-1) ?? begin.model : "—";

  const pts      = downsample(metrics, 400);
  const lossData = pts.filter((r) => r.loss !== null).map((r) => ({ step: r.step, loss: +(r.loss!.toFixed(4)) }));
  const accData  = pts.filter((r) => r.mean_token_accuracy !== null).map((r) => ({ step: r.step, acc: +(r.mean_token_accuracy!.toFixed(4)) }));
  const gradData = pts.filter((r) => r.grad_norm !== null).map((r) => ({ step: r.step, grad: +(r.grad_norm!.toFixed(4)) }));
  const lrData   = pts.filter((r) => r.learning_rate !== null).map((r) => ({ step: r.step, lr: r.learning_rate! }));

  if (isLoading) return <div style={{ color: "var(--dim)", fontSize: 13 }}>Loading…</div>;
  if (error)     return <div style={{ color: "var(--fail)", fontSize: 13 }}>Failed to load metrics</div>;
  if (!begin)    return <div style={{ color: "var(--dim)", fontSize: 13 }}>No training data found.</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{
          fontSize: 11, padding: "2px 8px", borderRadius: 10, fontWeight: 600,
          background: complete ? "rgba(63,185,80,0.15)" : "rgba(251,146,60,0.15)",
          color: complete ? "var(--pass)" : "var(--warn)",
          border: `1px solid ${complete ? "rgba(63,185,80,0.4)" : "rgba(251,146,60,0.4)"}`,
        }}>
          {complete ? "COMPLETE" : `${pct}%`}
        </span>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
        <KpiCard label="Model"    value={modelName} />
        <KpiCard label="Steps"    value={`${metrics.length.toLocaleString()} / ${maxSteps.toLocaleString()}`} sub={`${begin.num_epochs} epochs`} />
        <KpiCard label="Loss"     value={last?.loss?.toFixed(4) ?? "—"} sub="final" />
        <KpiCard label="Accuracy" value={last?.mean_token_accuracy != null ? `${(last.mean_token_accuracy * 100).toFixed(1)}%` : "—"} sub="token" />
        <KpiCard label="Elapsed"  value={end ? fmtDuration(end.elapsed_s) : last ? fmtDuration(last.elapsed_s) : "—"} />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(380px, 1fr))", gap: 14 }}>
        <MetricChart data={lossData} dataKey="loss" label="Loss"           color="#fb923c" tickFormatter={(v) => v.toFixed(2)} maxStep={maxSteps} />
        <MetricChart data={accData}  dataKey="acc"  label="Token Accuracy" color="#3fb950" domain={[0, 1]} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} maxStep={maxSteps} />
        <MetricChart data={gradData} dataKey="grad" label="Gradient Norm"  color="#a78bfa" tickFormatter={(v) => v.toFixed(2)} maxStep={maxSteps} />
        <MetricChart data={lrData}   dataKey="lr"   label="Learning Rate"  color="#4f8ef7" tickFormatter={(v) => v.toExponential(2)} maxStep={maxSteps} />
      </div>
    </div>
  );
}

// ── preference pairs tab ──────────────────────────────────────────────────────

function PreferenceCard({ pair }: { pair: PreferencePair }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "12px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
      {/* header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
        <div style={{ fontSize: 12, color: "var(--text)", lineHeight: 1.5, flex: 1 }}>{trunc(pair.prompt, 200)}</div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4, flexShrink: 0 }}>
          <span style={{ fontSize: 11, fontWeight: 700, fontFamily: "var(--font-mono)", color: "var(--pass)" }}>
            Δ {pair.score_gap.toFixed(1)}
          </span>
          {pair.task_type && <span style={{ fontSize: 10, color: "var(--dim)" }}>{pair.task_type}</span>}
        </div>
      </div>

      {/* chosen / rejected side-by-side */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        {(["chosen", "rejected"] as const).map((side) => {
          const text  = pair[side];
          const score = side === "chosen" ? pair.chosen_score : pair.rejected_score;
          const round = side === "chosen" ? pair.chosen_round : pair.rejected_round;
          const borderColor = side === "chosen" ? "var(--pass)" : "var(--fail)";
          return (
            <div key={side} style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.07em", color: borderColor, fontWeight: 700 }}>{side}</span>
                <ScoreBadge score={score} />
                {round != null && (
                  <span style={{ fontSize: 10, color: "var(--dim)" }}>round {round}</span>
                )}
              </div>
              <div style={{
                fontSize: 11, lineHeight: 1.6, padding: "8px 10px",
                background: "var(--bg)", borderRadius: 5,
                borderLeft: `3px solid ${borderColor}`,
                maxHeight: expanded ? 500 : 100, overflowY: "auto",
              }}>
                {expanded ? <MdView content={text} /> : trunc(text, 300)}
              </div>
            </div>
          );
        })}
      </div>

      <button onClick={() => setExpanded((e) => !e)} style={{
        alignSelf: "flex-start", background: "none", border: "1px solid var(--border)",
        borderRadius: 4, color: "var(--dim)", cursor: "pointer", fontSize: 10,
        padding: "2px 8px", textTransform: "uppercase", letterSpacing: "0.05em",
      }}>
        {expanded ? "▲ collapse" : "▼ expand"}
      </button>
    </div>
  );
}

// ── reward tab ────────────────────────────────────────────────────────────────

function RewardCard({ rec }: { rec: RewardRecord }) {
  const [expanded, setExpanded] = useState(false);
  const hasDims     = rec.dimensions && Object.keys(rec.dimensions).length > 0;
  const hasIssues   = rec.issues && rec.issues.length > 0;
  const hasFeedback = !!rec.feedback;

  return (
    <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "12px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
      {/* header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
        <div style={{ fontSize: 12, color: "var(--text)", lineHeight: 1.5, flex: 1 }}>{trunc(rec.prompt, 200)}</div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4, flexShrink: 0 }}>
          <ScoreBadge score={rec.score} />
          <div style={{ display: "flex", gap: 6 }}>
            {rec.task_type    && <span style={{ fontSize: 10, color: "var(--dim)" }}>{rec.task_type}</span>}
            {rec.wiggum_rounds != null && <span style={{ fontSize: 10, color: "var(--dim)" }}>{rec.wiggum_rounds}r</span>}
          </div>
        </div>
      </div>

      {/* response */}
      <div style={{
        fontSize: 11, lineHeight: 1.6, padding: "8px 10px",
        background: "var(--bg)", borderRadius: 5, borderLeft: `3px solid ${scoreColor(rec.score)}`,
        maxHeight: expanded ? 600 : 80, overflowY: "auto",
      }}>
        {expanded ? <MdView content={rec.response} /> : trunc(rec.response, 400)}
      </div>

      {/* dims */}
      {hasDims && <DimBars dims={rec.dimensions!} />}

      {/* issues */}
      {hasIssues && (
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          {rec.issues!.map((iss, i) => (
            <div key={i} style={{
              fontSize: 11, color: "var(--dim)", lineHeight: 1.45,
              padding: "3px 0 3px 10px", wordBreak: "break-word",
              borderLeft: "2px solid var(--warn)",
            }}>{iss}</div>
          ))}
        </div>
      )}

      {/* feedback */}
      {hasFeedback && (
        <div style={{ fontSize: 11, color: "var(--dim)", lineHeight: 1.6, fontStyle: "italic", borderTop: "1px solid var(--border)", paddingTop: 8 }}>
          {rec.feedback}
        </div>
      )}

      <button onClick={() => setExpanded((e) => !e)} style={{
        alignSelf: "flex-start", background: "none", border: "1px solid var(--border)",
        borderRadius: 4, color: "var(--dim)", cursor: "pointer", fontSize: 10,
        padding: "2px 8px", textTransform: "uppercase", letterSpacing: "0.05em",
      }}>
        {expanded ? "▲ collapse" : "▼ expand"}
      </button>
    </div>
  );
}

// ── dpo tab ───────────────────────────────────────────────────────────────────

function DpoCard({ rec }: { rec: DpoRecord }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "12px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
        <div style={{ fontSize: 12, color: "var(--text)", lineHeight: 1.5, flex: 1 }}>{trunc(rec.prompt, 200)}</div>
        <div style={{ flexShrink: 0, display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 3 }}>
          <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", fontWeight: 700, color: "var(--pass)" }}>Δ {rec.score_delta?.toFixed(1)}</span>
          {rec.task_type && <span style={{ fontSize: 10, color: "var(--dim)" }}>{rec.task_type}</span>}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        {(["chosen", "rejected"] as const).map((side) => {
          const text  = rec[side];
          const score = side === "chosen" ? rec.chosen_score : rec.rejected_score;
          const dims  = side === "chosen" ? rec.chosen_dims  : rec.rejected_dims;
          const bc    = side === "chosen" ? "var(--pass)"    : "var(--fail)";
          return (
            <div key={side} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.07em", color: bc, fontWeight: 700 }}>{side}</span>
                <ScoreBadge score={score} />
              </div>
              {dims && <DimBars dims={dims} />}
              <div style={{
                fontSize: 11, lineHeight: 1.6, padding: "8px 10px",
                background: "var(--bg)", borderRadius: 5, borderLeft: `3px solid ${bc}`,
                maxHeight: expanded ? 500 : 80, overflowY: "auto",
              }}>
                {expanded ? <MdView content={text} /> : trunc(text, 240)}
              </div>
            </div>
          );
        })}
      </div>

      {rec.wiggum_feedback && (
        <div style={{ fontSize: 11, color: "var(--dim)", lineHeight: 1.6, fontStyle: "italic", borderTop: "1px solid var(--border)", paddingTop: 8 }}>
          <span style={{ fontStyle: "normal", fontWeight: 600, color: "var(--text)", marginRight: 6 }}>Evaluator:</span>
          {rec.wiggum_feedback}
        </div>
      )}

      <button onClick={() => setExpanded((e) => !e)} style={{
        alignSelf: "flex-start", background: "none", border: "1px solid var(--border)",
        borderRadius: 4, color: "var(--dim)", cursor: "pointer", fontSize: 10,
        padding: "2px 8px", textTransform: "uppercase", letterSpacing: "0.05em",
      }}>
        {expanded ? "▲ collapse" : "▼ expand"}
      </button>
    </div>
  );
}

// ── grpo tab ──────────────────────────────────────────────────────────────────

function GrpoCard({ rec }: { rec: GrpoRecord }) {
  const [expanded, setExpanded] = useState(false);
  const sorted = [...rec.completions].sort((a, b) => b.reward - a.reward);
  return (
    <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "12px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
        <div style={{ fontSize: 12, color: "var(--text)", lineHeight: 1.5, flex: 1 }}>{trunc(rec.prompt, 200)}</div>
        <div style={{ flexShrink: 0, display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 3 }}>
          <ScoreBadge score={rec.mean_reward} />
          <span style={{ fontSize: 10, color: "var(--dim)" }}>{rec.n_rollouts} rollouts</span>
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {sorted.map((c, i) => (
          <div key={i} style={{
            display: "flex", gap: 8, fontSize: 11,
            padding: "6px 10px", background: "var(--bg)", borderRadius: 5,
            borderLeft: `3px solid ${scoreColor(c.reward)}`,
          }}>
            <div style={{ flexShrink: 0, display: "flex", flexDirection: "column", gap: 2, alignItems: "flex-end", minWidth: 52 }}>
              <span style={{ fontFamily: "var(--font-mono)", fontWeight: 700, color: scoreColor(c.reward) }}>{c.reward.toFixed(1)}</span>
              <span style={{ fontSize: 10, color: "var(--dim)" }}>t={c.temp}</span>
            </div>
            <div style={{ lineHeight: 1.6, flex: 1, overflowY: "auto", maxHeight: expanded ? 400 : 60 }}>
              {expanded ? <MdView content={c.content} /> : trunc(c.content, 220)}
            </div>
          </div>
        ))}
      </div>

      <button onClick={() => setExpanded((e) => !e)} style={{
        alignSelf: "flex-start", background: "none", border: "1px solid var(--border)",
        borderRadius: 4, color: "var(--dim)", cursor: "pointer", fontSize: 10,
        padding: "2px 8px", textTransform: "uppercase", letterSpacing: "0.05em",
      }}>
        {expanded ? "▲ collapse" : "▼ expand"}
      </button>
    </div>
  );
}

// ── RL data tab ───────────────────────────────────────────────────────────────

function RlTab() {
  const { data, isLoading, error } = useQuery<RlData>({
    queryKey: ["finetune-rl"],
    queryFn:  () => fetch("/api/finetune/rl").then((r) => r.json()),
    staleTime: 60_000,
  });

  const [sub, setSub] = useState("Preference");
  if (isLoading) return <div style={{ color: "var(--dim)", fontSize: 13 }}>Loading…</div>;
  if (error)     return <div style={{ color: "var(--fail)", fontSize: 13 }}>Failed to load RL data</div>;
  if (!data)     return null;

  const tabs = [
    `Preference (${data.preference.length})`,
    `Reward (${data.reward.length})`,
    `DPO (${data.dpo.length})`,
    `GRPO (${data.grpo.length})`,
  ];
  const activeTab = tabs.find((t) => t.startsWith(sub)) ?? tabs[0];

  return (
    <div>
      <TabBar tabs={tabs} active={activeTab} onChange={(t) => setSub(t.split(" ")[0])} />
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {sub === "Preference" && data.preference.map((p, i) => <PreferenceCard key={i} pair={p} />)}
        {sub === "Reward"     && data.reward.map((r, i)     => <RewardCard     key={i} rec={r} />)}
        {sub === "DPO"        && data.dpo.map((d, i)        => <DpoCard        key={i} rec={d} />)}
        {sub === "GRPO"       && data.grpo.map((g, i)        => <GrpoCard       key={i} rec={g} />)}
      </div>
    </div>
  );
}

// ── root view ─────────────────────────────────────────────────────────────────

export function Finetune() {
  const [tab, setTab] = useState("Training");
  return (
    <div style={{ padding: "24px 28px", display: "flex", flexDirection: "column", gap: 4, height: "100%", overflowY: "auto" }}>
      <h1 style={{ margin: "0 0 16px", fontSize: 18, fontWeight: 700, color: "var(--text)" }}>Fine-tune</h1>
      <TabBar tabs={["Training", "RL Data"]} active={tab} onChange={setTab} />
      {tab === "Training" && <TrainingTab />}
      {tab === "RL Data"  && <RlTab />}
    </div>
  );
}

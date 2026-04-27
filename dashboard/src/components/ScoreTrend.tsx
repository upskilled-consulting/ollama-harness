import { LineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer } from "recharts";
import type { ScoreTrendPoint } from "@/types";

interface Props { data: ScoreTrendPoint[] }

const TASK_COLORS: Record<string, string> = {
  enumerated:     "#60a5fa",
  best_practices: "#34d399",
  research:       "#f59e0b",
};

export function ScoreTrend({ data }: Props) {
  return (
    <ResponsiveContainer width="100%" height={240}>
      <LineChart data={data} margin={{ top: 4, right: 16, bottom: 4, left: 0 }}>
        <XAxis dataKey="i" hide />
        <YAxis domain={[0, 10]} ticks={[0, 2, 4, 6, 8, 10]} width={24} />
        <Tooltip
          formatter={(v: number) => v.toFixed(2)}
          labelFormatter={(i) => `Run ${i}`}
        />
        <ReferenceLine y={8} stroke="#f87171" strokeDasharray="4 2" label={{ value: "pass", fill: "#f87171", fontSize: 11 }} />
        <Line
          type="monotone"
          dataKey="score"
          dot={{ r: 3 }}
          strokeWidth={2}
          stroke="#818cf8"
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

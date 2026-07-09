/* ── DAG layout constants ── */
const VW = 980, VH = 500;
const NW = 128, NH = 40, NR = 6;          // node width / height / corner-radius
const HW = NW / 2;                         // half-width for edge attachment

/* ── Colors ── */
const C = {
  blue:   "#60a5fa",
  orange: "#f59e0b",
  green:  "#34d399",
  purple: "#a78bfa",
  accent: "#64c8b4",
  dim:    "rgba(100,200,180,0.3)",
  bg:     "#141820",
  border: "rgba(100,200,180,0.13)",
  text:   "rgba(220,235,230,0.92)",
  textDim:"rgba(100,200,180,0.55)",
};

/* ── Node definitions ── */
type N = { id: string; label: string; label2?: string; cx: number; cy: number; color: string };

const NODES: N[] = [
  // col 0 — input
  { id: "task",    label: "Task Query",     cx: 75,  cy: 245, color: C.accent },
  // col 1 — research
  { id: "wsearch", label: "Web Search",     cx: 235, cy: 100, color: C.blue   },
  { id: "bbk",     label: "Beige Book",     cx: 235, cy: 200, color: C.orange },
  // col 2 — economic APIs + market DB
  { id: "fred",    label: "FRED",           cx: 405, cy: 130, color: C.orange },
  { id: "bea",     label: "BEA",            cx: 405, cy: 235, color: C.orange },
  { id: "trending",label: "Trending DB",    cx: 405, cy: 370, color: C.green  },
  // col 3 — derived market data
  { id: "signals", label: "Market",         label2: "Signals", cx: 568, cy: 195, color: C.green  },
  { id: "yf",      label: "yfinance",       cx: 568, cy: 320, color: C.green  },
  { id: "alpaca",  label: "Alpaca",         label2: "Portfolio", cx: 568, cy: 430, color: C.purple },
  // col 4 — pipeline core
  { id: "merge",   label: "Context Merge",  cx: 735, cy: 240, color: C.accent },
  { id: "synth",   label: "LLM Synthesis",  cx: 735, cy: 380, color: C.accent },
  // col 5 — output
  { id: "wiggum",  label: "Wiggum Eval",    cx: 910, cy: 150, color: C.orange },
  { id: "report",  label: "Report (.md)",   cx: 910, cy: 275, color: C.green  },
  { id: "orders",  label: "Alpaca Orders",  cx: 910, cy: 395, color: C.purple },
];

const nodeMap = Object.fromEntries(NODES.map(n => [n.id, n]));

/* ── Edge definitions ── */
type E = { from: string; to: string; color: string; dashed?: boolean; below?: boolean };

const EDGES: E[] = [
  // task → research
  { from: "task",    to: "wsearch",  color: C.blue   },
  { from: "task",    to: "bbk",      color: C.orange },
  // task → economic APIs (long beziers)
  { from: "task",    to: "fred",     color: C.orange },
  { from: "task",    to: "bea",      color: C.orange },
  // task → alpaca (routed below)
  { from: "task",    to: "alpaca",   color: C.purple, below: true },
  // market DB chain
  { from: "trending",to: "signals",  color: C.green  },
  { from: "signals", to: "yf",       color: C.green, dashed: true },
  // all sources → merge
  { from: "wsearch", to: "merge",    color: C.blue   },
  { from: "bbk",     to: "merge",    color: C.orange },
  { from: "fred",    to: "merge",    color: C.orange },
  { from: "bea",     to: "merge",    color: C.orange },
  { from: "signals", to: "merge",    color: C.green  },
  { from: "yf",      to: "merge",    color: C.green  },
  { from: "alpaca",  to: "merge",    color: C.purple },
  // core pipeline
  { from: "merge",   to: "synth",    color: C.accent },
  { from: "synth",   to: "wiggum",   color: C.accent },
  { from: "wiggum",  to: "report",   color: C.green  },
  // conditional output
  { from: "synth",   to: "orders",   color: C.purple, dashed: true },
];

/* ── Arrow marker IDs ── */
const MARKER_COLORS = [C.blue, C.orange, C.green, C.purple, C.accent];

function mkId(color: string) {
  return `arr-${color.replace(/[^a-zA-Z0-9]/g, "")}`;
}

/* ── SVG helpers ── */
function bezierPath(x1: number, y1: number, x2: number, y2: number): string {
  const mx = (x1 + x2) / 2;
  return `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`;
}

function belowPath(x1: number, y1: number, x2: number, y2: number): string {
  // Route the edge below the diagram
  const bot = VH - 20;
  return `M ${x1} ${y1} C ${x1 + 40} ${bot}, ${x2 - 40} ${bot}, ${x2} ${y2}`;
}

/* ── Node component ── */
function Node({ n }: { n: N }) {
  const twoLine = !!n.label2;
  return (
    <g>
      <rect
        x={n.cx - HW} y={n.cy - NH / 2}
        width={NW} height={NH} rx={NR}
        fill={C.bg}
        stroke={n.color}
        strokeWidth={1.5}
        opacity={0.92}
      />
      {twoLine ? (
        <>
          <text
            x={n.cx} y={n.cy - 5}
            textAnchor="middle" dominantBaseline="middle"
            fontSize={11} fill={n.color} fontFamily="Inconsolata,monospace" letterSpacing="0.05em"
          >
            {n.label}
          </text>
          <text
            x={n.cx} y={n.cy + 9}
            textAnchor="middle" dominantBaseline="middle"
            fontSize={11} fill={n.color} fontFamily="Inconsolata,monospace" letterSpacing="0.05em"
          >
            {n.label2}
          </text>
        </>
      ) : (
        <text
          x={n.cx} y={n.cy}
          textAnchor="middle" dominantBaseline="middle"
          fontSize={11} fill={n.color} fontFamily="Inconsolata,monospace" letterSpacing="0.05em"
        >
          {n.label}
        </text>
      )}
    </g>
  );
}

/* ── Edge component ── */
function Edge({ e }: { e: E }) {
  const f = nodeMap[e.from], t = nodeMap[e.to];
  if (!f || !t) return null;

  let d: string;
  // Determine attachment points
  // Vertical edges (same column, top-to-bottom)
  if (Math.abs(f.cx - t.cx) < 20) {
    // same column — connect bottom to top
    const x1 = f.cx, y1 = f.cy + NH / 2;
    const x2 = t.cx, y2 = t.cy - NH / 2;
    d = `M ${x1} ${y1} L ${x2} ${y2}`;
  } else if (e.below) {
    d = belowPath(f.cx + HW, f.cy, t.cx - HW, t.cy);
  } else if (f.cx < t.cx) {
    // left to right — right side of source, left side of dest
    d = bezierPath(f.cx + HW, f.cy, t.cx - HW, t.cy);
  } else {
    // right to left — shouldn't happen in this DAG
    d = bezierPath(f.cx - HW, f.cy, t.cx + HW, t.cy);
  }

  return (
    <path
      d={d}
      stroke={e.color}
      strokeWidth={1.4}
      fill="none"
      strokeDasharray={e.dashed ? "5 3" : undefined}
      markerEnd={`url(#${mkId(e.color)})`}
      opacity={0.55}
      className="dag-pulse"
    />
  );
}

/* ── Legend ── */
const LEGEND = [
  { color: C.blue,   label: "Research" },
  { color: C.orange, label: "Economic APIs" },
  { color: C.green,  label: "Market Data" },
  { color: C.purple, label: "Portfolio / Execution" },
  { color: C.accent, label: "Core Pipeline" },
];

/* ── Main view ── */
export function Pipeline() {
  return (
    <div>
      <div className="view-header">
        <h1>Pipeline</h1>
        <p>Data enrichment DAG — macro to micro, context to action</p>
      </div>

      <div className="card" style={{ padding: "20px 16px" }}>
        <svg
          viewBox={`0 0 ${VW} ${VH}`}
          style={{ width: "100%", height: "auto", display: "block" }}
          aria-label="Enrichment pipeline DAG"
        >
          <defs>
            {MARKER_COLORS.map(color => (
              <marker
                key={color}
                id={mkId(color)}
                markerWidth="7" markerHeight="7"
                refX="6" refY="3.5"
                orient="auto"
              >
                <polygon points="0 0, 7 3.5, 0 7" fill={color} opacity={0.7} />
              </marker>
            ))}
          </defs>

          {/* Column labels */}
          {[
            { x: 75,  label: "Input"       },
            { x: 235, label: "Research"    },
            { x: 405, label: "Knowledge"   },
            { x: 568, label: "Market Data" },
            { x: 735, label: "Synthesis"   },
            { x: 910, label: "Output"      },
          ].map(col => (
            <text
              key={col.x}
              x={col.x} y={22}
              textAnchor="middle"
              fontSize={9} fill={C.textDim}
              fontFamily="Inconsolata,monospace"
              letterSpacing="0.12em"
              textDecoration="none"
              style={{ textTransform: "uppercase" }}
            >
              {col.label.toUpperCase()}
            </text>
          ))}

          {/* Divider line */}
          <line x1={0} y1={32} x2={VW} y2={32} stroke={C.border} strokeWidth={1} />

          {/* Edges (drawn first, nodes on top) */}
          {EDGES.map((e, i) => <Edge key={i} e={e} />)}

          {/* Nodes */}
          {NODES.map(n => <Node key={n.id} n={n} />)}
        </svg>

        {/* Legend */}
        <div style={{
          display: "flex", flexWrap: "wrap", gap: "16px",
          marginTop: "14px", paddingTop: "12px",
          borderTop: `1px solid ${C.border}`,
        }}>
          {LEGEND.map(({ color, label }) => (
            <div key={label} style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <div style={{
                width: 20, height: 2, background: color, borderRadius: 1,
              }} />
              <span style={{ fontSize: 11, color: C.textDim, letterSpacing: "0.06em", fontFamily: "Inconsolata,monospace" }}>
                {label.toUpperCase()}
              </span>
            </div>
          ))}
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <div style={{
              width: 20, height: 2,
              background: `repeating-linear-gradient(90deg, ${C.purple} 0px, ${C.purple} 5px, transparent 5px, transparent 8px)`,
            }} />
            <span style={{ fontSize: 11, color: C.textDim, letterSpacing: "0.06em", fontFamily: "Inconsolata,monospace" }}>
              CONDITIONAL
            </span>
          </div>
        </div>
      </div>

      {/* Stage descriptions */}
      <div className="section" style={{ marginTop: 24 }}>
        <div className="section-title">Enrichment layers</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 10 }}>
          {[
            {
              label: "Research",
              color: C.blue,
              items: ["Web Search — live search results for the query", "Beige Book — Fed district economic narrative"],
            },
            {
              label: "Economic APIs",
              color: C.orange,
              items: ["FRED — rates, inflation, employment time series", "BEA — GDP, regional income, trade balances"],
            },
            {
              label: "Market Data",
              color: C.green,
              items: [
                "Trending Tickers DB — momentum universe from yfinance",
                "Market Signals — Hurst, Bollinger, cointegration, momentum rank",
                "yfinance — live fundamentals, earnings, analyst targets",
              ],
            },
            {
              label: "Portfolio",
              color: C.purple,
              items: ["Alpaca Portfolio — current positions, buying power, pending orders"],
            },
            {
              label: "Core Pipeline",
              color: C.accent,
              items: [
                "Context Merge — all enrichment blocks concatenated",
                "LLM Synthesis — producer model generates report or thesis",
                "Wiggum Eval — multi-round quality gate with revision",
              ],
            },
            {
              label: "Output",
              color: C.green,
              items: [
                "Report (.md) — saved to runs, scored by Wiggum",
                "Alpaca Orders — paper trade execution (trading thesis tasks only)",
              ],
            },
          ].map(stage => (
            <div key={stage.label} className="card">
              <div className="card-title" style={{ color: stage.color }}>{stage.label}</div>
              <ul style={{ listStyle: "none", display: "flex", flexDirection: "column", gap: 5 }}>
                {stage.items.map(item => {
                  const [name, desc] = item.split(" — ");
                  return (
                    <li key={item} style={{ fontSize: 12, lineHeight: 1.5 }}>
                      <span style={{ color: stage.color, fontFamily: "Inconsolata,monospace" }}>{name}</span>
                      {desc && <span style={{ color: C.textDim }}> — {desc}</span>}
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

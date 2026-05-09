import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useGithub } from "@/hooks/useRuns";
import { api } from "@/api/client";
import type { GhCommit, GhCommitDetail, GhIssue, GhPr, GhRun } from "@/types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function ago(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60_000);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

function CiDot({ status, conclusion }: { status: string; conclusion: string | null }) {
  let color = "var(--dim)";
  if (status === "in_progress" || status === "queued") color = "var(--warn)";
  else if (conclusion === "success") color = "var(--pass)";
  else if (conclusion === "failure" || conclusion === "timed_out") color = "var(--fail)";
  else if (conclusion === "cancelled" || conclusion === "skipped") color = "var(--dim)";
  return (
    <span
      style={{
        display: "inline-block",
        width: 8, height: 8,
        borderRadius: "50%",
        background: color,
        flexShrink: 0,
        marginTop: 1,
        ...(status === "in_progress" ? { animation: "pulse 1.5s infinite" } : {}),
      }}
    />
  );
}

// ---------------------------------------------------------------------------
// Section: Local repo card
// ---------------------------------------------------------------------------

function RepoCard() {
  const { repo } = useGithub();
  const d = repo.data;

  const dot = (n: number, color: string) =>
    n > 0 ? <span style={{ color, fontWeight: 700 }}>{n}</span> : <span style={{ color: "var(--dim)" }}>0</span>;

  return (
    <div className="card" style={{ marginBottom: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        {/* Repo name */}
        <div style={{ fontWeight: 700, fontSize: 15 }}>
          {d?.meta ? (
            <a href={d.meta.url} target="_blank" rel="noreferrer" style={{ color: "var(--accent)", textDecoration: "none" }}>
              {d.meta.owner.login}/{d.meta.name}
            </a>
          ) : (
            <span style={{ color: "var(--dim)" }}>—</span>
          )}
          {d?.meta?.isPrivate && (
            <span style={{ marginLeft: 6, fontSize: 10, color: "var(--dim)", border: "1px solid var(--border)", borderRadius: 4, padding: "1px 4px" }}>
              private
            </span>
          )}
        </div>

        <div style={{ display: "flex", gap: 20, fontSize: 12, color: "var(--dim)", flexWrap: "wrap" }}>
          {/* Branch */}
          <span>
            <span style={{ opacity: 0.6 }}>branch </span>
            <code style={{ color: "var(--text)", fontFamily: "var(--font-mono)" }}>{d?.branch ?? "…"}</code>
          </span>

          {/* Ahead / behind */}
          {d && (d.ahead > 0 || d.behind > 0) && (
            <span>
              {d.ahead > 0 && <span style={{ color: "var(--pass)" }}>↑{d.ahead}</span>}
              {d.behind > 0 && <span style={{ color: "var(--warn)", marginLeft: d.ahead > 0 ? 4 : 0 }}>↓{d.behind}</span>}
            </span>
          )}

          {/* Dirty files */}
          <span>
            <span style={{ opacity: 0.6 }}>dirty </span>
            {dot(d?.dirty_files ?? 0, "var(--warn)")}
          </span>

          {/* Stars / forks */}
          {d?.meta && (
            <>
              <span>★ {d.meta.stargazerCount}</span>
              <span>⑂ {d.meta.forkCount}</span>
            </>
          )}
        </div>
      </div>
      {d?.meta?.description && (
        <div style={{ marginTop: 6, fontSize: 12, color: "var(--dim)" }}>{d.meta.description}</div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Pull requests
// ---------------------------------------------------------------------------

function PrRow({ pr }: { pr: GhPr }) {
  const url = `https://github.com/${pr.author?.login ?? ""}`;
  const color = pr.isDraft ? "var(--dim)" : pr.reviewDecision === "APPROVED" ? "var(--pass)" : "var(--accent)";
  return (
    <div style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--dim)", flexShrink: 0, paddingTop: 1 }}>
        #{pr.number}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {pr.isDraft && <span style={{ fontSize: 10, color: "var(--dim)", marginRight: 6, border: "1px solid var(--border)", borderRadius: 3, padding: "1px 4px" }}>draft</span>}
          {pr.title}
        </div>
        <div style={{ fontSize: 11, color: "var(--dim)", marginTop: 2 }}>
          <code style={{ fontFamily: "var(--font-mono)", marginRight: 8 }}>{pr.headRefName}</code>
          by <a href={url} target="_blank" rel="noreferrer" style={{ color: "var(--dim)" }}>{pr.author?.login}</a>
          &nbsp;· {ago(pr.createdAt)}
        </div>
      </div>
      <span style={{ fontSize: 10, color, flexShrink: 0, paddingTop: 2 }}>
        {pr.reviewDecision === "APPROVED" ? "approved" : pr.isDraft ? "draft" : "open"}
      </span>
    </div>
  );
}

function PrsSection() {
  const { prs } = useGithub();
  const list = prs.data ?? [];
  return (
    <div className="card">
      <div className="card-title" style={{ marginBottom: 4 }}>
        Pull requests
        <span style={{ marginLeft: 8, fontWeight: 400, color: "var(--dim)", fontSize: 11 }}>{list.length} open</span>
      </div>
      {prs.isLoading && <div style={{ color: "var(--dim)", fontSize: 12 }}>Loading…</div>}
      {!prs.isLoading && list.length === 0 && <div style={{ color: "var(--dim)", fontSize: 12 }}>No open pull requests.</div>}
      {list.map((pr) => <PrRow key={pr.number} pr={pr} />)}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Issues
// ---------------------------------------------------------------------------

function IssueRow({ issue }: { issue: GhIssue }) {
  return (
    <div style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--dim)", flexShrink: 0, paddingTop: 1 }}>
        #{issue.number}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {issue.title}
        </div>
        <div style={{ fontSize: 11, color: "var(--dim)", marginTop: 2, display: "flex", gap: 8, flexWrap: "wrap" }}>
          <span>by {issue.author?.login}</span>
          <span>· {ago(issue.createdAt)}</span>
          {issue.labels.map((l) => (
            <span
              key={l.name}
              style={{
                background: `#${l.color}22`,
                color: `#${l.color}`,
                border: `1px solid #${l.color}55`,
                borderRadius: 4,
                padding: "0 5px",
                fontSize: 10,
              }}
            >
              {l.name}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function IssuesSection() {
  const { issues } = useGithub();
  const list = issues.data ?? [];
  return (
    <div className="card">
      <div className="card-title" style={{ marginBottom: 4 }}>
        Issues
        <span style={{ marginLeft: 8, fontWeight: 400, color: "var(--dim)", fontSize: 11 }}>{list.length} open</span>
      </div>
      {issues.isLoading && <div style={{ color: "var(--dim)", fontSize: 12 }}>Loading…</div>}
      {!issues.isLoading && list.length === 0 && <div style={{ color: "var(--dim)", fontSize: 12 }}>No open issues.</div>}
      {list.map((issue) => <IssueRow key={issue.number} issue={issue} />)}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: CI runs
// ---------------------------------------------------------------------------

function RunRow({ run }: { run: GhRun }) {
  return (
    <div style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
      <CiDot status={run.status} conclusion={run.conclusion} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          <a href={run.url} target="_blank" rel="noreferrer" style={{ color: "inherit", textDecoration: "none" }}>{run.name}</a>
        </div>
        <div style={{ fontSize: 11, color: "var(--dim)", marginTop: 2 }}>
          <code style={{ fontFamily: "var(--font-mono)", marginRight: 6 }}>{run.headBranch}</code>
          · {run.event} · {ago(run.createdAt)}
        </div>
      </div>
      <span style={{
        fontSize: 10, flexShrink: 0, paddingTop: 2,
        color: run.conclusion === "success" ? "var(--pass)"
             : run.conclusion === "failure" ? "var(--fail)"
             : run.status === "in_progress" ? "var(--warn)"
             : "var(--dim)",
      }}>
        {run.status === "in_progress" ? "running" : (run.conclusion ?? run.status)}
      </span>
    </div>
  );
}

function CiSection() {
  const { runs } = useGithub();
  const list = runs.data ?? [];
  return (
    <div className="card">
      <div className="card-title" style={{ marginBottom: 4 }}>CI runs</div>
      {runs.isLoading && <div style={{ color: "var(--dim)", fontSize: 12 }}>Loading…</div>}
      {!runs.isLoading && list.length === 0 && <div style={{ color: "var(--dim)", fontSize: 12 }}>No recent CI runs.</div>}
      {list.map((run) => <RunRow key={run.databaseId} run={run} />)}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Commit heatmap
// ---------------------------------------------------------------------------

const CELL = 11;
const GAP  = 2;
const STEP = CELL + GAP;

function cellColor(count: number): string {
  if (count <= 0) return "rgba(255,255,255,0.05)";
  if (count === 1) return "rgba(34,211,238,0.22)";
  if (count === 2) return "rgba(34,211,238,0.45)";
  if (count === 3) return "rgba(34,211,238,0.65)";
  return "rgba(34,211,238,0.90)";
}

type GridCell = { date: string; count: number; future: boolean };

function buildGrid(commits: GhCommit[]): { weeks: GridCell[][]; months: { label: string; col: number }[] } {
  const countByDate = new Map<string, number>();
  for (const c of commits) {
    if (c.date) countByDate.set(c.date, (countByDate.get(c.date) ?? 0) + 1);
  }

  const today = new Date();
  // Start on the Sunday 52 weeks ago
  const start = new Date(today);
  start.setDate(today.getDate() - 52 * 7 + 1);
  start.setDate(start.getDate() - start.getDay()); // back to Sunday

  const weeks: GridCell[][] = [];
  const months: { label: string; col: number }[] = [];
  const cur = new Date(start);
  let lastMonth = -1;

  while (cur <= today || weeks[weeks.length - 1]?.length < 7) {
    if (cur.getDay() === 0) {
      if (weeks.length >= 53) break;
      weeks.push([]);
    }
    const dateStr = cur.toISOString().slice(0, 10);
    const future  = cur > today;
    weeks[weeks.length - 1].push({ date: dateStr, count: future ? 0 : (countByDate.get(dateStr) ?? 0), future });

    if (!future && cur.getDate() <= 7 && cur.getMonth() !== lastMonth) {
      lastMonth = cur.getMonth();
      months.push({
        label: cur.toLocaleString("en-US", { month: "short" }),
        col:   weeks.length - 1,
      });
    }
    cur.setDate(cur.getDate() + 1);
  }

  return { weeks, months };
}

// ── Commit detail drawer ────────────────────────────────────────────────────

function DiffView({ diff }: { diff: string }) {
  return (
    <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, lineHeight: 1.55, overflowX: "auto" }}>
      {diff.split("\n").map((line, i) => {
        const color = line.startsWith("+") && !line.startsWith("+++") ? "rgba(63,185,80,0.9)"
                    : line.startsWith("-") && !line.startsWith("---") ? "rgba(248,81,73,0.9)"
                    : line.startsWith("@@") ? "rgba(167,139,250,0.9)"
                    : line.startsWith("diff ") || line.startsWith("index ") ? "var(--accent)"
                    : "var(--dim)";
        const bg = line.startsWith("+") && !line.startsWith("+++") ? "rgba(63,185,80,0.06)"
                 : line.startsWith("-") && !line.startsWith("---") ? "rgba(248,81,73,0.06)"
                 : "transparent";
        return (
          <div key={i} style={{ color, background: bg, whiteSpace: "pre", paddingLeft: 4 }}>{line || " "}</div>
        );
      })}
    </div>
  );
}

function CommitDetailDrawer({ sha, repoUrl, onClose }: { sha: string; repoUrl: string | null; onClose: () => void }) {
  const { data, isLoading } = useQuery<GhCommitDetail>({
    queryKey:  ["commit_detail", sha],
    queryFn:   () => api.github_commit_detail(sha),
    staleTime: Infinity,
  });

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 800,
      display: "flex", alignItems: "stretch", justifyContent: "flex-end",
    }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      {/* scrim */}
      <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.4)" }} onClick={onClose} />

      {/* drawer */}
      <div style={{
        position: "relative", width: "min(680px, 92vw)", height: "100%",
        background: "var(--surface)", borderLeft: "1px solid var(--border)",
        display: "flex", flexDirection: "column", overflow: "hidden",
        boxShadow: "-12px 0 40px rgba(0,0,0,0.5)",
        animation: "slideInRight 0.18s ease",
      }}>
        {/* header */}
        <div style={{
          display: "flex", alignItems: "center", gap: 10,
          padding: "12px 16px", borderBottom: "1px solid var(--border)",
          background: "var(--bg)", flexShrink: 0,
        }}>
          <code style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--accent)", flex: 1 }}>{sha.slice(0, 12)}</code>
          {repoUrl && (
            <a
              href={`${repoUrl}/commit/${sha}`}
              target="_blank"
              rel="noreferrer"
              style={{
                fontSize: 11, color: "var(--dim)", textDecoration: "none",
                border: "1px solid var(--border)", borderRadius: 4,
                padding: "2px 8px", flexShrink: 0,
              }}
              onMouseEnter={(e) => (e.currentTarget.style.color = "var(--text)")}
              onMouseLeave={(e) => (e.currentTarget.style.color = "var(--dim)")}
            >
              View on GitHub ↗
            </a>
          )}
          <button onClick={onClose} style={{ background: "none", border: "none", color: "var(--dim)", cursor: "pointer", padding: 2 }}>
            <X size={16} />
          </button>
        </div>

        {isLoading && <div style={{ padding: 24, color: "var(--dim)", fontSize: 12 }}>Loading diff…</div>}

        {data && (
          <div style={{ flex: 1, overflowY: "auto", padding: "14px 16px", display: "flex", flexDirection: "column", gap: 16 }}>
            {/* commit message */}
            <div>
              <div style={{ fontSize: 10, color: "var(--dim)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>Message</div>
              <pre style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text)", whiteSpace: "pre-wrap", margin: 0 }}>{data.message}</pre>
            </div>

            {/* files changed */}
            {data.files.length > 0 && (
              <div>
                <div style={{ fontSize: 10, color: "var(--dim)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>
                  Files changed ({data.files.length})
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  {data.files.map((f, i) => {
                    const color = f.status === "A" ? "var(--pass)" : f.status === "D" ? "var(--fail)" : f.status === "M" ? "var(--warn)" : "var(--dim)";
                    const label = f.status === "A" ? "A" : f.status === "D" ? "D" : f.status === "M" ? "M" : f.status;
                    return (
                      <div key={i} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12 }}>
                        <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color, width: 14, textAlign: "center", flexShrink: 0 }}>{label}</span>
                        <span style={{ fontFamily: "var(--font-mono)", color: "var(--text)" }}>{f.file}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* diff */}
            <div>
              <div style={{ fontSize: 10, color: "var(--dim)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>Diff</div>
              <div style={{
                background: "#0a0c12", border: "1px solid var(--border)", borderRadius: 6,
                padding: "10px 12px", overflowX: "auto",
              }}>
                <DiffView diff={data.diff} />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Day popup ───────────────────────────────────────────────────────────────

function DayPopup({ date, commits, anchor, onClose, onSelectCommit }: {
  date: string;
  commits: GhCommit[];
  anchor: { x: number; y: number };
  onClose: () => void;
  onSelectCommit: (sha: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    // small delay so the click that opened it doesn't immediately close it
    const t = setTimeout(() => document.addEventListener("mousedown", handler), 80);
    return () => { clearTimeout(t); document.removeEventListener("mousedown", handler); };
  }, [onClose]);

  // flip left if too close to right edge
  const flipLeft = anchor.x > window.innerWidth - 280;

  return (
    <div ref={ref} style={{
      position: "fixed",
      top:  anchor.y + 8,
      left: flipLeft ? anchor.x - 240 : anchor.x,
      width: 260,
      background: "var(--surface)", border: "1px solid var(--border)",
      borderRadius: 8, boxShadow: "0 12px 32px rgba(0,0,0,0.5)",
      zIndex: 700, overflow: "hidden",
    }}>
      <div style={{
        padding: "8px 12px", borderBottom: "1px solid var(--border)",
        fontSize: 11, color: "var(--dim)", fontFamily: "var(--font-mono)",
        display: "flex", justifyContent: "space-between", alignItems: "center",
      }}>
        <span>{date}</span>
        <span style={{ color: "var(--accent)" }}>{commits.length} commit{commits.length !== 1 ? "s" : ""}</span>
      </div>
      {commits.length === 0 ? (
        <div style={{ padding: "10px 12px", fontSize: 12, color: "var(--dim)" }}>No commits this day.</div>
      ) : (
        <div style={{ maxHeight: 260, overflowY: "auto" }}>
          {commits.map((c) => (
            <div key={c.sha}
              onClick={() => { onSelectCommit(c.sha); onClose(); }}
              style={{
                padding: "8px 12px", cursor: "pointer", borderBottom: "1px solid rgba(42,45,58,0.5)",
                transition: "background 0.1s",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(129,140,248,0.08)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "none")}
            >
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 2 }}>
                <code style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--accent)", flexShrink: 0 }}>{c.short}</code>
                <span style={{ fontSize: 10, color: "var(--dim)", marginLeft: "auto", flexShrink: 0 }}>{c.ago}</span>
              </div>
              <div style={{ fontSize: 12, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.message}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main heatmap component ──────────────────────────────────────────────────

const DAY_LABELS = ["S", "M", "T", "W", "T", "F", "S"];

function CommitHeatmap({ onSelectCommit }: { onSelectCommit: (sha: string) => void }) {
  const { commits } = useGithub();
  const list = commits.data ?? [];

  const [popup, setPopup] = useState<{ date: string; x: number; y: number } | null>(null);

  const { weeks, months } = useMemo(() => buildGrid(list), [list]);

  const byDate = useMemo(() => {
    const m = new Map<string, GhCommit[]>();
    for (const c of list) {
      if (c.date) {
        const arr = m.get(c.date) ?? [];
        arr.push(c);
        m.set(c.date, arr);
      }
    }
    return m;
  }, [list]);

  const handleCellClick = useCallback((e: React.MouseEvent, day: GridCell) => {
    if (day.future || day.count === 0) { setPopup(null); return; }
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setPopup({ date: day.date, x: rect.left + rect.width / 2, y: rect.bottom });
  }, []);

  return (
    <>
      <div className="card" style={{ marginBottom: 0 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
          <span className="card-title" style={{ margin: 0 }}>
            Commit activity
            {commits.isLoading
              ? <span style={{ marginLeft: 8, fontWeight: 400, color: "var(--dim)", fontSize: 11 }}>loading…</span>
              : list.length > 0
                ? <span style={{ marginLeft: 8, fontWeight: 400, color: "var(--dim)", fontSize: 11 }}>{list.length} commits · past year</span>
                : null}
          </span>
          {/* legend */}
          <div style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10, color: "var(--dim)" }}>
            <span>less</span>
            {[0, 1, 2, 3, 4].map((n) => (
              <div key={n} style={{
                width: CELL, height: CELL, borderRadius: 2,
                background: cellColor(n), border: "1px solid rgba(255,255,255,0.06)",
              }} />
            ))}
            <span>more</span>
          </div>
        </div>

        {/* grid always renders; fills in when data arrives */}
        <div style={{ overflowX: "auto", opacity: commits.isLoading ? 0.35 : 1, transition: "opacity 0.3s" }}>
          <div style={{ display: "flex", gap: 6 }}>
            {/* day labels */}
            <div style={{ display: "flex", flexDirection: "column", gap: GAP, paddingTop: 18, flexShrink: 0 }}>
              {DAY_LABELS.map((d, i) => (
                <div key={i} style={{
                  width: 10, height: CELL, fontSize: 9, color: "var(--dim)",
                  display: "flex", alignItems: "center", justifyContent: "flex-end",
                  opacity: i % 2 === 0 ? 0 : 1,
                }}>{d}</div>
              ))}
            </div>

            {/* grid */}
            <div style={{ position: "relative" }}>
              {/* month labels */}
              <div style={{ height: 16, position: "relative", marginBottom: 2 }}>
                {months.map((m) => (
                  <span key={`${m.label}-${m.col}`} style={{
                    position: "absolute", left: m.col * STEP,
                    fontSize: 9, color: "var(--dim)", whiteSpace: "nowrap",
                  }}>{m.label}</span>
                ))}
              </div>

              {/* week columns */}
              <div style={{ display: "flex", gap: GAP }}>
                {weeks.map((week, wi) => (
                  <div key={wi} style={{ display: "flex", flexDirection: "column", gap: GAP }}>
                    {week.map((day, di) => (
                      <div key={di}
                        title={day.future ? "" : `${day.date}${day.count ? ` · ${day.count} commit${day.count !== 1 ? "s" : ""}` : ""}`}
                        onClick={(e) => handleCellClick(e, day)}
                        style={{
                          width: CELL, height: CELL, borderRadius: 2,
                          background: day.future ? "transparent" : cellColor(day.count),
                          border: day.future ? "none" : "1px solid rgba(255,255,255,0.06)",
                          cursor: (!day.future && day.count > 0) ? "pointer" : "default",
                          transition: "opacity 0.1s",
                        }}
                        onMouseEnter={(e) => { if (!day.future && day.count > 0) (e.currentTarget as HTMLDivElement).style.opacity = "0.75"; }}
                        onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.opacity = "1"; }}
                      />
                    ))}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Day popup */}
      {popup && (
        <DayPopup
          date={popup.date}
          commits={byDate.get(popup.date) ?? []}
          anchor={{ x: popup.x, y: popup.y }}
          onClose={() => setPopup(null)}
          onSelectCommit={onSelectCommit}
        />
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Commit list with search
// ---------------------------------------------------------------------------

function CommitList({ onSelectCommit }: { onSelectCommit: (sha: string) => void }) {
  const { commits } = useGithub();
  const list = commits.data ?? [];
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return list;
    return list.filter((c) =>
      c.message.toLowerCase().includes(q) ||
      c.author.toLowerCase().includes(q)  ||
      c.short.toLowerCase().includes(q)   ||
      (c.date ?? "").includes(q)          ||
      c.ago.toLowerCase().includes(q)
    );
  }, [list, query]);

  return (
    <div className="card" style={{ marginBottom: 0 }}>
      {/* header + search */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
        <span className="card-title" style={{ margin: 0, flexShrink: 0 }}>
          Commits
          <span style={{ marginLeft: 8, fontWeight: 400, color: "var(--dim)", fontSize: 11 }}>
            {query ? `${filtered.length} of ${list.length}` : list.length}
          </span>
        </span>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search message, author, SHA, date…"
          style={{
            flex: 1, background: "var(--bg)", border: "1px solid var(--border)",
            borderRadius: 6, padding: "5px 10px", fontSize: 12,
            color: "var(--text)", outline: "none",
            fontFamily: "inherit",
          }}
          onFocus={(e)  => (e.currentTarget.style.borderColor = "var(--accent)")}
          onBlur={(e)   => (e.currentTarget.style.borderColor = "var(--border)")}
        />
        {query && (
          <button
            onClick={() => setQuery("")}
            style={{ background: "none", border: "none", color: "var(--dim)", cursor: "pointer", fontSize: 13, padding: "0 2px", flexShrink: 0 }}
          >
            ✕
          </button>
        )}
      </div>

      {/* list */}
      {commits.isLoading ? (
        <div style={{ color: "var(--dim)", fontSize: 12 }}>Loading…</div>
      ) : filtered.length === 0 ? (
        <div style={{ color: "var(--dim)", fontSize: 12 }}>No commits match.</div>
      ) : (
        <div style={{ maxHeight: 420, overflowY: "auto" }}>
          {filtered.map((c) => (
            <div
              key={c.sha}
              onClick={() => onSelectCommit(c.sha)}
              style={{
                display: "flex", gap: 10, alignItems: "flex-start",
                padding: "7px 0", borderBottom: "1px solid rgba(42,45,58,0.5)",
                cursor: "pointer",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(129,140,248,0.06)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "none")}
            >
              <code style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--accent)", flexShrink: 0, paddingTop: 2 }}>
                {c.short}
              </code>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {c.message}
                </div>
                <div style={{ fontSize: 11, color: "var(--dim)", marginTop: 2 }}>
                  {c.author} · {c.date ?? c.ago}
                </div>
              </div>
              <span style={{ fontSize: 10, color: "var(--dim)", flexShrink: 0, paddingTop: 2, whiteSpace: "nowrap" }}>{c.ago}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Root view
// ---------------------------------------------------------------------------

export function Github() {
  const qc = useQueryClient();
  const { repo } = useGithub();
  const repoUrl  = repo.data?.meta?.url ?? null;

  const [detailSha, setDetailSha] = useState<string | null>(null);

  async function refresh() {
    await api.github_refresh();
    void qc.invalidateQueries({ queryKey: ["gh_repo"] });
    void qc.invalidateQueries({ queryKey: ["gh_prs"] });
    void qc.invalidateQueries({ queryKey: ["gh_issues"] });
    void qc.invalidateQueries({ queryKey: ["gh_runs"] });
    void qc.invalidateQueries({ queryKey: ["gh_commits"] });
  }

  return (
    <div>
      <style>{`
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
        @keyframes slideInRight { from { transform: translateX(100%); } to { transform: translateX(0); } }
      `}</style>

      <div className="view-header" style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <h1>GitHub</h1>
          <p>Repo health at a glance — PRs, issues, CI, commits</p>
        </div>
        <button
          onClick={() => void refresh()}
          style={{
            background: "var(--surface)", border: "1px solid var(--border)",
            color: "var(--dim)", borderRadius: 6, padding: "6px 14px",
            cursor: "pointer", fontSize: 12,
          }}
        >
          Refresh
        </button>
      </div>

      <RepoCard />

      <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 16 }}>
        <CommitHeatmap onSelectCommit={setDetailSha} />
        <CommitList    onSelectCommit={setDetailSha} />
      </div>

      {detailSha && (
        <CommitDetailDrawer sha={detailSha} repoUrl={repoUrl} onClose={() => setDetailSha(null)} />
      )}

      <div className="chart-grid-2" style={{ marginTop: 16 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <PrsSection />
          <CiSection />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <IssuesSection />
        </div>
      </div>
    </div>
  );
}

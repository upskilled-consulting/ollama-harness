import { useQueryClient } from "@tanstack/react-query";
import { useGithub } from "@/hooks/useRuns";
import { api } from "@/api/client";
import type { GhCommit, GhIssue, GhPr, GhRun } from "@/types";

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
// Section: Commits
// ---------------------------------------------------------------------------

function CommitRow({ c }: { c: GhCommit }) {
  return (
    <div style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "6px 0", borderBottom: "1px solid var(--border)" }}>
      <code style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--accent)", flexShrink: 0, paddingTop: 1 }}>
        {c.short}
      </code>
      <div style={{ flex: 1, minWidth: 0, fontSize: 12, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {c.message}
      </div>
      <span style={{ fontSize: 11, color: "var(--dim)", flexShrink: 0, paddingTop: 1 }}>{c.ago}</span>
    </div>
  );
}

function CommitsSection() {
  const { commits } = useGithub();
  const list = commits.data ?? [];
  return (
    <div className="card">
      <div className="card-title" style={{ marginBottom: 4 }}>Recent commits</div>
      {commits.isLoading && <div style={{ color: "var(--dim)", fontSize: 12 }}>Loading…</div>}
      {!commits.isLoading && list.length === 0 && <div style={{ color: "var(--dim)", fontSize: 12 }}>No commits found.</div>}
      {list.map((c) => <CommitRow key={c.sha} c={c} />)}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Root view
// ---------------------------------------------------------------------------

export function Github() {
  const qc = useQueryClient();

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
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.3; }
        }
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

      <div className="chart-grid-2" style={{ marginTop: 16 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <PrsSection />
          <CiSection />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <IssuesSection />
          <CommitsSection />
        </div>
      </div>
    </div>
  );
}

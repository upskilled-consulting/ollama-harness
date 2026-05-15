import { useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSystemFiles, useSystemFile, useSystemConfig, useSystemSkills } from "@/hooks/useRuns";
import { api } from "@/api/client";
import type { SkillEntry, SystemConfig, SystemFileMeta } from "@/types";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const HOOK_COLOR: Record<string, string> = {
  standalone:     "#6366f1",
  pre_research:   "#0ea5e9",
  pre_synthesis:  "#10b981",
  post_synthesis: "#f59e0b",
  post_wiggum:    "#ec4899",
  modifier:       "#8b5cf6",
};

const GROUP_ORDER = ["Governance", "Knowledge", "User"];

// Virtual entries rendered separately (not file content)
type VirtualKey = "config" | "skills";
type SelectedKey = string | VirtualKey;

// ---------------------------------------------------------------------------
// File list sidebar
// ---------------------------------------------------------------------------

function FileList({
  files, selected, onSelect,
}: {
  files: SystemFileMeta[];
  selected: SelectedKey;
  onSelect: (k: SelectedKey) => void;
}) {
  const grouped: Record<string, SystemFileMeta[]> = {};
  for (const f of files) {
    if (!grouped[f.group]) grouped[f.group] = [];
    grouped[f.group].push(f);
  }

  return (
    <div style={{
      width: 200, flexShrink: 0,
      borderRight: "1px solid var(--border, rgba(255,255,255,0.08))",
      paddingRight: 12, display: "flex", flexDirection: "column", gap: 18,
    }}>
      {GROUP_ORDER.filter((g) => grouped[g]).map((group) => (
        <div key={group}>
          <div style={{ fontSize: 10, color: "var(--dim)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
            {group}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {grouped[group].map((f) => (
              <button
                key={f.key}
                onClick={() => onSelect(f.key)}
                style={{
                  textAlign: "left", border: "none", cursor: "pointer",
                  padding: "5px 8px", borderRadius: 6, fontSize: 12,
                  color: selected === f.key ? "var(--accent, #818cf8)" : f.exists ? "inherit" : "var(--dim)",
                  background: selected === f.key ? "var(--accent-faint, rgba(99,102,241,0.12))" : "transparent",
                  fontFamily: f.label.startsWith(".") ? "var(--font-mono, monospace)" : "inherit",
                  display: "flex", alignItems: "center", gap: 6,
                }}
              >
                <span style={{ fontSize: 10, opacity: 0.5 }}>{f.label.endsWith(".toml") ? "⚙" : "📄"}</span>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.label}</span>
                {f.editable && (
                  <span style={{ marginLeft: "auto", fontSize: 9, color: "var(--dim)", opacity: 0.6 }}>edit</span>
                )}
              </button>
            ))}
          </div>
        </div>
      ))}

      {/* Virtual entries */}
      <div>
        <div style={{ fontSize: 10, color: "var(--dim)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
          Live
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {(["config", "skills"] as VirtualKey[]).map((k) => (
            <button
              key={k}
              onClick={() => onSelect(k)}
              style={{
                textAlign: "left", border: "none", cursor: "pointer",
                padding: "5px 8px", borderRadius: 6, fontSize: 12,
                color: selected === k ? "var(--accent, #818cf8)" : "inherit",
                background: selected === k ? "var(--accent-faint, rgba(99,102,241,0.12))" : "transparent",
                display: "flex", alignItems: "center", gap: 6,
              }}
            >
              <span style={{ fontSize: 10, opacity: 0.5 }}>{k === "config" ? "⚙" : "⚡"}</span>
              <span>{k === "config" ? "Active config" : "Skills registry"}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// File content pane
// ---------------------------------------------------------------------------

function FilePane({ fileKey }: { fileKey: string }) {
  const [editing, setEditing]   = useState(false);
  const [draft,   setDraft]     = useState<string | null>(null);
  const [saving,  setSaving]    = useState(false);
  const [saveMsg, setSaveMsg]   = useState("");
  const qc = useQueryClient();

  const { data: file, isLoading, error } = useSystemFile(fileKey);

  const startEdit = useCallback(() => {
    setDraft(file?.content ?? "");
    setEditing(true);
    setSaveMsg("");
  }, [file]);

  const cancel = useCallback(() => {
    setEditing(false);
    setDraft(null);
    setSaveMsg("");
  }, []);

  const save = useCallback(async () => {
    if (draft === null) return;
    setSaving(true);
    try {
      await api.system_file_save(fileKey, draft);
      await qc.invalidateQueries({ queryKey: ["system_file", fileKey] });
      setEditing(false);
      setDraft(null);
      setSaveMsg("Saved.");
      setTimeout(() => setSaveMsg(""), 3000);
    } catch (e) {
      setSaveMsg(`Error: ${e}`);
    } finally {
      setSaving(false);
    }
  }, [fileKey, draft, qc]);

  if (isLoading) return <div className="loading">Loading…</div>;
  if (error)     return <div className="page-error">Could not load file.</div>;
  if (!file)     return null;

  const isToml = file.label.endsWith(".toml");

  return (
    <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 0 }}>
      {/* Header bar */}
      <div style={{
        display: "flex", alignItems: "center", gap: 12, marginBottom: 14,
        paddingBottom: 10, borderBottom: "1px solid var(--border, rgba(255,255,255,0.08))",
      }}>
        <span className="mono" style={{ fontSize: 13, fontWeight: 600 }}>{file.label}</span>
        {file.size !== undefined && (
          <span style={{ fontSize: 11, color: "var(--dim)" }}>
            {(file.size / 1024).toFixed(1)} KB
          </span>
        )}
        {file.truncated && (
          <span style={{ fontSize: 11, color: "#f59e0b" }}>truncated at 80 KB</span>
        )}
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          {saveMsg && <span style={{ fontSize: 11, color: "#10b981" }}>{saveMsg}</span>}
          {file.editable && !editing && (
            <button onClick={startEdit} style={btnStyle("var(--accent, #6366f1)")}>Edit</button>
          )}
          {editing && <>
            <button onClick={cancel} style={btnStyle("var(--dim)")}>Cancel</button>
            <button onClick={save} disabled={saving} style={btnStyle("#10b981")}>
              {saving ? "Saving…" : "Save"}
            </button>
          </>}
        </div>
      </div>

      {!file.exists ? (
        <div style={{ color: "var(--dim)", fontSize: 13, padding: "32px 0" }}>
          File does not exist yet. Click Edit to create it.
        </div>
      ) : editing ? (
        <textarea
          value={draft ?? ""}
          onChange={(e) => setDraft(e.target.value)}
          style={{
            flex: 1, width: "100%", minHeight: 500, resize: "vertical",
            background: "var(--surface2, rgba(255,255,255,0.05))",
            border: "1px solid var(--accent, #6366f1)", borderRadius: 8,
            padding: 14, fontFamily: "var(--font-mono, monospace)", fontSize: 12,
            lineHeight: 1.6, color: "inherit", outline: "none",
          }}
        />
      ) : (
        <pre style={{
          flex: 1, margin: 0, padding: 16,
          background: "var(--surface2, rgba(255,255,255,0.04))",
          borderRadius: 8, overflow: "auto",
          fontFamily: isToml ? "var(--font-mono, monospace)" : "inherit",
          fontSize: isToml ? 12 : 13, lineHeight: 1.7,
          whiteSpace: "pre-wrap", wordBreak: "break-word",
          color: "var(--fg, #e2e8f0)", maxHeight: "calc(100vh - 200px)",
        }}>
          {file.content || <span style={{ color: "var(--dim)" }}>(empty)</span>}
        </pre>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Config pane
// ---------------------------------------------------------------------------

function ConfigPane({ config }: { config: SystemConfig }) {
  return (
    <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 24 }}>
      <Section title="Environment (non-secret)">
        <KVTable rows={Object.entries(config.env)} mono />
      </Section>

      <Section title="Runtime settings">
        <KVTable rows={Object.entries(config.settings).map(([k, v]) => [k, String(v)])} />
      </Section>

      {config.synth && Object.keys(config.synth).length > 0 && (
        <Section title="Synthesis instructions">
          {Object.entries(config.synth).map(([variant, text]) => (
            <div key={variant} style={{ marginBottom: 16 }}>
              <div style={{
                fontSize: 10, color: "var(--dim)", textTransform: "uppercase",
                letterSpacing: "0.06em", marginBottom: 6,
              }}>
                {variant}
              </div>
              <pre style={{
                margin: 0, padding: 12,
                background: "var(--surface2, rgba(255,255,255,0.05))",
                borderRadius: 6, fontSize: 12, lineHeight: 1.6,
                whiteSpace: "pre-wrap", wordBreak: "break-word",
                borderLeft: "3px solid var(--accent, #6366f1)",
              }}>
                {text}
              </pre>
            </div>
          ))}
        </Section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skills pane
// ---------------------------------------------------------------------------

function SkillsPane({ skills }: { skills: SkillEntry[] }) {
  const hooks = Array.from(new Set(skills.map((s) => s.hook)));
  const [activeHook, setActiveHook] = useState("");

  const filtered = activeHook ? skills.filter((s) => s.hook === activeHook) : skills;

  return (
    <div style={{ flex: 1, minWidth: 0 }}>
      {/* Hook filter chips */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 16 }}>
        <HookChip label="All" color="var(--dim)" active={!activeHook} onClick={() => setActiveHook("")} />
        {hooks.map((h) => (
          <HookChip key={h} label={h.replace("_", " ")} color={HOOK_COLOR[h] ?? "#888"}
            active={activeHook === h} onClick={() => setActiveHook(activeHook === h ? "" : h)} />
        ))}
      </div>

      {/* Column headers */}
      <div style={{
        display: "grid", gridTemplateColumns: "120px 80px 60px 60px 1fr",
        gap: 10, padding: "4px 10px 8px",
        borderBottom: "1px solid var(--border, rgba(255,255,255,0.08))",
      }}>
        {["Skill", "Hook", "Auto", "Prompt", "Description"].map((h) => (
          <span key={h} style={{ fontSize: 10, color: "var(--dim)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            {h}
          </span>
        ))}
      </div>

      <div>
        {filtered.map((s) => (
          <div key={s.name} style={{
            display: "grid", gridTemplateColumns: "120px 80px 60px 60px 1fr",
            gap: 10, padding: "7px 10px", alignItems: "start",
            borderBottom: "1px solid var(--border, rgba(255,255,255,0.05))",
          }}>
            <span className="mono" style={{ fontSize: 12, fontWeight: 600 }}>/{s.name}</span>
            <span style={{
              fontSize: 10, padding: "2px 6px", borderRadius: 4, width: "fit-content",
              background: (HOOK_COLOR[s.hook] ?? "#888") + "22",
              color: HOOK_COLOR[s.hook] ?? "#888",
            }}>
              {s.hook.replace("_", " ")}
            </span>
            <span style={{ fontSize: 12, color: s.has_auto ? "#10b981" : "var(--dim)" }}>
              {s.has_auto ? "✓" : "—"}
            </span>
            <span style={{ fontSize: 12, color: s.has_prompt ? "#6366f1" : "var(--dim)" }}>
              {s.has_prompt ? "✓" : "—"}
            </span>
            <span style={{ fontSize: 12, color: "var(--dim)", lineHeight: 1.5 }}>{s.description}</span>
          </div>
        ))}
      </div>
      <div style={{ fontSize: 11, color: "var(--dim)", marginTop: 10 }}>
        {filtered.length} skill{filtered.length !== 1 ? "s" : ""}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="section-title" style={{ marginBottom: 10 }}>{title}</div>
      <div className="card" style={{ padding: 16 }}>{children}</div>
    </div>
  );
}

function KVTable({ rows, mono }: { rows: [string, string][]; mono?: boolean }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {rows.map(([k, v]) => (
        <div key={k} style={{ display: "grid", gridTemplateColumns: "220px 1fr", gap: 12, alignItems: "flex-start" }}>
          <span className="mono" style={{ fontSize: 11, color: "var(--dim)", paddingTop: 2 }}>{k}</span>
          <span className={mono ? "mono" : ""} style={{ fontSize: 12, wordBreak: "break-all", lineHeight: 1.5 }}>{v || <span style={{ color: "var(--dim)" }}>—</span>}</span>
        </div>
      ))}
    </div>
  );
}

function HookChip({ label, color, active, onClick }: { label: string; color: string; active: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} style={{
      fontSize: 11, padding: "3px 10px", borderRadius: 20, border: "none", cursor: "pointer",
      background: active ? color : "var(--surface2, rgba(255,255,255,0.07))",
      color: active ? "#fff" : "var(--dim)",
      fontWeight: active ? 600 : 400,
    }}>
      {label}
    </button>
  );
}

function btnStyle(color: string): React.CSSProperties {
  return {
    fontSize: 12, padding: "4px 12px", borderRadius: 6, border: "none", cursor: "pointer",
    background: color + "22", color, fontWeight: 600,
  };
}

// ---------------------------------------------------------------------------
// Root view
// ---------------------------------------------------------------------------

export function System() {
  const [selected, setSelected] = useState<SelectedKey>("agents");

  const { data: files = [], isLoading: filesLoading } = useSystemFiles();
  const { data: config }  = useSystemConfig();
  const { data: skills }  = useSystemSkills();

  const isVirtual = selected === "config" || selected === "skills";

  return (
    <div>
      <div className="view-header">
        <h1>System</h1>
        <p>Governance docs · Active configuration · Skills registry</p>
      </div>

      <div style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>
        {/* Left: file list */}
        {filesLoading ? (
          <div className="loading" style={{ width: 200 }}>Loading…</div>
        ) : (
          <FileList files={files} selected={selected} onSelect={setSelected} />
        )}

        {/* Right: content pane */}
        {isVirtual ? (
          selected === "config" ? (
            config
              ? <ConfigPane config={config} />
              : <div className="loading">Loading config…</div>
          ) : (
            skills
              ? <SkillsPane skills={skills} />
              : <div className="loading">Loading skills…</div>
          )
        ) : (
          <FilePane key={selected} fileKey={selected as string} />
        )}
      </div>
    </div>
  );
}

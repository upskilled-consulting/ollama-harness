import { LayoutDashboard, Table2, SendHorizontal, BarChart2, CalendarDays, FolderOpen, Microscope, Cpu, Github as GithubIcon, Lock, Settings, TerminalSquare, Mic, Brain } from "lucide-react";
import { clsx } from "clsx";

export type View = "home" | "runs" | "submit" | "analytics" | "sessions" | "artifacts" | "finetune" | "voice" | "mcp" | "github" | "security" | "system" | "memory";

interface NavItem {
  id:    View;
  icon:  React.ReactNode;
  label: string;
}

const TOP_ITEMS: NavItem[] = [
  { id: "home",      icon: <LayoutDashboard size={18} />, label: "Dashboard"  },
  { id: "runs",      icon: <Table2 size={18} />,          label: "Runs"       },
  { id: "submit",    icon: <SendHorizontal size={18} />,  label: "Submit"     },
  { id: "analytics", icon: <BarChart2 size={18} />,       label: "Analytics"  },
  { id: "sessions",  icon: <CalendarDays size={18} />,    label: "Sessions"   },
  { id: "artifacts", icon: <FolderOpen size={18} />,      label: "Artifacts"  },
  { id: "finetune",  icon: <Microscope size={18} />,      label: "Fine-tune"  },
  { id: "mcp",       icon: <Cpu size={18} />,             label: "MCP"        },
  { id: "memory",    icon: <Brain size={18} />,          label: "Memory"     },
  { id: "github",    icon: <GithubIcon size={18} />,     label: "GitHub"     },
  { id: "security",  icon: <Lock size={18} />,           label: "Security"   },
  { id: "system",    icon: <Settings size={18} />,       label: "System"     },
];

const BOTTOM_ITEMS: NavItem[] = [];

interface Props {
  active:        View;
  onChange:      (v: View) => void;
  panelOpen:     "terminal" | "voice" | null;
  onPanelToggle: (p: "terminal" | "voice") => void;
}

function NavBtn({ item, active, onChange }: { item: NavItem; active: View; onChange: (v: View) => void }) {
  return (
    <button
      className={clsx("nav-btn", item.id === active && "active")}
      onClick={() => onChange(item.id)}
      aria-label={item.label}
    >
      {item.icon}
      <span className="nav-tooltip">{item.label}</span>
    </button>
  );
}

export function Sidebar({ active, onChange, panelOpen, onPanelToggle }: Props) {
  return (
    <nav id="sidebar">
      {TOP_ITEMS.map((item) => (
        <NavBtn key={item.id} item={item} active={active} onChange={onChange} />
      ))}
      <div className="nav-spacer" />
      {BOTTOM_ITEMS.map((item) => (
        <NavBtn key={item.id} item={item} active={active} onChange={onChange} />
      ))}
      <button
        className={clsx("nav-btn", panelOpen === "terminal" && "active")}
        onClick={() => onPanelToggle("terminal")}
        aria-label="Terminal"
      >
        <TerminalSquare size={18} />
        <span className="nav-tooltip">Terminal</span>
      </button>
      <button
        className={clsx("nav-btn", panelOpen === "voice" && "active")}
        onClick={() => onPanelToggle("voice")}
        aria-label="Voice"
      >
        <Mic size={18} />
        <span className="nav-tooltip">Voice</span>
      </button>
    </nav>
  );
}

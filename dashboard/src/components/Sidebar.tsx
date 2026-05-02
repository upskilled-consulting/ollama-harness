import { LayoutDashboard, Table2, SendHorizontal, BarChart2, Mic, Cpu, Workflow, CalendarDays, FolderOpen } from "lucide-react";
import { clsx } from "clsx";

export type View = "home" | "runs" | "submit" | "analytics" | "explorer" | "sessions" | "artifacts" | "voice" | "mcp";

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
  { id: "explorer",  icon: <Workflow size={18} />,         label: "Explorer"   },
  { id: "sessions",  icon: <CalendarDays size={18} />,    label: "Sessions"   },
  { id: "artifacts", icon: <FolderOpen size={18} />,      label: "Artifacts"  },
];

const BOTTOM_ITEMS: NavItem[] = [
  { id: "voice", icon: <Mic size={18} />, label: "Voice" },
  { id: "mcp",   icon: <Cpu size={18} />, label: "MCP"   },
];

interface Props {
  active:   View;
  onChange: (v: View) => void;
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

export function Sidebar({ active, onChange }: Props) {
  return (
    <nav id="sidebar">
      {TOP_ITEMS.map((item) => (
        <NavBtn key={item.id} item={item} active={active} onChange={onChange} />
      ))}
      <div className="nav-spacer" />
      {BOTTOM_ITEMS.map((item) => (
        <NavBtn key={item.id} item={item} active={active} onChange={onChange} />
      ))}
    </nav>
  );
}

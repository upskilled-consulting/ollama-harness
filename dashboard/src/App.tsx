import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Sidebar, type View } from "@/components/Sidebar";
import { useLiveRuns } from "@/hooks/useRuns";
import { Home }      from "@/views/Home";
import { Runs }      from "@/views/Runs";
import { Submit }    from "@/views/Submit";
import { Analytics } from "@/views/Analytics";
import { Voice }     from "@/views/Voice";
import { Mcp }       from "@/views/Mcp";
import { Sessions }  from "@/views/Sessions";
import { Artifacts }       from "@/views/Artifacts";
import { Finetune }        from "@/views/Finetune";
import { Github }          from "@/views/Github";
import { FloatingPanels }  from "@/components/FloatingPanels";

const qc = new QueryClient();

const VIEWS: Record<View, React.ReactNode> = {
  home:      <Home />,
  runs:      <Runs />,
  submit:    <Submit />,
  analytics: <Analytics />,
  sessions:  <Sessions />,
  artifacts: <Artifacts />,
  finetune:  <Finetune />,
  voice:     <Voice />,
  mcp:       <Mcp />,
  github:    <Github />,
};

function App() {
  const [view, setView] = useState<View>("home");
  const [panelOpen, setPanelOpen] = useState<"terminal" | "voice" | null>(null);
  useLiveRuns();

  const togglePanel = (p: "terminal" | "voice") =>
    setPanelOpen((cur) => (cur === p ? null : p));

  return (
    <div id="layout">
      <Sidebar active={view} onChange={setView} panelOpen={panelOpen} onPanelToggle={togglePanel} />
      <div id="content">{VIEWS[view]}</div>
      <FloatingPanels open={panelOpen} onClose={() => setPanelOpen(null)} />
    </div>
  );
}

export default function Root() {
  return (
    <QueryClientProvider client={qc}>
      <App />
    </QueryClientProvider>
  );
}

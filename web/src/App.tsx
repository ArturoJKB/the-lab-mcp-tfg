import { useEffect, useState } from "react";
import "./theme/breeze.css";
import type { ChatTurn } from "./components/ChatDrawer";
import { ChatDrawer } from "./components/ChatDrawer";
import { Dock } from "./components/Dock";
import { Sidebar, type ViewId } from "./components/Sidebar";
import { api } from "./api";

import DataView from "./views/DataView";
import ExperimentsView from "./views/ExperimentsView";
import ModelsView from "./views/ModelsView";
import ContextView from "./views/ContextView";
import SandboxView from "./views/SandboxView";
import McpView from "./views/McpView";

const VIEW_TITLES: Record<
  ViewId,
  { title: string; subtitle: string; folder: string; agent?: boolean }
> = {
  data: { title: "Data", subtitle: "Upload, inspect, clean, explore", folder: "Deterministic" },
  experiments: { title: "Experiments", subtitle: "Orchestrated by sub-agents, live", folder: "Agentic", agent: true },
  models: { title: "Models", subtitle: "Registry, artifacts, prediction", folder: "Admin" },
  context: { title: "Context", subtitle: "Search + agent sessions", folder: "Admin" },
  sandbox: { title: "Sandbox", subtitle: "Restricted Python execution", folder: "Admin" },
  mcp: { title: "MCP servers", subtitle: "Model Context Protocol surfaces", folder: "Admin" },
};

export type DatasetState = { id: string; target: string };

export default function App() {
  const [view, setView] = useState<ViewId>("data");
  const [adminMode, setAdminMode] = useState(false);
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatTurns, setChatTurns] = useState<ChatTurn[]>([]);
  const [chatExpanded, setChatExpanded] = useState(false);
  const [pendingOpenExperiment, setPendingOpenExperiment] = useState<string | null>(null);
  // Dataset context shared across views: selected in Data, reused in Experiments.
  const [datasetState, setDatasetState] = useState<DatasetState>({ id: "", target: "" });

  useEffect(() => {
    api("GET", "/health").then((r) => setHealthy(r.ok));
  }, []);

  const meta = VIEW_TITLES[view];

  return (
    <>
      <div className="app-shell">
        <Dock
          healthy={healthy}
          adminMode={adminMode}
          chatOpen={chatOpen}
          onToggleChat={() => setChatOpen((c) => !c)}
          onToggleAdmin={() => {
            const next = !adminMode;
            setAdminMode(next);
            setView(next ? "models" : "experiments");
          }}
        />
        <Sidebar view={view} adminMode={adminMode} onSelect={setView} />
        <main className="app-main">
        <header className="view-header">
          <div>
            <span className="view-kicker">
              {adminMode ? "Admin" : meta.folder} / {meta.title}
            </span>
            <h1 className={meta.agent ? "agent-title" : ""}>{meta.title}</h1>
          </div>
          <span className={`subtitle-chip ${meta.agent ? "agent-chip" : ""}`}>
            <span className="dot" />
            {meta.subtitle}
          </span>
        </header>
        {view === "data" && (
          <DataView datasetState={datasetState} onDatasetChange={setDatasetState} />
        )}
                {view === "experiments" && (
          <ExperimentsView
            datasetState={datasetState}
            onDatasetChange={setDatasetState}
            pendingOpenExperiment={pendingOpenExperiment}
            onExperimentConsumed={() => setPendingOpenExperiment(null)}
          />
        )}
        {view === "models" && <ModelsView />}
        {view === "context" && <ContextView />}
        {view === "sandbox" && <SandboxView />}
        {view === "mcp" && <McpView />}
        </main>
      </div>
      <div className={chatOpen ? "chat-visible" : "hidden"}>
        <ChatDrawer
          datasetId={datasetState.id}
          target={datasetState.target}
          turns={chatTurns}
          setTurns={setChatTurns}
          expanded={chatExpanded}
          onToggleExpand={() => setChatExpanded((e) => !e)}
          onClose={() => setChatOpen(false)}
          onOpenExperiment={(experimentId) => {
            setChatOpen(false);
            setPendingOpenExperiment(experimentId);
            setView("experiments");
          }}
        />
      </div>
    </>
  );
}

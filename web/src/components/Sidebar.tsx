export type ViewId =
  | "mcp"
  | "data"
  | "experiments"
  | "models"
  | "context"
  | "sandbox";

type SidebarProps = {
  view: ViewId;
  adminMode: boolean;
  onSelect: (view: ViewId) => void;
};

const WORKSPACE_ITEMS: { id: ViewId; icon: string; label: string; agent?: boolean }[] = [
  { id: "data", icon: "▦", label: "Data" },
  { id: "experiments", icon: "✦", label: "Experiments", agent: true },
];

const ADMIN_ITEMS: { id: ViewId; icon: string; label: string }[] = [
  { id: "models", icon: "◈", label: "Models" },
  { id: "context", icon: "◐", label: "Context" },
  { id: "sandbox", icon: "▣", label: "Sandbox" },
  { id: "mcp", icon: "⇄", label: "MCP" },
];

export function Sidebar({ view, adminMode, onSelect }: SidebarProps) {
  if (adminMode) {
    return (
      <nav className="app-sidebar" aria-label="Admin">
        <div className="nav-group-title">Admin</div>
        {ADMIN_ITEMS.map((item) => (
          <button
            key={item.id}
            className={`nav-item ${view === item.id ? "active" : ""}`}
            onClick={() => onSelect(item.id)}
          >
            <span className="nav-icon">{item.icon}</span> {item.label}
          </button>
        ))}
      </nav>
    );
  }

  return (
    <nav className="app-sidebar" aria-label="Workspace">
      <div className="nav-group-title">Deterministic</div>
      {WORKSPACE_ITEMS.filter((i) => !i.agent).map((item) => (
        <button
          key={item.id}
          className={`nav-item ${view === item.id ? "active" : ""}`}
          onClick={() => onSelect(item.id)}
        >
          <span className="nav-icon">{item.icon}</span> {item.label}
        </button>
      ))}
      <div className="nav-group-title">Agentic</div>
      {WORKSPACE_ITEMS.filter((i) => i.agent).map((item) => (
        <button
          key={item.id}
          className={`nav-item agent ${view === item.id ? "active" : ""}`}
          onClick={() => onSelect(item.id)}
        >
          <span className="nav-icon">{item.icon}</span> {item.label}
        </button>
      ))}
    </nav>
  );
}

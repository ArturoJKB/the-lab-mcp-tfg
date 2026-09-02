type DockProps = {
  healthy: boolean | null;
  adminMode: boolean;
  chatOpen: boolean;
  onToggleChat: () => void;
  onToggleAdmin: () => void;
};

export function Dock({ healthy, adminMode, chatOpen, onToggleChat, onToggleAdmin }: DockProps) {
  return (
    <aside className="app-dock">
      <div className="dock-brand" title="The Lab">TL</div>

      <button
        className={`dock-btn ${chatOpen ? "active" : ""}`}
        onClick={onToggleChat}
        title="Global agent chat"
        aria-label="Global agent chat"
      >
        ✦
      </button>
      <button
        className={`dock-btn ${adminMode ? "active" : ""}`}
        onClick={onToggleAdmin}
        title={adminMode ? "Back to workspace" : "Admin view (models, context, sandbox)"}
        aria-label="Toggle admin view"
      >
        ⚙
      </button>

      <div className="dock-spacer" />
      <span
        className={`status-dot ${healthy === null ? "" : healthy ? "ok pulse" : "down"}`}
        title={healthy === null ? "Checking service…" : healthy ? "Service online" : "Service unreachable"}
      />
    </aside>
  );
}

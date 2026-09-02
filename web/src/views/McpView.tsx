const SERVERS: { name: string; entry: string; tools: string[]; kind: string }[] = [
  { name: "data_catalog_mcp", entry: "thelab-data-catalog-mcp", tools: ["list_datasets", "get_data_profile", "get_dataset_contract"], kind: "read" },
  { name: "model_registry_mcp", entry: "thelab-model-registry-mcp", tools: ["list_models", "get_model_manifest", "get_model_card", "get_model_metrics", "predict"], kind: "read + predict" },
  { name: "workspace_mcp", entry: "thelab-workspace-mcp", tools: ["list_runs", "get_run_manifest", "list_run_artifacts", "get_artifact", "read_model_card"], kind: "read" },
  { name: "context_mcp", entry: "thelab-context-mcp", tools: ["get_context_status", "get_context_entry", "search_context"], kind: "read" },
  { name: "context_write_mcp", entry: "thelab-context-write-mcp", tools: ["append_session_summary"], kind: "write (validated + redacted)" },
  { name: "eda_mcp", entry: "thelab-eda-mcp", tools: ["missing_profile", "correlation_hints", "class_balance", "outlier_scan", "leakage_suspects", "feature_types"], kind: "read" },
  { name: "agent_mcp", entry: "thelab-agent-mcp", tools: ["orchestrate_experiment", "spawn_subagent", "run_deterministic_skill", "run_training_job", "get_job_status", "log_agent_activity"], kind: "orchestration" },
];

export default function McpView() {
  return (
    <>
      <div className="banner loading-banner">
        The Lab exposes {SERVERS.length} stdio MCP servers. Any MCP client can connect
        (<code>python -m thelab.mcp.&lt;server&gt;</code> or the console scripts below) and use these
        typed tools without touching pipeline internals. Remote MCP sources (e.g. Kaggle's MCP
        server) would connect the same way — the backend is provider-agnostic by design.
      </div>
      {SERVERS.map((s) => (
        <section className="panel" key={s.name}>
          <h2>
            {s.name} <span className="count-chip">{s.kind}</span>
          </h2>
          <p className="muted mono" style={{ fontSize: "0.78rem", marginBottom: "var(--space-2)" }}>
            {s.entry}
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-1)" }}>
            {s.tools.map((t) => (
              <span key={t} className="badge pending mono" style={{ textTransform: "none" }}>
                {t}
              </span>
            ))}
          </div>
        </section>
      ))}
    </>
  );
}

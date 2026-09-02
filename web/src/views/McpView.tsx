import { useEffect, useState } from "react";
import { api } from "../api";

const SERVERS: { name: string; entry: string; tools: string[]; kind: string }[] = [
  { name: "data_catalog_mcp", entry: "thelab-data-catalog-mcp", tools: ["list_datasets", "get_data_profile", "get_dataset_contract"], kind: "read" },
  { name: "model_registry_mcp", entry: "thelab-model-registry-mcp", tools: ["list_models", "get_model_manifest", "get_model_card", "get_model_metrics", "predict"], kind: "read + predict" },
  { name: "workspace_mcp", entry: "thelab-workspace-mcp", tools: ["list_runs", "get_run_manifest", "list_run_artifacts", "get_artifact", "read_model_card"], kind: "read" },
  { name: "context_mcp", entry: "thelab-context-mcp", tools: ["get_context_status", "get_context_entry", "search_context"], kind: "read" },
  { name: "context_write_mcp", entry: "thelab-context-write-mcp", tools: ["append_session_summary"], kind: "write (validated + redacted)" },
  { name: "eda_mcp", entry: "thelab-eda-mcp", tools: ["missing_profile", "correlation_hints", "class_balance", "outlier_scan", "leakage_suspects", "feature_types"], kind: "read" },
  { name: "agent_mcp", entry: "thelab-agent-mcp", tools: ["orchestrate_experiment", "spawn_subagent", "run_deterministic_skill", "run_training_job", "get_job_status", "log_agent_activity"], kind: "orchestration" },
];

type RemoteServer = {
  url: string;
  reachable: boolean;
  tools?: { name: string; description: string }[];
  error?: string;
};

type RemotePayload = {
  configured: boolean;
  servers?: Record<string, RemoteServer>;
};

function RemoteSection() {
  const [data, setData] = useState<RemotePayload | null>(null);

  useEffect(() => {
    api<RemotePayload>("GET", "/mcp/remote").then((r) => {
      if (r.ok && r.data) setData(r.data);
    });
  }, []);

  if (!data) return null;
  if (!data.configured) {
    return (
      <section className="panel">
        <h2>Remote MCP servers</h2>
        <p className="muted">
          None configured. Add to <code>.env</code>:
          <br />
          <code>
            THELAB_REMOTE_MCP_SERVERS=[{'{"'}"name": "kaggle", "url":
            "https://www.kaggle.com/mcp"{'{"'}]
          </code>
          <br />
          then restart the service — the chat agent gains those tools automatically.
        </p>
      </section>
    );
  }

  const servers = data.servers ?? {};
  return (
    <section className="panel">
      <h2>Remote MCP servers</h2>
      {Object.entries(servers).map(([name, info]) => (
        <div key={name} className="list-card" style={{ cursor: "default" }}>
          <h3>
            {name}{" "}
            <span className={`badge ${info.reachable ? "completed" : "failed"}`}>
              {info.reachable ? "connected" : "unreachable"}
            </span>
          </h3>
          <p className="mono">{info.url}</p>
          {info.error && <p className="error">{info.error}</p>}
          {info.tools && info.tools.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
              {info.tools.map((t) => (
                <span key={t.name} className="badge pending mono" style={{ textTransform: "none" }}>
                  {name}__{t.name}
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
    </section>
  );
}

export default function McpView() {
  return (
    <>
      <div className="banner loading-banner">
        The Lab exposes {SERVERS.length} stdio MCP servers. Any MCP client can connect
        (<code>python -m thelab.mcp.&lt;server&gt;</code> or the console scripts below) and use these
        typed tools without touching pipeline internals. Remote MCP sources are merged into the
        global agent's tool set — see the remote section below.
      </div>
      <RemoteSection />
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

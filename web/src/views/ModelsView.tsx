import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { StatusBadge } from "../components/StatusBadge";

type ModelRow = {
  run_id: string;
  model: string;
  target: string;
  task_type: string;
  metric: number | null;
  metric_name?: string;
  dataset?: string;
};

type ArtifactRef = { name: string; path: string; artifact_type?: string };

type RunSummary = {
  run_id: string;
  final_status?: string;
  validation_status?: string;
  feature_columns?: string[];
  metrics?: Record<string, number>;
};

type Notebook = { cells: { cell_type: string; source: string }[]; nbformat: number };

type Tab = "metrics" | "artifacts" | "predict" | "evidence";

function NotebookViewer({ notebook }: { notebook: Notebook }) {
  return (
    <div>
      {notebook.cells.map((cell, i) => (
        <div key={i} className={`nb-cell ${cell.cell_type === "code" ? "nb-code" : "nb-md"}`}>
          <div className="nb-label">{cell.cell_type}</div>
          <pre>{cell.source}</pre>
        </div>
      ))}
    </div>
  );
}

export default function ModelsView() {
  const [models, setModels] = useState<ModelRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("metrics");
  const [summary, setSummary] = useState<RunSummary | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactRef[]>([]);
  const [artifactContent, setArtifactContent] = useState<{ name: string; text: string } | null>(null);
  const [notebook, setNotebook] = useState<Notebook | null>(null);
  const [features, setFeatures] = useState<string>("");
  const [prediction, setPrediction] = useState<string>("");
  const [predictError, setPredictError] = useState("");

  const refresh = useCallback(async () => {
    const res = await api<ModelRow[]>("GET", "/models");
    if (res.ok && res.data) setModels(res.data);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const open = useCallback(async (runId: string) => {
    setSelected(runId);
    setTab("metrics");
    setArtifactContent(null);
    setNotebook(null);
    setPrediction("");
    setPredictError("");
    const res = await api<RunSummary>("GET", `/runs/${encodeURIComponent(runId)}`);
    if (res.ok && res.data) setSummary(res.data);
    const art = await api<ArtifactRef[]>("GET", `/runs/${encodeURIComponent(runId)}/artifacts`);
    if (art.ok && art.data) setArtifacts(art.data);
  }, []);

  const loadArtifact = async (name: string) => {
    if (!selected) return;
    const res = await api<{ content?: string; text?: string }>(
      "GET",
      `/runs/${encodeURIComponent(selected)}/artifacts/${encodeURIComponent(name)}`,
    );
    if (res.ok) {
      const payload = res.data ?? {};
      setArtifactContent({ name, text: String(payload.content ?? payload.text ?? JSON.stringify(payload, null, 2)).slice(0, 20000) });
    } else {
      setArtifactContent({ name, text: res.detail || "failed to load artifact" });
    }
  };

  const loadNotebook = async () => {
    if (!selected) return;
    const res = await api<Notebook>("GET", `/runs/${encodeURIComponent(selected)}/notebook`);
    setNotebook(res.ok && res.data ? res.data : null);
  };

  const predict = async () => {
    if (!selected || !features.trim()) return;
    setPredictError("");
    let featuresPayload: unknown = features.trim();
    try {
      featuresPayload = JSON.parse(features);
    } catch {
      // keep raw string (comma-separated values)
    }
    const res = await api<{ predictions: unknown[] }>("POST", "/predict", {
      run_id: selected,
      features: featuresPayload,
    });
    if (res.ok && res.data) {
      setPrediction(JSON.stringify(res.data.predictions));
    } else {
      setPrediction("");
      setPredictError(res.detail || res.error || "prediction failed");
    }
  };

  return (
    <>
      <section className="panel">
        <h2>
          Approved models <span className="count-chip">{models.length}</span>
        </h2>
        {models.length === 0 && <p className="empty">No approved models yet — run an experiment first.</p>}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Run ID</th>
                <th>Model</th>
                <th>Target</th>
                <th>Task</th>
                <th>Metric</th>
              </tr>
            </thead>
            <tbody>
              {models.map((m) => (
                <tr
                  key={m.run_id}
                  onClick={() => open(m.run_id)}
                  style={{ cursor: "pointer", background: selected === m.run_id ? "var(--surface-raised)" : undefined }}
                >
                  <td className="mono">{m.run_id}</td>
                  <td className="mono">{m.model}</td>
                  <td>{m.target}</td>
                  <td>{m.task_type}</td>
                  <td className="mono">{m.metric != null ? m.metric.toFixed(4) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {selected && (
        <section className="panel">
          <h2>
            {selected} {summary?.validation_status && <StatusBadge status={summary.validation_status} />}
          </h2>
          <div className="tab-row">
            {(["metrics", "artifacts", "predict", "evidence"] as Tab[]).map((t) => (
              <button
                key={t}
                className={tab === t ? "active" : ""}
                onClick={() => {
                  setTab(t);
                  if (t === "evidence") loadNotebook();
                }}
              >
                {t}
              </button>
            ))}
          </div>

          {tab === "metrics" && (
            <div className="table-wrap">
              <table>
                <tbody>
                  {Object.entries(summary?.metrics ?? {}).map(([k, v]) => (
                    <tr key={k}>
                      <td className="mono">{k}</td>
                      <td className="mono">{typeof v === "number" ? v.toFixed(4) : String(v)}</td>
                    </tr>
                  ))}
                  {Object.keys(summary?.metrics ?? {}).length === 0 && (
                    <tr>
                      <td className="empty">No metrics loaded.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}

          {tab === "artifacts" && (
            <>
              <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap", marginBottom: "var(--space-2)" }}>
                {artifacts.map((a) => (
                  <button key={a.name} className="secondary" onClick={() => loadArtifact(a.name)}>
                    {a.name}
                  </button>
                ))}
              </div>
              {artifactContent && (
                <pre className="job-log" style={{ maxHeight: 320 }}>
                  {artifactContent.text}
                </pre>
              )}
            </>
          )}

          {tab === "predict" && (
            <>
              <p className="muted">
                Feature values in column order: {(summary?.feature_columns ?? []).join(", ")}
              </p>
              <div style={{ display: "flex", gap: "var(--space-2)" }}>
                <input
                  value={features}
                  onChange={(e) => setFeatures(e.target.value)}
                  placeholder="5.1, 3.5, 1.4, 0.2"
                  style={{
                    flex: 1,
                    background: "var(--bg)",
                    color: "var(--text)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius)",
                    padding: "7px 9px",
                    fontFamily: "var(--font-mono)",
                  }}
                />
                <button className="primary" onClick={predict}>
                  Predict
                </button>
              </div>
              {predictError && <div className="banner error-banner">{predictError}</div>}
              {prediction && <div className="banner ok-banner">Prediction: {prediction}</div>}
            </>
          )}

          {tab === "evidence" && (
            <>
              {!notebook && <p className="empty">Generating notebook… (or failed — check the run status)</p>}
              {notebook && <NotebookViewer notebook={notebook} />}
            </>
          )}
        </section>
      )}
    </>
  );
}

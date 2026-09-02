import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useState } from "react";
import { StatusBadge } from "../components/StatusBadge";
import { api } from "../api";
import { useJob, type JobEvent } from "../hooks/useJob";

type TryAllResult = {
  dataset_id: string;
  target: string;
  persisted?: boolean;
  results: {
    model: string;
    status: string;
    metrics: Record<string, number | null>;
    error?: string | null;
    run_id?: string | null;
    seed?: number;
  }[];
  best?: { model: string } | null;
};

function primaryMetric(m: Record<string, number | null>): { label: string; value: number | null } {
  if (m["test_r2"] != null) return { label: "R²", value: m["test_r2"] };
  if (m["test_rmse"] != null) return { label: "RMSE", value: m["test_rmse"] };
  if (m["test_accuracy"] != null) return { label: "Accuracy", value: m["test_accuracy"] };
  return { label: "—", value: null };
}

export default function ModelLabSection({ datasetId, target }: { datasetId: string; target: string }) {
  const { job, events, submit, cancel } = useJob();
  const [seedText, setSeedText] = useState("42");
  const [taskType, setTaskType] = useState("auto");
  const [persist, setPersist] = useState(false);
  const [formError, setFormError] = useState("");
  const [predictRun, setPredictRun] = useState<string | null>(null);
  const [featureInput, setFeatureInput] = useState("");
  const [featureColumns, setFeatureColumns] = useState<string[]>([]);
  const [predictOut, setPredictOut] = useState("");
  const [predictErr, setPredictErr] = useState("");



  const running = job != null && (job.status === "running" || job.status === "pending");
  const result = (job?.result ?? null) as TryAllResult | null;

  const run = async () => {
    setFormError("");
    if (!datasetId || !target) {
      setFormError("Select a dataset and enter the target column in the EDA section above.");
      return;
    }
    const parsedSeed = parseInt(seedText, 10);
    if (Number.isNaN(parsedSeed) || parsedSeed < 0) {
      setFormError("Seed must be a non-negative integer (empty = 42).");
      return;
    }
    await submit("try_all", { dataset_id: datasetId, target, seed: parsedSeed, task_type: taskType });
  };

  const modelEvents = events.filter((e: JobEvent) => e.data?.stage === "try_all");

  const chartData =
    result?.results
      .filter((r) => r.status === "completed")
      .map((r) => {
        const { label, value } = primaryMetric(r.metrics);
        return { model: r.model, value, label };
      })
      .filter((d) => d.value != null) ?? [];

  return (
    <>
      {formError && <div className="banner error-banner">{formError}</div>}

      <section className="panel">
        <h2>Model Lab — deterministic try-all</h2>
        <p className="muted">
          Dry-run of every registered model on the dataset selected above. Nothing is
          persisted; no agents involved.
        </p>
        <div style={{ display: "grid", gap: "var(--space-2)", maxWidth: 480 }}>
          <div className="mono muted" style={{ padding: "7px 0" }}>
            {datasetId || "No dataset selected"} — target: <strong>{target || "?"}</strong>
          </div>
          <div style={{ display: "flex", gap: "var(--space-2)" }}>
            <input
              type="number"
              value={seedText}
              onChange={(e) => setSeedText(e.target.value)}
              title="Seed"
              style={{
                width: 100,
                background: "var(--bg)",
                color: "var(--text)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius)",
                padding: "7px 8px",
              }}
            />
            <select
              value={taskType}
              onChange={(e) => setTaskType(e.target.value)}
              style={{
                flex: 1,
                background: "var(--bg)",
                color: "var(--text)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius)",
                padding: "7px 8px",
              }}
            >
              <option value="auto">task: auto</option>
              <option value="classification">task: classification</option>
              <option value="regression">task: regression</option>
            </select>
          </div>
          <label className="muted" style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.8rem" }}>
            <input
              type="checkbox"
              checked={persist}
              onChange={(e) => setPersist(e.target.checked)}
            />
            Persist runs (required for prediction; slower)
          </label>
          <div>
            <button className="primary" onClick={run} disabled={running}>
              {running ? "Running…" : persist ? "Train all (persisted)" : "Run try-all"}
            </button>{" "}
            {running && (
              <button className="secondary" onClick={cancel}>
                Cancel
              </button>
            )}
          </div>
        </div>
      </section>

      {job && (
        <section className="panel">
          <h2>
            Job <code className="mono">{job.job_id}</code> <StatusBadge status={job.status} />
          </h2>
          {modelEvents.length > 0 && (
            <ul style={{ margin: 0, paddingLeft: 18, fontFamily: "var(--font-mono)", fontSize: "0.85rem" }}>
              {modelEvents.map((e, i) => (
                <li key={i}>{e.message}</li>
              ))}
            </ul>
          )}
        </section>
      )}

      {result && (
        <section className="panel">
          <h2>Comparison — {result.dataset_id}</h2>
          {result.persisted && (
            <p className="muted" style={{ fontSize: "0.8rem" }}>
              Runs persisted — approved models are available for prediction below and in
              Admin → Models.
            </p>
          )}
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Status</th>
                  <th>Primary metric</th>
                </tr>
              </thead>
              <tbody>
                {result.results.map((r) => {
                  const { label, value } = primaryMetric(r.metrics ?? {});
                  return (
                    <tr key={r.model}>
                      <td className="mono">{r.model}</td>
                      <td>
                        <StatusBadge status={r.status} />
                        {r.error ? <div className="muted" style={{ fontSize: "0.78rem" }}>{r.error}</div> : null}
                      </td>
                      <td className="mono">
                        {value != null ? `${label}: ${value.toFixed(4)}` : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {result.persisted && (
            <div style={{ marginTop: "var(--space-3)" }}>
              <h3 className="muted" style={{ fontSize: "0.75rem", textTransform: "uppercase" }}>
                Predict
              </h3>
              <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap", alignItems: "center" }}>
                <select
                  value={predictRun ?? ""}
                  onChange={async (e) => {
                    const rid = e.target.value;
                    setPredictRun(rid || null);
                    setPredictOut("");
                    setPredictErr("");
                    if (rid) {
                      const res = await api<{ feature_columns?: string[] }>(
                        "GET",
                        `/runs/${encodeURIComponent(rid)}`,
                      );
                      setFeatureColumns(res.ok ? res.data?.feature_columns ?? [] : []);
                    }
                  }}
                  style={{
                    background: "var(--bg)",
                    color: "var(--text)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius)",
                    padding: "6px 8px",
                  }}
                >
                  <option value="">Select persisted run…</option>
                  {result.results
                    .filter((r) => r.status === "completed" && r.run_id)
                    .map((r) => (
                      <option key={r.run_id} value={r.run_id ?? ""}>
                        {r.model} (seed {r.seed}) — {r.run_id}
                      </option>
                    ))}
                </select>
                <input
                  value={featureInput}
                  onChange={(e) => setFeatureInput(e.target.value)}
                  placeholder={
                    featureColumns.length ? featureColumns.join(", ") : "feature values (column order)"
                  }
                  style={{
                    flex: 1,
                    minWidth: 200,
                    background: "var(--bg)",
                    color: "var(--text)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius)",
                    padding: "6px 8px",
                    fontFamily: "var(--font-mono)",
                  }}
                />
                <button
                  className="primary"
                  onClick={async () => {
                    if (!predictRun || !featureInput.trim()) return;
                    setPredictErr("");
                    let payload: unknown = featureInput.trim();
                    try {
                      payload = JSON.parse(featureInput);
                    } catch {
                      payload = featureInput.split(",").map((v) => parseFloat(v.trim()));
                    }
                    const res = await api<{ predictions: unknown[] }>("POST", "/predict", {
                      run_id: predictRun,
                      features: payload,
                    });
                    if (res.ok && res.data) setPredictOut(JSON.stringify(res.data.predictions));
                    else setPredictErr(res.detail || res.error || "prediction failed");
                  }}
                  disabled={!predictRun || !featureInput.trim()}
                >
                  Predict
                </button>
              </div>
              {featureColumns.length > 0 && (
                <p className="muted" style={{ fontSize: "0.75rem" }}>
                  Columns: {featureColumns.join(", ")}
                </p>
              )}
              {predictOut && <div className="banner ok-banner">Prediction: {predictOut}</div>}
              {predictErr && <div className="banner error-banner">{predictErr}</div>}
            </div>
          )}

          {chartData.length > 0 && (
            <div style={{ marginTop: "var(--space-3)" }}>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="model" tick={{ fontSize: 10, fill: "var(--muted)" }} />
                  <YAxis tick={{ fontSize: 10, fill: "var(--muted)" }} />
                  <Tooltip
                    contentStyle={{
                      background: "var(--surface-raised)",
                      border: "1px solid var(--border)",
                      fontSize: 12,
                    }}
                  />
                  <Bar dataKey="value" radius={[3, 3, 0, 0]}>
                    {chartData.map((d, i) => (
                      <Cell key={i} fill={d.model === result.best?.model ? "var(--accent-2)" : "var(--accent)"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
              <p className="muted" style={{ fontSize: "0.8rem" }}>
                Purple = best model. Metric shown: {chartData[0]?.label}.
              </p>
            </div>
          )}
        </section>
      )}
    </>
  );
}

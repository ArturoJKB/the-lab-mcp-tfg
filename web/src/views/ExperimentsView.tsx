import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { StatusBadge } from "../components/StatusBadge";
import { StagePipeline, type StageStatus } from "../components/StagePipeline";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useExperimentStream, type ExperimentEvent } from "../hooks/useExperimentStream";
import ProposalsView from "./ProposalsView";

type ExperimentSummary = {
  experiment_id: string;
  goal: string;
  dataset_id: string;
  target: string;
  state: string;
  updated_at: string;
  best_run_id?: string | null;
};

type Interpretation = { llm_interpretation?: string; llm_usage?: UsageInfo };

type ExperimentStatus = {
  experiment_id: string;
  goal: string;
  dataset_id: string;
  target: string;
  state: string;
  feedback?: string | null;
  plan: { job_id?: string; previous_job_ids?: string[]; recommendation?: Record<string, unknown> };
  sub_agent_results: Record<string, Interpretation>;
  best_run_id?: string | null;
  best_metrics?: Record<string, number> | null;
  error?: string | null;
};

type DatasetRow = { dataset_id: string; rows: number };
type ProviderInfo = {
  name: string;
  configured: boolean;
  env: string[];
  note: string;
  reachable?: boolean;
  models?: { id: string; name: string }[];
};

type UsageInfo = Record<string, unknown>;

const STAGES = ["planning", "cleaning", "training", "evaluating"];
const INTERPRETERS: [string, string][] = [
  ["EDAAnalyst", "EDAAnalyst — findings"],
  ["FeatureEngineer", "FeatureEngineer — cleaning rationale"],
  ["ModelSelector", "ModelSelector — recommendation"],
];

type Tab = "plan" | "run" | "proposals" | "history";

type Props = {
  datasetState: { id: string; target: string };
  onDatasetChange: (state: { id: string; target: string }) => void;
  pendingOpenExperiment?: string | null;
  onExperimentConsumed?: () => void;
};

export default function ExperimentsView({
  datasetState,
  onDatasetChange,
  pendingOpenExperiment,
  onExperimentConsumed,
}: Props) {
  const [tab, setTab] = useState<Tab>("plan");

  // plan form — dataset/target shared with Data view until changed here
  const [datasets, setDatasets] = useState<DatasetRow[]>([]);
  const [datasetId, setDatasetId] = useState(datasetState.id);
  const [target, setTarget] = useState(datasetState.target);
  const [datasetQuery, setDatasetQuery] = useState("");
  const [targetColumns, setTargetColumns] = useState<Record<string, string[]>>({});
  const [goal, setGoal] = useState("");
  const [provider, setProvider] = useState("mock");
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [providerModel, setProviderModel] = useState("");
  const [startStatus, setStartStatus] = useState("");
  const [starting, setStarting] = useState(false);

  // run
  const [experimentId, setExperimentId] = useState<string | null>(null);
  const [status, setStatus] = useState<ExperimentStatus | null>(null);
  const [stageStatus, setStageStatus] = useState<Record<string, StageStatus>>({});
  const [feedback, setFeedback] = useState("");
  const [feedbackStatus, setFeedbackStatus] = useState("");
  const [running, setRunning] = useState(false);

  // history
  const [history, setHistory] = useState<ExperimentSummary[]>([]);

  const loadHistory = useCallback(async () => {
    const res = await api<ExperimentSummary[]>("GET", "/experiments");
    if (res.ok && res.data) setHistory(res.data);
  }, []);

  useEffect(() => {
    api<DatasetRow[]>("GET", "/datasets").then((r) => {
      if (r.ok && r.data) setDatasets(r.data);
    });
    api<ProviderInfo[]>("GET", "/agent/providers").then((r) => {
      if (r.ok && r.data) setProviders(r.data);
    });
    loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    if (pendingOpenExperiment) {
      openExperiment(pendingOpenExperiment, true);
      onExperimentConsumed?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingOpenExperiment]);

  useEffect(() => {
    if (datasetId && !targetColumns[datasetId]) {
      api<{ columns: { name: string; dtype: string }[] }>(
        "GET",
        `/datasets/${encodeURIComponent(datasetId)}/preview?limit=1`,
      ).then((r) => {
        if (r.ok && r.data) {
          setTargetColumns((prev) => ({
            ...prev,
            [datasetId]: r.data!.columns.map((c) => c.name),
          }));
        }
      });
    }
  }, [datasetId, targetColumns]);

  useEffect(() => {
    if (datasetState.id && datasetState.id !== datasetId) setDatasetId(datasetState.id);
    if (datasetState.target && datasetState.target !== target) setTarget(datasetState.target);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetState]);

  const onDone = useCallback(() => {
    if (!experimentId) return;
    api<ExperimentStatus>("GET", `/experiment/${encodeURIComponent(experimentId)}/status`).then((r) => {
      if (r.ok && r.data) setStatus(r.data);
    });
    loadHistory();
  }, [experimentId, loadHistory]);

  const { events, connected } = useExperimentStream(experimentId, onDone);

  const applyStageEvents = useCallback((evs: ExperimentEvent[]) => {
    setStageStatus((prev) => {
      const next = { ...prev };
      for (const e of evs) {
        const stage = e.data?.stage;
        if (stage && STAGES.includes(stage)) next[stage] = "running";
      }
      return next;
    });
  }, []);

  useEffect(() => {
    applyStageEvents(events);
  }, [events, applyStageEvents]);

  const openExperiment = useCallback(
    async (id: string, connectIfRunning = true) => {
      setExperimentId(id);
      setTab("run");
      const res = await api<ExperimentStatus>("GET", `/experiment/${encodeURIComponent(id)}/status`);
      if (!res.ok || !res.data) return;
      const data = res.data;
      setStatus(data);
      setStageStatus({});
      const live = ["pending", "running", "iterating"].includes(data.state);
      setRunning(live && connectIfRunning);
      if (!live) onDone();
    },
    [onDone],
  );

  const start = async () => {
    setStartStatus("");
    if (!datasetId || !target || !goal.trim()) {
      setStartStatus("Dataset, target, and goal are required.");
      return;
    }
    setStarting(true);
    const res = await api<{ experiment_id: string; job_id: string; state: string }>(
      "POST",
      "/experiment/run",
      { goal, dataset_id: datasetId, target, provider, model: providerModel || null },
    );
    setStarting(false);
    if (!res.ok || !res.data) {
      setStartStatus(res.detail || res.error || "Failed to start experiment");
      return;
    }
    setStartStatus(`Experiment ${res.data.experiment_id} started.`);
    setStatus(null);
    setStageStatus({});
    setRunning(true);
    setExperimentId(res.data.experiment_id);
    setTab("run");
    loadHistory();
  };

  const sendFeedback = async () => {
    if (!experimentId || !feedback.trim()) return;
    setFeedbackStatus("Queueing iteration…");
    const res = await api<{ job_id: string; state: string }>(
      "POST",
      `/experiment/${encodeURIComponent(experimentId)}/feedback`,
      { feedback },
    );
    if (!res.ok || !res.data) {
      setFeedbackStatus(res.detail || res.error || "Failed to send feedback");
      return;
    }
    setFeedbackStatus("Iteration queued — watching progress…");
    setStageStatus({});
    setRunning(true);
  };

  const cancelRun = async () => {
    const jobId = status?.plan?.job_id;
    if (!jobId) return;
    await api("POST", `/jobs/${encodeURIComponent(jobId)}/cancel`);
  };

  const metricsEntries = Object.entries(status?.best_metrics ?? {}).filter(
    ([k, v]) => k.startsWith("test_") && typeof v === "number",
  );

  return (
    <>
      <div className="tab-row">
        {(["plan", "run", "proposals", "history"] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
            {t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === "plan" && (
        <section className="panel agent-panel">
          <h2>Plan experiment</h2>
          <p className="muted">
            Sub-agents run the pipeline: EDAAnalyst → FeatureEngineer → ModelSelector → approved
            batch training.
          </p>
          <div className="form-grid">
            <label htmlFor="exp-dataset">Dataset</label>
            <div>
              <input
                className="search-input"
                style={{ marginBottom: "var(--space-1)" }}
                value={datasetQuery}
                onChange={(e) => setDatasetQuery(e.target.value)}
                placeholder="Search datasets…"
              />
              <select
                id="exp-dataset"
                style={{
                  background: "var(--bg)",
                  color: "var(--text)",
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius)",
                  padding: "7px 8px",
                  width: "100%",
                }}
                value={datasetId}
                onChange={(e) => {
                  setDatasetId(e.target.value);
                  onDatasetChange({ ...datasetState, id: e.target.value });
                  const match = e.target.value.match(/_cleaned_([A-Za-z0-9_-]+?)(?:_\d+)?\.csv$/);
                  if (match) setTarget(match[1]);
                }}
              >
                <option value="">Select dataset…</option>
                {datasets
                  .filter((d) => d.dataset_id.toLowerCase().includes(datasetQuery.toLowerCase()))
                  .map((d) => {
                    const cleaned = /_cleaned_([A-Za-z0-9_-]+?)(?:_\d+)?\.csv$/.exec(d.dataset_id);
                    return (
                      <option key={d.dataset_id} value={d.dataset_id}>
                        {cleaned ? `◆ ${d.dataset_id} (target: ${cleaned[1]})` : `▦ ${d.dataset_id}`} ({d.rows})
                      </option>
                    );
                  })}
              </select>
            </div>
            <label htmlFor="exp-target">Target</label>
            <select
              id="exp-target"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            >
              <option value="">Select target…</option>
              {(targetColumns[datasetId] ?? []).map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
              {target !== "" && !(targetColumns[datasetId] ?? []).includes(target) && (
                <option value={target}>{target}</option>
              )}
            </select>
            <label htmlFor="exp-goal">Goal</label>
            <textarea
              id="exp-goal"
              rows={2}
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              placeholder="Predict the target and compare models"
            />
            <label htmlFor="exp-provider">LLM provider</label>
            <select id="exp-provider" value={provider} onChange={(e) => { setProvider(e.target.value); setProviderModel(""); }}>
              {providers.length === 0 && (
                <>
                  <option value="mock">mock (deterministic)</option>
                  <option value="ollama">ollama</option>
                </>
              )}
              {providers.map((p) => {
                let label = p.name;
                if (p.name === "ollama") {
                  label = p.reachable ? `ollama (${p.models?.length ?? 0} models)` : "ollama — server not reachable";
                } else if (!p.configured) {
                  label = `${p.name} — not configured`;
                }
                return (
                  <option key={p.name} value={p.name}>
                    {label}
                  </option>
                );
              })}
            </select>
            {provider === "ollama" && (() => {
              const info = providers.find((p) => p.name === "ollama");
              if (info?.reachable && info.models && info.models.length > 0) {
                return (
                  <>
                    <label htmlFor="exp-ollama-model">Ollama model</label>
                    <input
                      id="exp-ollama-model"
                      list="ollama-models"
                      value={providerModel}
                      onChange={(e) => setProviderModel(e.target.value)}
                      placeholder="pick a downloaded model"
                    />
                    <datalist id="ollama-models">
                      {info.models.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name === m.id ? m.id : `${m.name} (${m.id})`}
                        </option>
                      ))}
                    </datalist>                  </>
                );
              }
              return (
                <div className="banner error-banner" style={{ gridColumn: "1 / -1" }}>
                  <strong>Ollama is not reachable.</strong> Start the server
                  (<code>ollama serve</code>) and pull a model
                  (<code>ollama pull llama3.2</code>), then refresh this page.
                </div>
              );
            })()}
            {provider === "openrouter" && (() => {
              const info = providers.find((p) => p.name === "openrouter");
              return (
                <>
                  <label htmlFor="exp-openrouter-model">OpenRouter model</label>
                  <input
                    id="exp-openrouter-model"
                    list="openrouter-models"
                    value={providerModel}
                    onChange={(e) => setProviderModel(e.target.value)}
                    placeholder="pick or type, e.g. openai/gpt-4o-mini"
                  />
                  <datalist id="openrouter-models">
                    {(providers.find((p) => p.name === "openrouter")?.models ?? []).map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name ? `${m.name} (${m.id})` : m.id}
                      </option>
                    ))}
                  </datalist>
                  {info && !info.configured && (
                    <div className="banner error-banner" style={{ gridColumn: "1 / -1" }}>
                      <strong>OpenRouter needs an API key.</strong> Add{" "}
                      <code>THELAB_LLM_API_KEY=sk-or-…</code> to the{" "}
                      <code>.env</code> file in the project root, then restart{" "}
                      <code>thelab-model-service</code> and refresh this page.
                    </div>
                  )}
                </>
              );
            })()}
            {provider === "openai_compat" && (() => {
              const info = providers.find((p) => p.name === "openai_compat");
              if (info && !info.configured) {
                return (
                  <div className="banner error-banner" style={{ gridColumn: "1 / -1" }}>
                    <strong>openai-compatible</strong> needs env:{" "}
                    <code>{info.env.join(", ")}</code> — for a local Ollama use the
                    ollama provider instead.
                  </div>
                );
              }
              return null;
            })()}
            <button className="primary" onClick={start} disabled={starting}>
              {starting ? "Starting…" : "Start experiment"}
            </button>
          </div>
          {startStatus && <div className="banner loading-banner">{startStatus}</div>}
        </section>
      )}

      {tab === "run" && (
        <section className="panel agent-panel">
          <h2>
            Run {experimentId ? <code className="mono">{experimentId}</code> : ""}{" "}
            {status && <StatusBadge status={status.state} />}
          </h2>
          {!experimentId && <p className="empty">Start an experiment or pick one from History.</p>}

          {experimentId && (
            <>
              <StagePipeline stageStatus={stageStatus} finalState={status?.state ?? null} />

              <div style={{ display: "flex", gap: "var(--space-2)", marginBottom: "var(--space-2)" }}>
                {running && (
                  <button className="secondary" onClick={cancelRun}>
                    Cancel
                  </button>
                )}
                <span className={`muted mono`} style={{ alignSelf: "center" }}>
                  {connected ? "● live" : "○ stream ended"}
                </span>
              </div>

              <div className="exp-feed">
                {events.length === 0 && <p className="empty">Agent activity will stream here.</p>}
                {events.map((e, i) => (
                  <div key={i} className="exp-feed-entry">
                    <span className="timestamp">{(e.timestamp || "").slice(11, 19)}</span>
                    {e.data?.stage && <span className="stage-tag">[{e.data.stage}]</span>}
                    <span className={`level-${e.level}`}>{e.message}</span>
                  </div>
                ))}
              </div>

              {status?.best_run_id && (
                <div className="banner ok-banner" style={{ marginTop: "var(--space-3)" }}>
                  <strong>Best run:</strong> <code>{status.best_run_id}</code>
                  {metricsEntries.length > 0 && (
                    <>
                      <br />
                      {metricsEntries
                        .map(([k, v]) => `${k}: ${(v as number).toFixed(4)}`)
                        .join(" · ")}
                    </>
                  )}
                </div>
              )}
              {status?.error && <div className="banner error-banner">{status.error}</div>}

              {status?.sub_agent_results?.Proposal && (() => {
                const block = status.sub_agent_results.Proposal as {
                  rationale?: string;
                  model_grid?: string[];
                  seeds?: number[];
                  proposal_id?: string;
                };
                if (!block.rationale) return null;
                return (
                  <div key="proposal" className="interp-card">
                    <h4>Proposal — {block.proposal_id ?? "approved"}</h4>
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{block.rationale}</ReactMarkdown>
                    <div className="muted mono" style={{ fontSize: "0.72rem", marginTop: 6 }}>
                      grid: {block.model_grid?.join(", ")} · seeds: {block.seeds?.join(", ")}
                    </div>
                  </div>
                );
              })()}

              {INTERPRETERS.map(([key, label]) => {
                const result = status?.sub_agent_results?.[key];
                const interp = result?.llm_interpretation;
                if (!interp) return null;
                const usage = result?.llm_usage ?? {};
                const usageLine = [
                  usage.model ? String(usage.model) : null,
                  usage.prompt_tokens != null ? `${usage.prompt_tokens} prompt` : null,
                  usage.completion_tokens != null ? `${usage.completion_tokens} completion` : null,
                ]
                  .filter(Boolean)
                  .join(" · ");
                return (
                  <div key={key} className="interp-card">
                    <h4>{label}</h4>
                    <div className="md">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{String(interp)}</ReactMarkdown>
                    </div>
                    {usageLine && (
                      <div className="muted mono" style={{ fontSize: "0.72rem", marginTop: 6 }}>
                        {usageLine}
                      </div>
                    )}
                  </div>
                );
              })}

              <div className="form-grid" style={{ marginTop: "var(--space-3)" }}>
                <label htmlFor="exp-feedback">Feedback</label>
                <input
                  id="exp-feedback"
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                  placeholder="e.g. focus on tree models, drop petal_width"
                  disabled={running}
                />
                <button className="secondary" onClick={sendFeedback} disabled={running || !feedback.trim()}>
                  Send feedback (new iteration)
                </button>
              </div>
              {feedbackStatus && <div className="banner loading-banner">{feedbackStatus}</div>}
            </>
          )}
        </section>
      )}

      {tab === "proposals" && (
        <ProposalsView onOpenExperiment={(experimentId) => openExperiment(experimentId, true)} />
      )}

      {tab === "history" && (
        <section className="panel agent-panel">
          <h2>
            History <span className="count-chip">{history.length}</span>
          </h2>
          {history.length === 0 && <p className="empty">No experiments yet.</p>}
          {history.map((e) => (
            <div
              key={e.experiment_id}
              className={`list-card ${experimentId === e.experiment_id ? "active" : ""}`}
              onClick={() => openExperiment(e.experiment_id)}
            >
              <h3>
                {e.goal || "Untitled experiment"} <StatusBadge status={e.state} />
              </h3>
              <p>
                <code>{e.dataset_id}</code> · target {e.target} · updated{" "}
                {e.updated_at.slice(0, 19).replace("T", " ")}
              </p>
              {e.best_run_id && (
                <p>
                  best run <code>{e.best_run_id}</code>
                </p>
              )}
            </div>
          ))}
        </section>
      )}
    </>
  );
}

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { StatusBadge } from "../components/StatusBadge";

type RunAsExperimentProps = { onOpenExperiment?: (experimentId: string) => void };

type Proposal = {
  proposal_id: string;
  status: string;
  goal: string;
  dataset: string;
  target: string;
  model_grid: string[];
  seeds: number[];
  rationale?: string;
  batch_config?: string;
};

export default function ProposalsView({ onOpenExperiment }: RunAsExperimentProps = {}) {
  const [queryDataset, setQueryDataset] = useState("");
  const [queryDate, setQueryDate] = useState("");
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [selected, setSelected] = useState<Proposal | null>(null);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const res = await api<Proposal[]>("GET", "/proposals");
    if (res.ok && res.data) {
      // newest first (ids carry a creation timestamp)
      const sorted = [...res.data].sort((a, b) => b.proposal_id.localeCompare(a.proposal_id));
      setProposals(sorted);
      if (selected) {
        const updated = sorted.find((p) => p.proposal_id === selected.proposal_id);
        if (updated) setSelected(updated);
      }
    }
  }, [selected]);

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const open = async (id: string) => {
    const res = await api<Proposal>("GET", `/proposals/${encodeURIComponent(id)}`);
    if (res.ok && res.data) setSelected(res.data);
  };

  const act = async (action: "approve" | "reject" | "approve-and-run" | "run") => {
    if (!selected) return;
    setBusy(true);
    setStatus(`${action === "approve-and-run" ? "Approving and running" : action + "ing"} proposal…`);
    const res = await api("POST", `/proposals/${encodeURIComponent(selected.proposal_id)}/${action}`);
    setBusy(false);
    if (!res.ok) {
      setStatus(res.detail || res.error || `${action} failed`);
      return;
    }
    const data = (res.data ?? {}) as Record<string, unknown>;
    if (action === "approve-and-run" || action === "run") {
      const results = (data["results"] as { model: string; status: string; run_id?: string }[]) ?? [];
      const completed = results.filter((r) => r.status === "completed").length;
      setStatus(
        `${action}: ${data["status"] ?? "done"} — ${completed}/${results.length} runs completed`,
      );
    } else {
      setStatus(`${action}: ${selected.proposal_id}`);
    }
    refresh();
    open(selected.proposal_id);
  };

  const canApprove = selected?.status === "pending";
  const canRun = selected?.status === "approved";

  const filtered = proposals.filter(
    (p) =>
      (!queryDataset || p.dataset.toLowerCase().includes(queryDataset.toLowerCase())) &&
      (!queryDate || p.proposal_id.startsWith(`prop-${queryDate.replace(/-/g, "")}`)),
  );

  return (
    <>
      {status && <div className="banner loading-banner">{status}</div>}

      <section className="panel agent-panel">
        <h2>
          Proposals <span className="count-chip">{proposals.length}</span>
        </h2>
        <div style={{ display: "flex", gap: "var(--space-2)", marginBottom: "var(--space-2)", flexWrap: "wrap" }}>
          <input
            className="search-input"
            style={{ marginBottom: 0, flex: 2, minWidth: 160 }}
            value={queryDataset}
            onChange={(e) => setQueryDataset(e.target.value)}
            placeholder="Filter by dataset…"
          />
          <input
            type="date"
            className="search-input"
            style={{ marginBottom: 0, flex: 1, minWidth: 140 }}
            value={queryDate}
            onChange={(e) => setQueryDate(e.target.value)}
            aria-label="Filter by date"
          />
        </div>
        {filtered.length === 0 && proposals.length > 0 && <p className="empty">No proposals match the filters.</p>}
        {filtered.map((p) => (
          <div
            key={p.proposal_id}
            className={`list-card ${selected?.proposal_id === p.proposal_id ? "active" : ""}`}
            onClick={() => open(p.proposal_id)}
          >
            <h3>
              {p.goal || "Untitled proposal"} <StatusBadge status={p.status} />
            </h3>
            <p>
              <code>{p.dataset}</code> · target {p.target} · grid {p.model_grid?.join(", ") || "—"} ·
              seeds {p.seeds?.join(", ") || "—"}
            </p>
          </div>
        ))}
      </section>

      {selected && (
        <section className="panel agent-panel">
          <h2>
            {selected.proposal_id} <StatusBadge status={selected.status} />
          </h2>
          <div className="chip-grid">
            <div className="stat-chip">
              <div className="label">Dataset</div>
              <div className="value mono" style={{ fontSize: "0.8rem", wordBreak: "break-all" }}>
                {selected.dataset}
              </div>
            </div>
            <div className="stat-chip">
              <div className="label">Target</div>
              <div className="value mono" style={{ fontSize: "0.9rem" }}>
                {selected.target}
              </div>
            </div>
            <div className="stat-chip">
              <div className="label">Grid</div>
              <div className="value mono" style={{ fontSize: "0.9rem" }}>
                {selected.model_grid?.length ?? 0}
              </div>
            </div>
            <div className="stat-chip">
              <div className="label">Seeds</div>
              <div className="value mono" style={{ fontSize: "0.9rem" }}>
                {selected.seeds?.join(", ") || "—"}
              </div>
            </div>
          </div>
          {selected.rationale && (
            <div className="interp-card">
              <h4>Rationale</h4>
              {selected.rationale}
            </div>
          )}
          {selected.batch_config && (
            <p className="muted mono" style={{ fontSize: "0.8rem" }}>
              batch config: {selected.batch_config}
            </p>
          )}
          <div style={{ display: "flex", gap: "var(--space-2)", marginTop: "var(--space-2)", flexWrap: "wrap" }}>
            {canApprove && (
              <button className="primary" onClick={() => act("approve")} disabled={busy}>
                Approve
              </button>
            )}
            {canApprove && (
              <button className="secondary" onClick={() => act("reject")} disabled={busy}>
                Reject
              </button>
            )}
            {(canApprove || canRun) && (
              <button
                className="primary"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  setStatus("Starting experiment…");
                  const res = await api<{ experiment_id: string }>(
                    "POST",
                    `/proposals/${encodeURIComponent(selected.proposal_id)}/run-as-experiment`,
                  );
                  setBusy(false);
                  if (res.ok && res.data) {
                    setStatus(`Experiment ${res.data.experiment_id} started — watching in Run tab.`);
                    onOpenExperiment?.(res.data.experiment_id);
                  } else {
                    setStatus(res.detail || res.error || "failed to start");
                  }
                }}
              >
                Approve &amp; run (tracked experiment)
              </button>
            )}
            {canRun && (
              <button className="secondary" onClick={() => act("run")} disabled={busy}>
                Run (batch only)
              </button>
            )}
          </div>
        </section>
      )}
    </>
  );
}

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api";
import ModelLabSection from "../components/ModelLabSection";

type DatasetRow = {
  dataset_id: string;
  filename: string;
  source: string;
  rows: number;
  columns: number;
};

type Preview = {
  dataset_id: string;
  columns: { name: string; dtype: string }[];
  rows: Record<string, unknown>[];
};

type CorrPair = { feature_a: string; feature_b: string; correlation: number };
type LeakSuspect = { feature: string; correlation?: number };

type Eda = {
  dataset_id: string;
  rows: number;
  columns: number;
  feature_types?: {
    numeric_count?: number;
    categorical_count?: number;
    datetime_count?: number;
  };
  missing_profile?: {
    total_rows?: number;
    columns?: Record<string, { missing: number; missing_rate: number }>;
    most_missing?: string[];
  };
  class_balance?: {
    classes?: { class: string; count: number; rate: number }[];
    imbalance_ratio?: number | string;
  };
  correlation_hints?: { top_correlations?: CorrPair[] };
  outlier_scan?: {
    numeric_columns?: string[];
    columns?: Record<string, { iqr_outlier_count?: number; iqr_outlier_rate?: number }>;
  };
  leakage_suspects?: { suspects?: LeakSuspect[] };
};

type CleanReport = {
  dataset_id: string;
  rows: number;
  columns: number;
  dropped_rows: number;
  cleaning_report: { actions: string[] };
};

function cleanedTargetOf(datasetId: string): string | null {
  const match = datasetId.match(/_cleaned_([A-Za-z0-9_-]+?)(?:_\d+)?\.csv$/);
  return match ? match[1] : null;
}

function Histogram({ rows, column }: { rows: Record<string, unknown>[]; column: string }) {
  const values = rows
    .map((r) => r[column])
    .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  if (values.length < 2) return <p className="empty">Not enough numeric values.</p>;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const bins = 14;
  const width = (max - min) / bins || 1;
  const counts = new Array(bins).fill(0);
  for (const v of values) counts[Math.min(bins - 1, Math.floor((v - min) / width))] += 1;

  const data = counts.map((count, i) => ({ bin: `${(min + i * width).toFixed(1)}`, count }));

  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="bin" tick={{ fontSize: 10, fill: "var(--muted)" }} interval={2} />
        <YAxis tick={{ fontSize: 10, fill: "var(--muted)" }} allowDecimals={false} />
        <Tooltip
          contentStyle={{ background: "var(--surface-raised)", border: "1px solid var(--border)", fontSize: 12 }}
        />
        <Bar dataKey="count" fill="var(--accent)" radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function CorrBars({ pairs }: { pairs: CorrPair[] }) {
  if (!pairs.length) return <p className="empty">No numeric pairs to correlate.</p>;
  return (
    <table style={{ width: "100%", borderCollapse: "collapse" }}>
      <tbody>
        {pairs.slice(0, 8).map((p, i) => {
          const pct = Math.min(100, Math.abs(p.correlation) * 100);
          const color = p.correlation >= 0 ? "var(--accent)" : "var(--accent-2)";
          return (
            <tr key={i}>
              <td className="mono" style={{ padding: "3px 6px 3px 0", fontSize: "0.8rem" }}>
                {p.feature_a} ↔ {p.feature_b}
              </td>
              <td style={{ width: "42%" }}>
                <div style={{ background: "var(--bg)", borderRadius: 3, overflow: "hidden" }}>
                  <div style={{ width: `${pct}%`, background: color, height: 7 }} />
                </div>
              </td>
              <td className="mono" style={{ fontSize: "0.8rem" }}>
                {p.correlation.toFixed(3)}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function HBarChart({ data, color }: { data: { name: string; value: number }[]; color: string }) {
  if (!data.length) return <p className="empty">Nothing to show.</p>;
  return (
    <ResponsiveContainer width="100%" height={Math.max(120, data.length * 26)}>
      <BarChart data={data} layout="vertical" margin={{ top: 0, right: 12, bottom: 0, left: 40 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
        <XAxis type="number" tick={{ fontSize: 10, fill: "var(--muted)" }} />
        <YAxis
          type="category"
          dataKey="name"
          width={110}
          tick={{ fontSize: 10, fill: "var(--text)", fontFamily: "var(--font-mono)" }}
        />
        <Tooltip
          contentStyle={{ background: "var(--surface-raised)", border: "1px solid var(--border)", fontSize: 12 }}
        />
        <Bar dataKey="value" fill={color} radius={[0, 3, 3, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

type Props = {
  datasetState: { id: string; target: string };
  onDatasetChange: (state: { id: string; target: string }) => void;
};

export default function DataView({ datasetState, onDatasetChange }: Props) {
  const [showAllClasses, setShowAllClasses] = useState(false);
  const [datasets, setDatasets] = useState<DatasetRow[]>([]);
  const [kaggleSlug, setKaggleSlug] = useState("");
  const [kaggleBusy, setKaggleBusy] = useState(false);
  const [query, setQuery] = useState("");
  const selected = datasetState.id;
  const target = datasetState.target;
  const setTarget = (t: string) => onDatasetChange({ ...datasetState, target: t });
  const [preview, setPreview] = useState<Preview | null>(null);
  const [histCol, setHistCol] = useState<string>("");
  const [eda, setEda] = useState<Eda | null>(null);
  const [edaError, setEdaError] = useState("");
  const [status, setStatus] = useState<string>("");
  const [cleanReport, setCleanReport] = useState<CleanReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [openGroups, setOpenGroups] = useState({ raw: true, cleaned: true });

  const importKaggle = async () => {
    const raw = kaggleSlug.trim();
    const match = raw.match(/kaggle\.com\/datasets\/([^"'/\s]+\/?[^"'/\s]*)/) || raw.match(/^([\w-]+\/[\w-]+)/);
    const slug = match ? match[1].replace(/\/.only if$/, "") : raw;
    if (!slug.includes("/")) {
      setStatus("Provide a Kaggle dataset link or slug like 'owner/dataset'.");
      return;
    }
    setKaggleBusy(true);
    setStatus(`Importing ${slug}…`);
    const res = await api<{
      dataset_id: string;
      profile: { rows: number; columns: number };
    }>("POST", "/datasets/ingest-kaggle", { slug });
    setKaggleBusy(false);
    if (res.ok && res.data) {
      setStatus(`Imported ${res.data.dataset_id} (${res.data.profile.rows} rows)`);
      setKaggleSlug("");
      await refreshDatasets();
      await selectDataset(res.data.dataset_id);
    } else {
      setStatus(res.detail || res.error || "Kaggle import failed");
    }
  };

  const refreshDatasets = useCallback(async () => {
    const res = await api<DatasetRow[]>("GET", "/datasets");
    if (res.ok && res.data) setDatasets(res.data);
  }, []);

  useEffect(() => {
    refreshDatasets();
  }, [refreshDatasets]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return datasets;
    return datasets.filter((d) => d.dataset_id.toLowerCase().includes(q));
  }, [datasets, query]);

  const rawDatasets = filtered.filter((d) => !cleanedTargetOf(d.dataset_id));
  const cleanedDatasets = filtered.filter((d) => cleanedTargetOf(d.dataset_id));

  const loadPreview = useCallback(async (id: string) => {
    const res = await api<Preview>("GET", `/datasets/${encodeURIComponent(id)}/preview?limit=50`);
    if (res.ok && res.data) {
      setPreview(res.data);
      const numeric = res.data.columns.find((c) => c.dtype === "numeric");
      setHistCol(numeric ? numeric.name : "");
    }
  }, []);

  const selectDataset = async (id: string) => {
    onDatasetChange({ id, target: cleanedTargetOf(id) ?? "" });
    setEda(null);
    setEdaError("");
    setCleanReport(null);
    setStatus("");
    await loadPreview(id);
  };

  const onUpload = async (file: File) => {
    setBusy(true);
    setStatus(`Uploading ${file.name}…`);
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch("/datasets/upload", { method: "POST", body: form });
      const payload = (await res.json().catch(() => ({}))) as {
        ok?: boolean;
        data?: { dataset_id: string; rows: number };
        detail?: string;
        error?: string;
      };
      if (res.ok && payload.ok && payload.data) {
        setStatus(`Uploaded ${payload.data.dataset_id} (${payload.data.rows} rows)`);
        await refreshDatasets();
        await selectDataset(payload.data.dataset_id);
      } else {
        setStatus(payload.detail || payload.error || "Upload failed");
      }
    } finally {
      setBusy(false);
    }
  };

  const runEda = async () => {
    if (!selected) return;
    setBusy(true);
    setEdaError("");
    setStatus("Running EDA…");
    const q = target ? `?target=${encodeURIComponent(target)}` : "";
    const res = await api<Eda>("GET", `/eda/${encodeURIComponent(selected)}${q}`);
    setBusy(false);
    if (res.ok && res.data) {
      setEda(res.data);
      setStatus("");
    } else {
      setEda(null);
      setEdaError(res.detail || res.error || "EDA failed");
    }
  };

  const clean = async () => {
    if (!selected || !target) {
      setStatus("Enter a target column before cleaning.");
      return;
    }
    setBusy(true);
    setStatus("Cleaning…");
    const res = await api<CleanReport>("POST", `/datasets/${encodeURIComponent(selected)}/clean`, { target });
    setBusy(false);
    if (res.ok && res.data) {
      setCleanReport(res.data);
      setStatus(`Cleaned → ${res.data.dataset_id} (${res.data.rows} rows × ${res.data.columns} cols)`);
      await refreshDatasets();
      await selectDataset(res.data.dataset_id);
    } else {
      setStatus(res.detail || res.error || "Cleaning failed");
    }
  };

  const numericCols = preview?.columns.filter((c) => c.dtype === "numeric") ?? [];

  const missingData = eda?.missing_profile?.columns
    ? Object.entries(eda.missing_profile.columns)
        .filter(([, v]) => v.missing > 0)
        .sort((a, b) => b[1].missing - a[1].missing)
        .slice(0, 8)
        .map(([col, v]) => ({ name: col, value: v.missing }))
    : [];

  const outlierData =
    eda?.outlier_scan?.numeric_columns
      ?.map((c) => ({
        name: c,
        value: eda.outlier_scan?.columns?.[c]?.iqr_outlier_count ?? 0,
      }))
      .filter((d) => d.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 8) ?? [];

  const totalMissing = eda?.missing_profile?.columns
    ? Object.values(eda.missing_profile.columns).reduce((acc, v) => acc + v.missing, 0)
    : 0;

  const datasetList = (items: DatasetRow[], emptyLabel: string) =>
    items.length === 0 ? (
      <p className="empty" style={{ margin: "4px 0" }}>
        {emptyLabel}
      </p>
    ) : (
      items.map((d) => {
        const cleanedTarget = cleanedTargetOf(d.dataset_id);
        return (
          <button
            key={d.dataset_id}
            className={`nav-item ${selected === d.dataset_id ? "active" : ""}`}
            onClick={() => selectDataset(d.dataset_id)}
            style={{ marginBottom: 2 }}
          >
            <span className="nav-icon">{cleanedTarget ? "◆" : "▦"}</span>
            <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis" }}>
              <span className="mono" style={{ fontSize: "0.82rem" }}>
                {d.dataset_id}
              </span>
              <br />
              <span className="muted" style={{ fontSize: "0.74rem" }}>
                {d.rows} × {d.columns}
                {cleanedTarget ? ` · target: ${cleanedTarget}` : ""}
              </span>
            </span>
          </button>
        );
      })
    );

  return (
    <>
      {status && <div className="banner loading-banner">{status}</div>}
      {selected && /_cleaned/.test(selected) && (
        <div className="banner loading-banner">
          This dataset is already cleaned (target: {cleanedTargetOf(selected)}). Select the raw
          original to clean for a different target.
        </div>
      )}

      <section className="panel">
        <h2>Import from Kaggle</h2>
        <p className="muted">
          Paste a dataset link, a kagglehub snippet, or a slug (<code>owner/dataset</code>). The
          download plus the dataset&apos;s own documentation are stored as a context pack.
        </p>
        <div style={{ display: "flex", gap: "var(--space-2)" }}>
          <input
            value={kaggleSlug}
            onChange={(e) => setKaggleSlug(e.target.value)}
            placeholder="https://www.kaggle.com/datasets/owner/dataset"
            style={{
              flex: 1,
              background: "var(--bg)",
              color: "var(--text)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              padding: "7px 9px",
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") importKaggle();
            }}
          />
          <button className="primary" onClick={importKaggle} disabled={kaggleBusy || !kaggleSlug.trim()}>
            {kaggleBusy ? "Importing…" : "Import"}
          </button>
        </div>
      </section>

      <section className="panel">
        <h2>Upload</h2>
        <div
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const file = e.dataTransfer.files[0];
            if (file) onUpload(file);
          }}
          onClick={() => document.getElementById("dataset-file-input")?.click()}
          style={{
            border: "1px dashed var(--border-strong)",
            borderRadius: "var(--radius)",
            padding: "var(--space-3)",
            textAlign: "center",
            color: "var(--muted)",
            cursor: "pointer",
          }}
        >
          {busy ? "Working…" : "Drop a CSV/Parquet file here, or click to browse"}
        </div>
        <input
          id="dataset-file-input"
          type="file"
          accept=".csv,.parquet,text/csv"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) onUpload(file);
            e.target.value = "";
          }}
        />
      </section>

      <section className="panel">
        <h2>
          Datasets <span className="count-chip">{datasets.length}</span>
        </h2>
        <input
          className="search-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search datasets…"
        />
        <div
          className={`nav-group-title collapsible ${openGroups.raw ? "" : "collapsed"}`}
          onClick={() => setOpenGroups((g) => ({ ...g, raw: !g.raw }))}
        >
          <span className="chevron">▾</span> Raw{" "}
          <span className="count-chip">{rawDatasets.length}</span>
        </div>
        {openGroups.raw && datasetList(rawDatasets, "No raw datasets match.")}
        <div
          className={`nav-group-title collapsible ${openGroups.cleaned ? "" : "collapsed"}`}
          onClick={() => setOpenGroups((g) => ({ ...g, cleaned: !g.cleaned }))}
        >
          <span className="chevron">▾</span> Cleaned{" "}
          <span className="count-chip">{cleanedDatasets.length}</span>
        </div>
        {openGroups.cleaned && datasetList(cleanedDatasets, "No cleaned datasets yet — pick a target and click Clean.")}
      </section>

      {preview && (
        <section className="panel">
          <h2>
            Preview <span className="count-chip">{preview.dataset_id}</span>
          </h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {preview.columns.map((c) => (
                    <th key={c.name}>
                      {c.name}
                      <br />
                      <span className="muted" style={{ fontWeight: 400 }}>
                        {c.dtype}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.rows.slice(0, 20).map((row, i) => (
                  <tr key={i}>
                    {preview.columns.map((c) => (
                      <td key={c.name} className="mono">
                        {String(row[c.name] ?? "")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted" style={{ fontSize: "0.8rem" }}>
            First {Math.min(20, preview.rows.length)} of {preview.rows.length} rows — scroll
            horizontally for wide datasets.
          </p>
        </section>
      )}

      <section className="panel">
        <h2>EDA &amp; cleaning</h2>
        <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", flexWrap: "wrap" }}>
          <input
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            placeholder="Target column"
            style={{
              background: "var(--bg)",
              color: "var(--text)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              padding: "7px 8px",
              minWidth: 180,
            }}
          />
          <button className="primary" onClick={runEda} disabled={!selected || busy}>
            Run EDA
          </button>
          <button
            className="secondary"
            onClick={clean}
            disabled={!selected || busy || !target || /_cleaned/.test(selected)}
            title={/_cleaned/.test(selected) ? "Already cleaned — select the raw original to clean for a different target" : ""}
          >
            Clean dataset
          </button>
          {selected && <span className="muted mono">on {selected}</span>}
        </div>

        {edaError && (
          <div className="banner error-banner">
            <strong>EDA failed:</strong> {edaError}
          </div>
        )}

        {cleanReport && (
          <div className="banner ok-banner">
            <strong>Cleaning report — {cleanReport.dataset_id}</strong>
            <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
              {cleanReport.cleaning_report.actions.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ul>
          </div>
        )}

        {eda && (
          <>
            <div className="chip-grid" style={{ marginTop: "var(--space-3)" }}>
              <div className="stat-chip">
                <div className="label">Rows</div>
                <div className="value">{eda.rows}</div>
              </div>
              <div className="stat-chip">
                <div className="label">Columns</div>
                <div className="value">{eda.columns}</div>
              </div>
              <div className="stat-chip">
                <div className="label">Missing cells</div>
                <div className="value">{totalMissing}</div>
              </div>
              <div className="stat-chip">
                <div className="label">Numeric / categorical</div>
                <div className="value">
                  {eda.feature_types?.numeric_count ?? 0}/{eda.feature_types?.categorical_count ?? 0}
                </div>
              </div>
            </div>

            {eda.leakage_suspects?.suspects && eda.leakage_suspects.suspects.length > 0 && (
              <div className="banner error-banner">
                <strong>Leakage suspects:</strong>{" "}
                {eda.leakage_suspects.suspects.map((s) => s.feature).join(", ")}
              </div>
            )}

            <div className="eda-grid-2">
              <div className="eda-card">
                <h4>Missing values — top {missingData.length || 0}</h4>
                <HBarChart data={missingData} color="var(--warning)" />
              </div>

              <div className="eda-card">
                <h4>Top correlations</h4>
                <CorrBars pairs={eda.correlation_hints?.top_correlations ?? []} />
              </div>

              {eda.class_balance?.classes && eda.class_balance.classes.length > 0 && (
                <div className="eda-card">
                  <h4>Class balance — {target}</h4>
                  <HBarChart
                    data={(showAllClasses
                      ? eda.class_balance.classes
                      : eda.class_balance.classes.slice(0, 20)
                    ).map((c) => ({
                      name: String(c.class),
                      value: c.count,
                    }))}
                    color="var(--accent)"
                  />
                  {eda.class_balance.classes.length > 20 && (
                    <button
                      className="secondary"
                      style={{ fontSize: "0.75rem", padding: "3px 10px", marginTop: 4 }}
                      onClick={() => setShowAllClasses((s) => !s)}
                    >
                      {showAllClasses
                        ? "Show top 20"
                        : `Show all (${eda.class_balance.classes.length})`}
                    </button>
                  )}
                </div>
              )}

              <div className="eda-card">
                <h4>IQR outliers — top {outlierData.length || 0}</h4>
                <HBarChart data={outlierData} color="var(--accent-2)" />
              </div>
            </div>
          </>
        )}
      </section>

      {selected && target && (
        <ModelLabSection datasetId={selected} target={target} />
      )}

      {preview && numericCols.length > 0 && (
        <section className="panel">
          <h2>Distribution</h2>
          <select
            value={histCol}
            onChange={(e) => setHistCol(e.target.value)}
            style={{
              background: "var(--bg)",
              color: "var(--text)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              padding: "6px 8px",
              marginBottom: "var(--space-2)",
            }}
          >
            {numericCols.map((c) => (
              <option key={c.name} value={c.name}>
                {c.name}
              </option>
            ))}
          </select>
          <Histogram rows={preview.rows} column={histCol} />
        </section>
      )}
    </>
  );
}

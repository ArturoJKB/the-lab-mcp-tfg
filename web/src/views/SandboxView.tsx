import { useState } from "react";
import { api } from "../api";
import { StatusBadge } from "../components/StatusBadge";

type SandboxResult = {
  status: string;
  stdout: string;
  stderr?: string;
  return_value?: unknown;
  error?: string | null;
  artifacts?: { name?: string }[];
};

export default function SandboxView() {
  const [code, setCode] = useState(
    "import pandas as pd\n\ndf = pd.read_csv('dataset.csv') if __import__('pathlib').Path('dataset.csv').exists() else pd.DataFrame({'x': [1, 2, 3]})\nprint(df.shape)\nprint(df.head())",
  );
  const [result, setResult] = useState<SandboxResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const run = async () => {
    setBusy(true);
    setError("");
    const res = await api<SandboxResult>("POST", "/sandbox/run", { code });
    setBusy(false);
    if (!res.ok) {
      setError(res.detail || res.error || "sandbox failed");
      setResult(null);
      return;
    }
    setResult(res.data ?? null);
  };

  return (
    <>
      <div className="banner loading-banner">
        Restricted subprocess: deny-by-default imports, no network, memory + wall-clock limits.
        Compute isolation only — see <code>docs/legacy/P2_AUDIT.md</code>.
      </div>

      <section className="panel">
        <h2>Code</h2>
        <textarea
          value={code}
          onChange={(e) => setCode(e.target.value)}
          rows={12}
          style={{
            width: "100%",
            background: "var(--bg)",
            color: "var(--text)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
            padding: "var(--space-3)",
            fontFamily: "var(--font-mono)",
            fontSize: "0.85rem",
          }}
        />
        <button className="primary" onClick={run} disabled={busy} style={{ marginTop: "var(--space-2)" }}>
          {busy ? "Running…" : "Run"}
        </button>
        {error && <div className="banner error-banner">{error}</div>}
      </section>

      {result && (
        <section className="panel">
          <h2>
            Output <StatusBadge status={result.status} />
          </h2>
          <pre className="job-log" style={{ maxHeight: 320 }}>
            {result.stdout || "(no stdout)"}
          </pre>
          {result.error && <div className="banner error-banner">{result.error}</div>}
          {result.return_value != null && (
            <>
              <h3 className="muted" style={{ fontSize: "0.75rem", textTransform: "uppercase" }}>
                Return value
              </h3>
              <pre className="job-log" style={{ maxHeight: 200 }}>
                {String(result.return_value)}
              </pre>
            </>
          )}
        </section>
      )}
    </>
  );
}

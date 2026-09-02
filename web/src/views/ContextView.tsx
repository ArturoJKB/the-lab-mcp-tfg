import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";

type Session = {
  event_id: string;
  timestamp?: string;
  outcome?: { summary?: string };
  tags?: string[];
};

type ContextHit = {
  event_id: string;
  summary?: string;
  run_id?: string | null;
  tags?: string[];
};

type Entry = { event_id: string; redacted_summary?: string; tags?: string[]; timestamp?: string };

export default function ContextView() {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<ContextHit[]>([]);
  const [searched, setSearched] = useState(false);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [entry, setEntry] = useState<Entry | null>(null);
  const [status, setStatus] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  const loadSessions = useCallback(async () => {
    const res = await api<Session[]>("GET", "/agent-sessions");
    if (res.ok && res.data) setSessions(res.data);
  }, []);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  const search = async () => {
    const q = query.trim();
    if (!q) return;
    const res = await api<ContextHit[]>(
      "GET",
      `/agent/research/context/search?query=${encodeURIComponent(q)}&limit=20`,
    );
    setSearched(true);
    if (res.ok && res.data) setHits(res.data);
    else setStatus(res.detail || "search failed");
  };

  const openEntry = async (eventId: string) => {
    const res = await api<Entry>("GET", `/agent/research/context/entries/${encodeURIComponent(eventId)}`);
    if (res.ok && res.data) setEntry(res.data);
  };

  return (
    <>
      {status && <div className="banner error-banner">{status}</div>}

      <section className="panel">
        <h2>Context search</h2>
        <p className="muted">
          Full-text search over the local, redacted context store. No external RAG, no generative
          answers — this is retrieval over your own evidence.
        </p>
        <div style={{ display: "flex", gap: "var(--space-2)" }}>
          <input
            ref={searchRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") search();
            }}
            placeholder="e.g. proposal, churn, rejection…"
            style={{
              flex: 1,
              background: "var(--bg)",
              color: "var(--text)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              padding: "8px 10px",
            }}
          />
          <button className="primary" onClick={search}>
            Search
          </button>
        </div>

        {searched && hits.length === 0 && <p className="empty">No hits for "{query}".</p>}
        {hits.map((h) => (
          <div key={h.event_id} className="list-card" onClick={() => openEntry(h.event_id)}>
            <p className="mono" style={{ marginBottom: 4 }}>
              {h.event_id}
              {h.run_id ? ` · ${h.run_id}` : ""}
            </p>
            <p style={{ color: "var(--text)" }}>{h.summary}</p>
          </div>
        ))}
      </section>

      {entry && (
        <section className="panel">
          <h2>Entry {entry.event_id}</h2>
          <p className="muted mono" style={{ fontSize: "0.78rem" }}>
            {entry.timestamp}
          </p>
          <p>{entry.redacted_summary}</p>
          {entry.tags && entry.tags.length > 0 && (
            <p className="mono muted" style={{ fontSize: "0.78rem" }}>
              {entry.tags.join(" · ")}
            </p>
          )}
        </section>
      )}

      <section className="panel">
        <h2>
          Agent sessions <span className="count-chip">{sessions.length}</span>
        </h2>
        {sessions.length === 0 && <p className="empty">No agent sessions recorded yet.</p>}
        {sessions.map((s) => (
          <div key={s.event_id} className="list-card" onClick={() => openEntry(s.event_id)}>
            <h3>{s.outcome?.summary || s.event_id}</h3>
            <p>
              {s.timestamp?.slice(0, 19).replace("T", " ")}
              {s.tags && s.tags.length > 0 ? ` · ${s.tags.join(", ")}` : ""}
            </p>
          </div>
        ))}
      </section>
    </>
  );
}

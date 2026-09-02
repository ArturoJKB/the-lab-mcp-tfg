import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "../api";
import type { ProviderInfo, ToolTrace } from "./ProviderInfo";

export type ChatTurn = {
  role: "user" | "assistant";
  content: string;
  toolCalls?: ToolTrace[];
  usage?: Record<string, unknown> | null;
  elapsed?: number | null;
  error?: string | null;
  streaming?: boolean;
};

type StreamEvent = {
  type: "event" | "result" | "token";
  delta?: string;
  // event payload
  tool?: string;
  ok?: boolean;
  error?: string;
  // result payload
  status?: string;
  answer?: string | null;
  tool_calls?: ToolTrace[];
  usage?: {
    models?: string[];
    prompt_tokens?: number;
    completion_tokens?: number;
    elapsed_seconds?: number;
  } | null;
};

type Props = {
  datasetId: string;
  target: string;
  turns: ChatTurn[];
  setTurns: React.Dispatch<React.SetStateAction<ChatTurn[]>>;
  onOpenExperiment: (experimentId: string) => void;
  expanded: boolean;
  onToggleExpand: () => void;
  onClose: () => void;
};

export function ChatDrawer({
  datasetId,
  target,
  turns,
  setTurns,
  onOpenExperiment,
  expanded,
  onToggleExpand,
  onClose,
}: Props) {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [provider, setProvider] = useState("mock");
  const [providerModel, setProviderModel] = useState("");
  const [roleHint, setRoleHint] = useState("");
  const [styleHint, setStyleHint] = useState("");
  const [showDirectives, setShowDirectives] = useState(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [liveTrace, setLiveTrace] = useState<ToolTrace[]>([]);
  const turnsEndRef = useRef<HTMLDivElement>(null);
  const turnsRef = useRef(turns);
  turnsRef.current = turns;

  useEffect(() => {
    api<ProviderInfo[]>("GET", "/agent/providers").then((r) => {
      if (r.ok && r.data) setProviders(r.data);
    });
  }, []);

  useEffect(() => {
    turnsEndRef.current?.scrollTo({ top: turnsEndRef.current.scrollHeight });
  }, [turns, busy, liveTrace]);

  const send = async () => {
    const message = input.trim();
    if (!message || busy) return;
    setInput("");
    setTurns((prev) => [...prev, { role: "user", content: message }]);
    setBusy(true);
    setElapsed(0);
    setLiveTrace([]);
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed((Date.now() - started) / 1000), 250);

    const history = turnsRef.current
      .filter((t) => !t.error)
      .map((t) => ({ role: t.role, content: t.content }));

    try {
      const res = await fetch("/agent/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          history,
          provider,
          model: providerModel || null,
          dataset_id: datasetId || null,
          style: styleHint || null,
          role_hint: roleHint || null,
        }),
      });
      if (!res.ok || !res.body) {
        const detail = await res.text();
        setTurns((prev) => [
          ...prev.filter((t) => !t.streaming || t.content),
          { role: "assistant", content: "", error: detail.slice(0, 300) || "agent failed" },
        ]);
        return;
      }

      // progressive answer bubble
      setTurns((prev) => [...prev, { role: "assistant", content: "", streaming: true }]);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let done = false;
      while (!done) {
        const { value, done: rdDone } = await reader.read();
        if (rdDone) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";
        for (const part of parts) {
          const line = part.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;
          let evt: StreamEvent;
          try {
            evt = JSON.parse(line.slice(6));
          } catch {
            continue;
          }
          if (evt.type === "token" && evt.delta) {
            setTurns((prev) => {
              const copy = [...prev];
              const last = copy[copy.length - 1];
              if (last && last.role === "assistant" && last.streaming) {
                copy[copy.length - 1] = { ...last, content: last.content + evt.delta! };
              }
              return copy;
            });
          } else if (evt.type === "event" && evt.tool) {
            setLiveTrace((prev) => [
              ...prev,
              { tool: evt.tool!, ok: evt.ok ?? false, error: evt.error ?? null },
            ]);
          } else if (evt.type === "result") {
            done = true;
            if (evt.status === "success") {
              setTurns((prev) => {
                const copy = [...prev];
                const last = copy[copy.length - 1];
                const streamed = last && last.role === "assistant" && last.streaming;
                const finalTurn: ChatTurn = {
                  role: "assistant",
                  content: evt.answer ?? "",
                  toolCalls: evt.tool_calls,
                  usage: evt.usage,
                  elapsed: evt.usage?.elapsed_seconds ?? null,
                };
                if (streamed) {
                  copy[copy.length - 1] = finalTurn;
                } else {
                  copy.push(finalTurn);
                }
                return copy;
              });
            } else {
              setTurns((prev) => {
                // drop the empty streaming bubble if it appeared
                const copy = prev.filter((t) => !t.streaming || t.content);
                return [
                  ...copy,
                  { role: "assistant" as const, content: "", error: evt.error || "agent refused" },
                ];
              });
            }
          }
        }
      }
    } catch (err) {
      setTurns((prev) => [
        ...prev,
        { role: "assistant", content: "", error: err instanceof Error ? err.message : String(err) },
      ]);
    } finally {
      window.clearInterval(timer);
      setBusy(false);
      setLiveTrace([]);
    }
  };

  const providerInfo = providers.find((p) => p.name === provider);
  const providerLabel = (() => {
    if (!providerInfo) return provider;
    if (providerInfo.name === "ollama") {
      return providerInfo.reachable
        ? `ollama (${providerInfo.models?.length ?? 0} models)`
        : "ollama — not reachable";
    }
    return providerInfo.configured ? providerInfo.name : `${providerInfo.name} — not configured`;
  })();

  return (
    <div className="chat-overlay" onClick={onClose}>
      <aside
        className={`chat-drawer ${expanded ? "expanded" : ""}`}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="chat-header">
          <h2>Global agent</h2>
          <span className="muted mono" style={{ fontSize: "0.72rem" }}>
            {providerLabel}
            {providerModel ? ` · ${providerModel}` : ""}
          </span>
          <button className="dock-btn" onClick={onToggleExpand} title="Expand">
            {expanded ? "⤡" : "⤢"}
          </button>
          <button className="dock-btn" onClick={onClose} aria-label="Close chat">
            ✕
          </button>
        </header>

        <div className="chat-context muted">
          Grounded in:{" "}
          {datasetId ? (
            <>
              <code>{datasetId}</code>
              {target ? ` · target ${target}` : ""}
            </>
          ) : (
            "no dataset selected (pick one in Data)"
          )}
        </div>

        <div className="chat-messages">
          <ChatTurnList turns={turns} onApproved={onOpenExperiment} />
          {busy && (
            <div className="chat-turn assistant">
              <div className="chat-role">Agent</div>
              {!turns.some((t) => t.streaming && t.content) && (
              <div className="chat-bubble">
                <span className="pulse-dot" /> working…
                {liveTrace.length > 0 && (
                  <div className="chat-tools mono">
                    {liveTrace.map((t, i) => (
                      <div key={i}>
                        <span className={t.ok ? "level-done" : "level-error"}>
                          {t.ok ? "✓" : "✗"} {t.tool}
                        </span>
                        {t.error ? ` — ${t.error}` : ""}
                      </div>
                    ))}
                  </div>
                )}
                <div className="muted mono" style={{ fontSize: "0.7rem", marginTop: 4 }}>
                  {elapsed.toFixed(1)}s
                </div>
              </div>
              )}
            </div>
          )}
          <div ref={turnsEndRef} />
        </div>

        <div className="chat-directives">
          <button
            className="dock-btn"
            title="Response directives (role + style)"
            onClick={() => setShowDirectives((s) => !s)}
          >
            ⌗
          </button>
          <select
            value={provider}
            onChange={(e) => {
              setProvider(e.target.value);
              setProviderModel("");
            }}
            title={providerLabel}
            aria-label="Provider"
          >
            {providers.length === 0 && <option value="mock">mock</option>}
            {providers.map((p) => (
              <option key={p.name} value={p.name}>
                {p.name}
                {p.name === "ollama"
                  ? p.reachable
                    ? ` (${p.models?.length ?? 0})`
                    : " (down)"
                  : p.configured
                    ? ""
                    : " (not configured)"}
              </option>
            ))}
          </select>
          {provider === "ollama" && (
            <input
              list="chat-ollama-models"
              value={providerModel}
              onChange={(e) => setProviderModel(e.target.value)}
              placeholder="model (optional)"
              aria-label="Ollama model"
            />
          )}
          {provider === "openrouter" && (
            <input
              list="chat-openrouter-models"
              value={providerModel}
              onChange={(e) => setProviderModel(e.target.value)}
              placeholder="model (optional)"
              aria-label="OpenRouter model"
            />
          )}
          <datalist id="chat-ollama-models">
            {(providerInfo?.models ?? []).map((m) => (
              <option key={m.id} value={m.id} />
            ))}
          </datalist>
          <datalist id="chat-openrouter-models">
            {(providerInfo?.models ?? []).map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </datalist>
        </div>

        {showDirectives && (
          <div className="chat-directives-panel">
            <label>
              Role <span className="muted">(e.g. "data science tutor")</span>
            </label>
            <input value={roleHint} onChange={(e) => setRoleHint(e.target.value)} />
            <label>
              Style <span className="muted">(e.g. "short, actionable, non-technical")</span>
            </label>
            <input value={styleHint} onChange={(e) => setStyleHint(e.target.value)} />
          </div>
        )}

        <div className="chat-input-row">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            rows={2}
            placeholder={
              datasetId ? "Ask about this dataset… (Shift+Enter for a new line)" : "Ask about your runs…"
            }
            disabled={busy}
          />
          <button className="primary" onClick={send} disabled={busy || !input.trim()}>
            Send
          </button>
        </div>
      </aside>
    </div>
  );
}

function ProposalAction({ proposalId, onApproved }: { proposalId: string; onApproved: (experimentId: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [started, setStarted] = useState<string | null>(null);
  const [error, setError] = useState("");

  const run = async () => {
    setBusy(true);
    setError("");
    const res = await api<{ experiment_id: string }>(
      "POST",
      `/proposals/${encodeURIComponent(proposalId)}/run-as-experiment`,
    );
    setBusy(false);
    if (res.ok && res.data) {
      setStarted(res.data.experiment_id);
      onApproved(res.data.experiment_id);
    } else {
      setError(res.detail || res.error || "failed to start");
    }
  };

  return (
    <div className="chat-proposal-actions">
      {!started ? (
        <>
          <button className="primary" onClick={run} disabled={busy}>
            {busy ? "Starting…" : "Approve & run as experiment"}
          </button>
          <span className="muted" style={{ fontSize: "0.75rem" }}>
            tracked in Experiments → History with live progress
          </span>
          {error && <div className="banner error-banner">{error}</div>}
        </>
      ) : (
        <div className="banner ok-banner">Experiment {started} started — see Experiments → History.</div>
      )}
    </div>
  );
}

function ChatTurnList({
  turns,
  onApproved,
}: {
  turns: ChatTurn[];
  onApproved: (experimentId: string) => void;
}) {
  return (
    <>
      {turns.map((t, i) => (
        <div key={i} className={`chat-turn ${t.role}`}>
          <div className="chat-role">{t.role === "user" ? "You" : "Agent"}</div>
          {t.content && (
            <div className="chat-bubble md">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{t.content}</ReactMarkdown>
              {t.streaming && <span className="pulse-dot" />}
            </div>
          )}
          {t.toolCalls && t.toolCalls.length > 0 && (
            <div className="chat-tools mono">
              {t.toolCalls.map((tc, j) => (
                <div key={j}>
                  <span className={tc.ok ? "level-done" : "level-error"}>
                    {tc.ok ? "✓" : "✗"} {tc.tool}
                  </span>
                  {tc.error ? ` — ${tc.error}` : ""}
                </div>
              ))}
            </div>
          )}
          {t.usage && (
            <div className="muted mono" style={{ fontSize: "0.7rem", marginTop: 4 }}>
              {(t.usage.models as string[] | undefined)?.join(", ")}
              {t.usage.prompt_tokens ? ` · ${t.usage.prompt_tokens} prompt` : ""}
              {t.usage.completion_tokens ? ` · ${t.usage.completion_tokens} completion` : ""}
              {t.elapsed != null ? ` · ${t.elapsed}s` : ""}
            </div>
          )}
          {t.error && <div className="banner error-banner">{t.error}</div>}
          {(t.toolCalls ?? [])
            .filter((tc) => tc.tool === "propose_experiment" && tc.ok && tc.proposal_id)
            .map((tc) => (
              <ProposalAction
                key={`${i}-${tc.proposal_id}`}
                proposalId={tc.proposal_id!}
                onApproved={onApproved}
              />
            ))}
        </div>
      ))}
    </>
  );
}

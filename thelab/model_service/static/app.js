let activeRunId = null;
let activeFeatureColumns = [];
let benchmarkData = null;

function show(el, html) {
  el.innerHTML = html;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

async function api(method, path, body) {
  const options = { method, headers: {} };
  if (body) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const res = await fetch(path, options);
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { ok: false, error: "Non-JSON response" };
  }
  return { ok: res.ok && (data ? data.ok : false), status: res.status, data };
}

// ---------- Sidebar navigation ----------

function initSidebar() {
  document.querySelectorAll(".nav-button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const panelId = btn.dataset.panel;
      document.querySelectorAll(".nav-button").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".panel-section").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      const panel = document.getElementById(panelId);
      if (panel) panel.classList.add("active");
    });
  });
}

function setSidebarHealth(ok) {
  const dot = document.getElementById("sidebar-health");
  if (!dot) return;
  dot.classList.toggle("ok", ok);
  dot.classList.toggle("error", !ok);
}

// ---------- Models panel (Slice 5) ----------

async function loadStatus() {
  const el = document.getElementById("status-content");
  const res = await api("GET", "/health");
  const ok = res.ok && res.data && res.data.status === "ok";
  setSidebarHealth(ok);
  if (ok) {
    show(el, `<span class="ok">●</span> Service ok`);
  } else {
    show(el, `<span class="error">●</span> Service unreachable`);
  }
}

async function loadModels() {
  const tbody = document.getElementById("models-table-body");
  const res = await api("GET", "/models");
  if (!res.ok) {
    show(tbody, `<tr><td colspan="5" class="error">Failed to load models</td></tr>`);
    return;
  }
  const models = res.data.data || [];
  if (models.length === 0) {
    show(tbody, `<tr><td colspan="5">No approved models found.</td></tr>`);
    return;
  }
  function formatModelMetric(m) {
    const metrics = m.metrics || {};
    if (m.task_type === "regression") {
      return metrics.test_r2 != null ? `R2 ${metrics.test_r2.toFixed(4)}` : "—";
    }
    return metrics.test_accuracy != null ? `Acc ${metrics.test_accuracy.toFixed(4)}` : "—";
  }
  tbody.innerHTML = models.map(m => `
    <tr data-run-id="${escapeHtml(m.run_id)}">
      <td>${escapeHtml(m.run_id)}</td>
      <td>${escapeHtml(m.model || "")}</td>
      <td>${escapeHtml(m.target || "")}</td>
      <td>${escapeHtml(m.task_type || "")}</td>
      <td>${formatModelMetric(m)}</td>
    </tr>
  `).join("");

  tbody.querySelectorAll("tr").forEach(row => {
    row.addEventListener("click", () => selectRun(row.dataset.runId));
  });
}

async function selectRun(runId) {
  activeRunId = runId;
  document.querySelectorAll("#models-table-body tr").forEach(row => row.classList.remove("active"));
  const row = document.querySelector(`#models-table-body tr[data-run-id="${CSS.escape(runId)}"]`);
  if (row) row.classList.add("active");

  await loadRunMetrics(runId);
  await loadArtifacts(runId);
  buildPredictForm(runId);

  const iteratePanel = document.getElementById("panel-iterate");
  const iterateRunId = document.getElementById("iterate-run-id");
  if (iteratePanel && iterateRunId) {
    iteratePanel.classList.remove("hidden");
    iterateRunId.value = runId;
  }
}

async function loadRunMetrics(runId) {
  const el = document.getElementById("metrics-content");
  const res = await api("GET", `/runs/${encodeURIComponent(runId)}`);
  if (!res.ok) {
    show(el, `<span class="error">${res.data && res.data.error ? escapeHtml(res.data.error) : "Failed to load run"}</span>`);
    return;
  }
  const run = res.data.data;
  activeFeatureColumns = run.feature_columns || [];
  const metrics = run.metrics || {};
  const isRegression = run.task_type === "regression";
  const metricLine = isRegression
    ? `<strong>Test RMSE:</strong> ${metrics.test_rmse != null ? metrics.test_rmse.toFixed(4) : "—"} &nbsp;|&nbsp; <strong>Test R2:</strong> ${metrics.test_r2 != null ? metrics.test_r2.toFixed(4) : "—"}`
    : `<strong>Test accuracy:</strong> ${metrics.test_accuracy != null ? metrics.test_accuracy.toFixed(4) : "—"} &nbsp;|&nbsp; <strong>Test F1:</strong> ${metrics.test_f1_macro != null ? metrics.test_f1_macro.toFixed(4) : "—"}`;
  show(el, `
    <p><strong>Run ID:</strong> ${escapeHtml(run.run_id)}</p>
    <p><strong>Model:</strong> ${escapeHtml(run.model || "")} &nbsp;|&nbsp; <strong>Target:</strong> ${escapeHtml(run.target || "")}</p>
    <p><strong>Task type:</strong> ${escapeHtml(run.task_type || "")} &nbsp;|&nbsp; <strong>Status:</strong> ${escapeHtml(run.final_status)} / ${escapeHtml(run.validation_status)}</p>
    <p>${metricLine}</p>
    <p><strong>Feature columns:</strong> ${(run.feature_columns || []).map(c => `<code>${escapeHtml(c)}</code>`).join(", ")}</p>
  `);
}

async function loadArtifacts(runId) {
  const toolbar = document.getElementById("artifacts-toolbar");
  const content = document.getElementById("artifacts-content");
  const res = await api("GET", `/runs/${encodeURIComponent(runId)}/artifacts`);
  if (!res.ok) {
    show(toolbar, "");
    show(content, `<span class="error">Failed to load artifacts</span>`);
    return;
  }
  const artifacts = res.data.data || [];
  if (artifacts.length === 0) {
    show(toolbar, "");
    show(content, "No allowlisted artifacts available.");
    return;
  }
  show(toolbar, `
    <label for="artifact-select">Artifact:</label>
    <select id="artifact-select">
      ${artifacts.map(a => `<option value="${escapeHtml(a.name)}">${escapeHtml(a.name)} (${escapeHtml(a.kind)})</option>`).join("")}
    </select>
    <button id="artifact-load">Load</button>
  `);
  document.getElementById("artifact-load").addEventListener("click", () => {
    const name = document.getElementById("artifact-select").value;
    loadArtifact(runId, name);
  });
  await loadArtifact(runId, artifacts[0].name);
}

async function loadArtifact(runId, artifactName) {
  const content = document.getElementById("artifacts-content");
  const res = await api("GET", `/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactName)}`);
  if (!res.ok) {
    show(content, `<span class="error">${res.data && res.data.error ? escapeHtml(res.data.error) : "Failed to load artifact"}</span>`);
    return;
  }
  const data = res.data.data;
  if (typeof data === "string") {
    show(content, escapeHtml(data));
  } else {
    show(content, escapeHtml(JSON.stringify(data, null, 2)));
  }
}

function buildPredictForm(runId) {
  const area = document.getElementById("predict-form-area");
  const result = document.getElementById("predict-result");
  show(result, "");
  if (!activeFeatureColumns.length) {
    show(area, "No feature columns available for prediction.");
    return;
  }
  show(area, `
    <p class="muted">Run ID: <code>${escapeHtml(runId)}</code></p>
    ${activeFeatureColumns.map(col => `
      <div class="feature-field">
        <label for="pred-${escapeHtml(col)}">${escapeHtml(col)}</label>
        <input type="number" step="any" id="pred-${escapeHtml(col)}" required>
      </div>
    `).join("")}
    <button id="predict-submit">Predict</button>
  `);
  document.getElementById("predict-submit").addEventListener("click", () => runPredict(runId));
}

async function runPredict(runId) {
  const resultEl = document.getElementById("predict-result");
  const features = {};
  for (const col of activeFeatureColumns) {
    const input = document.getElementById(`pred-${col}`);
    const value = parseFloat(input.value);
    if (Number.isNaN(value)) {
      show(resultEl, `<span class="error">Invalid value for ${escapeHtml(col)}</span>`);
      return;
    }
    features[col] = value;
  }
  const res = await api("POST", "/predict", { run_id: runId, features: [features] });
  if (!res.ok) {
    show(resultEl, `<span class="error">${res.data && res.data.error ? escapeHtml(res.data.error) : "Prediction failed"}</span>`);
    return;
  }
  const data = res.data.data;
  show(resultEl, `
    <p class="ok">Prediction ready</p>
    <p><strong>Predictions:</strong> ${escapeHtml(JSON.stringify(data.predictions))}</p>
    <p class="muted">Model: ${escapeHtml(data.model || "")} | Target: ${escapeHtml(data.target || "")}</p>
  `);
}

// ---------- Coding / Logger panel ----------

let codingRunId = null;
let codingArtifacts = [];

async function loadCodingRuns() {
  const select = document.getElementById("coding-run-select");
  const res = await api("GET", "/agent/coding/runs");
  if (!res.ok) {
    show(select, `<option>Failed to load runs</option>`);
    return;
  }
  const runs = res.data.data || [];
  if (runs.length === 0) {
    show(select, `<option>No runs available</option>`);
    return;
  }
  select.innerHTML = runs.map(r =>
    `<option value="${escapeHtml(r.run_id)}">${escapeHtml(r.run_id)} (${escapeHtml(r.final_status || "?")}/${escapeHtml(r.validation_status || "?")})</option>`
  ).join("");
  codingRunId = runs[0].run_id;
  await loadCodingRun(codingRunId);
}

async function loadCodingRun(runId) {
  codingRunId = runId;
  const content = document.getElementById("coding-content");
  const artifactsEl = document.getElementById("coding-artifacts");
  const artifactContent = document.getElementById("coding-artifact-content");
  const res = await api("GET", `/agent/coding/runs/${encodeURIComponent(runId)}`);
  if (!res.ok) {
    show(content, `<span class="error">${res.data && res.data.error ? escapeHtml(res.data.error) : "Failed to load run"}</span>`);
    return;
  }
  const run = res.data.data;
  codingArtifacts = run.artifacts || [];
  const metrics = run.metrics || {};
  const isRegression = run.task_type === "regression";
  const metricLine = isRegression
    ? `<strong>Test RMSE:</strong> ${metrics.test_rmse != null ? metrics.test_rmse.toFixed(4) : "—"} &nbsp;|&nbsp; <strong>Test R2:</strong> ${metrics.test_r2 != null ? metrics.test_r2.toFixed(4) : "—"}`
    : `<strong>Test accuracy:</strong> ${metrics.test_accuracy != null ? metrics.test_accuracy.toFixed(4) : "—"} &nbsp;|&nbsp; <strong>Test F1:</strong> ${metrics.test_f1_macro != null ? metrics.test_f1_macro.toFixed(4) : "—"}`;
  show(content, `
    <p><strong>Run ID:</strong> <code>${escapeHtml(run.run_id)}</code></p>
    <p><strong>Status:</strong> ${escapeHtml(run.final_status)} / ${escapeHtml(run.validation_status)}</p>
    <p><strong>Model:</strong> ${escapeHtml(run.model || "")} &nbsp;|&nbsp; <strong>Target:</strong> ${escapeHtml(run.target || "")}</p>
    <p><strong>Task type:</strong> ${escapeHtml(run.task_type || "")}</p>
    <p><strong>Dataset:</strong> ${escapeHtml(run.dataset || "—")}</p>
    <p><strong>Seed:</strong> ${run.seed != null ? escapeHtml(String(run.seed)) : "—"}</p>
    <p>${metricLine}</p>
    <p><strong>Feature columns:</strong> ${(run.feature_columns || []).map(c => `<code>${escapeHtml(c)}</code>`).join(", ")}</p>
  `);
  if (codingArtifacts.length) {
    show(artifactsEl, `
      <label for="coding-artifact-select">Artifact:</label>
      <select id="coding-artifact-select">
        ${codingArtifacts.map(a => `<option value="${escapeHtml(a.name)}">${escapeHtml(a.name)}</option>`).join("")}
      </select>
      <button id="coding-artifact-load">Load</button>
    `);
    document.getElementById("coding-artifact-load").addEventListener("click", () => {
      const name = document.getElementById("coding-artifact-select").value;
      loadCodingArtifact(runId, name);
    });
    await loadCodingArtifact(runId, codingArtifacts[0].name);
  } else {
    show(artifactsEl, "<p class=\"muted\">No allowlisted artifacts.</p>");
    show(artifactContent, "");
  }
}

async function loadCodingArtifact(runId, artifactName) {
  const content = document.getElementById("coding-artifact-content");
  const res = await api("GET", `/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactName)}`);
  if (!res.ok) {
    show(content, `<span class="error">${res.data && res.data.error ? escapeHtml(res.data.error) : "Failed to load artifact"}</span>`);
    return;
  }
  const data = res.data.data;
  if (typeof data === "string") {
    show(content, escapeHtml(data));
  } else {
    show(content, escapeHtml(JSON.stringify(data, null, 2)));
  }
}

function initCodingPanel() {
  const loadBtn = document.getElementById("coding-load-run");
  if (loadBtn) {
    loadBtn.addEventListener("click", () => {
      const runId = document.getElementById("coding-run-select").value;
      loadCodingRun(runId);
    });
  }
}

// ---------- Research / Copilot panel ----------

async function loadResearchStatus() {
  const el = document.getElementById("research-status");
  const res = await api("GET", "/agent/research/context/status");
  if (!res.ok) {
    show(el, `<span class="error">Failed to load context status</span>`);
    return;
  }
  const status = res.data.data;
  if (!status.indexed) {
    show(el, `<p class="muted">Context index not initialized.</p>`);
    return;
  }
  show(el, `
    <p><strong>Context indexed:</strong> ${status.indexed}</p>
    <p><strong>Entries:</strong> ${status.entry_count} &nbsp;|&nbsp; <strong>FTS5 available:</strong> ${status.fts5_available}</p>
  `);
}

async function runResearchSearch() {
  const query = document.getElementById("research-query").value.trim();
  const resultsEl = document.getElementById("research-results");
  const entryEl = document.getElementById("research-entry");
  show(entryEl, "");
  if (!query) {
    show(resultsEl, "");
    return;
  }
  const res = await api("GET", `/agent/research/context/search?query=${encodeURIComponent(query)}&limit=20`);
  if (!res.ok) {
    show(resultsEl, `<span class="error">${res.data && res.data.error ? escapeHtml(res.data.error) : "Search failed"}</span>`);
    return;
  }
  const entries = res.data.data || [];
  if (entries.length === 0) {
    show(resultsEl, "<p class=\"muted\">No matching entries.</p>");
    return;
  }
  show(resultsEl, `
    <p class="muted">${entries.length} result(s)</p>
    <ul>
      ${entries.map(e => `
        <li>
          <button class="link-button" data-event-id="${escapeHtml(e.event_id)}">
            ${escapeHtml(e.event_id)} — ${escapeHtml(e.event_type)}
          </button>
          <br><span class="muted">${escapeHtml(e.redacted_summary || "")}</span>
        </li>
      `).join("")}
    </ul>
  `);
  resultsEl.querySelectorAll(".link-button").forEach(btn => {
    btn.addEventListener("click", () => loadResearchEntry(btn.dataset.eventId));
  });
}

async function loadResearchEntry(eventId) {
  const el = document.getElementById("research-entry");
  const res = await api("GET", `/agent/research/context/entries/${encodeURIComponent(eventId)}`);
  if (!res.ok) {
    show(el, `<span class="error">${res.data && res.data.error ? escapeHtml(res.data.error) : "Entry not found"}</span>`);
    return;
  }
  const entry = res.data.data;
  show(el, `
    <h3>${escapeHtml(entry.event_id)}</h3>
    <p><strong>Type:</strong> ${escapeHtml(entry.event_type)} &nbsp;|&nbsp; <strong>Privacy:</strong> ${escapeHtml(entry.privacy_level)}</p>
    <p><strong>Run ID:</strong> ${escapeHtml(entry.run_id || "—")} &nbsp;|&nbsp; <strong>Session:</strong> ${escapeHtml(entry.session_id)}</p>
    <p><strong>Timestamp:</strong> ${escapeHtml(entry.timestamp)}</p>
    <p><strong>Tags:</strong> ${(entry.tags || []).map(t => escapeHtml(t)).join(", ")}</p>
    <p><strong>Summary:</strong> ${escapeHtml(entry.redacted_summary || "")}</p>
    <pre>${escapeHtml(JSON.stringify(entry.related_artifact_refs || [], null, 2))}</pre>
  `);
}

function initResearchPanel() {
  const searchBtn = document.getElementById("research-search-button");
  if (searchBtn) searchBtn.addEventListener("click", runResearchSearch);
  const queryInput = document.getElementById("research-query");
  if (queryInput) {
    queryInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") runResearchSearch();
    });
  }
}

// ---------- Sandbox panel ----------

function initSandboxPanel() {
  const runBtn = document.getElementById("sandbox-run-button");
  if (runBtn) runBtn.addEventListener("click", runSandboxCode);
}

async function runSandboxCode() {
  const codeEl = document.getElementById("sandbox-code");
  const statusEl = document.getElementById("sandbox-status");
  const outputEl = document.getElementById("sandbox-output");
  const artifactsEl = document.getElementById("sandbox-artifacts");
  const code = codeEl.value;
  if (!code.trim()) {
    show(statusEl, `<span class="error">Enter some code first.</span>`);
    return;
  }

  show(statusEl, `<span class="loading">Running sandbox…</span>`);
  show(outputEl, "");
  show(artifactsEl, "<p class=\"empty\">No artifacts produced.</p>");

  const res = await api("POST", "/sandbox/run", { code });
  if (!res.ok) {
    const msg = res.data && (res.data.error || res.data.detail) ? escapeHtml(res.data.error || res.data.detail) : "Sandbox run failed";
    show(statusEl, `<span class="error">${msg}</span>`);
    return;
  }
  const data = res.data.data;
  show(statusEl, `<span class="${data.status === "completed" ? "ok" : "error"}">Sandbox ${escapeHtml(data.status)}</span>`);

  let output = "";
  if (data.stdout) output += `<strong>stdout:</strong>\n${escapeHtml(data.stdout)}\n\n`;
  if (data.stderr) output += `<strong>stderr:</strong>\n${escapeHtml(data.stderr)}\n\n`;
  if (data.return_value != null) output += `<strong>return_value:</strong> ${escapeHtml(JSON.stringify(data.return_value))}\n\n`;
  if (data.error) output += `<strong>error:</strong> ${escapeHtml(data.error)}\n\n`;
  show(outputEl, output || "No output.");

  const artifacts = data.artifacts || [];
  if (artifacts.length) {
    show(artifactsEl, artifacts.map(a => `
      <div class="artifact-item">
        <strong>${escapeHtml(a.name)}</strong> <span class="muted">(${a.kind}, ${a.size} bytes)</span>
        ${a.kind === "text" && a.content ? `<pre>${escapeHtml(a.content)}</pre>` : ""}
      </div>
    `).join(""));
  }
}

// ---------- Iterate panel ----------

function initIteratePanel() {
  const submitBtn = document.getElementById("iterate-submit");
  if (submitBtn) submitBtn.addEventListener("click", runIterate);
}

async function runIterate() {
  const statusEl = document.getElementById("iterate-status");
  const resultEl = document.getElementById("iterate-result");
  const runId = document.getElementById("iterate-run-id").value;
  const goal = document.getElementById("iterate-goal").value.trim() || null;

  if (!runId) {
    show(statusEl, `<span class="error">Select a run first.</span>`);
    return;
  }

  show(statusEl, `<span class="loading">Generating iteration proposal…</span>`);
  show(resultEl, "");

  const payload = { run_id: runId };
  if (goal) payload.goal = goal;
  const res = await api("POST", "/agent/iterate", payload);
  if (!res.ok) {
    const msg = res.data && (res.data.error || res.data.detail) ? escapeHtml(res.data.error || res.data.detail) : "Iteration failed";
    show(statusEl, `<span class="error">${msg}</span>`);
    return;
  }
  const p = res.data.data;
  show(statusEl, `<span class="ok">Iteration proposal created: <code>${escapeHtml(p.proposal_id)}</code></span>`);
  show(resultEl, `
    <div class="proposal-card">
      <h3>${escapeHtml(p.goal)} <span class="badge pending">pending</span></h3>
      <p><strong>Dataset:</strong> ${escapeHtml(p.dataset)} &nbsp;|&nbsp; <strong>Target:</strong> ${escapeHtml(p.target)}</p>
      <p><strong>Models:</strong> ${(p.model_grid || []).map(m => `<code>${escapeHtml(m)}</code>`).join(", ")}</p>
      <p><strong>Seeds:</strong> ${(p.seeds || []).map(s => escapeHtml(String(s))).join(", ")}</p>
      <p class="rationale">${escapeHtml(p.rationale || "")}</p>
      <div class="proposal-actions">
        <button type="button" class="approve" data-action="approve" data-proposal-id="${escapeHtml(p.proposal_id)}">Approve</button>
        <button type="button" class="reject" data-action="reject" data-proposal-id="${escapeHtml(p.proposal_id)}">Reject</button>
      </div>
    </div>
  `);
  attachProposalActionHandlers(resultEl);
  await loadProposals();
}

// ---------- Benchmarks panel ----------

async function loadBenchmarks() {
  const content = document.getElementById("benchmarks-content");
  const select = document.getElementById("benchmark-provider");
  const res = await api("GET", "/benchmarks");
  if (!res.ok) {
    show(content, `<span class="error">Failed to load benchmarks</span>`);
    return;
  }
  benchmarkData = res.data.data;
  if (!benchmarkData) {
    show(content, `<p class="empty">${escapeHtml(res.data.message || "No benchmark manifest found.")}</p>`);
    show(select, `<option value="">No providers</option>`);
    return;
  }
  const providers = benchmarkData.providers || [];
  if (providers.length === 0) {
    show(content, "<p class=\"empty\">No providers in manifest.</p>");
    show(select, `<option value="">No providers</option>`);
    return;
  }
  select.innerHTML = providers.map((p, idx) =>
    `<option value="${idx}">${escapeHtml(p.provider)} (${escapeHtml(p.model || "")})</option>`
  ).join("");
  select.addEventListener("change", () => renderBenchmarkProvider(parseInt(select.value, 10)));
  renderBenchmarkProvider(0);
}

function renderBenchmarkProvider(index) {
  const content = document.getElementById("benchmarks-content");
  if (!benchmarkData || !benchmarkData.providers || !benchmarkData.providers[index]) {
    show(content, "<p class=\"empty\">Select a provider.</p>");
    return;
  }
  const provider = benchmarkData.providers[index];
  const datasets = provider.datasets || [];
  if (datasets.length === 0) {
    show(content, "<p class=\"empty\">No datasets for this provider.</p>");
    return;
  }

  const rows = datasets.map(ds => {
    const isRegression = ds.task_type === "regression";
    const det = ds.metrics && ds.metrics.deterministic ? ds.metrics.deterministic : {};
    const agent = ds.metrics && ds.metrics.agent ? ds.metrics.agent : null;
    const detMetric = isRegression
      ? (det.test_r2 != null ? `R2 ${det.test_r2.toFixed(4)}` : "—")
      : (det.test_accuracy != null ? `Acc ${det.test_accuracy.toFixed(4)}` : "—");
    const agentMetric = agent
      ? (isRegression
          ? (agent.test_r2 != null ? `R2 ${agent.test_r2.toFixed(4)}` : "—")
          : (agent.test_accuracy != null ? `Acc ${agent.test_accuracy.toFixed(4)}` : "—"))
      : "—";
    const status = ds.deterministic_status === "completed" && agent !== null ? "OK" : "AGENT_FAILED";
    const badgeClass = status === "OK" ? "ok" : "failed";
    return `
      <tr>
        <td>${escapeHtml(ds.domain || "")}</td>
        <td>${escapeHtml(ds.name || "")}</td>
        <td>${escapeHtml(ds.task_type || "")}</td>
        <td>${detMetric}</td>
        <td>${agentMetric}</td>
        <td><span class="badge ${badgeClass}">${escapeHtml(status)}</span></td>
      </tr>
    `;
  }).join("");

  show(content, `
    <p class="muted">${escapeHtml(provider.provider)} — ${escapeHtml(provider.model || "")}</p>
    <div class="table-wrap">
      <table class="benchmark-table">
        <thead>
          <tr>
            <th>Domain</th>
            <th>Dataset</th>
            <th>Task</th>
            <th>Deterministic</th>
            <th>Agent</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <p class="muted">Report: <code>benchmarks/b1/reports/b1_report.md</code></p>
  `);
}

// ---------- Proposals panel ----------

async function loadProposals() {
  const content = document.getElementById("proposals-content");
  const res = await api("GET", "/proposals");
  if (!res.ok) {
    show(content, `<span class="error">Failed to load proposals</span>`);
    return;
  }
  const proposals = res.data.data || [];
  if (proposals.length === 0) {
    show(content, "<p class=\"empty\">No proposals found.</p>");
    return;
  }
  show(content, proposals.map(p => {
    const canApprove = p.status === "pending";
    const canRun = p.status === "approved";
    return `
    <div class="proposal-card">
      <h3>${escapeHtml(p.goal || "Untitled proposal")} <span class="badge ${p.status}">${escapeHtml(p.status)}</span></h3>
      <p><strong>Dataset:</strong> ${escapeHtml(p.dataset || "—")} &nbsp;|&nbsp; <strong>Target:</strong> ${escapeHtml(p.target || "—")}</p>
      <p><strong>Models:</strong> ${(p.model_grid || []).map(m => `<code>${escapeHtml(m)}</code>`).join(", ")}</p>
      <p><strong>Seeds:</strong> ${(p.seeds || []).map(s => escapeHtml(String(s))).join(", ")}</p>
      <p class="rationale">${escapeHtml(p.rationale || "")}</p>
      <div class="proposal-actions">
        ${canApprove ? `<button type="button" class="approve" data-action="approve" data-proposal-id="${escapeHtml(p.proposal_id)}">Approve</button>` : ""}
        ${canApprove ? `<button type="button" class="reject" data-action="reject" data-proposal-id="${escapeHtml(p.proposal_id)}">Reject</button>` : ""}
        ${canRun ? `<button type="button" class="run" data-action="run" data-proposal-id="${escapeHtml(p.proposal_id)}">Run</button>` : ""}
        <button type="button" class="secondary" data-proposal-id="${escapeHtml(p.proposal_id)}">View details</button>
        ${p.batch_config ? `<span class="muted">Batch: <code>${escapeHtml(p.batch_config)}</code></span>` : ""}
      </div>
    </div>
  `}).join(""));

  content.querySelectorAll("button[data-action][data-proposal-id]").forEach(btn => {
    btn.addEventListener("click", () => proposalAction(btn.dataset.action, btn.dataset.proposalId));
  });
  content.querySelectorAll("button[data-proposal-id]:not([data-action])").forEach(btn => {
    btn.addEventListener("click", () => showProposalDetail(btn.dataset.proposalId));
  });
}

async function showProposalDetail(proposalId) {
  const detailPanel = document.getElementById("panel-proposal-detail");
  const content = document.getElementById("proposal-detail-content");
  detailPanel.classList.remove("hidden");
  show(content, "<p class=\"loading\">Loading…</p>");
  const res = await api("GET", `/proposals/${encodeURIComponent(proposalId)}`);
  if (!res.ok) {
    show(content, `<span class="error">${res.data && res.data.error ? escapeHtml(res.data.error) : "Failed to load proposal"}</span>`);
    return;
  }
  const p = res.data.data;
  show(content, `
    <p><strong>ID:</strong> <code>${escapeHtml(p.proposal_id)}</code> <span class="badge ${p.status}">${escapeHtml(p.status)}</span></p>
    <p><strong>Goal:</strong> ${escapeHtml(p.goal || "—")}</p>
    <p><strong>Dataset:</strong> ${escapeHtml(p.dataset || "—")}</p>
    <p><strong>Target:</strong> ${escapeHtml(p.target || "—")}</p>
    <p><strong>Task type:</strong> ${escapeHtml(p.task_type || "—")}</p>
    <p><strong>Model grid:</strong> ${(p.model_grid || []).map(m => `<code>${escapeHtml(m)}</code>`).join(", ")}</p>
    <p><strong>Seeds:</strong> ${(p.seeds || []).map(s => escapeHtml(String(s))).join(", ")}</p>
    <p><strong>Rationale:</strong> ${escapeHtml(p.rationale || "—")}</p>
    <p><strong>Created:</strong> ${escapeHtml(p.created_at || "—")}</p>
    ${p.batch_config ? `<p><strong>Batch config:</strong> <code>${escapeHtml(p.batch_config)}</code></p>` : ""}
  `);
}

// ---------- Agent Sessions panel ----------

async function loadAgentSessions() {
  const content = document.getElementById("sessions-content");
  const res = await api("GET", "/agent-sessions?limit=50");
  if (!res.ok) {
    show(content, `<span class="error">Failed to load agent sessions</span>`);
    return;
  }
  const sessions = res.data.data || [];
  if (sessions.length === 0) {
    show(content, "<p class=\"empty\">No agent session summaries found.</p>");
    return;
  }
  show(content, sessions.map(s => {
    const outcome = s.outcome || {};
    const statusClass = outcome.status === "completed" ? "ok" : (outcome.status === "failed" ? "error" : "muted");
    return `
      <div class="session-card">
        <h3><code>${escapeHtml(s.event_id || "—")}</code> <span class="badge ${statusClass}">${escapeHtml(outcome.status || "unknown")}</span></h3>
        <p><strong>Source:</strong> ${escapeHtml(s.source || "—")} &nbsp;|&nbsp; <strong>Time:</strong> ${escapeHtml(s.timestamp || "—")}</p>
        <p>${escapeHtml(outcome.summary || "")}</p>
        <p>Tags: ${(s.tags || []).map(t => `<code>${escapeHtml(t)}</code>`).join(", ")}</p>
      </div>
    `;
  }).join(""));
}

// ---------- Viewer panel ----------

let viewerData = null;
let viewerSort = { column: null, asc: true };

function populateDatasetSelectInto(selectId) {
  const select = document.getElementById(selectId);
  if (!select) return;
  return api("GET", "/datasets").then((res) => {
    if (!res.ok || !select) return;
    const datasets = res.data.data || [];
    select.innerHTML = datasets.map(d =>
      `<option value="${escapeHtml(d.dataset_id)}">${escapeHtml(d.dataset_id)} (${d.rows} rows)</option>`
    ).join("");
  });
}

async function loadDatasetPreview() {
  const statusEl = document.getElementById("viewer-status");
  const tableEl = document.getElementById("viewer-table");
  const columnsEl = document.getElementById("viewer-columns");
  const datasetId = document.getElementById("viewer-dataset").value;
  const limit = parseInt(document.getElementById("viewer-limit").value, 10) || 100;

  if (!datasetId) {
    show(statusEl, `<span class="error">Select a dataset first.</span>`);
    return;
  }

  show(statusEl, `<span class="loading">Loading preview…</span>`);
  show(tableEl, "");
  show(columnsEl, "");

  const res = await api("GET", `/datasets/${encodeURIComponent(datasetId)}/preview?limit=${limit}`);
  if (!res.ok) {
    const msg = res.data && (res.data.error || res.data.detail) ? escapeHtml(res.data.error || res.data.detail) : "Preview failed";
    show(statusEl, `<span class="error">${msg}</span>`);
    return;
  }

  viewerData = res.data.data;
  viewerSort = { column: null, asc: true };

  show(statusEl, `<span class="ok">Loaded ${viewerData.returned_rows} of ${viewerData.total_rows} rows${viewerData.truncated ? " (truncated)" : ""}</span>`);

  show(columnsEl, (viewerData.columns || []).map(c => `
    <div class="eda-metric"><strong>${escapeHtml(c.name)}</strong>${escapeHtml(c.dtype)}</div>
  `).join(""));

  const distSelect = document.getElementById("dist-column");
  const numericCols = (viewerData.columns || []).filter(c => c.dtype === "numeric").map(c => c.name);
  if (distSelect) {
    distSelect.innerHTML = numericCols.map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("");
  }

  renderViewerTable();
}

function renderViewerTable() {
  const tableEl = document.getElementById("viewer-table");
  if (!viewerData || !viewerData.rows) {
    show(tableEl, "<p class=\"empty\">Load a dataset first.</p>");
    return;
  }
  const columns = (viewerData.columns || []).map(c => c.name);
  const numericCols = new Set((viewerData.columns || []).filter(c => c.dtype === "numeric").map(c => c.name));
  let rows = viewerData.rows.slice();

  if (viewerSort.column) {
    const col = viewerSort.column;
    rows.sort((a, b) => {
      let av = a[col], bv = b[col];
      if (av == null) return 1;
      if (bv == null) return -1;
      if (numericCols.has(col)) return viewerSort.asc ? av - bv : bv - av;
      return viewerSort.asc
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av));
    });
  }

  const arrow = (col) => viewerSort.column === col ? (viewerSort.asc ? " ▲" : " ▼") : "";
  const header = columns.map(col => `<th data-col="${escapeHtml(col)}">${escapeHtml(col)}${arrow(col)}</th>`).join("");
  const body = rows.map(row =>
    `<tr>${columns.map(col => {
      const v = row[col] == null ? "" : row[col];
      return numericCols.has(col)
        ? `<td class="num">${escapeHtml(String(v))}</td>`
        : `<td>${escapeHtml(String(v))}</td>`;
    }).join("")}</tr>`
  ).join("");

  show(tableEl, `
    <div class="viewer-table-wrap">
      <table class="viewer-table">
        <thead><tr>${header}</tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>
    <p class="muted">Click a column header to sort.</p>
  `);

  tableEl.querySelectorAll("th[data-col]").forEach(th => {
    th.addEventListener("click", () => {
      const col = th.dataset.col;
      if (viewerSort.column === col) {
        viewerSort.asc = !viewerSort.asc;
      } else {
        viewerSort.column = col;
        viewerSort.asc = true;
      }
      renderViewerTable();
    });
  });
}

function renderHistogram() {
  const contentEl = document.getElementById("dist-content");
  if (!viewerData || !viewerData.rows) {
    show(contentEl, "<p class=\"empty\">Load a dataset first.</p>");
    return;
  }
  const colName = document.getElementById("dist-column").value;
  const bins = parseInt(document.getElementById("dist-bins").value, 10) || 12;
  const values = viewerData.rows.map(r => r[colName]).filter(v => typeof v === "number" && Number.isFinite(v));
  if (!values.length) {
    show(contentEl, `<p class="empty">No finite numeric values in ${escapeHtml(colName)}.</p>`);
    return;
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const counts = new Array(bins).fill(0);
  for (const v of values) {
    const idx = Math.min(bins - 1, Math.floor(((v - min) / span) * bins));
    counts[idx] += 1;
  }
  const maxCount = Math.max(...counts);
  const width = 640, height = 200, pad = 30;
  const bw = (width - 2 * pad) / bins;

  let svg = `<svg class="histogram" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img">`;
  for (let i = 0; i < bins; i++) {
    const h = maxCount ? (counts[i] / maxCount) * (height - 2 * pad) : 0;
    const x = pad + i * bw;
    const y = height - pad - h;
    svg += `<rect class="histogram-bar" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${(bw - 2).toFixed(1)}" height="${h.toFixed(1)}"><title>${min + (i / bins) * span} – ${min + ((i + 1) / bins) * span}: ${counts[i]}</title></rect>`;
  }
  svg += `<text x="${pad}" y="${height - 8}">${min.toPrecision(4)}</text>`;
  svg += `<text x="${width - pad}" y="${height - 8}" text-anchor="end">${max.toPrecision(4)}</text>`;
  svg += `<text x="${pad}" y="${pad - 8}">${escapeHtml(colName)} (${values.length} values, ${bins} bins)</text>`;
  svg += "</svg>";

  show(contentEl, svg);
}

async function loadHeatmap() {
  const contentEl = document.getElementById("heatmap-content");
  const datasetId = document.getElementById("heatmap-dataset").value;
  const target = document.getElementById("heatmap-target").value.trim() || null;
  if (!datasetId) {
    show(contentEl, `<span class="error">Select a dataset first.</span>`);
    return;
  }

  show(contentEl, "<p class=\"loading\">Running EDA…</p>");
  const url = `/eda/${encodeURIComponent(datasetId)}` + (target ? `?target=${encodeURIComponent(target)}` : "");
  const res = await api("GET", url);
  if (!res.ok) {
    const msg = res.data && (res.data.error || res.data.detail) ? escapeHtml(res.data.error || res.data.detail) : "EDA failed";
    show(contentEl, `<span class="error">${msg}</span>`);
    return;
  }

  const pairs = res.data.data.correlation_hints.top_correlations || [];
  if (!pairs.length) {
    show(contentEl, "<p class=\"empty\">Not enough numeric columns for correlations.</p>");
    return;
  }
  show(contentEl, renderCorrelationHeatmap(pairs.slice(0, 8)));
}

function corrColor(value) {
  // value in [-1, 1]: red for negative, blue for positive, dark for near zero.
  const clamped = Math.max(-1, Math.min(1, value));
  const intensity = Math.round(Math.abs(clamped) * 220) + 35;
  return clamped >= 0 ? `rgb(40, ${intensity}, 255)` : `rgb(${intensity}, 60, 60)`;
}

function renderCorrelationHeatmap(pairs) {
  const cell = 56, labelW = 110, labelH = 46, pad = 8;
  const labels = [...new Set(pairs.flatMap(p => [p.feature_a, p.feature_b]))];
  const size = labels.length;
  const width = labelW + size * cell + 2 * pad;
  const height = labelH + size * cell + 2 * pad;
  const idx = Object.fromEntries(labels.map((l, i) => [l, i]));

  // Dense symmetric matrix initialized to identity=1, missing=NaN.
  const matrix = Array.from({ length: size }, () => new Array(size).fill(null));
  for (let i = 0; i < size; i++) matrix[i][i] = 1;
  for (const p of pairs) {
    const a = idx[p.feature_a], b = idx[p.feature_b];
    matrix[a][b] = p.correlation;
    matrix[b][a] = p.correlation;
  }

  let svg = `<svg class="heatmap-svg" viewBox="0 0 ${width} ${height}" width="${Math.min(width, 900)}" role="img">`;
  labels.forEach((label, j) => {
    svg += `<text x="${labelW + j * cell + cell / 2}" y="${labelH - 10}" text-anchor="start" transform="rotate(-45 ${labelW + j * cell + cell / 2} ${labelH - 10})">${escapeHtml(label)}</text>`;
    svg += `<text x="${labelW - 8}" y="${labelH + j * cell + cell / 2 + 4}" text-anchor="end">${escapeHtml(label)}</text>`;
  });
  for (let i = 0; i < size; i++) {
    for (let j = 0; j < size; j++) {
      const v = matrix[i][j];
      const x = labelW + j * cell, y = labelH + i * cell;
      const fill = v == null ? "#30363d" : corrColor(v);
      const text = v == null ? "—" : v.toFixed(2);
      const textColor = v != null && Math.abs(v) > 0.55 ? "#0d1117" : "inherit";
      svg += `<rect x="${x}" y="${y}" width="${cell - 2}" height="${cell - 2}" rx="4" fill="${fill}"><title>${escapeHtml(String(labels[i]))} × ${escapeHtml(String(labels[j]))}: ${v == null ? "n/a" : escapeHtml(String(v))}</title></rect>`;
      svg += `<text x="${x + (cell - 2) / 2}" y="${y + (cell - 2) / 2 + 4}" text-anchor="middle" style="fill:${textColor}">${text}</text>`;
    }
  }
  svg += "</svg>";
  return svg;
}

async function loadComparison() {
  const contentEl = document.getElementById("comparison-content");
  const barsEl = document.getElementById("comparison-bars");
  const res = await api("GET", "/runs/comparison");
  if (!res.ok) {
    show(contentEl, `<span class="error">Failed to load comparison</span>`);
    return;
  }
  const runs = res.data.data.runs || [];
  if (!runs.length) {
    show(contentEl, "<p class=\"empty\">No completed runs yet.</p>");
    return;
  }

  const rows = runs.map(r => {
    const m = r.metrics || {};
    const isRegression = r.task_type === "regression";
    const primary = isRegression
      ? (m.test_rmse != null ? m.test_rmse.toFixed(4) : "—")
      : (m.test_accuracy != null ? m.test_accuracy.toFixed(4) : "—");
    const secondary = isRegression
      ? (m.test_r2 != null ? m.test_r2.toFixed(4) : "—")
      : (m.test_f1_macro != null ? m.test_f1_macro.toFixed(4) : "—");
    return `
      <tr>
        <td><code>${escapeHtml(r.run_id)}</code></td>
        <td>${escapeHtml(r.model || "")}</td>
        <td>${escapeHtml(r.target || "")}</td>
        <td>${escapeHtml(r.task_type)}</td>
        <td>${r.seed != null ? r.seed : "—"}</td>
        <td>${primary}</td>
        <td>${secondary}</td>
        <td><span class="badge ${r.validation_status === "approved" ? "approved" : "pending"}">${escapeHtml(r.validation_status || "?")}</span></td>
      </tr>
    `;
  }).join("");

  show(contentEl, `
    <p class="muted">${runs.length} completed run(s), newest first.</p>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>Run ID</th><th>Model</th><th>Target</th><th>Task</th><th>Seed</th><th>Primary</th><th>Secondary</th><th>Status</th></tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `);

  // Metric bars for classification accuracy across approved runs.
  const approved = runs.filter(r => r.validation_status === "approved");
  const metricKey = approved.some(r => r.task_type === "regression") ? "test_r2" : "test_accuracy";
  const withMetric = approved.filter(r => r.metrics && r.metrics[metricKey] != null);
  if (withMetric.length && document.getElementById("comparison-bars")) {
    show(document.getElementById("comparison-bars"), `
      <h3>${metricKey.replace("test_", "").replace("_", " ")} by run</h3>
      <div class="metric-bars">
        ${withMetric.map(r => {
          const v = r.metrics[metricKey];
          const pct = Math.max(0, Math.min(100, v * 100));
          return `
            <div class="bar-row">
              <span class="bar-label" title="${escapeHtml(r.run_id)}">${escapeHtml(`${r.model} · ${r.run_id}`)}</span>
              <div class="bar-track"><div class="bar-fill" style="width:${pct.toFixed(1)}%"></div></div>
              <span class="bar-value">${v.toFixed(4)}</span>
            </div>
          `;
        }).join("")}
      </div>
    `);
  }
}

function initViewerPanel() {
  const loadBtn = document.getElementById("viewer-load");
  if (loadBtn) loadBtn.addEventListener("click", loadDatasetPreview);
  const distBtn = document.getElementById("dist-render");
  if (distBtn) distBtn.addEventListener("click", renderHistogram);
  const heatBtn = document.getElementById("heatmap-load");
  if (heatBtn) heatBtn.addEventListener("click", loadHeatmap);
}

// ---------- Init ----------

let activeDatasetId = null;

// ---------- Datasets panel ----------

async function loadDatasets() {
  const tbody = document.getElementById("datasets-table-body");
  const res = await api("GET", "/datasets");
  if (!res.ok) {
    show(tbody, `<tr><td colspan="5" class="error">Failed to load datasets</td></tr>`);
    return;
  }
  const datasets = res.data.data || [];
  if (datasets.length === 0) {
    show(tbody, `<tr><td colspan="5">No datasets found.</td></tr>`);
    return;
  }
  tbody.innerHTML = datasets.map(d => `
    <tr data-dataset-id="${escapeHtml(d.dataset_id)}">
      <td><code>${escapeHtml(d.dataset_id)}</code></td>
      <td>${escapeHtml(d.filename)}</td>
      <td>${escapeHtml(d.source)}</td>
      <td>${d.rows}</td>
      <td>${d.columns}</td>
    </tr>
  `).join("");
  tbody.querySelectorAll("tr").forEach(row => {
    row.addEventListener("click", () => selectDataset(row.dataset.datasetId));
  });
}

function selectDataset(datasetId) {
  activeDatasetId = datasetId;
  document.querySelectorAll("#datasets-table-body tr").forEach(row => row.classList.remove("active"));
  const row = document.querySelector(`#datasets-table-body tr[data-dataset-id="${CSS.escape(datasetId)}"]`);
  if (row) row.classList.add("active");
  document.getElementById("eda-target").value = "";
  const expSelect = document.getElementById("experiment-dataset");
  if (expSelect) expSelect.value = datasetId;
  const edaContent = document.getElementById("eda-content");
  show(edaContent, "<p class=\"empty\">Click Run EDA to analyze the selected dataset.</p>");
}

async function uploadDataset(file) {
  const statusEl = document.getElementById("dataset-upload-status");
  if (!file || !file.name.toLowerCase().endsWith(".csv")) {
    show(statusEl, `<span class="error">Please select a CSV file.</span>`);
    return;
  }
  const maxMb = 100;
  if (file.size > maxMb * 1024 * 1024) {
    show(statusEl, `<span class="error">File too large. Maximum size is ${maxMb} MB.</span>`);
    return;
  }
  show(statusEl, `<span class="loading">Uploading ${escapeHtml(file.name)}…</span>`);
  const formData = new FormData();
  formData.append("file", file);
  try {
    const res = await fetch("/datasets/upload", { method: "POST", body: formData });
    let data = null;
    try {
      data = await res.json();
    } catch {
      data = { ok: false, error: "Non-JSON response" };
    }
    if (!res.ok || !data.ok) {
      show(statusEl, `<span class="error">${escapeHtml(data.error || "Upload failed")}</span>`);
      return;
    }
    show(statusEl, `<span class="ok">Uploaded ${escapeHtml(data.data.filename)} (${data.data.rows} rows, ${data.data.columns} columns)</span>`);
    await loadDatasets();
    await populateDatasetSelectInto("experiment-dataset");
    selectDataset(data.data.dataset_id);
  } catch (err) {
    show(statusEl, `<span class="error">Upload failed: ${escapeHtml(err.message || String(err))}</span>`);
  }
}

function initDatasetUpload() {
  const zone = document.getElementById("dataset-upload-zone");
  const input = document.getElementById("dataset-upload-input");
  if (!zone || !input) return;

  zone.addEventListener("click", () => input.click());
  input.addEventListener("change", () => {
    if (input.files && input.files[0]) uploadDataset(input.files[0]);
  });

  zone.addEventListener("dragover", (e) => {
    e.preventDefault();
    zone.classList.add("dragover");
  });
  zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("dragover");
    if (e.dataTransfer && e.dataTransfer.files.length) {
      uploadDataset(e.dataTransfer.files[0]);
    }
  });
}

function initEdaPanel() {
  const runBtn = document.getElementById("eda-run-button");
  if (runBtn) {
    runBtn.addEventListener("click", () => {
      if (!activeDatasetId) {
        show(document.getElementById("eda-content"), `<span class="error">Select a dataset first.</span>`);
        return;
      }
      const target = document.getElementById("eda-target").value.trim() || null;
      loadEda(activeDatasetId, target);
    });
  }
  const cleanBtn = document.getElementById("eda-clean-button");
  if (cleanBtn) {
    cleanBtn.addEventListener("click", () => {
      if (!activeDatasetId) {
        show(document.getElementById("eda-status"), `<div class="banner error-banner">Select a dataset first.</div>`);
        return;
      }
      const target = document.getElementById("eda-target").value.trim();
      if (!target) {
        show(document.getElementById("eda-status"), `<div class="banner error-banner">Enter a target column to clean the dataset.</div>`);
        return;
      }
      cleanDataset(activeDatasetId, target);
    });
  }
}

async function cleanDataset(datasetId, target) {
  const statusEl = document.getElementById("eda-status");
  show(statusEl, `<div class="banner loading-banner">Cleaning dataset…</div>`);
  const res = await api("POST", `/datasets/${encodeURIComponent(datasetId)}/clean`, { target });
  if (!res.ok) {
    const msg = res.data && (res.data.error || res.data.detail) ? escapeHtml(res.data.error || res.data.detail) : "Cleaning failed";
    show(statusEl, `<div class="banner error-banner">${msg}</div>`);
    return;
  }
  const data = res.data.data;
  show(statusEl, `<div class="banner ok-banner">Cleaned dataset created: <code>${escapeHtml(data.dataset_id)}</code> (${data.rows} rows × ${data.columns} columns, dropped ${data.dropped_rows} rows)</div>`);
  await loadDatasets();
  await populateDatasetSelectInto("experiment-dataset");
  selectDataset(data.dataset_id);
}


function attachProposalActionHandlers(container) {
  container.querySelectorAll("button[data-action][data-proposal-id]").forEach(btn => {
    btn.addEventListener("click", () => proposalAction(btn.dataset.action, btn.dataset.proposalId));
  });
}

async function proposalAction(action, proposalId) {
  const statusEl = document.getElementById("proposals-status") || document.getElementById("goal-status");
  if (action === "approve-and-run") {
    show(statusEl, `<div class="banner loading-banner">Approving and queueing batch run for proposal <code>${escapeHtml(proposalId)}</code>…</div>`);
    const res = await api("POST", `/proposals/${encodeURIComponent(proposalId)}/approve-and-run`);
    if (!res.ok) {
      const msg = res.data && (res.data.error || res.data.detail) ? escapeHtml(res.data.error || res.data.detail) : "Approve and run failed";
      show(statusEl, `<div class="banner error-banner">${msg}</div>`);
      return;
    }
    show(statusEl, `<div class="banner ok-banner">Proposal approved and batch job queued.</div>`);
    await loadProposals();
    return;
  }
  if (action === "run") {
    show(statusEl, `<div class="banner loading-banner">Queueing batch run for proposal <code>${escapeHtml(proposalId)}</code>…</div>`);
    const job = await submitJob("batch", { proposal_id: proposalId });
    if (!job.ok) {
      show(statusEl, `<div class="banner error-banner">${escapeHtml(job.error)}</div>`);
      return;
    }
    show(statusEl, `<div class="banner ok-banner">Batch job queued: <code>${escapeHtml(job.job_id)}</code></div>`);
    selectJob(job.job_id);
    await loadProposals();
    return;
  }

  const url = `/proposals/${encodeURIComponent(proposalId)}/${action}`;
  let body = null;
  if (action === "reject") {
    body = { reason: "Rejected from UI" };
  }
  show(statusEl, `<div class="banner loading-banner">${action.charAt(0).toUpperCase() + action.slice(1)}ing proposal <code>${escapeHtml(proposalId)}</code>…</div>`);
  const res = await api("POST", url, body);
  if (!res.ok) {
    const msg = res.data && (res.data.error || res.data.detail) ? escapeHtml(res.data.error || res.data.detail) : `${action} failed`;
    show(statusEl, `<div class="banner error-banner">${msg}</div>`);
    return;
  }
  show(statusEl, `<div class="banner ok-banner">Proposal ${action}ed.</div>`);
  await loadProposals();
}

async function submitJob(type, payload) {
  const res = await api("POST", "/jobs", { type, payload });
  if (!res.ok) {
    return { ok: false, error: res.data && (res.data.error || res.data.detail) ? res.data.error || res.data.detail : "Job submission failed" };
  }
  return { ok: true, job_id: res.data.data.job_id };
}

let activeJobId = null;
let eventSource = null;

function renderPipelineStep(step, status, active = false) {
  const stepEl = document.querySelector(`.pipeline-step[data-step="${step}"]`);
  if (!stepEl) return;
  const statusEl = stepEl.querySelector(".pipeline-status");
  statusEl.textContent = status;
  statusEl.className = `pipeline-status ${status}`;
  stepEl.classList.toggle("active", active);
}

async function updatePipeline() {
  const datasetsRes = await api("GET", "/datasets");
  const datasets = (datasetsRes.ok && datasetsRes.data.data) || [];
  renderPipelineStep("upload", datasets.length ? "completed" : "pending");

  const edaDone = document.getElementById("eda-content") && !document.getElementById("eda-content").classList.contains("empty");
  renderPipelineStep("eda", edaDone ? "completed" : "pending");

  const proposalsRes = await api("GET", "/proposals");
  const proposals = (proposalsRes.ok && proposalsRes.data.data) || [];
  renderPipelineStep("propose", proposals.length ? "completed" : "pending");
  renderPipelineStep("approve", proposals.some(p => p.status === "approved") ? "completed" : "pending");

  const modelsRes = await api("GET", "/models");
  const models = (modelsRes.ok && modelsRes.data.data) || [];
  const hasModels = models.length > 0;

  const jobsRes = await api("GET", "/jobs");
  const jobs = (jobsRes.ok && jobsRes.data.data) || [];
  const runningJob = jobs.find(j => j.status === "running");

  renderPipelineStep("train", runningJob ? "running" : (hasModels ? "completed" : "pending"), !!runningJob);
  renderPipelineStep("validate", hasModels ? "completed" : "pending");
  renderPipelineStep("evaluate", hasModels ? "completed" : "pending");
}

async function loadJobs() {
  const content = document.getElementById("jobs-content");
  const res = await api("GET", "/jobs");
  if (!res.ok) {
    show(content, `<span class="error">Failed to load jobs</span>`);
    return;
  }
  const jobs = res.data.data || [];
  if (jobs.length === 0) {
    show(content, "<p class=\"empty\">No jobs yet.</p>");
    return;
  }
  show(content, jobs.map(j => {
    const isActive = j.status === "pending" || j.status === "running";
    const cancelButton = isActive
      ? `<button type="button" class="secondary" data-cancel-job="${escapeHtml(j.job_id)}">Cancel</button>`
      : "";
    return `
      <div class="job-card ${j.job_id === activeJobId ? "active" : ""}" data-job-id="${escapeHtml(j.job_id)}">
        <h3><code>${escapeHtml(j.job_id)}</code> <span class="badge ${j.status}">${escapeHtml(j.status)}</span></h3>
        <p><strong>Type:</strong> ${escapeHtml(j.job_type)} &nbsp;|&nbsp; <strong>Created:</strong> ${escapeHtml(j.created_at)}</p>
        ${j.error ? `<p class="error">${escapeHtml(j.error)}</p>` : ""}
        ${cancelButton}
      </div>
    `;
  }).join(""));

  content.querySelectorAll(".job-card").forEach(card => {
    card.addEventListener("click", () => selectJob(card.dataset.jobId));
  });
  content.querySelectorAll("button[data-cancel-job]").forEach(btn => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await api("POST", `/jobs/${encodeURIComponent(btn.dataset.cancelJob)}/cancel`);
      await loadJobs();
    });
  });
}

function selectJob(jobId) {
  activeJobId = jobId;
  loadJobs();
  const logEl = document.getElementById("job-log-content");
  show(logEl, "Connecting to live log…");
  connectJobLog(jobId);
}

function connectJobLog(jobId) {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
  const logEl = document.getElementById("job-log-content");
  show(logEl, "");

  eventSource = new EventSource(`/jobs/${encodeURIComponent(jobId)}/events`);
  eventSource.onmessage = (event) => {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch {
      return;
    }
    appendJobLogEntry(data);
    if (data.level === "done") {
      eventSource.close();
      eventSource = null;
      loadJobs();
      loadModels();
    }
  };
  eventSource.onerror = () => {
    appendJobLogEntry({ timestamp: new Date().toISOString(), level: "warn", message: "Log stream ended." });
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    loadJobs();
  };
}

function appendJobLogEntry(event) {
  const logEl = document.getElementById("job-log-content");
  if (logEl.classList.contains("empty")) {
    show(logEl, "");
    logEl.classList.remove("empty");
  }
  const line = document.createElement("div");
  line.className = "job-log-entry";
  line.innerHTML = `<span class="timestamp">${escapeHtml(event.timestamp || "")}</span><span class="level-${escapeHtml(event.level)}">${escapeHtml(event.level.toUpperCase())}</span> ${escapeHtml(event.message)}`;
  logEl.appendChild(line);
  logEl.scrollTop = logEl.scrollHeight;
}

function initPipelinePanel() {
  const refreshBtn = document.getElementById("jobs-refresh");
  if (refreshBtn) refreshBtn.addEventListener("click", loadJobs);
}

function renderCappedTable(id, headers, rows, maxInitial = 20) {
  if (!rows.length) return "";
  const renderRow = (row) => `<tr>${row.map(cell => `<td>${cell}</td>`).join("")}</tr>`;
  const allRows = rows.map(renderRow).join("");
  if (rows.length <= maxInitial) {
    return `<div class="eda-table-wrap"><table class="eda-table"><thead><tr>${headers.map(h => `<th>${h}</th>`).join("")}</tr></thead><tbody>${allRows}</tbody></table></div>`;
  }
  const initial = rows.slice(0, maxInitial).map(renderRow).join("");
  const rest = rows.slice(maxInitial).map(renderRow).join("");
  return `
    <div class="eda-table-wrap">
      <table class="eda-table"><thead><tr>${headers.map(h => `<th>${h}</th>`).join("")}</tr></thead>
        <tbody>${initial}</tbody>
        <tbody id="${id}-rest" class="collapsed">${rest}</tbody>
      </table>
    </div>
    <button class="eda-toggle" type="button" onclick="toggleEdaRows(this, '${id}-rest')">
      Show ${rows.length - maxInitial} more
    </button>
  `;
}

function toggleEdaRows(button, restId) {
  const rest = document.getElementById(restId);
  if (!rest) return;
  const collapsed = rest.classList.toggle("collapsed");
  button.textContent = collapsed
    ? `Show ${rest.children.length} more`
    : "Show less";
}

function renderFeatureTypes(value) {
  const cols = value.columns || {};
  const summary = [
    { label: "Numeric", count: value.numeric_count || 0 },
    { label: "Categorical", count: value.categorical_count || 0 },
    { label: "Datetime", count: value.datetime_count || 0 },
    { label: "Text", count: value.text_count || 0 },
  ];
  let html = `<div class="eda-grid">${summary.map(s => `
    <div class="eda-metric"><strong>${escapeHtml(s.label)}</strong>${s.count}</div>
  `).join("")}</div>`;
  const rows = Object.entries(cols).map(([name, info]) => [
    escapeHtml(name),
    escapeHtml(info.inferred_dtype),
    escapeHtml(info.coerced_type),
    info.unique_count,
    (info.sample_values || []).map(v => `<code>${escapeHtml(v)}</code>`).join(", "),
  ]);
  html += renderCappedTable("ft-rows", ["Column", "Type", "Coerced", "Unique", "Sample values"], rows, 25);
  return html;
}

function renderMissingProfile(value) {
  const cols = value.columns || {};
  const withMissing = Object.entries(cols).filter(([_, info]) => info.missing > 0);
  let html = `<div class="eda-grid">
    <div class="eda-metric"><strong>Total rows</strong>${value.total_rows}</div>
    <div class="eda-metric"><strong>Columns with missing</strong>${withMissing.length}</div>
  </div>`;
  if (withMissing.length === 0) {
    html += `<p class="ok">No missing values detected.</p>`;
    return html;
  }
  const rows = withMissing.map(([name, info]) => [
    escapeHtml(name),
    info.missing,
    `${(info.missing_rate * 100).toFixed(2)}%`,
  ]);
  html += renderCappedTable("miss-rows", ["Column", "Missing", "Missing rate"], rows, 25);
  return html;
}

function renderClassBalance(value) {
  if (value.error) return `<p class="error">${escapeHtml(value.error)}</p>`;
  const classes = value.classes || [];
  const highCardinality = classes.length > 50;
  let html = `<div class="eda-grid">
    <div class="eda-metric"><strong>Classes</strong>${classes.length}</div>
    <div class="eda-metric"><strong>Imbalance ratio</strong>${value.imbalance_ratio != null ? value.imbalance_ratio.toFixed(2) : "—"}</div>
    <div class="eda-metric"><strong>Small class warning</strong>${value.min_class_warning ? "Yes" : "No"}</div>
  </div>`;
  if (highCardinality) {
    html += `<p class="warning">This target has ${classes.length} unique values. It may be a numeric/regression target rather than a classification target.</p>`;
  }
  if (classes.length) {
    const rows = classes.map(c => [escapeHtml(String(c.class)), c.count, `${(c.rate * 100).toFixed(2)}%`]);
    html += renderCappedTable("class-rows", ["Class", "Count", "Rate"], rows, 20);
  }
  return html;
}

function renderCorrelationHints(value) {
  const pairs = value.top_correlations || [];
  const target = value.target_correlations || [];
  let html = "";
  if (pairs.length) {
    const rows = pairs.map(p => [escapeHtml(p.feature_a), escapeHtml(p.feature_b), p.correlation.toFixed(4)]);
    html += `<h4>Top feature correlations</h4>${renderCappedTable("corr-top", ["Feature A", "Feature B", "Correlation"], rows, 20)}`;
  }
  if (target.length) {
    const rows = target.map(t => [escapeHtml(t.feature), t.correlation.toFixed(4)]);
    html += `<h4>Target correlations</h4>${renderCappedTable("corr-target", ["Feature", "Correlation"], rows, 20)}`;
  }
  if (!pairs.length && !target.length) {
    html += `<p class="muted">No correlations computed (need numeric columns).</p>`;
  }
  return html;
}

function renderOutlierScan(value) {
  const cols = value.columns || {};
  const names = value.numeric_columns || [];
  if (!names.length) return `<p class="muted">No numeric columns to scan.</p>`;
  const rows = names.map(name => {
    const info = cols[name] || {};
    return [
      escapeHtml(name),
      info.iqr_outlier_count,
      `${((info.iqr_outlier_rate || 0) * 100).toFixed(2)}%`,
      info.z_outlier_count,
      `${((info.z_outlier_rate || 0) * 100).toFixed(2)}%`,
    ];
  });
  return renderCappedTable("outlier-rows", ["Column", "IQR outliers", "IQR rate", "Z-score outliers", "Z-score rate"], rows, 25);
}

function renderLeakageSuspects(value) {
  const suspects = value.suspects || [];
  if (!suspects.length) return `<p class="ok">No leakage suspects detected.</p>`;
  const rows = suspects.map(s => [
    escapeHtml(s.feature),
    escapeHtml(s.reason),
    s.target_correlation != null ? s.target_correlation.toFixed(4) : "—",
  ]);
  return renderCappedTable("leak-rows", ["Feature", "Reason", "Target correlation"], rows, 25);
}

const EDA_RENDERERS = {
  feature_types: { title: "Feature types", render: renderFeatureTypes },
  missing_profile: { title: "Missing values", render: renderMissingProfile },
  class_balance: { title: "Class balance", render: renderClassBalance },
  correlation_hints: { title: "Correlations", render: renderCorrelationHints },
  outlier_scan: { title: "Outliers", render: renderOutlierScan },
  leakage_suspects: { title: "Leakage suspects", render: renderLeakageSuspects },
};

async function loadEda(datasetId, target) {
  const content = document.getElementById("eda-content");
  show(content, "<p class=\"loading\">Running EDA…</p>");
  const url = `/eda/${encodeURIComponent(datasetId)}` + (target ? `?target=${encodeURIComponent(target)}` : "");
  const res = await api("GET", url);
  if (!res.ok) {
    show(content, `<span class="error">${res.data && res.data.error ? escapeHtml(res.data.error) : "Failed to run EDA"}</span>`);
    return;
  }
  const data = res.data.data;
  let html = `<p class="muted"><strong>Dataset:</strong> <code>${escapeHtml(data.dataset_id)}</code> — ${data.rows} rows × ${data.columns} columns</p>`;
  for (const [key, { title, render }] of Object.entries(EDA_RENDERERS)) {
    html += `
      <div class="eda-section">
        <h3>${escapeHtml(title)}</h3>
        ${render(data[key])}
      </div>
    `;
  }
  show(content, html);
}

// ---------- Experiment panel ----------

let activeExperimentId = null;
let activeExperimentJobId = null;
let experimentSource = null;

function updateExperimentCancelButton(state, jobId) {
  const btn = document.getElementById("experiment-cancel-button");
  if (!btn) return;
  const active = ["pending", "running", "iterating"].includes(state) && !!jobId;
  btn.classList.toggle("hidden", !active);
}

async function cancelActiveExperiment() {
  if (!activeExperimentJobId) return;
  const res = await api("POST", `/jobs/${encodeURIComponent(activeExperimentJobId)}/cancel`);
  if (!res.ok) {
    const detail = res.data && res.data.detail ? escapeHtml(res.data.detail) : "Failed to cancel";
    show(document.getElementById("experiment-feedback-status"), `<div class="banner error-banner">${detail}</div>`);
    return;
  }
  appendExperimentActivity({ timestamp: new Date().toISOString(), level: "warn", message: "Cancellation requested…" });
}

function switchExpTab(name) {
  document.querySelectorAll(".exp-tab").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.expTab === name);
  });
  document.querySelectorAll(".exp-tab-page").forEach(page => {
    page.classList.toggle("active", page.id === `exp-tab-${name}`);
  });
}

function setExpStage(stage, status) {
  const el = document.querySelector(`#experiment-stages .exp-stage[data-stage="${stage}"]`);
  if (!el) return;
  const statusEl = el.querySelector(".exp-stage-status");
  statusEl.textContent = status;
  statusEl.className = `exp-stage-status ${status}`;
  el.classList.toggle("active", status === "running");
}

function resetExpStages() {
  ["planning", "cleaning", "training", "evaluating"].forEach(stage => setExpStage(stage, "pending"));
}

function setExperimentStateBadge(state) {
  const badge = document.getElementById("experiment-state-badge");
  badge.textContent = state;
  badge.className = `badge ${state}`;
}

function appendExperimentActivity(event) {
  const feed = document.getElementById("experiment-activity");
  if (feed.classList.contains("empty")) {
    feed.innerHTML = "";
    feed.classList.remove("empty");
  }
  const line = document.createElement("div");
  line.className = "exp-feed-entry";
  const stage = event.data && event.data.stage ? ` [${escapeHtml(event.data.stage)}]` : "";
  line.innerHTML = `<span class="timestamp">${escapeHtml(event.timestamp || "")}</span><span class="level-${escapeHtml(event.level)}">${escapeHtml(event.level.toUpperCase())}</span>${stage} ${escapeHtml(event.message)}`;
  feed.appendChild(line);
  feed.scrollTop = feed.scrollHeight;
}

function renderExperimentResultsSummary(data) {
  const el = document.getElementById("experiment-results-summary");
  if (!data || data.state !== "completed") {
    el.innerHTML = "";
    return;
  }
  const metrics = data.best_metrics || {};
  const metricBits = Object.entries(metrics)
    .filter(([key]) => key.startsWith("test_"))
    .map(([key, value]) => `${escapeHtml(key)}: <strong>${typeof value === "number" ? value.toFixed(4) : escapeHtml(String(value))}</strong>`)
    .join(" &nbsp;|&nbsp; ");
  el.innerHTML = `
    <div class="banner ok-banner">
      Best run: <code>${escapeHtml(data.best_run_id || "-")}</code><br>
      ${metricBits}
    </div>
  `;
}

function disconnectExperimentEvents() {
  if (experimentSource) {
    experimentSource.close();
    experimentSource = null;
  }
}

function connectExperimentEvents(experimentId) {
  disconnectExperimentEvents();
  resetExpStages();
  const feed = document.getElementById("experiment-activity");
  feed.innerHTML = "";
  feed.classList.add("empty");

  experimentSource = new EventSource(`/experiment/${encodeURIComponent(experimentId)}/events`);
  experimentSource.onmessage = (event) => {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch {
      return;
    }
    appendExperimentActivity(data);
    if (data.data && data.data.stage) {
      setExpStage(data.data.stage, "running");
    }
    if (data.level === "done") {
      experimentSource.close();
      experimentSource = null;
      ["planning", "cleaning", "training", "evaluating"].forEach(stage => setExpStage(stage, "done"));
      loadExperimentStatus(experimentId);
      loadExperimentHistory();
    }
  };
  experimentSource.onerror = () => {
    appendExperimentActivity({ timestamp: new Date().toISOString(), level: "warn", message: "Activity stream ended." });
    disconnectExperimentEvents();
    loadExperimentStatus(experimentId);
  };
}

async function startExperiment() {
  const statusEl = document.getElementById("experiment-start-status");
  const datasetId = document.getElementById("experiment-dataset").value;
  const target = document.getElementById("experiment-target").value.trim();
  const goal = document.getElementById("experiment-goal").value.trim();

  if (!datasetId || !target || !goal) {
    show(statusEl, `<div class="banner error-banner">Dataset, target, and goal are required.</div>`);
    return;
  }

  show(statusEl, `<div class="banner loading-banner">Starting experiment…</div>`);
  const res = await api("POST", "/experiment/run", { dataset_id: datasetId, target, goal });
  if (!res.ok) {
    const detail = res.data && res.data.detail ? escapeHtml(res.data.detail) : "Failed to start experiment";
    show(statusEl, `<div class="banner error-banner">${detail}</div>`);
    return;
  }
  const data = res.data.data;
  show(statusEl, `<div class="banner ok-banner">Experiment <code>${escapeHtml(data.experiment_id)}</code> started.</div>`);
  activeExperimentId = data.experiment_id;
  activeExperimentJobId = data.job_id;
  document.getElementById("experiment-id-label").innerHTML = `Experiment <code>${escapeHtml(data.experiment_id)}</code>`;
  setExperimentStateBadge(data.state);
  updateExperimentCancelButton(data.state, data.job_id);
  switchExpTab("run");
  connectExperimentEvents(data.experiment_id);
}

async function submitExperimentFeedback() {
  const statusEl = document.getElementById("experiment-feedback-status");
  const feedback = document.getElementById("experiment-feedback").value.trim();
  if (!activeExperimentId) {
    show(statusEl, `<div class="banner error-banner">No experiment selected.</div>`);
    return;
  }
  if (!feedback) {
    show(statusEl, `<div class="banner error-banner">Feedback is required.</div>`);
    return;
  }
  show(statusEl, `<div class="banner loading-banner">Queueing iteration…</div>`);
  const res = await api("POST", `/experiment/${encodeURIComponent(activeExperimentId)}/feedback`, { feedback });
  if (!res.ok) {
    const detail = res.data && res.data.detail ? escapeHtml(res.data.detail) : "Failed to send feedback";
    show(statusEl, `<div class="banner error-banner">${detail}</div>`);
    return;
  }
  show(statusEl, `<div class="banner ok-banner">Iteration queued. Watching progress…</div>`);
  activeExperimentJobId = res.data.data.job_id;
  setExperimentStateBadge(res.data.data.state);
  updateExperimentCancelButton(res.data.data.state, activeExperimentJobId);
  connectExperimentEvents(activeExperimentId);
}

async function loadExperimentStatus(experimentId) {
  const res = await api("GET", `/experiment/${encodeURIComponent(experimentId)}/status`);
  if (!res.ok) return;
  const data = res.data.data;
  activeExperimentJobId = data.plan && data.plan.job_id ? data.plan.job_id : activeExperimentJobId;
  setExperimentStateBadge(data.state);
  renderExperimentResultsSummary(data);
  updateExperimentCancelButton(data.state, activeExperimentJobId);
  if (["completed", "failed", "cancelled"].includes(data.state)) {
    ["planning", "cleaning", "training", "evaluating"].forEach(stage => setExpStage(stage, data.state === "completed" ? "done" : data.state === "cancelled" ? "pending" : "failed"));
  }
  loadExperimentHistory();
}

function renderExperimentHistory(experiments) {
  const content = document.getElementById("experiment-history-content");
  if (experiments.length === 0) {
    show(content, "<p class=\"empty\">No experiments yet.</p>");
    return;
  }
  show(content, experiments.map(e => `
    <div class="exp-history-card ${e.experiment_id === activeExperimentId ? "active" : ""}" data-experiment-id="${escapeHtml(e.experiment_id)}">
      <h3>${escapeHtml(e.goal || "Untitled experiment")} <span class="badge ${escapeHtml(e.state)}">${escapeHtml(e.state)}</span></h3>
      <p><strong>Dataset:</strong> <code>${escapeHtml(e.dataset_id)}</code> &nbsp;|&nbsp; <strong>Target:</strong> ${escapeHtml(e.target)} &nbsp;|&nbsp; <strong>Updated:</strong> ${escapeHtml(e.updated_at)}</p>
      ${e.best_run_id ? `<p><strong>Best run:</strong> <code>${escapeHtml(e.best_run_id)}</code></p>` : ""}
    </div>
  `).join(""));

  content.querySelectorAll(".exp-history-card").forEach(card => {
    card.addEventListener("click", () => selectExperiment(card.dataset.experimentId));
  });
}

async function loadExperimentHistory() {
  const res = await api("GET", "/experiments");
  if (!res.ok) return;
  renderExperimentHistory(res.data.data || []);
}

function selectExperiment(experimentId) {
  activeExperimentId = experimentId;
  document.getElementById("experiment-id-label").innerHTML = `Experiment <code>${escapeHtml(experimentId)}</code>`;
  switchExpTab("run");
  connectExperimentEvents(experimentId);
}

function initExperimentPanel() {
  document.querySelectorAll(".exp-tab").forEach(btn => {
    btn.addEventListener("click", () => switchExpTab(btn.dataset.expTab));
  });
  const startBtn = document.getElementById("experiment-start-button");
  if (startBtn) startBtn.addEventListener("click", startExperiment);
  const feedbackBtn = document.getElementById("experiment-feedback-button");
  if (feedbackBtn) feedbackBtn.addEventListener("click", submitExperimentFeedback);
  const historyBtn = document.getElementById("experiment-history-refresh");
  if (historyBtn) historyBtn.addEventListener("click", loadExperimentHistory);
  const cancelBtn = document.getElementById("experiment-cancel-button");
  if (cancelBtn) cancelBtn.addEventListener("click", cancelActiveExperiment);
}

async function init() {
  initSidebar();
  initCodingPanel();
  initResearchPanel();
  initDatasetUpload();
  initEdaPanel();
  initPipelinePanel();
  initSandboxPanel();
  initIteratePanel();
  initViewerPanel();
  initExperimentPanel();

  await loadStatus();
  await loadDatasets();
  await loadModels();
  await loadCodingRuns();
  await loadResearchStatus();
  await loadBenchmarks();
  await loadProposals();
  await loadAgentSessions();
  await updatePipeline();
  await loadJobs();
  await populateDatasetSelectInto("viewer-dataset");
  await populateDatasetSelectInto("heatmap-dataset");
  await populateDatasetSelectInto("experiment-dataset");
  await loadExperimentHistory();
  await loadComparison();
}

init();

let activeRunId = null;
let activeFeatureColumns = [];

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

// ---------- Tabs ----------

function initTabs() {
  document.querySelectorAll(".tab-button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tabId = btn.dataset.tab;
      document.querySelectorAll(".tab-button").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(tabId).classList.add("active");
    });
  });
}

// ---------- Models tab (Slice 5) ----------

async function loadStatus() {
  const el = document.getElementById("status-content");
  const res = await api("GET", "/health");
  if (res.ok && res.data && res.data.status === "ok") {
    show(el, `<span class="ok">Service ok</span>`);
  } else {
    show(el, `<span class="error">Service unreachable</span>`);
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
      <div>
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
    <p><strong>Predictions:</strong> ${JSON.stringify(data.predictions)}</p>
    <p class="muted">Model: ${escapeHtml(data.model || "")} | Target: ${escapeHtml(data.target || "")}</p>
  `);
}

// ---------- Coding / Logger tab ----------

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
  document.getElementById("coding-load-run").addEventListener("click", () => {
    const runId = document.getElementById("coding-run-select").value;
    loadCodingRun(runId);
  });
}

// ---------- Research / Copilot tab ----------

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
    <p><strong>Tags:</strong> ${(entry.tags || []).join(", ")}</p>
    <p><strong>Summary:</strong> ${escapeHtml(entry.redacted_summary || "")}</p>
    <pre>${escapeHtml(JSON.stringify(entry.related_artifact_refs || [], null, 2))}</pre>
  `);
}

function initResearchPanel() {
  document.getElementById("research-search-button").addEventListener("click", runResearchSearch);
  document.getElementById("research-query").addEventListener("keydown", (e) => {
    if (e.key === "Enter") runResearchSearch();
  });
}

// ---------- Init ----------

async function init() {
  initTabs();
  initCodingPanel();
  initResearchPanel();

  await loadStatus();
  await loadModels();
  await loadCodingRuns();
  await loadResearchStatus();
}

init();

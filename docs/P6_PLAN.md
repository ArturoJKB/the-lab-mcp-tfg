# P6 Plan — The Continuous Working Loop

> Binding plan for P6. Approved direction (2026-09-03): the factory becomes its
> own first user. The loop runs real public datasets end-to-end, its outputs
> feed the context store (continuous learning via context), and its failures
> become structured fix-tickets for a coding agent (continuous software
> development via real-data testing).

## Position in the roadmap

- **P6 wraps Experiment 4; it never replaces it.** The thesis Experiment 4
  protocol (`thesis/chapters/ch5_methodology.tex` §Exp 4, Annex D) is executed
  *by* this loop — one effort, three deliverables: the experiment tables, the
  hole/fix log, and the feature proposals.
- **Order (locked):** P5.B lands → Experiment 3 recorded runs (RQ4–RQ6) first
  → then P6. P6 never displaces the agentic-group measurements.
- **No new RQ, no pass bars.** P6 reports counts (datasets processed, holes
  found, fixes proposed/applied, features shipped), not science. This protects
  the honesty discipline established in P5: claims only where instruments exist.

## Narrative

The original project framing — *infrastructure is the lab; the apps are the
experiments* — is closed here. The lab runs on real data where a trained model
is genuinely useful (genomics, health, crypto, energy, NLP, music signals);
everything the loop learns is recorded in the same evidence format the system
already produces; and what the loop breaks or finds missing becomes a typed
ticket a coding agent can act on. Data → models → MCP → software development,
one continuous circuit.

## Autonomy policy (inherits P5, binding)

- Deterministic, loop-initiated stages carry the recorded mandate
  `auto:p6loop:<dataset-slug>` — "a human launched the loop; no human saw the
  specific proposal" (documented thesis limitation, P5 §autonomy).
- **Agentic rounds run on ≥3 datasets and only behind an explicit human
  approval checkpoint** (UI approve or `thelab proposals approve --run`).
  The gate is never bypassed for the loop's convenience; a rejected proposal
  is unexecutable.
- All LLM-generated code executes only inside `thelab/sandbox` (AGENTS.md
  rule); sandbox artifacts are validated deterministically outside the sandbox.

## Phases

### P6.A — The loop (= Experiment 4 execution)

Full journey per dataset: `thelab ingest kaggle <slug>` → context pack → EDA →
clean (policy + report) → agent proposal → approve → deterministic training →
agentic round (where the arm calls for it) → generated notebook → index into
the context store.

Per dataset, record: shape, inferred task type, models attempted, best
deterministic and best agentic metrics with deltas, wall-clock time, and every
validation rejection with its reason.

### P6.B — Hole harvest

From the loop's runs/proposals/context events, produce
**`docs/P6_FINDINGS.md`** — one structured ticket per finding:

```text
### P6-BLK-<n>: <short symptom>
- Severity:   blocker | major | minor | note
- Symptom:    what the loop hit, observable behavior
- Evidence:   run_ids / event_ids / file paths (traceable, no guessing)
- Root cause: best-supported hypothesis
- Fix:        proposed change (file hints; small enough for a coding agent)
- Status:     proposed | applied | deferred
```

Harvest categories: validation rejections, provider failures, UX dead-ends,
performance, schema surprises, claim-drift (docs vs behavior). Fix tickets are
for a coding agent to consume; **apply only cheap, obviously-safe fixes** and
mark them `applied` with the commit. The rest stay `proposed`/`deferred` —
a curated backlog is a legitimate P6 result.

### P6.C — Feature harvest

From the loop's own friction, propose workspace features as context-indexed
proposals (the loop requesting its own features from its own domain data —
motivated by the thesis-field datasets): **clustering analysis, graph view,
better EDA cards, faster computations**.

Constraint: **implement at most one**, cheapest first, with tests (the
clustering-profile card over an ingested dataset is the expected candidate;
graph view is a ticket, not a build). Everything else stays a P6-B ticket.
Shipping one feature > three stubs.

## Dataset table (executive list; mirrors thesis Annex D verbatim)

Storage policy: analysis CSVs (≤ ~20 MB each) stay in `data/uploads/` as proof,
with context pack and cleaning report. Heavy raws stay in the transient
kagglehub cache and are purged after ingest. Bitcoin gets a deterministic
daily-aggregation subsample stored — the full file cannot fit the sandbox RLIMIT,
and recording that boundary is part of the result.

**Arm A — agentic re-run over recorded baselines** (already in `uploads/`;
deterministic results recorded; only the agentic round is new):

| Dataset | Domain | Recorded baseline |
|---|---|---|
| `shrutimechlearn/churn-modelling` | banking | RF acc 0.8615 |
| `camnugent/california-housing-prices` | housing | RFR R² 0.8172 |
| `pavansubhasht/ibm-hr-analytics-attrition-dataset` | HR | LR acc 0.8605 |
| `erfan4524/e-commerce-sales-data-analysis-and-eda` | e-commerce | ridge R² 1.0000 (computed col) |
| `yasserh/titanic-dataset` | classic | LR acc 0.8045 (identical ×3 providers) |
| S&P 500 analyst ratings (local CSV) | finance | RF acc 0.7492 (headroom target) |

**Arm B — new stress domains** (slugs verified live 2026-09-02):

| Dataset (slug) | Domain | Task | Tier |
|---|---|---|---|
| `kevinarvai/clinvar-conflicting` | genomics (DNA variants) | classification | must |
| `rabieelkharoua/chronic-kidney-disease-dataset-analysis` | health | classification | must |
| `sudalairajkumar/cryptocurrencypricehistory` | crypto | direction classification | must |
| `robikscube/hourly-energy-consumption` | electrical usage | regression | must |
| `shivamb/real-or-fake-fake-jobposting-prediction` | NLP/AI | featurize (RQ5 track) + classification | strong |
| `andradaolteanu/gtzan-dataset-music-genre-classification` | music signals | classification (ingest `features_3_sec.csv` only) | strong |
| `mczielinski/bitcoin-historical-data` | crypto (1-min bars) | scale-stress; daily aggregate | stretch |
| `rahman4li/patch-bay-the-mcp-server-ecosystem-graph` | MCP ecosystem | graph view + node clustering (`nodes.csv` + `edges.csv`, two ingests) | stretch |
| `adarsh1077/huggingface-hub-50k-ai-models` | AI models | clustering at scale | stretch |

Target: all six must-tier datasets end-to-end; strong tier strongly
recommended (the NLP featurization rejection→fix and the music-signal features
are two of the thesis's best stories); stretch tier as time allows.

## File map

```text
docs/P6_PLAN.md                            # this file
docs/P6_FINDINGS.md                        # P6.B output: the hole/fix log
data/uploads/<slug>_*.csv                  # stored analysis CSVs (proof)
data/uploads/<slug>_*.kaggle.json          # context packs
runs/<run_id>/                             # loop artifacts (deterministic + agentic)
proposals/                                 # loop proposals + approval records
.thelab/context/context.db                 # indexed loop events
```

## Out of scope

Autonomous multi-hour self-improvement, agent-to-agent free chat, cloud
deployment, multi-user, any change to the deterministic training path
(RQ1–RQ3 stays byte-for-byte untouched), new research questions.

## Verification

```bash
.venv/bin/ruff check thelab tests scripts
.venv/bin/mypy thelab
.venv/bin/python -m pytest tests/ -q
PATH=.venv/bin:$PATH python scripts/evaluate_thesis.py   # must stay PASS
```

**Done when:** must-tier datasets completed end-to-end with agentic rounds
behind approval; `docs/P6_FINDINGS.md` exists with evidence-backed tickets;
cheap fixes applied and marked; one feature implemented or consciously
deferred; suite green; evaluator PASS. Everything recorded as normal Lab
artifacts — the loop's proof *is* the workspace itself.

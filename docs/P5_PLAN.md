# P5 Plan — Real Multi-Agent Orchestration (Grounded Autonomy)

> Binding plan for P5. Approved direction (2026-09-02): keep the deterministic
> factory untouched as the baseline, then give role-specialized agents bounded
> liberty in a second, agentic round seeded by its artifacts. This makes the
> thesis title — *Context-Aware Multi-Agent Orchestration via MCP* — literally
> true: context-aware (context pack), multi-agent (distinct roles, prompts,
> tool allowlists), orchestration (bounded loop, approval gate), via MCP
> (harness → stdio servers).

## Motivation

First-review audit (2026-09-02) found the engineering core solid
(`thelab/run`, `thelab/context`, MCP servers, 474 tests, real RQ1–RQ3
evaluator) but the agentic claims overstated:

- Sub-agents share one system prompt; the `role` argument is unused
  (`thelab/ide/orchestrator.py:68-91`); `thelab/ide/sub_agents.py` is dead code
  yet cited in `THESIS_MAP.md`.
- Human approval exists only in the CLI; orchestrator, `agent_mcp` and jobs
  self-approve (`principal="orchestrator"/"agent_mcp"/"experiment_run"`).
- Feedback is threaded into `orchestrate(feedback=...)` and never read.
- There is no research question measuring what the agent layer adds.

P5 closes all of that and turns the weakness into the contribution: the
deterministic pipeline is the **grounding evidence**; the agentic round is
**grounded autonomy** on top of it.

## Narrative

Grounded autonomy: a deterministic, reproducible factory (RQ1–RQ3) whose
artifacts seed a bounded, role-specialized agentic exploration round (RQ4–RQ6),
coordinated via MCP with a real human approval boundary. Every agent decision
is traceable to typed artifacts; every agent output is deterministically
validated before it can affect training.

## Research questions (agentic)

| RQ | Claim | Instrument | Pass bar |
|---|---|---|---|
| RQ4 Grounding | Agents grounded in the local context store produce more verifiable proposals than ungrounded agents | Ablation: same task, with-context vs stripped-context, ≥3 datasets | Grounded ≥ ungrounded on verified-claim rate; hallucinated claims reported; proposal validity ≥ 90% |
| RQ5 Agentic capability | Sandboxed agent-generated code trains valid, competitive models beyond the fixed deterministic grid | Agentic round: agent-written FE/training scripts in `thelab/sandbox`; validator recomputes metrics outside the sandbox | ≥80% script validity; 0 silent failures; best-agentic ≥ best-deterministic − 1pt (deltas reported) |
| RQ6 Orchestration value | Role-specialized agents coordinated via MCP with human approval boundaries outperform a single shared-prompt agent | Ablation: multi-agent round vs single-agent control (one shared prompt); current pipeline serves as the reference arm | Multi-agent completes ≥ single-agent; every handoff a typed artifact; intervention rate reported |

Bar design: RQ5/RQ6 measure **validity, safety, competitiveness** — not victory.
Improvement over baseline (S&P 74.9% headroom, leakage/FE area) is a bonus.
Iris is excluded from RQ5 (saturated at 1.0 accuracy).

Provider policy (approved): results recorded for **Ollama (local) and
OpenRouter separately**; mock provider drives the test suite.

## Phases

### Phase A — Honesty fixes (pre-req; no new claims)

| # | Work item | Files |
|---|---|---|
| A1 | Per-role system prompts: pass `role` into the sub-agent system prompt; distinct role instruction contract per stage | `thelab/ide/orchestrator.py` |
| A2 | Delete dead `sub_agents.py`; fix `THESIS_MAP.md` evidence pointers | `thelab/ide/sub_agents.py`, `docs/THESIS_MAP.md` |
| A3 | Single `ApprovalGate`: human approval default; auto-approve only behind explicit config (`THELAB_AUTO_APPROVE=1`); remove self-approvals; wire harness approval requests to existing UI endpoints | new `thelab/agents/approval.py`; `orchestrator.py:378`, `mcp/agent_mcp.py:248`, `ide/jobs.py:330`, `agents/harness.py` |
| A4 | Feedback wired into the round planning prompt (real consumer) | `orchestrator.py` |
| A5 | Sandbox descriptions match reality: "compute-isolated, import-restricted; artifacts validated" (BLK-01) | `agents/chat.py:400-401,578` |
| A6 | Dedupe grounding logic into one module; fix `agent_mcp` dead locals and private cross-server imports | new `thelab/agents/grounding.py`; `harness.py`, `chat.py`, `global_agents.py`, `agent_mcp.py` |

**Done when:** ruff + mypy + full suite green; deterministic path unchanged;
README/THESIS_MAP claims match code.

### Phase B — The Agentic Round

New orchestrator stage executed **after** the deterministic batch, seeded by
its artifacts:

```
Deterministic batch (existing, untouched)
  EDA → clean → try_all dry-run → baseline runs → artifacts → indexed to context
        ↓ context pack (EDA brief + baseline metrics + prior-run evidence)
AGENTIC ROUND — ExperimentOrchestrator.run_agentic_round()
  1. Analyst   → reads EDA + baseline + context via MCP → typed findings brief
  2. FeatureEngineer → generates transform code → sandbox → dataset artifact
                 → deterministic post-check (shape, no leakage, target intact)
  3. ModelSelector   → proposes configs/code beyond the fixed grid
                 → ProposalStore → ApprovalGate (human default)
  4. Executor  → run_model with approved configs (seeded, provenance intact)
                 + sandbox training scripts where agents write code
  5. Validator → recomputes metrics outside sandbox; rejections = first-class
  6. Loop bounded by max_iterations + token budget + per-role tool allowlists
        ↓
Comparison artifact (best agentic vs best deterministic) → runs/ + context store
```

| # | Work item | Notes |
|---|---|---|
| B1 | `thelab/ide/agentic_round.py`: role configs (prompt + toolset per role), bounded loop, SSE stage events; built on `AgentHarness` against real MCP servers (context, eda, registry) | per-role tool allowlists: Analyst = context+eda reads; FE = sandbox `run_python` + eda; Selector = registry reads + proposal tools |
| B2 | Sandbox FE path: generated transform → sandbox → transformed CSV artifact → deterministic post-validator (shape/schema, target-presence, at-decision-time leakage policy from P2.6.5, metric recompute outside sandbox) | rejections are traceable outcomes, never silent |
| B3 | Model selection beyond the grid: agent configs → ProposalStore → ApprovalGate → `run_model` | provenance intact; optional sandbox training-script path for RQ5 |
| B4 | Comparison artifact `agentic_vs_deterministic.json` (best metrics, Δ, validity rates, tokens, rejections) → runs/ + context store | single source for RQ5/6 tables |
| B5 | UI: extend the Experiment stage pipeline with an "Agentic round" stage + per-agent events; code viewer for agent scripts (reuse notebook viewer) | no new panels |
| B6 | Provider handling: mock for tests; configured provider for live runs; every round + handoff indexed into the context store | `AGENTIC_ROUND_PROVIDER` env |

**Done when:** end-to-end agentic round on S&P + one Kaggle dataset with
Ollama AND OpenRouter; all handoffs typed + indexed; suite green.

### Phase C — Evaluation & thesis

| # | Work item | Notes |
|---|---|---|
| C1 | RQ4–RQ6 in `scripts/evaluate_thesis.py` (mock for suite; `--live` for recorded runs) | ablation runner: grounded/ungrounded, multi/single |
| C2 | Recorded results: Ollama + OpenRouter tables in `THESIS_EVALUATION.md`; S&P primary (headroom), iris excluded from RQ5 | |
| C3 | D1 demo: deterministic run → MCP discovery → agentic round live (SSE) → approval gate → comparison artifact → context search of the round | scripted for the defense |
| C4 | Docs: THESIS_MAP RQ table → 6 rows; README claims updated to measured reality | |

## Decisions locked

- 2–4 months runway; phases independent — A alone fixes all false claims,
  B alone demos the twist, C quantifies it.
- Dual-provider recorded results, reported separately.
- RQ6 = multi vs single ablation (no third arm).
- Deterministic path (RQ1–RQ3) stays byte-for-byte untouched.
- All LLM-generated code executes only inside `thelab/sandbox` (AGENTS.md rule).

## File map

```text
docs/P5_PLAN.md                           # this file
thelab/agents/approval.py                 # A3 ApprovalGate
thelab/agents/grounding.py                # A6 single grounding implementation
thelab/ide/agentic_round.py               # B1 role loop
thelab/ide/orchestrator.py                # A1, A4, B integration
thelab/mcp/agent_mcp.py                   # A3, A6 fixes
thelab/agents/chat.py                     # A5, A6
thelab/agents/global_agents.py            # A6
docs/THESIS_MAP.md, docs/THESIS_EVALUATION.md, README.md   # C4
scripts/evaluate_thesis.py                # C1
tests/test_agentic_round.py               # new
tests/test_agents_approval.py             # new
```

## Out of scope

Autonomous multi-hour self-improvement loops, cloud deployment, multi-user,
non-stdlib sandboxes (containers/VMs — BLK-01 mitigation stays: treat all
sandbox artifacts as untrusted + validate outside), agent-to-agent free chat.

## Verification

```bash
.venv/bin/ruff check thelab tests scripts
.venv/bin/mypy thelab
.venv/bin/python -m pytest tests/ -q
PATH=.venv/bin:$PATH python scripts/evaluate_thesis.py   # RQ1–RQ6 (mock) + --live for recorded results
```

# Slice A2 — Worker agent

**Status:** implemented and verified  
**Spec:** `docs/P1_PLAN.md` §3 Stage 2 — A2; `stage_2.md`  
**Scope:** An agent that carries an ML task end-to-end and proposes experiments for human approval.

---

## Changed files

| File | Change |
|---|---|
| `thelab/agents/worker.py` | New module: `ExperimentProposal` contract, `ProposalStore`, and `WorkerAgent` that reasons over EDA tools (S1) via the harness and persists proposals. |
| `thelab/agents/__init__.py` | Exports `ExperimentProposal`, `ProposalStore`, `WorkerAgent`. |
| `thelab/agents/cli.py` | Added `--mode worker` with `--dataset`, `--target`, `--model-grid`, `--seeds`, `--proposals-dir`; worker mode spawns all five MCP servers including EDA. |
| `thelab/cli.py` | Added `thelab proposals approve|reject|list|show` commands; `approve` writes an approval record and a 1:1 batch config, with optional `--run`. |
| `tests/test_agents_worker.py` | Tests for proposal store, batch-config translation, worker proposal creation, fallback on non-JSON provider answers, and approval gate. |
| `examples/worker_proposal_demo.py` | End-to-end demo: goal → EDA → proposal → approve → batch run. |
| `docs/ROADMAP.md` | A2 marked `done`, L2 marked `in_progress`. |

---

## Verification

### Automated gates

```bash
.venv/bin/ruff check thelab tests scripts
.venv/bin/mypy thelab
.venv/bin/python -m pytest tests/test_agents_worker.py -q
```

Results:

- `ruff check` — passed
- `mypy thelab` — passed
- `pytest tests/test_agents_worker.py -q` — **6 passed**

### Documented example commands

Create a proposal via the worker agent:

```bash
.venv/bin/python -m thelab.agents.cli --mode worker \
  "classify iris" --dataset data/fixtures/iris.csv --target species \
  --model-grid logistic_regression --seeds 42 --json
```

Result: JSON proposal persisted under `proposals/` with `model_grid=["logistic_regression"]` and `seeds=[42]`.

Approve and run the proposal:

```bash
.venv/bin/python -m thelab.cli proposals approve <proposal_id> --run
```

Result: approval record written, batch config generated, and two experiments complete (demo).

---

## Design notes

- **Proposals never execute directly.** The worker persists a typed `ExperimentProposal`; execution requires explicit `thelab proposals approve` (human or diagnosis agent).
- **1:1 batch translation.** `ProposalStore.write_batch_config` emits the exact JSON list format `BatchRunner.load_config` consumes.
- **Harness-mediated EDA.** The worker routes reasoning through the L1 harness so the same allowlist/grounding/approval gates apply; a deterministic EDA summary is used as fallback context.
- **Approval records** include the approving principal and timestamp, satisfying the audit trail requirement.

---

## Limitations

- The worker currently builds its fallback proposal from direct EDA calls; the harness is always invoked but non-mock providers would need to return parseable JSON for the proposal to reflect their reasoning.
- No automatic comparison against prior-run manifests in the rationale yet; the worker can read manifests via the workspace server but does not automatically cite them.

---

## Smallest next step

**L2 — Context writer MCP**: add `thelab-context-write-mcp` with a single `append_session_summary` tool so agents (including the worker and global agents) can persist session summaries in the canonical `/log` JSONL shape.

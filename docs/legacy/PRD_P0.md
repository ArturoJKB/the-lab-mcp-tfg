# The Lab: P0 Product Requirements Document

## Status

**Status:** Implementation baseline  
**Scope:** P0 only  
**Core principle:** Auditable, reproducible, and reusable

## Product statement

The Lab P0 is a local-first, model-agnostic, privacy-oriented
Data-to-Model Factory. It orchestrates specialized capabilities through
MCP to transform a local tabular dataset into a versioned, validated,
locally served ML model that an independent MCP client can discover and use.

The system must preserve complete execution evidence, including input hashes,
configuration, random seed, generated artifacts, validation outcomes, and
local context logs.

## Problem statement

Data and machine-learning workflows assisted by LLMs often mix informal
decisions, unstructured prompts, non-reproducible code, and tools without
stable interfaces. This makes outputs difficult to audit, reproduce, reuse,
or expose safely to other agents.

The Lab addresses this problem by defining a local orchestration architecture
based on typed contracts, controlled MCP capabilities, persistent artifacts,
and explicit approval boundaries.

## Thesis hypothesis

A local multi-agent orchestration architecture based on typed contracts and
MCP capabilities can execute a reproducible data-to-model workflow and expose
its resulting artifacts to independent agents without being coupled to a
specific LLM provider.

## Research questions

1. Can a model-training run be reproduced using the same dataset version,
   configuration, dependency versions, and random seed?

2. Can an independent MCP client discover and use a registered model without
   knowing the internal training-pipeline implementation?

3. Can local structured context retrieval recover useful information about
   previous runs, decisions, errors, snippets, and artifacts?

## Users

### Primary user

A student or technical user learning and working with data science, machine
learning, Git, Bash, Python, and agentic tools.

### Agent consumer

An independent agent or MCP client that needs to discover datasets, models,
run evidence, or local context without direct access to pipeline internals.

## User value

The system converts an informal ML task into a traceable local execution with:

- Typed inputs and outputs.
- Deterministic configuration.
- Versioned artifacts.
- Explicit validation outcomes.
- Local model serving.
- MCP-based reuse.
- Recoverable local context.

## P0 scope

Implement the following capabilities.

1. A local workspace for datasets, runs, models, artifacts, and logs.

2. A minimal orchestrator that creates and updates a `TaskSpec`.

3. Typed Pydantic contracts for:
   - `TaskSpec`
   - `RunManifest`
   - `ArtifactRef`
   - `DatasetSpec`
   - `ModelSpec`
   - `LogEntry`

4. A deterministic local tabular ML pipeline using an allowed scikit-learn
   algorithm.

5. Dataset profiling and validation:
   - Schema inspection.
   - Data-type validation.
   - Missing-value reporting.
   - Duplicate reporting.
   - Target-column validation.
   - Train/test split validation.

6. Versioned training configuration and explicit random seed.

7. Required run artifacts:
   - Input metadata.
   - Dataset profile.
   - Dataset contract.
   - Training configuration.
   - Metrics.
   - Validation report.
   - Serialized model.
   - Model card.
   - Run manifest.
   - Event log.

8. Local model registration and a local inference service for approved models.

9. MCP services for:
   - Data catalog.
   - Model registry.
   - Workspace and artifacts.
   - Local context and logs.

10. A read-only Coding/Logger Agent over repository evidence, logs, and
    artifacts.

11. A Research/Copilot Agent initially grounded in local evidence and
    documentation.

12. Local full-text search over logs, snippets, errors, decisions, and
    artifact references using SQLite FTS5 or an equivalent lightweight engine.

13. A minimal local UI with:
    - Global-agent navigation.
    - Execution-status panels.
    - Artifact browser.
    - Metrics and visual-output area.
    - Controlled 2x2 execution-log grid.

## Explicit non-goals

Do not implement any of the following in P0.

- Trading, brokers, order execution, leverage, derivatives, portfolios, or
  autonomous financial strategies.
- Arbitrary shell-command execution.
- Arbitrary LLM-generated code execution.
- Autonomous repository modifications.
- Embedded interactive Bash terminals.
- RAG, vector databases, embeddings, continuous training, fine-tuning, or
  advanced personalized recommendations.
- Multi-user support.
- Cloud deployment.
- Public hosting.
- Complex authentication.
- Multiple LLM-provider integrations.

Define a provider abstraction if needed, but implement at most one real
provider adapter in P0.

## Architecture rules

```text
User
  |
  v
CLI or Local UI
  |
  v
Orchestrator
  |
  v
TaskSpec + Capability Registry
  |
  +--------------------+--------------------+--------------------+
  |                    |                    |                    |
  v                    v                    v                    v
data_catalog_mcp   model_registry_mcp   workspace_mcp       context_mcp
  |                    |                    |                    |
  +--------------------+--------------------+--------------------+
                           |
                           v
         Local data, model, artifact, manifest, and log stores
                           |
                           v
                Visual evidence and execution logs
```

The orchestrator owns task state.

Agents must not use unstructured free-form messages as the source of truth.
They publish or consume versioned `ArtifactRef` objects.

MCP exposes controlled capabilities. It is not an unrestricted
agent-to-agent messaging layer.

## P0 MCP capability boundaries

### `workspace_mcp`

Read controlled artifacts, logs, manifests, and model cards.

Example tools:

- `get_artifact`
- `get_run_manifest`
- `list_run_artifacts`
- `read_model_card`

### `data_catalog_mcp`

Expose registered local datasets and their validated metadata.

Example tools:

- `list_datasets`
- `get_dataset_profile`
- `get_dataset_schema`
- `get_dataset_sample`

### `model_registry_mcp`

Expose approved models and controlled inference.

Example tools:

- `list_models`
- `get_model_card`
- `get_metrics`
- `predict`

### `context_mcp`

Store and retrieve local structured context.

Example tools:

- `append_log`
- `search_logs`
- `get_run_context`

### `model_service`

A local inference API for an approved, registered model.

The service must not expose unvalidated or rejected models.

## Required contracts

### `TaskSpec`

Contains:

- Task identifier.
- Objective.
- Input references.
- Constraints.
- Responsible agent.
- Task state.
- Artifact references.
- Creation and update timestamps.

### `RunManifest`

Contains:

- `run_id`.
- Input-data hash.
- Training configuration.
- Random seed.
- Relevant dependency versions.
- Execution timestamps.
- Final status.
- Validation status.
- Artifact references.
- Error summary, if applicable.

### `ArtifactRef`

Contains:

- Artifact identifier.
- Artifact type.
- Relative local path.
- Content hash.
- Origin.
- Parent `run_id`.

### `DatasetSpec`

Contains:

- Source.
- Expected schema.
- Target column.
- Data-quality rules.
- Train/test split configuration.
- Privacy classification.

### `ModelSpec`

Contains:

- Allowed algorithm.
- Hyperparameters.
- Target metric.
- Random seed.
- Approval rules.
- Model version.

### `LogEntry`

Contains:

- Event type.
- Session identifier.
- Tags.
- Redacted summary.
- Related artifact references.
- Privacy level.
- Timestamp.

## Data-to-Model workflow

1. The user creates a request through the CLI or local UI.

2. The orchestrator creates a `TaskSpec` and a unique run directory.

3. The pipeline validates and profiles the local dataset.

4. The pipeline transforms data using explicit, versioned configuration.

5. The trainer executes an allowed deterministic algorithm.

6. The system stores configuration, seed, metrics, and generated artifacts.

7. The validator marks the run as `approved` or `rejected`.

8. An approved model is registered and served locally.

9. An independent MCP client discovers the model and requests a prediction.

10. The logger stores the task, run evidence, errors, decisions, and artifact
    references for future retrieval.

## First mandatory direct run

The first usable milestone must work without a UI, an LLM, or network access.

```bash
thelab run model \
  --dataset data/fixtures/iris.csv \
  --target species \
  --model logistic_regression \
  --seed 42 \
  --output runs/
```

A successful run must create:

```text
runs/<run_id>/
  manifest.json
  events.jsonl
  inputs.json
  data_profile.json
  dataset_contract.json
  training_config.json
  metrics.json
  validation_report.json
  model.joblib
  model_card.md
```

`manifest.json` must include:

- Input-data hash.
- Configuration.
- Random seed.
- Relevant dependency versions.
- Final run status.
- Validation result.
- References to every produced artifact.

Re-running the same command must create a new `run_id` but equivalent results
within the documented tolerance.

## Privacy, retention, and safety rules

- Store datasets, models, logs, and artifacts locally by default.
- Do not send dataset contents, secrets, tokens, sensitive paths, or complete
  local-file contents to external providers by default.
- Log redacted summaries and metadata unless the user explicitly opts into
  expanded content storage.
- Exclude secrets and environment variables through redaction patterns.
- Support purge by run, tag, or time period.
- A remote LLM call must declare the context to be shared and require explicit
  human approval.
- The Coding/Logger Agent is read-only in P0.
- The Coding/Logger Agent must request approval before any write operation or
  potentially destructive command.
- Validation failure is a valid, traceable outcome and must be preserved.

## Acceptance criteria

### AC-01: Reproducible direct run

Given a valid local fixture dataset, valid configuration, and a fixed random
seed, when the user runs `thelab run model`, then the system creates a unique
`run_id`, a complete manifest, and every required artifact without using an
LLM.

### AC-02: Invalid dataset rejection

Given an incompatible dataset schema, when the pipeline starts, then the run
ends with `rejected`, stores the validation reason, and does not publish a
model.

### AC-03: Model registration and serving

Given an approved model, when it is registered, then the catalog exposes its
version, model card, metrics, local artifact path, and local inference
endpoint.

### AC-04: MCP interoperability

Given a registered model, when an independent MCP test client invokes
`list_models`, `get_model_card`, and `predict`, then it receives typed results
without accessing the training-pipeline implementation.

### AC-05: Local context retrieval

Given a log event with tags and artifact references, when the user searches
local logs, then relevant entries include their `run_id`, timestamp, tags, and
local references.

### AC-06: Coding-agent guardrail

Given a request to modify code or run a potentially destructive command, when
the Coding/Logger Agent receives it, then it does not act autonomously and
requests explicit approval.

### AC-07: Visual evidence

Given a completed run, when the user opens the results screen, then metrics,
status, artifact links, traces, and available charts are shown.

## Non-functional requirements

### Local-first

P0 must execute the ML pipeline without requiring cloud services.

### Model agnosticism

The core architecture must depend on typed provider interfaces rather than on
a specific LLM brand or vendor.

### Security

Use least privilege. Writing, external sharing, and potentially destructive
operations require explicit approval.

### Observability

Every meaningful system state must be traceable through a `run_id`.

### Determinism

Seeds and configuration must be persisted in the run manifest.

### Simplicity

Use sequential local execution. Do not add distributed queues, microservices,
or cloud infrastructure in P0.

## Incremental delivery plan

### Slice 0: Contracts and local storage

Implement:

- Project workspace conventions.
- Pydantic contracts.
- Fixture-data placeholder.
- Hashing utilities.
- Local artifact-path helpers.
- Unit tests.

Do not implement the CLI, model training, MCP, UI, or LLM providers yet.

### Slice 1: Direct reproducible run

Implement:

- `thelab run model`.
- Dataset validation.
- Deterministic logistic-regression training.
- Metrics.
- Validation report.
- Run manifest.
- Required run artifacts.

### Slice 2: MCP reuse

Implement:

- `data_catalog_mcp`.
- `model_registry_mcp`.
- Independent MCP test client.

### Slice 3: Logger and local memory

Implement:

- `context_mcp`.
- `/log` command or equivalent local interface.
- SQLite FTS5 search.
- Privacy levels and redacted storage.

### Slice 4: Service and visual results

Implement:

- Local model inference service.
- Minimal metrics and artifact dashboard.
- Controlled execution-status panels.

### Slice 5: Global-agent panels and evaluation

Implement:

- Read-only Coding/Logger Agent panel.
- Local-evidence Research/Copilot panel.
- Thesis evaluation protocol.
- Reproducibility and interoperability demonstrations.

Every slice must end with:

1. Automated tests.
2. An executable example.
3. A documented result.
4. An entry in the Build and Evaluation Log.

## Coding-agent operating constraints

- Read `AGENTS.md` and this PRD before proposing or changing code.
- Prefer small vertical slices over a big-bang implementation.
- Do not add features outside the active slice.
- Do not create arbitrary code-execution paths.
- Keep all run outputs under `runs/<run_id>/`.
- Use relative workspace paths in persisted references.
- Treat a failing validation as a valid, traceable outcome.
- Before declaring a slice complete, run its tests and its documented command.
- Report changed files, tests executed, test results, limitations, and the
  smallest next step.
- Do not modify repository files, dependencies, or architecture outside the
  requested task without explicit approval.

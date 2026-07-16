# The Lab — Context-Aware Multi-Agent Orchestration via MCP

> *"The infrastructure is the lab; the custom apps are the experiments you run in it."*

Bachelor thesis (TFG) at **Universidad Carlos III de Madrid**, Data Science and Engineering.
Started July 2026 · Target completion September 2026 · MIT License.

>  **Status:** planning and architecture stage. Implementation begins here and grows through weekly commits. Current commit publishes the scope, design, and system diagram. Code lands in `src/` and `notebook/` over the coming weeks.

---

## What this is

An open-source, MCP-based **multi-agent orchestrator** ("the Lab") that treats every capability as a Model Context Protocol module. Adding a new capability means adding a new module: no core edits required. The system is validated by a **demonstrator experiment** — an autonomous ML factory where specialized agents ingest data, train a model, evaluate it, and host it live behind a local endpoint, so the trained model itself becomes a tool other agents can call.

The problem: building autonomous multi-agent systems today means re-plumbing bespoke integrations for every new capability, with little standardization and weak reproducibility. This project designs and builds a standardized alternative on top of MCP.

## Five components

Each component maps to a phrase in the thesis title.

| Component | Role | Title phrase it proves |
|---|---|---|
| **The Lab** (orchestrator core) | Hand-rolled loop: shared context + agent registry + MCP client/router. Frameworks like LangGraph, CrewAI, and AutoGen are the *comparison*, not the base. | *Multi-Agent Orchestration* |
| **MCP module interface** | Every capability is an MCP server/tool (FastMCP). Adding a capability = adding a module, with zero core edits. | *Standardized Architecture via MCP* |
| **Open connection interface** | Documented contract + module template + AI-assisted **builder agent** (scaffold → sandbox → human approval → register) so third parties can add capabilities. | *Autonomous Agentic Systems* |
| **Context & memory** | SQLite experiment log with RAG for within-run knowledge retrieval and cross-run experiment memory. | *Context-Aware* (headline claim) |
| **The Experiment** | The Lab autonomously produces a working, hosted ML model, end to end, with measured outcomes. | Validation of the above |

## The demonstrator — the Lab as an autonomous ML factory

Given an ML goal (e.g. "classify this dataset"), specialized agents run the pipeline:

1. **Data agent** — collect and prepare the dataset.
2. **Trainer agent** — train a small, reproducible model.
3. **Evaluator agent** — score it.
4. **Deployer agent** — host it as a live MCP endpoint, so the trained model becomes a callable tool for other agents.

Every run is recorded to the experiment log. RAG retrieves relevant docs (capabilities, datasets, prior model cards) within a run, and relevant past runs across runs. When the Lab hits a capability gap, the builder agent scaffolds a new MCP module, a human approves it, and the run completes.

Architecture diagram: [`docs/figures/architecture.mmd`](./docs/figures/architecture.mmd).

## Scope and staging

Hard cut-lines to protect the core.

- **Core (Weeks 1-5):** orchestrator + MCP modules + Data → Train → Evaluate → Host, with SQLite experiment log + RAG. Complete, defensible thesis on its own.
- **Framework study (Week 6):** honest comparison against LangGraph / CrewAI / AutoGen and model-agnostic proof (Hugging Face + one local model).
- **Openness layer (Week 7, optional):** external connection interface, builder agent, public release with a `CONTRIBUTING` guide.
- **Graph memory (Week 8, optional and late):** a separate graph representation over accumulated experiment history. Not fused with RAG. Defers cleanly to Future Work.

## Design principles

- **Deterministic code over LLM calls.** If a function can do the job, don't call a model.
- **Log cost from day one.** Every model call records tokens and, where relevant, compute. Cost is a headline metric.
- **Model-agnostic.** Connects to local models and cloud AI providers alike.
- **Human-approved autonomy.** The builder agent scaffolds new modules but never registers them without a human approval step.
- **Reproducibility as default.** Pinned dependencies, fixed seeds, config-driven runs, results committed to the repo.

## Validation metrics

- Task success rate on the demonstrator.
- Token and compute cost per experiment.
- **RAG benefit:** measured improvement between a cold run and a run seeded with retrieved past-run memory.
- **Extensibility effort:** lines of code and core files touched (target: 0) to add a new module.

## Author

**Arturo Kolster Borges** · Universidad Carlos III de Madrid · Data Science and Engineering (2022-2026)

## License

[MIT](LICENSE). Chosen for permissive reuse; the memoria discusses the open-source licensing and IP angle.

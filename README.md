# The Lab — Context-Aware Multi-Agent Orchestration via MCP

> *"The infrastructure is the lab; the custom apps are the experiments you run in it."*

Bachelor thesis (TFG) at **Universidad Carlos III de Madrid**, Data Science and Engineering.
Started July 2026 · Target completion September 2026 · MIT License.

>  **Status:**: WIP (September-26)

---

## What this is

An open-source, MCP-based **multi-agent orchestration platform**, that will be validated by a **demo use case experiment**, an autonomous ML factory where specialized agents ingest data, train a model, evaluate it, and host it live behind a local endpoint, so the trained model itself becomes a tool other agents can call.The project aims to design and build a standardized arquitecture on top of MCP for different use cases (financial analysis, software engineering...)

## The demonstrator — the Lab as an autonomous ML factory

Given an ML goal (e.g. "classify this dataset"), specialized agents run the pipeline:

1. **Data agent** — collects and prepare the dataset.
2. **Trainer agent** — trains a small, reproducible model.
3. **Evaluator agent** — scores it.
4. **Deployer agent** — host it as a live MCP endpoint, so the trained model becomes a callable tool for other agents.

Every run is recorded to the experiment log. and RAG is used to retrieve relevant docs (capabilities, datasets, prior model cards) within a run, and relevant past runs.
Architecture diagram: [`docs/figures/architecture.mmd`](./docs/figures/architecture.mmd).

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

## Author

**Arturo Kolster Borges** · Universidad Carlos III de Madrid · Data Science and Engineering (2022-2026)

## License

[MIT](LICENSE). Chosen for permissive reuse; the memoria discusses the open-source licensing and IP angle.

# The Lab — Agent Onboarding

Before proposing or changing code in this repository, read these documents in order:

1. `docs/PRD_P0.md` — binding product requirements for P0.
2. `docs/ROADMAP.md` — implementation slice map and current status.
3. `docs/CODEBASE_GUIDE.md` — how the code is organized by slice.
4. `docs/Agents.md` — project principles, safety boundaries, and definition of done.

## Active scope

Implement only the slice explicitly requested. Do not build future slices early.

## Core principles

- Local-first, auditable, reproducible, reusable.
- Prefer small vertical slices over big-bang implementation.
- Use typed contracts and deterministic pipelines.
- Keep all persisted run outputs under `runs/<run_id>/`.
- Use relative workspace paths in persisted references.
- A rejected validation is a valid and traceable result.

## Safety boundaries

- Do not add arbitrary shell execution or arbitrary LLM-generated code execution.
- Do not modify repository files outside the requested slice.
- Do not add cloud services, vector databases, embeddings, fine-tuning,
  interactive terminals, trading, or broker integrations unless the active plan
  explicitly requires them.
- Do not silently change dependencies or architecture.
- Ask before destructive commands or broad refactors.

## Definition of done

For every slice:
1. Implement only the requested requirements.
2. Add or update tests.
3. Run the documented tests.
4. Run the documented example command when available.
5. Report changed files, test output, limitations, and next suggested slice.

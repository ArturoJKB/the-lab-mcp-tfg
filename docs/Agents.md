# The Lab: project instructions

Before proposing or changing code, read `docs/PRD_P0.md` and `docs/ROADMAP.md`.
The PRD is the binding implementation specification; the roadmap maps it to
implementation slices and current status.

## Active scope
Implement only the active slice explicitly requested by the user.
Do not build future slices early.

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
  interactive terminals, trading, or broker integrations.
- Do not silently change dependencies or architecture.
- Ask before destructive commands or broad refactors.

## Definition of done
For every slice:
1. Implement only the requested requirements.
2. Add or update tests.
3. Run the documented tests.
4. Run the documented example command when available.
5. Report changed files, test output, limitations, and next suggested slice.

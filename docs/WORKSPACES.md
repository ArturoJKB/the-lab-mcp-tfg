# Workspaces — Running The Lab from Anywhere

> How the workspace root is resolved, how to use The Lab from a different
> folder, and how to create throwaway ("hermetic") labs for testing.
> Facts verified against the code: `thelab/cli.py`, `thelab/ide/datasets.py`,
> `thelab/mcp/common.py`, `thelab/model_service/app.py`.

## How the workspace root is resolved

| Surface | Root resolution | Notes |
|---|---|---|
| `thelab` CLI (`run model/batch`, `inspect`, `predict`, `compare`, `context`, `proposals`) | **`Path.cwd()` — hard-bound** | `--dataset` / `--output` must be relative, no `..` (path-safety). Launch it from the workspace folder. |
| `thelab-model-service` (HTTP + UI) | `THELAB_WORKSPACE_ROOT` (default `.`) | Also auto-loads the repo `.env` from cwd **or** the repo directory. |
| The 7 MCP servers (`thelab-*-mcp`) | `THELAB_WORKSPACE_ROOT` (default `.`) | Plus per-surface env vars below. |
| `thelab-agent` / IDE HTTP APIs | `THELAB_WORKSPACE_ROOT` (default `.`) | Same as service. |

Sub-env vars (defaults resolve under the workspace root):

```bash
THELAB_RUNS_ROOT        # default: <root>/runs
THELAB_CONTEXT_DB       # default: <root>/.thelab/context/context.db
THELAB_PROPOSALS_DIR    # default: <root>/proposals
THELAB_EXPERIMENTS_DIR  # default: <root>/.thelab/experiments
```

## Running from another folder — three ways

### A. Shell functions (simplest, for the CLI)

The CLI is deliberately cwd-bound (that is the path-safety boundary), so wrap
it — the subshell keeps your current directory:

```bash
# add to ~/.bashrc
lab() { (cd /path/to/thelab-mcp-tfg && .venv/bin/thelab "$@"); }
labagent() { (cd /path/to/thelab-mcp-tfg && .venv/bin/thelab-agent "$@"); }
```

### B. Env-var launch (service and MCP servers)

True "from anywhere": point the root at the workspace and launch by absolute path.

```bash
export THELAB_WORKSPACE_ROOT=/path/to/thelab-mcp-tfg
export THELAB_RUNS_ROOT="$THELAB_WORKSPACE_ROOT/runs"
export THELAB_PROPOSALS_DIR="$THELAB_WORKSPACE_ROOT/proposals"
export THELAB_EXPERIMENTS_DIR="$THELAB_WORKSPACE_ROOT/.thelab/experiments"
export THELAB_CONTEXT_DB="$THELAB_WORKSPACE_ROOT/.thelab/context/context.db"

/path/to/thelab-mcp-tfg/.venv/bin/thelab-model-service --port 8000
# or an MCP server:
/path/to/thelab-mcp-tfg/.venv/bin/thelab-context-mcp
```

### C. Commands on PATH (optional)

`export PATH="/path/to/thelab-mcp-tfg/.venv/bin:$PATH"` (or `pip install -e .`
into a global tool env) makes the entry points resolvable anywhere. This solves
*what is on PATH*; A/B still solve *where the workspace is*.

## Quick check from another folder

```bash
cd ~
export THELAB_WORKSPACE_ROOT=/path/to/thelab-mcp-tfg
$THELAB_WORKSPACE_ROOT/.venv/bin/thelab-model-service --port 8000 &
curl -s localhost:8000/models | head    # lists approved models from the real run history
```

## The workspace is the memory

Pointing `THELAB_WORKSPACE_ROOT` at a fresh folder gives you an **empty lab**:
no runs, no proposals, no context store — agents grounded in your main context
lose their grounding there. That is the memory boundary working as designed,
not a bug. The CLI ignores `THELAB_WORKSPACE_ROOT` by design; for a disposable
CLI run, `cd` into the disposable directory instead (see below).

## Hermetic and parallel labs

This is the manual generalization of what `scripts/evaluate_thesis.py` already
does in-process (it runs all RQ checks inside a `tempfile.mkdtemp` workspace
and tears it down).

**One-shot hermetic lab** — test or demo with zero risk to the real evidence base:

```bash
export THELAB_WORKSPACE_ROOT=$(mktemp -d /tmp/thelab-lab-XXXX)
export THELAB_RUNS_ROOT="$THELAB_WORKSPACE_ROOT/runs"
export THELAB_PROPOSALS_DIR="$THELAB_WORKSPACE_ROOT/proposals"
export THELAB_EXPERIMENTS_DIR="$THELAB_WORKSPACE_ROOT/.thelab/experiments"
export THELAB_CONTEXT_DB="$THELAB_WORKSPACE_ROOT/.thelab/context/context.db"

/path/to/thelab-mcp-tfg/.venv/bin/thelab-model-service --port 8000
# …exercise freely; runs/, context, proposals all land in the temp dir…
rm -rf "$THELAB_WORKSPACE_ROOT"   # tear down when done
```

**Reproduce-before-touch** — rerun a reported failure in a disposable root with
a *copy* of the dataset, keeping the real run history pristine.

**Parallel labs** — side-by-side roots (main lab + experiment lab), each with
isolated `runs/`, `proposals/`, and `context.db`. The natural home for heavy
stress datasets (e.g., the Experiment 4 scale tests) without polluting the
main store.

Honesty caveat: a hermetic lab starts **empty** — that is the point, but it
also means cross-run grounding (prior-run evidence, context search) begins
from zero until the lab accumulates its own history.

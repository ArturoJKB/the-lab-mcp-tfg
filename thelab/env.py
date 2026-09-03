"""Shared .env loading for The Lab entry points (service and CLIs).

Loads ``KEY=VALUE`` pairs from a repo-root ``.env`` into ``os.environ`` using
``setdefault`` — explicit environment variables always win. Called at startup
by the model service and the agent CLI so live providers work from the same
configuration everywhere (full-app audit observation #2).
"""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv() -> None:
    """Load KEY=VALUE pairs from a repo-root .env into os.environ (setdefault)."""
    candidates = [Path.cwd() / ".env", Path(__file__).resolve().parents[1] / ".env"]
    for env_path in candidates:
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key.startswith("export "):
                key = key[len("export ") :].strip()
            os.environ.setdefault(key, value.strip().strip("'").strip('"'))

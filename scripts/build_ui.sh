#!/usr/bin/env bash
# Build the web UI (React/Vite) into the FastAPI static dir.
# node/npm are only needed for this step — the service itself is Python.
set -euo pipefail
cd "$(dirname "$0")/../web"

if [ ! -d node_modules ]; then
  npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund
fi

# Clear previous build output, preserving .gitkeep
find ../thelab/model_service/static -mindepth 1 ! -name '.gitkeep' -delete

npm run build
echo "UI built -> thelab/model_service/static/"

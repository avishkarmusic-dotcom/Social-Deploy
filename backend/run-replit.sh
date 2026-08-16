#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# The imported app expects Redis for rate limiting and its background queue.
# Start a local instance when no managed Redis URL is supplied. This keeps the
# app self-contained for preview and single-instance publishing.
if [[ -z "${REDIS_URL:-}" ]]; then
  export REDIS_URL="redis://127.0.0.1:6379/0"
fi

if ! (echo > /dev/tcp/127.0.0.1/6379) 2>/dev/null; then
  redis-server \
    --daemonize yes \
    --bind 127.0.0.1 \
    --port 6379 \
    --save "" \
    --appendonly no
fi

export PYTHONPATH="${PWD}/backend${PYTHONPATH:+:${PYTHONPATH}}"
exec python -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}"
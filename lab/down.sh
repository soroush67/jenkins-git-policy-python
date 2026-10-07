#!/usr/bin/env bash
# Stop the lab. `./down.sh --wipe` also deletes all lab data (volumes) and
# generated secrets.
set -euo pipefail
cd "$(dirname "$0")"
if docker compose version >/dev/null 2>&1; then DC=(docker compose); else DC=(docker-compose); fi
if [ "${1:-}" = --wipe ]; then
    "${DC[@]}" down -v
    rm -rf .env secrets
else
    "${DC[@]}" down
fi

#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

args=(--changed-only)
if [[ -n "${SOPHON_LIMIT:-}" ]]; then
    args+=(--limit "$SOPHON_LIMIT")
fi

uv run sophon init-catalog-db
uv run sophon ingest-moegirl "${args[@]}"
uv run sophon init-rag-db
uv run sophon build-rag --reset

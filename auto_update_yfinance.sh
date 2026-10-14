#!/usr/bin/env bash
set -euo pipefail

# Backward-compatible entry point.  Keep one implementation for version
# comparison, diff validation, commit, push, and deployment.
repo_dir="$(cd "$(dirname "$0")" && pwd)"

export SKIP_GIT_PULL="${SKIP_GIT_PULL:-${YFINANCE_SKIP_PULL:-0}}"
export SKIP_GIT_PUSH="${SKIP_GIT_PUSH:-${YFINANCE_SKIP_PUSH:-0}}"
export SKIP_DOCKER_BUILD="${SKIP_DOCKER_BUILD:-${YFINANCE_SKIP_DEPLOY:-0}}"
export SKIP_DOCKER_PUSH="${SKIP_DOCKER_PUSH:-${YFINANCE_SKIP_DOCKER_PUSH:-0}}"

exec bash "$repo_dir/check_and_update_yfinance.sh" "$@"

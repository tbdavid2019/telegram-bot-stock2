#!/bin/bash
# ==============================================================================
# 🔄 check_and_update_yfinance.sh
# Purpose: Check PyPI for the latest yfinance release, bump requirements.txt,
#          commit & push to git, rebuild Docker container, and push image.
# Compatible with cron jobs and Watchtower automated deployments.
# ==============================================================================
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR"

LOCK_DIR="$REPO_DIR/.yfinance_update.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "⚠️ Update process is already running. Exiting."
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

PACKAGE_NAME="yfinance"
REQUIREMENTS_FILE="$REPO_DIR/requirements.txt"
BRANCH="$(git branch --show-current 2>/dev/null || echo 'master')"
BRANCH="${BRANCH:-master}"

echo "================================================================="
echo "🔍 [$(date '+%Y-%m-%d %H:%M:%S')] Checking ${PACKAGE_NAME} for updates..."
echo "================================================================="

# 1. Fetch latest version from PyPI
fetch_pypi_version() {
  curl -fsS "https://pypi.org/pypi/${PACKAGE_NAME}/json" 2>/dev/null | \
    python3 -c 'import json, sys; print(json.load(sys.stdin)["info"]["version"])' 2>/dev/null || echo ""
}

# 2. Read currently pinned version from requirements.txt
read_requirements_version() {
  python3 - "$REQUIREMENTS_FILE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
if not path.exists():
    sys.exit(0)
for line in path.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line.startswith("yfinance=="):
        print(line.split("==", 1)[1])
        sys.exit(0)
    elif line.startswith("yfinance>="):
        print(line.split(">=", 1)[1])
        sys.exit(0)
PY
}

LATEST_VERSION="$(fetch_pypi_version)"
if [[ -z "$LATEST_VERSION" ]]; then
  echo "❌ Error: Failed to fetch latest version from PyPI. Aborting."
  exit 1
fi

CURRENT_VERSION="$(read_requirements_version || true)"
if [[ -z "$CURRENT_VERSION" ]]; then
  CURRENT_VERSION="unpinned"
fi

echo "  📦 Current Pinned Version : ${CURRENT_VERSION}"
echo "  🚀 Latest PyPI Version    : ${LATEST_VERSION}"

# Check if update is needed
if [[ "$CURRENT_VERSION" == "$LATEST_VERSION" ]]; then
  echo "  ✅ ${PACKAGE_NAME} is already up to date (${LATEST_VERSION}). No action needed."
  exit 0
fi

echo "  ⚡ New version detected! Upgrading ${PACKAGE_NAME} from ${CURRENT_VERSION} -> ${LATEST_VERSION}..."

# 3. Pull latest git changes
if [[ "${SKIP_GIT_PULL:-0}" != "1" ]]; then
  git pull --rebase --autostash origin "$BRANCH" || true
fi

# 4. Update requirements.txt
python3 - "$REQUIREMENTS_FILE" "$LATEST_VERSION" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
latest = sys.argv[2]
lines = path.read_text(encoding='utf-8').splitlines()
updated = []
replaced = False

for line in lines:
    stripped = line.strip()
    if stripped.startswith("yfinance"):
        updated.append(f"yfinance=={latest}")
        replaced = True
    else:
        updated.append(line)

if not replaced:
    updated.append(f"yfinance=={latest}")

path.write_text("\n".join(updated) + "\n", encoding='utf-8')
PY

# 5. Git Commit and Push
git add requirements.txt
git commit -m "chore: bump yfinance to ${LATEST_VERSION} and trigger auto-rebuild" || true

if [[ "${SKIP_GIT_PUSH:-0}" != "1" ]]; then
  echo "  📤 Pushing updated requirements.txt to origin/${BRANCH}..."
  git push origin "$BRANCH" || echo "⚠️ Warning: git push failed; continuing with local build."
fi

# 6. Rebuild Docker image with --no-cache
IMAGE_NAME="telegram-bot-stock2"
REMOTE_TAG="tbdavid2019/telegram-bot-stock2:latest"
CONTAINER_NAME="telegram-bot-stock2"

if [[ "${SKIP_DOCKER_BUILD:-0}" != "1" ]]; then
  echo "  🔨 Building new Docker image with no-cache (yfinance==${LATEST_VERSION})..."
  docker build --no-cache -t "$IMAGE_NAME" .
  docker tag "$IMAGE_NAME" "$REMOTE_TAG"

  # 7. Push image to registry for Watchtower
  if [[ "${SKIP_DOCKER_PUSH:-0}" != "1" ]]; then
    echo "  🚢 Pushing image ${REMOTE_TAG} to Docker Hub..."
    docker push "$REMOTE_TAG" || echo "⚠️ Warning: docker push failed."
  fi

  # 8. Restart local container if Docker is running locally
  if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
    echo "  🔄 Restarting local container ${CONTAINER_NAME}..."
    docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
    docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
    docker run -d \
      --name "$CONTAINER_NAME" \
      --restart unless-stopped \
      --label "com.centurylinklabs.watchtower.enable=true" \
      --env-file .env \
      "$IMAGE_NAME"
    echo "  ✅ Container ${CONTAINER_NAME} restarted with yfinance==${LATEST_VERSION}!"
  fi
fi

echo "================================================================="
echo "🎉 Update and deployment successfully completed!"
echo "================================================================="

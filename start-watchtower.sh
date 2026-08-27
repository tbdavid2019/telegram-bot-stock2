#!/bin/bash
# ==============================================================================
# 🚀 Start Watchtower Container for telegram-bot-stock2
# Documentation: https://containrrr.dev/watchtower/
# ==============================================================================
set -euo pipefail

CONTAINER_NAME="watchtower-stockbot"
POLL_INTERVAL="${WATCHTOWER_POLL_INTERVAL:-300}"  # Default: check every 5 minutes (300s)

echo "================================================================="
echo "🔭 Starting Watchtower Auto-Deploy Service (${CONTAINER_NAME})"
echo "   Poll Interval : ${POLL_INTERVAL} seconds"
echo "   Auto Clean Up : true (removes old images)"
echo "   Target Scope  : Containers with com.centurylinklabs.watchtower.enable=true"
echo "================================================================="

# Remove existing Watchtower instance if present
if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
  echo "Stopping and removing existing ${CONTAINER_NAME} container..."
  docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
  docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
fi

# Run Watchtower
docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e WATCHTOWER_CLEANUP=true \
  -e WATCHTOWER_POLL_INTERVAL="$POLL_INTERVAL" \
  -e WATCHTOWER_LABEL_ENABLE=true \
  -e TZ=Asia/Taipei \
  containrrr/watchtower:latest

echo "✅ Watchtower started successfully!"
echo "   Run 'docker logs -f ${CONTAINER_NAME}' to monitor automated updates."

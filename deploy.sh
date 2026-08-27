#!/bin/bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$repo_dir"

container_name="telegram-bot-stock2"
image_name="telegram-bot-stock2"
remote_tag="tbdavid2019/telegram-bot-stock2:latest"

if docker ps -a --format '{{.Names}}' | grep -qx "$container_name"; then
  docker stop "$container_name" >/dev/null 2>&1 || true
  docker rm "$container_name" >/dev/null 2>&1 || true
fi

docker build -t "$remote_tag" -t "$image_name" .
docker push "$remote_tag"

docker run -d \
  --name "$container_name" \
  --restart unless-stopped \
  --label "com.centurylinklabs.watchtower.enable=true" \
  --env-file .env \
  "$remote_tag"

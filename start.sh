#!/bin/bash
echo "Stopping existing container..."
docker stop telegram-bot-stock2 || true
docker rm telegram-bot-stock2 || true

echo "Building Docker image..."
docker build -t telegram-bot-stock2 .

echo "Running container..."
docker run -d \
  --name telegram-bot-stock2 \
  --restart unless-stopped \
  --env-file .env \
  telegram-bot-stock2

echo "Container started. Check logs with: docker logs -f telegram-bot-stock2"
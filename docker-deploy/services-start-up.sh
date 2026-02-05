#!/bin/bash
# Starts all services in the correct order

echo "Starting Proxy Stack..."
docker compose -f proxy/docker-compose.yml up -d

echo "Starting Nextcloud AIO Stack..."
docker compose -f nextcloud-aio/docker-compose.yml up -d

echo "Starting RAG Stack..."
docker compose -f rag-stack/docker-compose.yml up -d

echo "All services started."
docker ps

#!/bin/bash
# Stops all services

echo "Stopping RAG Stack..."
docker compose -f rag-stack/docker-compose.yml down

echo "Stopping Nextcloud AIO Stack..."
docker compose -f nextcloud-aio/docker-compose.yml down

echo "Stopping Proxy Stack..."
docker compose -f proxy/docker-compose.yml down

echo "All services stopped."

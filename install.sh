#!/bin/bash
set -e

# ==========================================
# NextCloud RAG Installation Script
# ==========================================

LOG_FILE="install_debug.log"
exec > >(tee -a "${LOG_FILE}") 2>&1

echo "Starting installation at $(date)"

# --- Helper Functions ---

function error_exit {
    echo ""
    echo "=========================================="
    echo "❌ CRITICAL ERROR IN STEP: $1"
    echo "=========================================="
    echo "An error occurred which stopped the installation."
    echo ""
    echo "--- DEBUG INFORMATION FOR AI ANALYSIS ---"
    echo "Failed Command: $2"
    echo ""
    
    if [ ! -z "$3" ]; then
        echo "--- CONTAINER LOGS ($3) ---"
        docker logs --tail 100 "$3" 2>/dev/null || echo "Could not retrieve logs for $3"
        echo "-----------------------------------"
    fi

    echo "--- SYSTEM STATE ---"
    echo "Running Containers:"
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    echo ""
    echo "Docker Network 'platform-net':"
    docker network inspect platform-net >/dev/null 2>&1 && echo "Exists" || echo "Missing"
    
    echo ""
    echo "Please provide this entire output to your AI assistant to diagnose the issue."
    exit 1
}

function check_command {
    if ! command -v "$1" &> /dev/null; then
        error_exit "PREREQUISITES" "$1 command not found"
    fi
}

function verify_container_up {
    container_name=$1
    echo "Verifying container '$container_name' is running..."
    if [ "$(docker inspect -f '{{.State.Running}}' ${container_name} 2>/dev/null)" != "true" ]; then
        error_exit "VERIFICATION" "Container $container_name is not running" "$container_name"
    fi
    echo "✅ Container '$container_name' is UP."
}

# --- 1. Prerequisites ---
echo "--- Step 1: Checking Prerequisites ---"
check_command docker
check_command grep

# Check Docker Daemon
if ! docker info > /dev/null 2>&1; then
    error_exit "PREREQUISITES" "Docker daemon is not running or accessible"
fi
echo "✅ Docker is running."

# --- 2. Network Setup ---
echo ""
echo "--- Step 2: Network Setup ---"
if docker network ls | grep -q "platform-net"; then
    echo "✅ Network 'platform-net' already exists."
else
    echo "Creating network 'platform-net'..."
    docker network create platform-net || error_exit "NETWORK" "docker network create platform-net"
    echo "✅ Network created."
fi

# --- 3. Proxy Stack (Caddy) ---
echo ""
echo "--- Step 3: Deploying Reverse Proxy (Caddy) ---"
cd docker-deploy/proxy

if [ ! -f .env ]; then
    echo "⚠️  No .env file found in docker-deploy/proxy."
    echo "   Creating one from .env.example..."
    cp .env.example .env
    echo "   PLEASE NOTE: You should edit this file to set your real email and domains."
fi

echo "Deploying Proxy Stack..."
docker compose up -d || error_exit "PROXY_DEPLOY" "docker compose up -d (proxy)" "caddy"

# Verify Caddy
sleep 5
verify_container_up "caddy"

cd ../..

# --- 4. Nextcloud AIO Stack ---
echo ""
echo "--- Step 4: Deploying Nextcloud AIO ---"
cd docker-deploy/nextcloud-aio

echo "Deploying Nextcloud AIO..."
docker compose up -d || error_exit "NEXTCLOUD_DEPLOY" "docker compose up -d (nextcloud)" "nextcloud-aio-mastercontainer"

# Verify AIO Master
sleep 5
verify_container_up "nextcloud-aio-mastercontainer"

cd ../..

# --- 5. RAG Stack ---
echo ""
echo "--- Step 5: Building and Deploying RAG Stack ---"
cd docker-deploy/rag-stack

if [ ! -f .env ]; then
    echo "⚠️  No .env file found in docker-deploy/rag-stack."
    echo "   Creating one from .env.example..."
    cp .env.example .env
    echo "   PLEASE NOTE: You MUST edit this file to set NEXTCLOUD_URL, WEBDAV creds, and OIDC."
fi

echo "Building RAG Services (this may take a while)..."
docker compose build || error_exit "RAG_BUILD" "docker compose build"

echo "Deploying RAG Stack..."
docker compose up -d || error_exit "RAG_DEPLOY" "docker compose up -d"

# Verify Key Containers
sleep 5
verify_container_up "rag-qdrant"
verify_container_up "rag-redis"
verify_container_up "rag-haystack-api"
verify_container_up "rag-webhook-gateway"
verify_container_up "rag-indexer-worker"

echo ""
echo "=========================================="
echo "✅ INSTALLATION SUCCESSFUL"
echo "=========================================="
echo "All stacks are up and running."
echo ""
echo "Next Steps:"
echo "1. Configure the Proxy domains in docker-deploy/proxy/.env"
echo "2. Configure Nextcloud AIO at https://<NEXTCLOUD_DOMAIN>:8443"
echo "3. Configure RAG credentials in docker-deploy/rag-stack/.env"
echo "   (Restart the rag-stack after editing .env: 'cd docker-deploy/rag-stack && docker compose up -d')"

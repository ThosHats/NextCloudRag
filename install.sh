#!/bin/bash
set -e

# Ensure we are running in Bash (because we use Process Substitution and read -p)
if [ -z "$BASH_VERSION" ]; then
    echo "⚠️  Detected execution via 'sh'. Re-launching with 'bash'..."
    exec bash "$0" "$@"
fi

# ==========================================
# NextCloud RAG Installation Script (Interactive)
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
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    echo ""
    echo "Please provide this output to your AI assistant."
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
    # We loop for a few seconds to catch early crash loops
    for i in {1..5}; do
        if [ "$(docker inspect -f '{{.State.Running}}' ${container_name} 2>/dev/null)" != "true" ]; then
             sleep 2
             if [ "$(docker inspect -f '{{.State.Running}}' ${container_name} 2>/dev/null)" != "true" ]; then
                 error_exit "VERIFICATION" "Container $container_name failed to start/stay up" "$container_name"
             fi
        fi
        sleep 1
    done
    echo "✅ Container '$container_name' is UP."
}

# --- 1. Prerequisites ---
echo "--- Step 1: Checking Prerequisites ---"
check_command docker
check_command openssl

if ! docker info > /dev/null 2>&1; then
    error_exit "PREREQUISITES" "Docker daemon is not running or accessible"
fi

# --- 2. Configuration Prompts ---
echo ""
echo "--- Step 2: Configuration ---"

# Detect Public IP
PUBLIC_IP=$(curl -s https://ifconfig.me || hostname -I | awk '{print $1}')
echo "Detected Public IP: $PUBLIC_IP"

if [ -z "$BASE_DOMAIN" ]; then
    read -p "Enter Base Domain (e.g., example.com): " INPUT_BASE_DOMAIN
    export BASE_DOMAIN=$INPUT_BASE_DOMAIN
fi

# Derive Subdomains
export NEXTCLOUD_DOMAIN="cloud.${BASE_DOMAIN}"
export RAG_DOMAIN="rag.${BASE_DOMAIN}"

if [ -z "$ACME_EMAIL" ]; then
    read -p "Enter Email for Let's Encrypt (e.g., admin@example.com): " INPUT_EMAIL
    export ACME_EMAIL=$INPUT_EMAIL
fi

echo ""
echo "Configuration:"
echo "- Base Domain: $BASE_DOMAIN"
echo "- Nextcloud:   $NEXTCLOUD_DOMAIN"
echo "- RAG App:     $RAG_DOMAIN"
echo "- Email:       $ACME_EMAIL"
echo ""

# --- 3. Network ---
if ! docker network ls | grep -q "platform-net"; then
    docker network create platform-net || error_exit "NETWORK" "docker network create platform-net"
fi
echo "✅ Network 'platform-net' ready."

# --- 4. Proxy Stack (Caddy) ---
echo ""
echo "--- Step 4: Deploying Reverse Proxy ---"
cd docker-deploy/proxy

# Generate .env
cat > .env <<EOF
ACME_EMAIL=${ACME_EMAIL}
NEXTCLOUD_DOMAIN=${NEXTCLOUD_DOMAIN}
RAG_DOMAIN=${RAG_DOMAIN}
EOF
echo "Generated proxy/.env"

docker compose up -d || error_exit "PROXY_DEPLOY" "docker compose up -d (proxy)" "caddy"
verify_container_up "caddy"
cd ../..

# --- 5. Nextcloud AIO ---
echo ""
echo "--- Step 5: Deploying Nextcloud AIO ---"
cd docker-deploy/nextcloud-aio
docker compose up -d || error_exit "NEXTCLOUD_DEPLOY" "docker compose up -d (nextcloud)" "nextcloud-aio-mastercontainer"
verify_container_up "nextcloud-aio-mastercontainer"
cd ../..

# --- 6. RAG Stack Config Generation ---
echo ""
echo "--- Step 6: Preparing RAG Stack ---"
cd docker-deploy/rag-stack

# Generate Random Webhook Secret
WEBHOOK_SECRET=$(openssl rand -hex 32)

# Generate .env if not exists, or update it? 
# We overwrite to ensure variables are propagated, assuming fresh install. 
# Check if file exists to warn user? Use explicit confirmation?
# For automation request, we assume overwriting basic config but PRESERVING manual if we parsed it.
# Simplest approach: Generate a specialized .env file.

cat > .env <<EOF
# Domain Configuration
RAG_DOMAIN=${RAG_DOMAIN}

# Nextcloud Connection
NEXTCLOUD_URL=https://${NEXTCLOUD_DOMAIN}
NEXTCLOUD_WEBHOOK_SECRET=${WEBHOOK_SECRET}

# --- MANUAL CONFIGURATION REQUIRED BELOW ---
# 1. Create 'readonly-bot' in Nextcloud -> Settings -> Security -> App passwords
WEBDAV_USER=readonly-bot
WEBDAV_PASSWORD=CHANGE_ME_TO_APP_PASSWORD

# Databases
POSTGRES_USER=rag_user
POSTGRES_PASSWORD=secure_password
POSTGRES_DB=rag_metadata
QDRANT_API_KEY=

# Authentication (OIDC) - Configure in your IdP
OIDC_ISSUER=https://auth.example.com/realms/master
OIDC_CLIENT_ID=rag-client
OIDC_AUDIENCE=rag-api

# LLM Provider
# 2. Get your OpenAI API Key
OPENAI_API_KEY=sk-CHANGE_ME
EOF

echo "Generated rag-stack/.env"
echo "✅ Webhook Secret generated: ${WEBHOOK_SECRET}" 
echo "   (You will need to configure this in the Nextcloud Webhook App later)"

echo ""
echo "=========================================="
echo "⚠️  MANUAL ACTION REQUIRED ⚠️"
echo "=========================================="
echo "1. Go to https://${PUBLIC_IP}:8080 and finish Nextcloud Setup."
echo "2. Log in to Nextcloud, create user 'readonly-bot', and generate an App Password."
echo "3. Edit docker-deploy/rag-stack/.env:"
echo "   - Set WEBDAV_PASSWORD=<your_app_password>"
echo "   - Set OPENAI_API_KEY=<your_key>"
echo "   - Check OIDC settings if needed."
echo ""
read -p "Press [Enter] once you have updated the .env file to continue..."

# --- 7. RAG Deployment ---
echo ""
echo "--- Step 7: Deploying RAG Stack ---"
docker compose build || error_exit "RAG_BUILD" "docker compose build"
docker compose up -d || error_exit "RAG_DEPLOY" "docker compose up -d"

verify_container_up "rag-indexer-worker"
verify_container_up "rag-haystack-api"

echo ""
echo "=========================================="
echo "✅ INSTALLATION SUCCESSFUL"
echo "=========================================="

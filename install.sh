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

# --- 1. Prerequisites & Installation ---
echo "--- Step 1: Checking and Installing Prerequisites ---"

# Function to install a package if it's missing
function ensure_package {
    if ! command -v "$1" &> /dev/null; then
        echo "📦 Package '$1' is missing. Installing..."
        SUDO_CMD=""
        if command -v sudo &> /dev/null; then SUDO_CMD="sudo"; fi
        $SUDO_CMD apt-get update -y
        $SUDO_CMD apt-get install -y "$2"
    else
        echo "✅ '$1' is already installed."
    fi
}

# 1a. Core Tools
ensure_package curl curl
ensure_package openssl openssl
ensure_package git git

# 1b. Docker Installation
if ! command -v docker &> /dev/null; then
    echo "🐳 Docker not found. Installing Docker..."
    SUDO_CMD=""
    if command -v sudo &> /dev/null; then SUDO_CMD="sudo"; fi
    $SUDO_CMD apt-get update -y
    $SUDO_CMD apt-get install -y ca-certificates gnupg lsb-release
    $SUDO_CMD mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | $SUDO_CMD gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" | $SUDO_CMD tee /etc/apt/sources.list.d/docker.list > /dev/null
    $SUDO_CMD apt-get update -y
    $SUDO_CMD apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
else
    echo "✅ Docker is already installed."
fi

# Ensure Docker is running
SUDO_CMD=""
if command -v sudo &> /dev/null; then SUDO_CMD="sudo"; fi

if ! $SUDO_CMD docker info > /dev/null 2>&1; then
    echo "🚀 Starting Docker service..."
    $SUDO_CMD systemctl start docker
    $SUDO_CMD systemctl enable docker
fi

# Verify Docker access
if ! $SUDO_CMD docker info > /dev/null 2>&1; then
    error_exit "PREREQUISITES" "Docker daemon is not running or accessible even after installation attempt."
fi

# Alias docker-compose if needed
if ! docker compose version &> /dev/null; then
    error_exit "PREREQUISITES" "Docker Compose (V2) is required but not found."
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
# Generate .env for AIO
cat > .env <<EOF
NEXTCLOUD_DOMAIN=${NEXTCLOUD_DOMAIN}
EOF
echo "Generated nextcloud-aio/.env"

docker compose up -d || error_exit "NEXTCLOUD_DEPLOY" "docker compose up -d (nextcloud)" "nextcloud-aio-mastercontainer"
verify_container_up "nextcloud-aio-mastercontainer"

echo ""
echo "----------------------------------------------------------------"
echo "ATTENTION: Nextcloud AIO Setup Needed"
echo "----------------------------------------------------------------"
echo "Open the following URL in your browser to complete the Nextcloud setup:"
echo "https://${PUBLIC_IP}:8080"
echo ""
echo "Important:"
echo "1. Your browser will show a 'Connection not private' warning."
echo "2. Click 'Advanced' and then 'Proceed' (this is safe for the setup)."
echo "3. Follow the instructions on the page."
echo "4. Use the Domain: ${NEXTCLOUD_DOMAIN}"
echo "5. After finishing the setup and starting the containers,"
echo "   Nextcloud will be available at: https://${NEXTCLOUD_DOMAIN}"
echo "----------------------------------------------------------------"
echo ""
read -p "Press [Enter] once you have finished the Nextcloud AIO setup..."

# Automatically enable the Webhook Listeners app
echo "Activating Webhook Listeners app in Nextcloud..."
docker exec -u www-data nextcloud-aio-nextcloud php occ app:enable webhook_listeners || echo "⚠️ Warning: Could not enable app automatically. Please enable 'Webhook Listeners' manually in the Nextcloud App Store."

cd ../..

# --- 6. RAG Stack Config Generation ---
echo ""
echo "--- Step 6: Preparing RAG Stack ---"
cd docker-deploy/rag-stack

# A. PostgreSQL Configuration
echo "Generating secure database passwords..."
POSTGRES_PASSWORD=$(openssl rand -hex 20)
echo "✅ Database passwords generated."

# B. Nextcloud Webhook Configuration
echo ""
# B. Nextcloud Webhook Configuration (Step 6)
echo ""
echo "----------------------------------------------------------------"
echo "SETUP: Nextcloud Webhook Automation"
echo "----------------------------------------------------------------"
echo "We will now automatically register the necessary webhooks via the Nextcloud API."
echo "Please provide your Nextcloud Admin credentials to authorize this action."
echo ""

# Function to register a webhook
register_webhook() {
    local endpoint="$1"
    local event="$2"
    local admin_user="$3"
    local admin_pass="$4"

    echo "   -> Registering event: $event..."
    
    # Use curl to send the request
    # separate capture of http code and exit status to prevent script crash
    if curl -s -o response.json -w "%{http_code}" -X POST "${NEXTCLOUD_URL}/ocs/v2.php/apps/webhook_listeners/api/v1/webhooks" \
        -u "${admin_user}:${admin_pass}" \
        -H "OCS-APIRequest: true" \
        -H "Content-Type: application/json" \
        -d "{\"uri\": \"${endpoint}\", \"event\": \"${event}\"}" > http_code.txt; then
        
        HTTP_RESPONSE=$(cat http_code.txt)
        
        if [ "$HTTP_RESPONSE" -eq 200 ] || [ "$HTTP_RESPONSE" -eq 201 ]; then
            echo "      ✅ Success."
        else
            echo "      ❌ Failed (HTTP $HTTP_RESPONSE). API/Server Response:"
            cat response.json
            echo ""
        fi
    else
        echo "      ❌ CRITICAL ERROR: Curl command failed to execute."
        echo "      Could not reach Nextcloud at: ${NEXTCLOUD_URL}"
        echo "      Please check if the URL is reachable from this server."
        echo "      The script will continue, but you may need to add webhooks manually."
    fi
    rm -f response.json http_code.txt
}

# Prompt for credentials
read -p "Enter Nextcloud Admin Username (default: admin): " NC_ADMIN_USER
NC_ADMIN_USER=${NC_ADMIN_USER:-admin}
read -s -p "Enter Nextcloud Admin Password: " NC_ADMIN_PASS
echo ""
echo ""

# Define the RAG Webhook URL
RAG_WEBHOOK_URL="https://${RAG_DOMAIN}/webhook/nextcloud"
echo "Target Webhook URL: $RAG_WEBHOOK_URL"
echo ""

# Register the events
register_webhook "$RAG_WEBHOOK_URL" "OCP\\Files\\Events\\Node\\NodeCreatedEvent" "$NC_ADMIN_USER" "$NC_ADMIN_PASS"
register_webhook "$RAG_WEBHOOK_URL" "OCP\\Files\\Events\\Node\\NodeWrittenEvent" "$NC_ADMIN_USER" "$NC_ADMIN_PASS"
register_webhook "$RAG_WEBHOOK_URL" "OCP\\Files\\Events\\Node\\NodeDeletedEvent" "$NC_ADMIN_USER" "$NC_ADMIN_PASS"

# Verify Webhooks
echo ""
echo "Verifying registered webhooks..."
VERIFY_RESPONSE=$(curl -s -X GET "${NEXTCLOUD_URL}/ocs/v2.php/apps/webhook_listeners/api/v1/webhooks" \
    -u "${NC_ADMIN_USER}:${NC_ADMIN_PASS}" \
    -H "OCS-APIRequest: true" \
    -H "Content-Type: application/json")

if echo "$VERIFY_RESPONSE" | grep -q "$RAG_WEBHOOK_URL"; then
    echo "✅ Verification Successful: Webhooks are active."
else
    echo "⚠️  Verification Failed: Could not find the registered URL in the list."
    echo "Debug Response: $VERIFY_RESPONSE"
fi

# Note on Secrets: The 'webhook_listeners' app does not use a shared secret in the payload.
# We generate a random secret for the RAG app config, but it might not be verified by this specific app.
NEXTCLOUD_WEBHOOK_SECRET=$(openssl rand -hex 20)
echo ""
echo "generated internal webhook secret: $NEXTCLOUD_WEBHOOK_SECRET"

# C. Nextcloud WebDAV Configuration (The Bot)
echo ""
echo "----------------------------------------------------------------"
echo "SETUP: WebDAV / Bot User"
echo "----------------------------------------------------------------"
echo "The RAG system needs to read files from Nextcloud via WebDAV."
echo "1. Log in to Nextcloud at https://${NEXTCLOUD_DOMAIN}"
echo "2. Create a dedicated user (e.g., 'rag-bot') or use your own."
echo "3. Go to 'Personal Settings' -> 'Security'."
echo "4. Scroll down to 'Devices & sessions'."
echo "5. Enter 'RAG-App' in the 'App name' field and click 'Create new app password'."
echo "6. IMPORTANT: Copy the password shown!"
echo ""
read -p "Enter the Nextcloud App Password for the bot: " WEBDAV_PASSWORD

# D. OpenAI Configuration
echo ""
echo "----------------------------------------------------------------"
echo "SETUP: AI Model (OpenAI)"
echo "----------------------------------------------------------------"
echo "The system uses OpenAI for processing text and answering questions."
echo "1. Go to https://platform.openai.com/"
echo "2. Login and navigate to 'API Keys'."
echo "3. Create a new secret key."
echo ""
read -p "Enter your OpenAI API Key (sk-...): " OPENAI_API_KEY

# E. OIDC Authentication
echo ""
echo "----------------------------------------------------------------"
echo "SETUP: Authentication (OIDC)"
echo "----------------------------------------------------------------"
echo "Do you want to use OpenID Connect (OIDC) for user authentication?"
echo "This is required if you want to restrict the web UI to specific users."
read -p "Use OIDC? (y/n): " USE_OIDC

OIDC_ISSUER="none"
OIDC_CLIENT_ID="none"
OIDC_AUDIENCE="none"

if [[ $USE_OIDC == "y"* ]]; then
    echo ""
    echo "Please provide your OIDC details (from Keycloak, Authentik, etc.):"
    read -p "OIDC Issuer URL: " OIDC_ISSUER
    read -p "OIDC Client ID: " OIDC_CLIENT_ID
    read -p "OIDC Audience: " OIDC_AUDIENCE
fi

# Generate the .env file
cat > .env <<EOF
# Domain Configuration
RAG_DOMAIN=${RAG_DOMAIN}

# Nextcloud Connection
NEXTCLOUD_URL=https://${NEXTCLOUD_DOMAIN}
NEXTCLOUD_WEBHOOK_SECRET=${NEXTCLOUD_WEBHOOK_SECRET}

# WebDAV Bot Configuration
WEBDAV_USER=rag-bot
WEBDAV_PASSWORD=${WEBDAV_PASSWORD}

# Databases
POSTGRES_USER=rag_user
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_DB=rag_metadata

# Authentication (OIDC)
OIDC_ISSUER=${OIDC_ISSUER}
OIDC_CLIENT_ID=${OIDC_CLIENT_ID}
OIDC_AUDIENCE=${OIDC_AUDIENCE}

# LLM Provider
OPENAI_API_KEY=${OPENAI_API_KEY}
EOF

echo ""
echo "✅ Generated rag-stack/.env with your provided configuration."
echo "----------------------------------------------------------------"
echo ""
read -p "Press [Enter] to start the deployment of the RAG stack..."

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

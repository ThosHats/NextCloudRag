#!/bin/bash
# ==============================================================================
# Nextcloud RAG Bootstrap Script
# ==============================================================================
# This script prepares a fresh server by installing Python 3 and its dependencies,
# then hands over the installation process to install.py.

# Ensure we are running in Bash (because we use Process Substitution)
if [ -z "$BASH_VERSION" ]; then
    echo "⚠️  Detected execution via 'sh'. Re-launching with 'bash'..."
    exec bash "$0" "$@"
fi

set -e

# Logging setup
LOG_FILE="install_debug.log"
exec > >(tee -a "${LOG_FILE}") 2>&1

echo "=========================================="
echo "🚀 Starting Nextcloud RAG Bootstrap"
echo "=========================================="
echo "Detected OS: $(uname -s)"
echo "Time: $(date)"
echo ""

# Ensure we have sudo if not root
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    else
        echo "❌ Error: This script must be run as root or with sudo."
        exit 1
    fi
fi

# Step 1: Update system packages
echo "--- Step 1: Updating System Packages ---"
$SUDO apt-get update -y

# Step 2: Install core prerequisites
echo "--- Step 2: Installing Python 3 and Core Tools ---"
$SUDO apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-yaml \
    curl \
    git \
    openssl \
    ca-certificates \
    gnupg \
    lsb-release

# Step 3: Global Python dependencies check
echo "--- Step 3: Verifying Installer Dependencies ---"
# PyYAML is now installed via apt (python3-yaml) in Step 2.
if python3 -c "import yaml" >/dev/null 2>&1; then
    echo "✅ PyYAML is available."
else
    echo "⚠️ PyYAML not found. Attempting emergency install..."
    $SUDO pip3 install pyyaml --break-system-packages || echo "❌ Failed to install PyYAML. The installer might fail."
fi

# Step 4: Handover to Python Installer
echo ""
echo "=========================================="
echo "✅ Bootstrap Complete. Handing over to Python..."
echo "=========================================="
echo ""

if [ -f "install.py" ]; then
    # Make sure we are in the correct directory if relative paths are used
    python3 install.py "$@"
else
    echo "❌ Error: install.py not found in current directory."
    exit 1
fi

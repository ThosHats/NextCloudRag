#!/bin/bash
# ==============================================================================
# Nextcloud RAG Bootstrap Script
# ==============================================================================
# This script prepares a fresh server by installing Python 3 and its dependencies,
# then hands over the installation process to install.py.

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
    curl \
    git \
    openssl \
    ca-certificates \
    gnupg \
    lsb-release

# Step 3: Global Python dependencies needed for the installer itself
echo "--- Step 3: Installing Installer Dependencies ---"
# We use --break-system-packages if on newer Debian/Ubuntu to allow pip install,
# or simply ensure the user has the basic tools.
$SUDO pip3 install --upgrade pip
$SUDO pip3 install pyyaml || $SUDO pip3 install pyyaml --break-system-packages || echo "Warning: Could not install PyYAML via pip, install.py will try again internally."

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

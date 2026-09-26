#!/usr/bin/env bash
# ==============================================================================
# Oracle Sentinel - One-Click Installer for Oracle Cloud VPS
# Supports: Ubuntu 20.04+, Ubuntu 22.04+, Debian 11+, Debian 12+ (x86_64 / ARM64)
# ==============================================================================

set -euo pipefail

INSTALL_DIR="/opt/oracle-sentinel"
REPO_URL="https://github.com/16893863/oracle-sentinel.git"

echo "===================================================================="
echo "    🚀 Installing Oracle Cloud Sentinel Control Center & Daemon     "
echo "===================================================================="

# Check root
if [ "$(id -u)" -ne 0 ]; then
    echo "[!] This script must be run as root (or with sudo)."
    exit 1
fi

# Update package lists and install system dependencies
echo ">>> Installing prerequisites (Python3, venv, curl, git)..."
apt-get update -y
apt-get install -y python3 python3-pip python3-venv git curl ufw

# Ensure installation directory exists
mkdir -p "$INSTALL_DIR"

# If current directory is the source directory, copy files; otherwise clone
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$SCRIPT_DIR/app.py" ]; then
    echo ">>> Copying files from local source tree: $SCRIPT_DIR ..."
    cp -ru "$SCRIPT_DIR"/* "$INSTALL_DIR/"
else
    if [ ! -f "$INSTALL_DIR/app.py" ]; then
        echo ">>> Cloning repository from GitHub: $REPO_URL ..."
        git clone "$REPO_URL" "$INSTALL_DIR"
    fi
fi

cd "$INSTALL_DIR"

# Setup Python Virtual Environment
echo ">>> Setting up Python virtual environment..."
if [ ! -d "$INSTALL_DIR/venv" ]; then
    python3 -m venv "$INSTALL_DIR/venv"
fi

"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# Initialize config.json if not present
if [ ! -f "$INSTALL_DIR/config.json" ]; then
    echo ">>> Creating initial config.json from template..."
    cp "$INSTALL_DIR/config.example.json" "$INSTALL_DIR/config.json"
    echo "[!] Please edit $INSTALL_DIR/config.json with your Cloudflare API token and OCI details."
fi

# Install systemd service
echo ">>> Installing systemd unit file..."
cp "$INSTALL_DIR/systemd/oracle-sentinel.service" /etc/systemd/system/oracle-sentinel.service
systemctl daemon-reload
systemctl enable oracle-sentinel

# Open default port on UFW if active
if command -v ufw >/dev/null 2>&1; then
    if ufw status | grep -q "Status: active"; then
        echo ">>> Allowing port 20540 on UFW..."
        ufw allow 20540/tcp comment "Oracle Sentinel Dashboard"
    fi
fi

echo "===================================================================="
echo "🎉 Installation completed successfully!"
echo "--------------------------------------------------------------------"
echo " Next steps:"
echo " 1. Configure credentials: nano $INSTALL_DIR/config.json"
echo " 2. (Optional) Setup SSL certificate with acme.sh or certbot"
echo " 3. Start service: systemctl restart oracle-sentinel"
echo " 4. View status:   systemctl status oracle-sentinel"
echo " 5. Open Web UI:   https://<YOUR_IP_OR_DOMAIN>:20540/"
echo "===================================================================="

#!/usr/bin/env bash
# ==============================================================================
# VPSentinel - Universal Cloud VPS Installer & Deployment Wizard
# Supports: Ubuntu 20.04+, Debian 11+, RHEL/CentOS/AlmaLinux/Rocky 8+, Arch Linux
# ==============================================================================

set -euo pipefail

if [ -d "/opt/oracle-sentinel" ] && [ ! -d "/opt/vpsentinel" ]; then
    echo ">>> 检测到旧版目录 /opt/oracle-sentinel，平滑迁移至 /opt/vpsentinel ..."
    mv /opt/oracle-sentinel /opt/vpsentinel
    ln -s /opt/vpsentinel /opt/oracle-sentinel
fi

INSTALL_DIR="/opt/vpsentinel"
REPO_URL="https://github.com/imprprpr/vpsentinel.git"

echo "===================================================================="
echo "         🚀 Installing VPSentinel Control Center & Daemon           "
echo "===================================================================="

# Check root
if [ "$(id -u)" -ne 0 ]; then
    echo "[!] This script must be run as root (or with sudo)."
    exit 1
fi

# Detect Package Manager & Install System Dependencies
echo ">>> Detecting Linux distribution and package manager..."
if command -v apt-get >/dev/null 2>&1; then
    echo ">>> Detected Debian/Ubuntu ecosystem (apt-get)."
    apt-get update -y
    apt-get install -y python3 python3-pip python3-venv git curl openssl iptables
elif command -v dnf >/dev/null 2>&1; then
    echo ">>> Detected RHEL/Fedora/AlmaLinux/Rocky ecosystem (dnf)."
    dnf install -y python3 python3-pip git curl openssl iptables
elif command -v yum >/dev/null 2>&1; then
    echo ">>> Detected CentOS/RHEL legacy ecosystem (yum)."
    yum install -y python3 python3-pip git curl openssl iptables
elif command -v pacman >/dev/null 2>&1; then
    echo ">>> Detected Arch Linux ecosystem (pacman)."
    pacman -Sy --noconfirm python python-pip git curl openssl iptables
else
    echo "[!] Warning: Unknown package manager. Please ensure python3, pip, git, curl, and openssl are installed."
fi

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
chmod +x "$INSTALL_DIR"/scripts/*.sh "$INSTALL_DIR"/scripts/*.py 2>/dev/null || true

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
fi

# Install systemd service
echo ">>> Installing systemd unit file..."
if [ -f "$INSTALL_DIR/systemd/vpsentinel.service" ]; then
    cp "$INSTALL_DIR/systemd/vpsentinel.service" /etc/systemd/system/vpsentinel.service
    ln -sf /etc/systemd/system/vpsentinel.service /etc/systemd/system/oracle-sentinel.service
    systemctl daemon-reload
    systemctl enable vpsentinel
else
    cp "$INSTALL_DIR/systemd/oracle-sentinel.service" /etc/systemd/system/oracle-sentinel.service
    systemctl daemon-reload
    systemctl enable oracle-sentinel
fi

# Open default port on UFW or firewalld if active
if command -v ufw >/dev/null 2>&1; then
    if ufw status | grep -q "Status: active"; then
        echo ">>> Allowing port 20540 on UFW..."
        ufw allow 20540/tcp comment "VPSentinel Dashboard"
    fi
elif command -v firewall-cmd >/dev/null 2>&1; then
    if systemctl is-active --quiet firewalld; then
        echo ">>> Allowing port 20540 on firewalld..."
        firewall-cmd --add-port=20540/tcp --permanent >/dev/null 2>&1 || true
        firewall-cmd --reload >/dev/null 2>&1 || true
    fi
fi

echo "===================================================================="
echo "🎉 Core components and dependencies installed successfully!"
echo "===================================================================="

# Check if running interactively in terminal
if [ -t 0 ]; then
    read -rp ">>> 是否立即启动全交互式配置向导 (自动配置 OCI、Cloudflare、BBR、防火墙)？[Y/n]: " RUN_WIZARD
    RUN_WIZARD=${RUN_WIZARD:-y}
    if [[ "$RUN_WIZARD" =~ ^[Yy]$ ]]; then
        python3 "$INSTALL_DIR/scripts/wizard.py"
        exit 0
    fi
fi

echo "--------------------------------------------------------------------"
echo " 您可以随时运行以下命令启动全流程交互式配置向导："
echo "   sudo python3 $INSTALL_DIR/scripts/wizard.py"
echo "--------------------------------------------------------------------"
echo " 或者手动维护配置文件："
echo "   nano $INSTALL_DIR/config.json"
echo "   systemctl restart vpsentinel"
echo "===================================================================="

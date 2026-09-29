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
echo "          Installing VPSentinel Control Center & Daemon             "
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

# Ensure firewall allows port 20540 and node ports (especially on Oracle Cloud)
if command -v iptables >/dev/null 2>&1; then
    iptables -C INPUT -p tcp --dport 20540 -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -p tcp --dport 20540 -j ACCEPT
    iptables -C INPUT -p tcp --dport 8443 -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -p tcp --dport 8443 -j ACCEPT
    iptables -C INPUT -p udp --dport 20000:40000 -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -p udp --dport 20000:40000 -j ACCEPT
    if command -v netfilter-persistent >/dev/null 2>&1; then
        netfilter-persistent save >/dev/null 2>&1 || true
    fi
fi

# Start or restart background service
echo ">>> Starting VPSentinel service..."
if systemctl is-enabled --quiet vpsentinel 2>/dev/null; then
    systemctl restart vpsentinel
else
    systemctl restart oracle-sentinel 2>/dev/null || true
fi

SERVER_IP=$(curl -s4 --max-time 3 https://api.ipify.org 2>/dev/null || curl -s4 --max-time 3 https://icanhazip.com 2>/dev/null || echo "127.0.0.1")

echo "===================================================================="
echo "[OK] VPSentinel 核心服务已成功安装并启动就绪！"
echo "===================================================================="

# Retrieve or generate random initial admin password
INITIAL_PASS=$(python3 -c "
import sys
sys.path.insert(0, '$INSTALL_DIR')
try:
    from auth_mgr import AuthManager
    from sentinel_core import ConfigManager
    mgr = AuthManager(ConfigManager)
    sec = mgr.get_security_config()
    print(sec.get('initial_password', ''))
except Exception:
    pass
" 2>/dev/null || true)

if [ -z "$INITIAL_PASS" ]; then
    INITIAL_PASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))" 2>/dev/null || echo "Sentinel$(date +%s)")
    python3 -c "
import sys
sys.path.insert(0, '$INSTALL_DIR')
try:
    from auth_mgr import AuthManager
    from sentinel_core import ConfigManager
    mgr = AuthManager(ConfigManager)
    cfg = ConfigManager.load()
    sec = cfg.setdefault('security', {})
    sec['admin_password_hash'] = mgr.hash_password('$INITIAL_PASS')
    sec['must_change_password'] = True
    sec['initial_password'] = '$INITIAL_PASS'
    ConfigManager.save(cfg)
except Exception:
    pass
" 2>/dev/null || true
fi

echo "控制台访问信息："
echo "  访问地址: https://${SERVER_IP}:20540/sentinel"
echo "  初始账号: admin"
echo "  初始随机密码: ${INITIAL_PASS}"
echo "  (请妥善保存此密码，首次登入后请立即在控制台中修改)"
echo "新手极简上手指南："
echo "  1. 复制上方链接在浏览器打开；"
echo "  2. 若 Chrome/Edge 提示'您的连接不是私密连接'，直接键盘盲打这几个字母即可跳过：thisisunsafe"
echo "  3. 网页将自动唤起向导，推荐选择【新手极速模式】，仅需 2 步即可直接生成可用订阅！"
echo "===================================================================="

# Check if running interactively in terminal and user wants CLI wizard
if [ -t 0 ]; then
    read -rp ">>> 是否在终端中启动 CLI 高级向导 (输入 n 可直接在网页端使用)？[y/N]: " RUN_WIZARD
    RUN_WIZARD=${RUN_WIZARD:-n}
    if [[ "$RUN_WIZARD" =~ ^[Yy]$ ]]; then
        python3 "$INSTALL_DIR/scripts/wizard.py"
        exit 0
    fi
fi

echo "提示：您可以随时通过浏览器控制台进行管理，或运行 sudo python3 $INSTALL_DIR/scripts/wizard.py"
echo "===================================================================="

#!/usr/bin/env bash
# ==============================================================================
# Oracle Sentinel - One-Click Transit Node Realm Deployer
# Usage:
#   bash setup-relay.sh <TARGET_VPS_DOMAIN_OR_IP>
# Example:
#   bash setup-relay.sh vps.yourdomain.com
# ==============================================================================

set -euo pipefail

TARGET="${1:-${TARGET_HOST:-}}"

if [ -z "$TARGET" ]; then
    echo "===================================================================="
    echo " [ERROR] Missing target destination host!"
    echo " Usage: sudo bash setup-relay.sh <TARGET_VPS_DOMAIN_OR_IP>"
    echo " Example: sudo bash setup-relay.sh vps.yourdomain.com"
    echo "===================================================================="
    exit 1
fi

echo "===================================================================="
echo ">>> Setting up Realm L4 Transit Port Forwarder for target: $TARGET"
echo "===================================================================="

# Check root
if [ "$(id -u)" -ne 0 ]; then
    echo "[!] Please run as root (use sudo)!"
    exit 1
fi

# Detect Architecture
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64|amd64)
        REALM_ARCH="x86_64-unknown-linux-gnu"
        ;;
    aarch64|arm64)
        REALM_ARCH="aarch64-unknown-linux-gnu"
        ;;
    armv7l|armhf)
        REALM_ARCH="armv7-unknown-linux-gnueabihf"
        ;;
    *)
        echo "[ERROR] Unsupported architecture: $ARCH"
        exit 1
        ;;
esac

mkdir -p /opt/realm
cd /opt/realm

echo ">>> Downloading latest Realm binary ($REALM_ARCH)..."
REALM_URL="https://github.com/zhboner/realm/releases/latest/download/realm-${REALM_ARCH}.tar.gz"
curl -fsSL "$REALM_URL" -o /tmp/realm.tar.gz
tar -zxvf /tmp/realm.tar.gz -C /opt/realm/
chmod +x /opt/realm/realm
rm -f /tmp/realm.tar.gz

echo ">>> Writing configuration /opt/realm/config.toml..."
cat << EOF > /opt/realm/config.toml
[log]
level = "warn"

[network]
no_tcp = false
use_udp = true

# Hysteria 2 Port Forwarding
[[endpoints]]
listen = "0.0.0.0:20443"
remote = "${TARGET}:443"

# VLESS-Reality Port Forwarding
[[endpoints]]
listen = "0.0.0.0:28443"
remote = "${TARGET}:8443"

# Trojan Port Forwarding
[[endpoints]]
listen = "0.0.0.0:22083"
remote = "${TARGET}:2083"
EOF

echo ">>> Registering and starting systemd service: realm.service..."
cat << EOF > /etc/systemd/system/realm.service
[Unit]
Description=Realm L4 Transit Port Forwarder
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/realm
ExecStart=/opt/realm/realm -c /opt/realm/config.toml
Restart=always
RestartSec=5
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable realm
systemctl restart realm

echo "===================================================================="
echo ">>> Realm transit service deployed and running successfully!"
echo "    - 20443 (UDP/TCP) -> ${TARGET}:443  [Hysteria 2]"
echo "    - 28443 (TCP)     -> ${TARGET}:8443 [VLESS-Reality]"
echo "    - 22083 (TCP)     -> ${TARGET}:2083 [Trojan]"
echo "===================================================================="
systemctl status realm --no-pager

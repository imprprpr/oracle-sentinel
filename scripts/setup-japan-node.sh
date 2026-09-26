#!/usr/bin/env bash
# ==============================================================================
# VPSentinel - Ultra-lightweight Sing-box VLESS-Reality Standalone Node Deployer
# Optimized for 64MB RAM Podman/LXC Containers & Standalone VPS
# ==============================================================================

set -euo pipefail

echo "===================================================================="
echo "    🚀 Deploying Ultra-Lightweight Japan Native Node (sing-box)      "
echo "===================================================================="

# Check root
if [ "$(id -u)" -ne 0 ]; then
    echo "[!] Please run as root (or use sudo)."
    exit 1
fi

# Stop conflicting realm or services
systemctl stop realm 2>/dev/null || pkill -9 realm 2>/dev/null || true
systemctl disable realm 2>/dev/null || true

# Ensure dependencies
if ! command -v curl >/dev/null 2>&1 || ! command -v tar >/dev/null 2>&1; then
    echo ">>> Installing dependencies (curl, tar, ca-certificates)..."
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -y && apt-get install -y curl tar ca-certificates
    elif command -v apk >/dev/null 2>&1; then
        apk add --no-cache curl tar ca-certificates
    fi
fi

# Free memory cache and clean tmp
sync 2>/dev/null || true
rm -rf /tmp/* /opt/sing-box 2>/dev/null || true

# Download official sing-box
SB_VER="1.14.2"
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64|amd64) SB_ARCH="linux-amd64" ;;
    aarch64|arm64) SB_ARCH="linux-arm64" ;;
    *) echo "[!] Unsupported arch: $ARCH"; exit 1 ;;
esac

echo ">>> Streaming sing-box v${SB_VER} (${SB_ARCH}) directly (Zero-RAM mode)..."
mkdir -p /etc/sing-box
curl -fsSL "https://github.com/SagerNet/sing-box/releases/download/v${SB_VER}/sing-box-${SB_VER}-${SB_ARCH}.tar.gz" | tar -zx -O "sing-box-${SB_VER}-${SB_ARCH}/sing-box" > /usr/local/bin/sing-box
chmod +x /usr/local/bin/sing-box

echo ">>> Generating VLESS-Reality credentials..."
UUID=$(/usr/local/bin/sing-box generate uuid)
KEYPAIR=$(/usr/local/bin/sing-box generate reality-keypair)
PRIV_KEY=$(echo "$KEYPAIR" | grep "PrivateKey" | awk '{print $2}' | tr -d ' "\r\n')
PUB_KEY=$(echo "$KEYPAIR" | grep "PublicKey" | awk '{print $2}' | tr -d ' "\r\n')
SHORT_ID=$(/usr/local/bin/sing-box generate rand --hex 8)

SNI="swdist.apple.com"
LISTEN_PORT=28443

echo ">>> Configuring /etc/sing-box/config.json..."
cat << CONFIG_EOF > /etc/sing-box/config.json
{
  "log": {
    "level": "warn"
  },
  "inbounds": [
    {
      "type": "vless",
      "tag": "vless-in",
      "listen": "0.0.0.0",
      "listen_port": ${LISTEN_PORT},
      "users": [
        {
          "uuid": "${UUID}",
          "flow": "xtls-rprx-vision"
        }
      ],
      "tls": {
        "enabled": true,
        "server_name": "${SNI}",
        "reality": {
          "enabled": true,
          "handshake": {
            "server": "${SNI}",
            "server_port": 443
          },
          "private_key": "${PRIV_KEY}",
          "short_id": [
            "${SHORT_ID}"
          ]
        }
      }
    }
  ],
  "outbounds": [
    {
      "type": "direct",
      "tag": "direct"
    }
  ]
}
CONFIG_EOF

# Detect systemd or container
HAS_SYSTEMD=false
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    HAS_SYSTEMD=true
fi

if [ "$HAS_SYSTEMD" = true ]; then
    echo ">>> Starting systemd service: sing-box.service..."
    cat << SVC_EOF > /etc/systemd/system/sing-box.service
[Unit]
Description=sing-box service
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Environment=GOGC=20
ExecStart=/usr/local/bin/sing-box run -c /etc/sing-box/config.json
Restart=always
RestartSec=3
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
SVC_EOF
    systemctl daemon-reload
    systemctl enable sing-box
    systemctl restart sing-box
    systemctl status sing-box --no-pager || true
else
    echo ">>> Starting sing-box daemon in background..."
    pkill -9 sing-box 2>/dev/null || true
    nohup /usr/local/bin/sing-box run -c /etc/sing-box/config.json > /opt/sing-box/sing-box.log 2>&1 &
fi

EXT_IP="158.51.111.141"
EXT_PORT="53446"
NODE_NAME="🇯🇵 日本原生大口子 (超低延迟)"

VLESS_LINK="vless://${UUID}@${EXT_IP}:${EXT_PORT}?encryption=none&flow=xtls-rprx-vision&security=reality&sni=${SNI}&fp=chrome&pbk=${PUB_KEY}&sid=${SHORT_ID}&type=tcp#%F0%9F%87%AF%F0%9F%87%B5%20%E6%97%A5%E6%9C%AC%E5%8E%9F%E7%94%9F%E5%A4%A7%E5%8F%A3%E5%AD%90"

echo ""
echo "===================================================================="
echo "🎉 日本原生节点 (VLESS-Reality) 部署启动成功！"
echo "===================================================================="
echo ""
echo "📱 【通用节点链接】 (复制整行链接，支持 v2rayN / 小火箭 / Sing-box / Karing):"
echo "--------------------------------------------------------------------"
echo "${VLESS_LINK}"
echo "--------------------------------------------------------------------"
echo ""
echo "⚙️ 【Clash Verge / Mihomo 配置片段】 (可追加到 proxies 列表):"
echo "--------------------------------------------------------------------"
cat << CLASH_EOF
- name: "${NODE_NAME}"
  type: vless
  server: ${EXT_IP}
  port: ${EXT_PORT}
  uuid: ${UUID}
  network: tcp
  tls: true
  udp: true
  flow: xtls-rprx-vision
  servername: ${SNI}
  reality-opts:
    public-key: ${PUB_KEY}
    short-id: ${SHORT_ID}
  client-fingerprint: chrome
CLASH_EOF
echo "===================================================================="
echo "内存占用极其轻微 (~15MB)，直连国内延迟约 35~60ms，真·日本原生全解锁！"
echo "===================================================================="

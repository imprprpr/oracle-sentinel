# Changelog

All notable changes to the **Oracle Sentinel** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-09-26

### 🌐 Universal Multi-Cloud & Cross-Distro Expansion (泛用性多云与通用 VPS 演进)
- **Multi-Cloud Provider Abstraction (`sentinel_core.py`)**:
  - Introduces extensible `BaseCloudProvider` architecture supporting `OracleCloudProvider`, `GenericProvider`, and `CustomHookProvider`.
  - Deferred OCI SDK import: non-Oracle servers run smoothly without requiring OCI dependencies.
  - Auto-detection engine (`get_cloud_info()`): Dynamically detects host hypervisor, cloud provider (Oracle, AWS, Hetzner, Alibaba, Tencent, DO, Generic KVM), and CPU architecture (`x86_64` / `aarch64`).
- **Multi-Channel Notification Dispatcher (`notification.py`)**:
  - Out-of-the-box instant alert dispatch across **Telegram Bot**, **Discord Webhook**, **Bark (iOS Push)**, and **Custom Webhook**.
  - Sends rich event cards on domestic probe GFW blocks, Re-IP rebirth initiation, DNS synchronization, and routine success/failure.
  - Interactive notification channel test endpoint (`/api/notifications/test`) with test button in Web UI.
- **Cross-Distribution Linux Support (`scripts/install.sh`)**:
  - Multi-package manager auto-detection supporting `apt` (Ubuntu/Debian), `dnf`/`yum` (CentOS/RHEL/Fedora/AlmaLinux/Rocky), and `pacman` (Arch Linux).
  - Cross-firewall port opening: auto-detects and configures either `ufw` or `firewalld`.
- **Universal CLI Wizard Expansion (`scripts/wizard.py`)**:
  - Mode selection: Oracle Cloud (OCI API), Generic VPS (monitoring & alerts), or Custom Hook script.
  - Dedicated step for Multi-Channel Notification setup (Telegram, Discord, Bark).
- **Web UI Universalization (`static/index.html`)**:
  - Dynamic host badge displaying detected cloud provider, region, and CPU architecture in real-time.
  - Settings Modal updated with Cloud Provider selection, Custom Hook input, and multi-channel notification fields with live testing.

---

## [1.2.0] - 2026-09-26

### 🚀 3x-ui Golden Inbounds Auto-Provisioning (出海全家桶预置注入)
- **Node Provisioner Engine (`scripts/node_provisioner.py`)**: Direct SQLite database injector for `/etc/x-ui/x-ui.db`.
- **Pure Python X25519 Key Generation**: Native Curve25519 public/private keypair and shortId generator for Reality without external xray binaries.
- **Three Golden Production Inbounds**:
  - `Oracle-US` (VLESS-Reality :8443) with auto-generated keys, Chrome fingerprint, and swdist.apple.com disguise.
  - `Oracle-Hy2` (Hysteria 2 :443) with auto-generated 16-char password, domain certificate mounting, and kernel-level port hopping.
  - `Oracle-Trojan` (Trojan-TLS :2083) with auto certificate binding and SNI matching.
- **Safe Non-Destructive Ingestion**: Auto-detects existing inbounds and avoids port collisions, preserving user's existing proxies.
- **Wizard Integration**: Seamlessly integrated into `scripts/wizard.py` as Step 5/5.

---

## [1.1.0] - 2026-09-26

### ✨ Interactive CLI Deployment Wizard (极简部署套件)
- **Zero-Dependency CLI Wizard (`scripts/wizard.py`)**: Built entirely with standard library Python, requiring no external packages.
- **Oracle Cloud Firewall & BBR Automation**: Unlocks Oracle Ubuntu default iptables DROP rules and activates Linux native BBR congestion control.
- **Kernel-Level Port Hopping**: Configures Hysteria 2 PREROUTING redirect rule (`UDP 20000:40000 -> 443`) via iptables.
- **OCI API Key Automation**: Generates 2048-bit RSA key pair, pretty-prints the public key for Oracle Console, and parses the config block directly into `/root/.oci/config`.
- **Cloudflare Zone Discovery**: Validates API token and dynamically lists active domains for interactive numerical selection.
- **ACME DNS-01 Silent SSL Issuance**: Integrates with acme.sh to issue ECC-256 SSL certificates via Cloudflare DNS challenge without opening ports 80/443.
- **Upgraded 1-Click Installer (`scripts/install.sh`)**: Prompting to launch the interactive wizard immediately upon dependency installation.

---

## [1.0.0] - 2026-09-26

### 🚀 Initial Production Release

#### 🛡️ Autonomous Self-Healing & Auto-Re-IP
- **OCI SDK Re-IP Automation**: Integrated Oracle Cloud Infrastructure (OCI) Python SDK to automatically detach blocked VNIC public IPs and allocate fresh, clean ephemeral IPs.
- **GFW Multi-Probe Telemetry**: Implemented multi-point cross-border probe monitoring (packet loss calculation, consecutive failure tripwires, latency tracking).
- **Cloudflare DNS Auto-Sync**: Seamlessly updates Cloudflare DNS A-records in real-time when the VPS changes public IP.
- **WebSocket Telemetry Stream**: Real-time broadcast of CPU, RAM, Disk, Network IO, WARP egress status, and rebirth countdowns.

#### 📡 Visual Multi-Protocol Subscription Engine
- **Cross-Client Protocol Support**: Unified subscription endpoints for **Clash (Mihomo Meta)**, **v2rayN**, **Sing-box**, and **Shadowrocket**.
- **X-UI / 3x-ui Database Extraction**: Automatically pulls configured inbounds (Hysteria 2, Trojan, VLESS-Reality) from `/etc/x-ui/x-ui.db`.
- **OpenClash Anti-Deadlock Injection**: Injects `hosts` resolution mappings and `default-nameserver` to eliminate the classic recursive DNS deadlock loop in OpenWrt OpenClash.
- **Sniffer Bypass & Port Exclusions**: Configured management port bypass (`20530`, `20540`) to prevent proxy loops into the control panel.
- **Hysteria 2 Port Hopping**: Full support for UDP multi-port ranges to bypass domestic ISP QoS port throttling.

#### ⚡ Chain Transit Relay Dispatcher
- **Realm L4 High-Performance Forwarding**: Generates configuration and 1-click installation script (`setup-relay.sh`) for domestic/overseas transit machines.
- **Dynamic Node Rewriting**: Rewrites subscription nodes to route through domestic transit relays while retaining upstream TLS sni/reality keys.
- **Soft Router Compatibility**: Plug-and-play compatibility with OpenWrt soft routers (native firewall DNAT or Realm binary).

#### 🎨 Control Center Web UI
- **Industrial Linear/Shadcn Dark Theme**: Designed with pure CSS variables, dark neutral aesthetic, and native Lucide SVG icons.
- **Interactive 3D Telemetry**: Integrated Three.js globe visualizer with ping and latency status.
- **Privacy Obfuscation**: Added `.privacy-blur` interactive CSS blur effect to safeguard public IP segments, domain names, and WARP values during screenshots or screen sharing.
- **Embedded MetaCubeX Dashboard**: Full dashboard suite bundled locally for direct node switching and rule inspection.

# Changelog

All notable changes to the **Oracle Sentinel** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.3.0] - 2026-09-27

### 🛡️ IP Purity & Streaming/AI Unlock Audit (IP 纯净度与流媒体/AI 解锁体检中心)
- **Base IP Profile & Risk Intelligence (`ip_audit.py`)**:
  - Automatically queries IPv4 ASN, ISP, organization, country flag, and detects DataCenter / Hosting vs. Residential ISP profiles.
  - Integrates Scamalytics fraud scoring engine (0~100 rating) and risk rating breakdown (Low / Medium / High / Very High).
  - Queries multi-vendor DNSBL blacklists (SpamCop, DroneBL, S5h, GBUdb Truncate) with clean status verification.
  - Detects Google Search "Unusual Traffic" Captcha restrictions.
- **AI & Global Streaming Media Unlock Matrix (`ip_audit.py`)**:
  - Native verification for OpenAI (API & Web 1020 firewall check), Claude (Anthropic), Google Gemini, Netflix (full catalog vs originals-only detection), YouTube Premium (with country code extraction), and Disney+.
  - Cloudflare WARP dual-stack verification via local Wireproxy SOCKS5 with out-of-band proxy status.
  - In-memory 30-minute caching with on-demand force refresh.

### ⚡ Multi-Node Network Performance & Speedtest Benchmark (多节点网络性能与基准测速中心)
- **Native Speedtest Engine (`speedtest_mgr.py`)**:
  - Integrates host `speedtest-cli` with full bandwidth extraction (Download, Upload, Ping, Server sponsor/location, data transferred).
  - Background asynchronous execution worker with live status updates over WebSocket and REST endpoints.
- **Three-Network & Global Backbone Benchmarks (`speedtest_mgr.py`)**:
  - Real-time ICMP RTT, loss percentage, and jitter measurements for China Telecom (Shanghai), China Unicom (Beijing), China Mobile (Shanghai & Guangzhou), Tencent Cloud BGP, Alibaba Cloud BGP, Cloudflare Anycast, and Google DNS.
  - Composite network quality rating (`A+` to `C`) based on throughput, packet loss, and overseas latency.
- **Interactive Control UI & Dropdown Navigation (`static/index.html`)**:
  - Embedded seamlessly into Section 3 and Section 4 of `tab-services` (仪表盘与管理后台).
  - Added direct quick-jump anchor links in the navbar dropdown with smooth scrolling and highlight animations.
  - Full support for `.privacy-blur` click-to-reveal on sensitive IP displays.
- **RESTful Endpoints & WebSocket Feeds (`app.py`)**:
  - `GET /api/ip/audit` (supports `?force=true`), `POST /api/speedtest/run` (full/ping_only), `GET /api/speedtest/status`.
  - Streamed live speedtest state and progress in the `/ws/live` telemetry broadcast.

---

## [2.2.1] - 2026-09-26

### 🩹 Reliability & OpenClash Router Integration Fixes (订阅兼容性与软路由深度加固)
- **Subscription IP Direct Injection (`sub_engine.py`)**:
  - Fixed `get_server_ip()` fallback to properly query `sentinel_core.SystemMonitor().get_public_ip()` and external IP probes, avoiding unintended `127.0.0.1` loopback fallback.
  - Automatically writes direct public IP into node `server` configurations, bypassing domestic GFW DNS pollution (`127.0.0.1` poisoning) and eliminating OpenClash `hosts` stripping dependencies.
- **Fake-IP Routing Blackhole Bugfix (`sub_engine.py`)**:
  - Removed erroneous `IP-CIDR, 198.18.0.0/15, 🎯 全球直连, no-resolve` rule that was intercepting Clash's Fake-IP pool (`198.18.0.1/16`) and dumping LAN web traffic to WAN gateways.
  - Added secure overseas DoH fallback resolvers (`1.1.1.1` and `8.8.8.8`) with CN GeoIP filters.
- **64MB Container Protection for Remote Nodes (`scripts/setup-japan-node.sh`)**:
  - Replaced piping tar extractions with sequential disk downloading to eliminate memory tmpfs spikes.
  - Added automatic 256MB swap creation for environments with under 128MB RAM.
  - Enforced `GOMEMLIMIT=40MiB` and `GOGC=50` to cap memory usage on ultra-small containers.
- **NAT Port Forwarding Support (`scripts/setup-japan-node.sh`)**:
  - Added support for `EXT_IP` and `EXT_PORT` parameter injection for NAT VPS environments.

---

## [2.2.0] - 2026-09-26

### 🌐 Custom Standalone Nodes Hub (外部独立与原生节点统一聚合)
- **Multi-Protocol Custom Nodes Hub (`custom_node_mgr.py`)**:
  - Full support for parsing standard share links (`vless://` Reality, `hysteria2://` / `hy2://`, `trojan://`, `ss://`) and custom dictionary objects into structured proxies.
  - Seamless dual-direction conversion for Clash/Mihomo YAML, Sing-box JSON, and v2ray Base64 / Shadowrocket formats.
  - Persistent storage in `config.json` with dynamic enable/disable toggling and deletion.
- **Subscription Engine Integration (`sub_engine.py`)**:
  - Automatically merges enabled custom standalone nodes into Clash proxies, `🚀 节点选择`, `⚡ 自动优选`, `🤖 AI 智能服务`, and `🎬 国际流媒体` policy groups.
  - Injects outbounds into Sing-box JSON with selector and urltest group bindings.
- **Web UI & REST APIs (`app.py` & `static/index.html`)**:
  - Added "自定义独立原生节点库 (Custom Standalone Nodes)" card and modal in the control dashboard.
  - REST endpoints: `GET /api/custom-nodes`, `POST /api/custom-nodes`, `DELETE /api/custom-nodes/{id}`, `POST /api/custom-nodes/{id}/toggle`.
- **Command-Line CLI Tool (`scripts/add-custom-node.py`)**:
  - One-line addition and query CLI tool: `python3 scripts/add-custom-node.py "<link>"`.

---

## [2.1.0] - 2026-09-26

### 🧙‍♂️ Web First-Time Setup Wizard (Web 可视化开箱向导)
- **Zero-CLI Web Onboarding Stepper (`static/index.html`)**:
  - Implements a responsive 6-step dark-mode setup wizard dialog triggered automatically on unconfigured instances.
  - Step 1: **Host Diagnostics** - Real-time inspection of hypervisor, provider, architecture, and IPv4.
  - Step 2: **Operation Mode** - Choose between Oracle Cloud (OCI Re-IP), Generic VPS (monitoring & alerts), or Custom Hook scripts. Includes 1-click 2048-bit RSA keypair generation right in the browser.
  - Step 3: **Cloudflare DNS Integration** - Interactive token verification with live domain (Zone) auto-discovery and preview.
  - Step 4: **3x-ui Golden Inbounds Provisioning** - Optional 1-click injection of VLESS-Reality, Hysteria 2 (with port hopping), and Trojan-TLS into SQLite DB.
  - Step 5: **Multi-Channel Alert Dispatcher** - Live configuration and in-wizard instant push testing for Telegram, Discord, and Bark.
  - Step 6: **Review & Instant Deployment** - One-click save and auto-refresh into healthy monitoring state.
- **Backend Setup APIs (`app.py` & `sentinel_core.py`)**:
  - `GET /api/setup/status`: Retrieves initialization state, detected cloud info, and public IP.
  - `POST /api/setup/verify-cf`: Calls Cloudflare API `/client/v4/zones` to validate tokens and dynamically list active domains.
  - `POST /api/setup/generate-key`: Generates standard 2048-bit RSA key pairs with pure standard library / cryptography.
  - `POST /api/setup/save`: Atomic persistent update of `config.json`, OCI credentials, and optional node provisioning.
- **Re-run Wizard Entry**: Added "重新运行 Web 部署向导 🚀" button in the Settings modal for effortless reconfiguration anytime.

---

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

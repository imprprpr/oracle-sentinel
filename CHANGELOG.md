# Changelog

All notable changes to the **Oracle Sentinel** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.6.1] - 2026-10-01

### Security Audit Closure & Refinement (安全审计加固与代码审查收口)
- **R1: Strict Proxy Anti-Spoofing & Leak Prevention (`app.py`, `auth_mgr.py`)**:
  - Removed loopback networks from `DEFAULT_TRUSTED_PROXY_NETWORKS`. Local reverse proxies (Nginx/Caddy) now require explicit configuration in `security.trusted_proxy_cidrs`, preventing header spoofing when unauthenticated clients connect via localhost.
  - Enforced official Cloudflare CIDR verification before trusting `CF-Connecting-IP`.
  - Implemented right-to-left `X-Forwarded-For` chain traversal, stripping trusted proxy hops to identify the true client IP.
  - Eliminated memory leak in login rate limiter by pruning expired attempt timestamps during lock checks.
- **R2: Secure Initial Admin Password Generation (`scripts/install.sh`)**:
  - Switched password generation to virtual environment Python (`$INSTALL_DIR/venv/bin/python3`) and captured raw stdout, preventing subshell parsing errors.
- **R3: Test Scaffolding Production Cleanup (`app.py`, `auth_mgr.py`)**:
  - Completely purged production-adjacent `testclient` and `testserver` bypass credentials from authentication checks.
- **R4: Nanosecond Fingerprint Config Caching & Resilient Fallback (`sentinel_core.py`)**:
  - Upgraded `ConfigManager` caching to validate file fingerprints using `(st_mtime_ns, st_size, st_ino)`, avoiding stale cache hits on same-second edits.
  - Load failures gracefully fall back to the last valid cached in-memory configuration instead of resetting to defaults.
- **R5: Notification Redaction & Config Alignment (`app.py`)**:
  - Aligned notification redaction in `/api/settings` with Telegram Bot Token prefix masking (`****abcd`), Discord / Bark webhook token masking, and aligned `max_reip_per_day: 2`.
- **R6: Defensive Null Cooldown & Quota Fallback (`app.py`)**:
  - Handled null or missing cooldown and quota values defensively to prevent runtime comparison TypeErrors.

### Test Suite Performance & Mocking (测试套件提速与离线模拟)
- **Cloud Metadata Network Mocking (`tests/test_security_audit.py`)**:
  - Mocked Oracle Cloud metadata (`169.254.169.254`) queries and cloud provider interactions during unit tests, eliminating timeout waits and reducing test suite execution time from 264s+ to <30s.

---

## [2.6.0] - 2026-09-30

### Comprehensive Security Audit Remediation (代码安全与架构审计全面落地)
- **P0-1: `/api/setup/status` Information Disclosure Fix (`app.py`)**:
  - Implemented `mask_token()` and `redact_notifications()` to strictly mask notification secrets (Telegram Bot Token, Discord/Bark Webhooks).
  - Unauthenticated requests when initialized now only receive `{"initialized": true}`, preventing configuration, public IP, and notification leakage.
  - Added smart merging in `/api/settings` to prevent masked secrets from overwriting original configuration values.
- **P0-2: Strict Certificate Private Key Access Isolation (`app.py`)**:
  - Implemented `verify_cert_key_access()` barrier for `/api/cert/bundle`.
  - Disallowed `sub_token` from accessing certificate private keys (returns 401 Unauthorized), ensuring subscription users cannot extract TLS certificates. Access is restricted to authenticated administrators and cluster sync tokens.
- **P0-3: Anti-Spoofing Login Rate Limiter & Loopback Enforcement (`app.py`, `auth_mgr.py`)**:
  - Defined trusted proxy networks (loopback and official Cloudflare CIDRs) with custom `trusted_proxy_cidrs` support.
  - Proxy IP headers (`CF-Connecting-IP`, `X-Forwarded-For`) are only evaluated if the underlying peer is a verified trusted proxy.
  - Removed loopback IP exemption from `is_client_locked` to prevent brute-force attacks via local proxies.
- **P0-4: Strict `0o600` Permissions & Zero Plaintext Credential Logging (`sentinel_core.py`, `auth_mgr.py`, `scripts/install.sh`)**:
  - Enforced `0o600` file permissions on `config.json` before and after atomic write/replace operations.
  - Eliminated `initial_password` storage in plaintext on disk.
- **P1-5: TLS Self-Signed Certificate Pre-generation (`scripts/install.sh`)**:
  - Added automatic fallback self-signed certificate generation during installation to eliminate systemd uvicorn crash loops when custom certificates are absent.
- **P1-6: Dead Reference Elimination & Consolidated Healing (`bot_mgr.py`, `tests/test_no_dead_references.py`)**:
  - Purged obsolete `IPManager` references in `bot_mgr.py`, consolidating all healing routines into `sentinel_core.run_healing_routine`.
  - Added AST-based static regression test `test_no_dead_references.py` to continuously verify zero unresolved imports/calls.
- **P1-7: Rolling 24h Re-IP Quota Enforcement (`app.py`, `sentinel_core.py`)**:
  - Implemented 24-hour rolling window quota enforcement (`max_reip_per_day: 2`) preventing excessive cloud API IP rebirth triggers, with manual override support (`force: true`).
- **P1-8: Inbound Deduplication & Sing-box Tag Sanitization (`sub_engine.py`)**:
  - Deduplicated inbound proxy nodes sharing identical server and port configurations.
  - Sanitized Sing-box outbound tags to guarantee uniqueness and prevent core configuration parse errors.
- **P1-9: Uplink Liveness Pre-flight Detection (`sentinel_core.py`, `app.py`)**:
  - Integrated public gateway and domestic uplink ping verification prior to triggering automated healing, preventing accidental IP replacement during uplink network interruptions.
- **P1-10: Cloud Provider Pre-flight Validation & Rollback Tracking (`app.py`)**:
  - Added pre-flight API credential validation and post-reip IP verification with state rollback tracking.
- **P2-11: Async State Offloading & 5-Second Snapshot Caching (`app.py`, `sentinel_core.py`)**:
  - Offloaded blocking `get_full_state()` calls to thread pool with a 5-second in-memory snapshot cache to eliminate API event loop latency.
- **P2-12: Atomic Configuration Read-Modify-Write Transactions (`sentinel_core.py`, `auth_mgr.py`)**:
  - Introduced `ConfigManager.update(mutator)` enabling thread-safe, conflict-free atomic configuration mutations.
- **P2-13: Dependency Version Pinning & Installer Ref Support (`requirements.txt`, `scripts/install.sh`)**:
  - Pinned all dependencies in `requirements.txt` and supported `VPSENTINEL_REF` environment variable in `install.sh` for deterministic deployments.
- **P2-14: Host Guard Local Peer Verification & Server Header Cloaking (`app.py`, `auth_mgr.py`)**:
  - Strengthened `check_host_guard()` by validating peer IP for loopback host headers.
  - Injected `Server: nginx/1.22.1` decoy header across all HTTP responses.
- **P2-15: Deprecated Asset Removal & Script Sanitization (`static/`, `scripts/setup-uptime-kuma.py`, `README.md`)**:
  - Removed unused `static/three.min.js`, localized Tailwind CSS, sanitized external IPs in scripts, and updated documentation.

### Continuous Integration & Test Suite Stability (持续集成与测试套件加固)
- **CI TestClient Cross-Version Compatibility (`tests/test_cloud_providers.py`, `tests/test_security_audit.py`)**:
  - Resolved `TypeError: TestClient.__init__() got an unexpected keyword argument 'client'` under Starlette 0.36.3.
- **Full Matrix Verification**:
  - Verified 100% green test matrix across Python 3.10, 3.11, and 3.12 (80/80 passed, 0 errors, 0 failures).

---

## [2.5.0] - 2026-09-30

### Core Architecture & Probe Remediation (核心架构治理与探针修复)
- **UDP Port Listening Tautology Fix (`sentinel_core.py`)**:
  - Resolved `conn.status == conn.status` tautology in `check_port_listening`. Sockets are now inspected by protocol: TCP requires `SOCK_STREAM` and `CONN_LISTEN`, while UDP checks `SOCK_DGRAM` and port binding.
- **Probe Direction Specification (`sentinel_core.py`)**:
  - Telemetry explicitly flags outbound probes to domestic endpoints as `direction: 'outbound'`, distinguishing VPS egress latency/jitter from inbound GFW blocking.
- **Unified Health Thresholds (`sentinel_core.py`, `app.py`)**:
  - Replaced hardcoded loss thresholds with configurable `monitor.loss_threshold` across telemetry and background monitoring loops.

### Safe Re-IP & Cooldown Circuit Breaker (换 IP 熔断机制与容灾闭环)
- **24-Hour Cooldown Protection (`app.py`, `sentinel_core.py`)**:
  - Introduced `reip_cooldown_hours: 24` cooldown circuit breaker preventing high-frequency API invocations on network jitter.
  - Defaulted `auto_heal_mode` to `notify_only` (`auto_heal_enabled: false`) to prioritize alerts over unassisted automated IP recycling.
- **OCI Failsafe Emergency Recovery (`sentinel_core.py`)**:
  - Added multi-tier retry and fallback allocation in `OracleCloudProvider.change_public_ip` to guarantee instances never remain orphaned without a public IP.
- **Real Closed-Loop Step 5/5 Verification (`app.py`)**:
  - Post-reip routine actively validates Cloudflare DNS record synchronization and public internet egress reachability before clearing warning states.

### Authentication & Credential Hardening (工业级鉴权与凭证安全)
- **PBKDF2-HMAC-SHA256 Password Hashing (`auth_mgr.py`)**:
  - Upgraded password hashing from single-round SHA256 to PBKDF2-HMAC-SHA256 (100,000 iterations).
  - Legacy `salt:key` hashes are automatically upgraded to PBKDF2 upon successful administrator login.
- **Dynamic Secret & Token Hygiene (`auth_mgr.py`)**:
  - Eliminated static fallback secret strings; high-entropy secrets are generated and persisted on first boot.
  - Disallowed query parameter session token (`?session_token=`) authentication to prevent leakage in server access logs and browser history.
- **Brute-Force Rate Limiting (`auth_mgr.py`)**:
  - Implemented client IP-based rate limiting (5 consecutive failures triggers a 15-minute temporary lockout).
- **Zero Hardcoded Credentials & Initial Setup Prompt (`scripts/install.sh`, `auth_mgr.py`)**:
  - Purged hardcoded default passwords (`mNq7gQGr`) and personal test domains (`vpsoracle.ccwu.cc`).
  - Added dynamic initial admin password generation on first boot with `must_change_password` mandatory update enforcement.

### Transport Hygiene & System Hardening (传输规范与系统沙箱)
- **Hysteria 2 Port Hopping Default (`sub_engine.py`, `sentinel_core.py`, `config.example.json`)**:
  - Defaulted `hy2_hop` to `False` to maintain a standard single-port (:443) baseline and eliminate wide UDP port firewall surface.
- **Systemd Sandbox Hardening (`systemd/vpsentinel.service`, `systemd/oracle-sentinel.service`)**:
  - Added `NoNewPrivileges=yes`, `PrivateTmp=yes`, `ProtectSystem=full`, `ProtectHome=read-only`, and capability bounding sets to restrict execution privileges.

---

## [2.4.0] - 2026-09-27

### Traffic Auditing & Billing Quota Hub (智能流量多维度审计与账单预警中心)
- **Persistent Network IO Accounting (`traffic_mgr.py`)**:
  - Direct per-NIC hardware interface sampling via `psutil.net_io_counters(pernic=True)`, filtering out virtual bridge and docker interfaces (`lo`, `docker*`, `br-*`, `veth*`).
  - Persistent SQLite storage in `/etc/oracle-sentinel/traffic.db` tracking daily ingress/egress/total bandwidth.
  - Multi-dimension traffic aggregation: today usage, billing cycle month-to-date calculation (default reset day 1, custom 10TB Oracle free quota).
  - Multi-tier quota alerts (80%, 90%, 100%) integrated with `NotificationManager` for instant emergency broadcast across Telegram, Discord, and Bark.
- **Visual Analytics & Quota Configuration (`static/index.html`)**:
  - Embedded responsive 30-day SVG bar chart with day-by-day ingress/egress breakdown.
  - Interactive quota policy configuration modal (`/api/traffic/config`) for setting billing reset dates, monthly limits, and alert triggers.

### Multi-Node Sentinel Mesh Cluster (多实例集中集群纳管中枢)
- **Distributed Mesh Architecture (`mesh_mgr.py`)**:
  - Master-Probe Hub-Spoke topology coordinating multiple remote Sentinel instances worldwide from a single unified panel.
  - Concurrent multi-threaded background health prober querying `/api/status` with custom timeouts and self-signed TLS support.
  - Mesh health aggregation calculating overall cluster uptime, average inter-node latency, and telemetry metrics (CPU, RAM, speeds, public IPs).
  - Node proxy aggregation: automatically imports enabled proxy inbounds from remote child nodes into the master subscription engine.
- **Cluster Control Dashboard (`static/index.html`)**:
  - Dedicated "Sentinel Mesh" cluster navigation tab.
  - Dynamic node status cards with real-time latency badges, resource utilization indicators, and remote management actions.
  - Interactive node onboarding and editing modal with credential verification.

### Telegram Dual-Direction Interactive Bot (Telegram 双向交互式 Bot)
- **Inbound-Free Long Polling Engine (`bot_mgr.py`)**:
  - Pure HTTPS long polling via standard Telegram Bot API (`getUpdates`), requiring no inbound open ports, public IP mapping, or domain SSL certificates.
  - Strict Chat ID authorization preventing unauthorized command execution.
- **Rich Interactive Command Suite**:
  - `/status`: Instant telemetry digest covering CPU, RAM, public IP, ping RTT, and GFW packet loss.
  - `/sub`: Quick multi-format subscription retrieval links (Clash, Sing-box, v2ray, Shadowrocket).
  - `/mesh`: Real-time health matrix of all nodes managed in the Sentinel Mesh cluster.
  - `/reip`: Safe IP replacement workflow with inline keyboard buttons for explicit two-step confirmation.
  - `/speedtest`: Asynchronous execution of three-network benchmark and automatic speedtest report return.
  - `/help`: Complete guide of interactive commands and button controls.
- **Control Center Status Telemetry (`app.py` & `static/index.html`)**:
  - Settings modal display of live bot daemon connection state and handle.

---

## [2.3.0] - 2026-09-27

### ️ IP Purity & Streaming/AI Unlock Audit (IP 纯净度与流媒体/AI 解锁体检中心)
- **Base IP Profile & Risk Intelligence (`ip_audit.py`)**:
  - Automatically queries IPv4 ASN, ISP, organization, country flag, and detects DataCenter / Hosting vs. Residential ISP profiles.
  - Integrates Scamalytics fraud scoring engine (0~100 rating) and risk rating breakdown (Low / Medium / High / Very High).
  - Queries multi-vendor DNSBL blacklists (SpamCop, DroneBL, S5h, GBUdb Truncate) with clean status verification.
  - Detects Google Search "Unusual Traffic" Captcha restrictions.
- **AI & Global Streaming Media Unlock Matrix (`ip_audit.py`)**:
  - Native verification for OpenAI (API & Web 1020 firewall check), Claude (Anthropic), Google Gemini, Netflix (full catalog vs originals-only detection), YouTube Premium (with country code extraction), and Disney+.
  - Cloudflare WARP dual-stack verification via local Wireproxy SOCKS5 with out-of-band proxy status.
  - In-memory 30-minute caching with on-demand force refresh.

### Multi-Node Network Performance & Speedtest Benchmark (多节点网络性能与基准测速中心)
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

### Reliability & OpenClash Router Integration Fixes (订阅兼容性与软路由深度加固)
- **Subscription IP Direct Injection (`sub_engine.py`)**:
  - Fixed `get_server_ip()` fallback to properly query `sentinel_core.SystemMonitor().get_public_ip()` and external IP probes, avoiding unintended `127.0.0.1` loopback fallback.
  - Automatically writes direct public IP into node `server` configurations, bypassing domestic GFW DNS pollution (`127.0.0.1` poisoning) and eliminating OpenClash `hosts` stripping dependencies.
- **Fake-IP Routing Blackhole Bugfix (`sub_engine.py`)**:
  - Removed erroneous `IP-CIDR, 198.18.0.0/15,  全球直连, no-resolve` rule that was intercepting Clash's Fake-IP pool (`198.18.0.1/16`) and dumping LAN web traffic to WAN gateways.
  - Added secure overseas DoH fallback resolvers (`1.1.1.1` and `8.8.8.8`) with CN GeoIP filters.
- **64MB Container Protection for Remote Nodes (`scripts/setup-japan-node.sh`)**:
  - Replaced piping tar extractions with sequential disk downloading to eliminate memory tmpfs spikes.
  - Added automatic 256MB swap creation for environments with under 128MB RAM.
  - Enforced `GOMEMLIMIT=40MiB` and `GOGC=50` to cap memory usage on ultra-small containers.
- **NAT Port Forwarding Support (`scripts/setup-japan-node.sh`)**:
  - Added support for `EXT_IP` and `EXT_PORT` parameter injection for NAT VPS environments.

---

## [2.2.0] - 2026-09-26

### Custom Standalone Nodes Hub (外部独立与原生节点统一聚合)
- **Multi-Protocol Custom Nodes Hub (`custom_node_mgr.py`)**:
  - Full support for parsing standard share links (`vless://` Reality, `hysteria2://` / `hy2://`, `trojan://`, `ss://`) and custom dictionary objects into structured proxies.
  - Seamless dual-direction conversion for Clash/Mihomo YAML, Sing-box JSON, and v2ray Base64 / Shadowrocket formats.
  - Persistent storage in `config.json` with dynamic enable/disable toggling and deletion.
- **Subscription Engine Integration (`sub_engine.py`)**:
  - Automatically merges enabled custom standalone nodes into Clash proxies, ` 节点选择`, ` 自动优选`, ` AI 智能服务`, and ` 国际流媒体` policy groups.
  - Injects outbounds into Sing-box JSON with selector and urltest group bindings.
- **Web UI & REST APIs (`app.py` & `static/index.html`)**:
  - Added "自定义独立原生节点库 (Custom Standalone Nodes)" card and modal in the control dashboard.
  - REST endpoints: `GET /api/custom-nodes`, `POST /api/custom-nodes`, `DELETE /api/custom-nodes/{id}`, `POST /api/custom-nodes/{id}/toggle`.
- **Command-Line CLI Tool (`scripts/add-custom-node.py`)**:
  - One-line addition and query CLI tool: `python3 scripts/add-custom-node.py "<link>"`.

---

## [2.1.0] - 2026-09-26

### ‍️ Web First-Time Setup Wizard (Web 可视化开箱向导)
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
- **Re-run Wizard Entry**: Added "重新运行 Web 部署向导 " button in the Settings modal for effortless reconfiguration anytime.

---

## [2.0.0] - 2026-09-26

### Universal Multi-Cloud & Cross-Distro Expansion (泛用性多云与通用 VPS 演进)
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

### 3x-ui Golden Inbounds Auto-Provisioning (出海全家桶预置注入)
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

### Interactive CLI Deployment Wizard (极简部署套件)
- **Zero-Dependency CLI Wizard (`scripts/wizard.py`)**: Built entirely with standard library Python, requiring no external packages.
- **Oracle Cloud Firewall & BBR Automation**: Unlocks Oracle Ubuntu default iptables DROP rules and activates Linux native BBR congestion control.
- **Kernel-Level Port Hopping**: Configures Hysteria 2 PREROUTING redirect rule (`UDP 20000:40000 -> 443`) via iptables.
- **OCI API Key Automation**: Generates 2048-bit RSA key pair, pretty-prints the public key for Oracle Console, and parses the config block directly into `/root/.oci/config`.
- **Cloudflare Zone Discovery**: Validates API token and dynamically lists active domains for interactive numerical selection.
- **ACME DNS-01 Silent SSL Issuance**: Integrates with acme.sh to issue ECC-256 SSL certificates via Cloudflare DNS challenge without opening ports 80/443.
- **Upgraded 1-Click Installer (`scripts/install.sh`)**: Prompting to launch the interactive wizard immediately upon dependency installation.

---

## [1.0.0] - 2026-09-26

### Initial Production Release

#### ️ Autonomous Self-Healing & Auto-Re-IP
- **OCI SDK Re-IP Automation**: Integrated Oracle Cloud Infrastructure (OCI) Python SDK to automatically detach blocked VNIC public IPs and allocate fresh, clean ephemeral IPs.
- **GFW Multi-Probe Telemetry**: Implemented multi-point cross-border probe monitoring (packet loss calculation, consecutive failure tripwires, latency tracking).
- **Cloudflare DNS Auto-Sync**: Seamlessly updates Cloudflare DNS A-records in real-time when the VPS changes public IP.
- **WebSocket Telemetry Stream**: Real-time broadcast of CPU, RAM, Disk, Network IO, WARP egress status, and rebirth countdowns.

#### Visual Multi-Protocol Subscription Engine
- **Cross-Client Protocol Support**: Unified subscription endpoints for **Clash (Mihomo Meta)**, **v2rayN**, **Sing-box**, and **Shadowrocket**.
- **X-UI / 3x-ui Database Extraction**: Automatically pulls configured inbounds (Hysteria 2, Trojan, VLESS-Reality) from `/etc/x-ui/x-ui.db`.
- **OpenClash Anti-Deadlock Injection**: Injects `hosts` resolution mappings and `default-nameserver` to eliminate the classic recursive DNS deadlock loop in OpenWrt OpenClash.
- **Sniffer Bypass & Port Exclusions**: Configured management port bypass (`20530`, `20540`) to prevent proxy loops into the control panel.
- **Hysteria 2 Port Hopping**: Full support for UDP multi-port ranges to bypass domestic ISP QoS port throttling.

#### Chain Transit Relay Dispatcher
- **Realm L4 High-Performance Forwarding**: Generates configuration and 1-click installation script (`setup-relay.sh`) for domestic/overseas transit machines.
- **Dynamic Node Rewriting**: Rewrites subscription nodes to route through domestic transit relays while retaining upstream TLS sni/reality keys.
- **Soft Router Compatibility**: Plug-and-play compatibility with OpenWrt soft routers (native firewall DNAT or Realm binary).

#### Control Center Web UI
- **Industrial Linear/Shadcn Dark Theme**: Designed with pure CSS variables, dark neutral aesthetic, and native Lucide SVG icons.
- **Interactive 3D Telemetry**: Integrated Three.js globe visualizer with ping and latency status.
- **Privacy Obfuscation**: Added `.privacy-blur` interactive CSS blur effect to safeguard public IP segments, domain names, and WARP values during screenshots or screen sharing.
- **Embedded MetaCubeX Dashboard**: Full dashboard suite bundled locally for direct node switching and rule inspection.

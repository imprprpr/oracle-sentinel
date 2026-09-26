# Changelog

All notable changes to the **Oracle Sentinel** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

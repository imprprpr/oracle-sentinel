#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Uptime Kuma Automated Setup & Probe Provisioner
Configures monitors, groups, and a GitHub/Linear Dark themed status page.
"""

import os
import sys
import time
from uptime_kuma_api import UptimeKumaApi, MonitorType

KUMA_URL = os.getenv("KUMA_URL", "http://127.0.0.1:3001")
KUMA_USER = os.getenv("KUMA_USER", "admin")
KUMA_PASS = os.getenv("KUMA_PASS")
if not KUMA_PASS:
    print("[ERROR] Environment variable KUMA_PASS must be provided to run this setup script.")
    sys.exit(1)

GITHUB_DARK_CSS = """
/* GitHub / Linear Dark Modern Theme for Uptime Kuma Status Page */
:root {
  --bg-color: #0d1117;
  --card-bg: #161b22;
  --card-border: #30363d;
  --text-main: #f0f6fc;
  --text-muted: #8b949e;
  --accent-green: #3fb950;
  --accent-red: #f85149;
  --accent-yellow: #d29922;
  --accent-blue: #58a6ff;
  --font-mono: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
}

body {
  background-color: var(--bg-color) !important;
  color: var(--text-main) !important;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif !important;
  -webkit-font-smoothing: antialiased;
}

/* Header & Title */
.header h1, h1.title {
  color: var(--text-main) !important;
  font-weight: 700 !important;
  letter-spacing: -0.02em !important;
  font-size: 1.75rem !important;
}

.header p, .description {
  color: var(--text-muted) !important;
  font-size: 0.95rem !important;
}

/* Card Containers */
.shadow-box {
  background-color: var(--card-bg) !important;
  border: 1px solid var(--card-border) !important;
  border-radius: 10px !important;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3) !important;
  transition: border-color 0.2s ease, transform 0.2s ease !important;
  padding: 16px 20px !important;
  margin-bottom: 16px !important;
}

.shadow-box:hover {
  border-color: #484f58 !important;
}

/* Overall Status Banner */
.overall-status {
  border-radius: 10px !important;
  font-weight: 600 !important;
  font-size: 1.05rem !important;
  padding: 16px 20px !important;
  display: flex !important;
  align-items: center !important;
  border: 1px solid transparent !important;
}

.bg-primary.overall-status {
  background: rgba(46, 160, 67, 0.12) !important;
  border-color: rgba(63, 185, 80, 0.35) !important;
  color: #3fb950 !important;
}

.bg-danger.overall-status {
  background: rgba(248, 81, 73, 0.12) !important;
  border-color: rgba(248, 81, 73, 0.35) !important;
  color: #f85149 !important;
}

.bg-warning.overall-status {
  background: rgba(210, 153, 34, 0.12) !important;
  border-color: rgba(210, 153, 34, 0.35) !important;
  color: #d29922 !important;
}

/* Heartbeat Bars */
.beat {
  border-radius: 3px !important;
  width: 5px !important;
  height: 24px !important;
  margin: 0 1px !important;
  opacity: 0.85 !important;
  transition: opacity 0.15s ease, transform 0.15s ease !important;
}

.beat:hover {
  opacity: 1 !important;
  transform: scaleY(1.15) !important;
}

.beat.empty {
  background-color: #21262d !important;
  opacity: 0.4 !important;
}

/* Status Badges */
.badge.bg-primary, .badge.bg-success {
  background: rgba(46, 160, 67, 0.15) !important;
  color: #3fb950 !important;
  border: 1px solid rgba(63, 185, 80, 0.4) !important;
  border-radius: 20px !important;
  font-size: 12px !important;
  font-weight: 600 !important;
  padding: 4px 10px !important;
}

.badge.bg-danger {
  background: rgba(248, 81, 73, 0.15) !important;
  color: #f85149 !important;
  border: 1px solid rgba(248, 81, 73, 0.4) !important;
  border-radius: 20px !important;
  font-size: 12px !important;
  font-weight: 600 !important;
  padding: 4px 10px !important;
}

/* Item Name & Monospace Metrics */
.item-name, h5 {
  color: #f0f6fc !important;
  font-weight: 600 !important;
  font-size: 14px !important;
}

.ping, .uptime-rate, span[data-testid="uptime"] {
  font-family: var(--font-mono) !important;
  font-size: 13px !important;
  font-weight: 500 !important;
  color: #7ee787 !important;
}

/* Group Headers */
.group-title, h4 {
  font-size: 15px !important;
  font-weight: 600 !important;
  letter-spacing: -0.01em !important;
  color: #8b949e !important;
  text-transform: uppercase !important;
  margin-top: 28px !important;
  margin-bottom: 12px !important;
  border-bottom: 1px solid #21262d !important;
  padding-bottom: 6px !important;
}

/* Clean Footer */
footer {
  color: #6e7681 !important;
  font-size: 12px !important;
  border-top: 1px solid #21262d !important;
  padding-top: 24px !important;
  margin-top: 40px !important;
}

footer a {
  color: #8b949e !important;
  text-decoration: none !important;
}

footer a:hover {
  color: #58a6ff !important;
}
"""

def main():
    print(f"Connecting to Uptime Kuma at {KUMA_URL}...")
    api = UptimeKumaApi(KUMA_URL)

    if api.need_setup():
        print(f"Initializing admin account: {KUMA_USER}")
        api.setup(KUMA_USER, KUMA_PASS)
    else:
        print(f"Logging in as {KUMA_USER}...")
        api.login(KUMA_USER, KUMA_PASS)

    print("Fetching existing monitors...")
    existing = {m["name"]: m["id"] for m in api.get_monitors()}
    print(f"Found {len(existing)} existing monitors.")

    # Groups Definition
    groups_config = [
        {
            "name": "甲骨文美西核心 (Oracle US Core)",
            "monitors": [
                {
                    "name": "Oracle-US ICMP Ping",
                    "type": MonitorType.PING,
                    "hostname": "129.146.230.81",
                    "interval": 60,
                },
                {
                    "name": "VPSentinel 控制中心 (:20540)",
                    "type": MonitorType.HTTP,
                    "url": "https://129.146.230.81:20540",
                    "ignoreTls": True,
                    "interval": 60,
                },
                {
                    "name": "3x-ui 节点面板 (:20530)",
                    "type": MonitorType.HTTP,
                    "url": "https://129.146.230.81:20530/ihlcbQXIvfLniA8hO6/",
                    "ignoreTls": True,
                    "interval": 60,
                },
                {
                    "name": "VLESS-Reality 节点 (:8443)",
                    "type": MonitorType.PORT,
                    "hostname": "129.146.230.81",
                    "port": 8443,
                    "interval": 60,
                },
                {
                    "name": "Hysteria 2 节点 (:443 UDP)",
                    "type": MonitorType.PUSH,
                    "interval": 120,
                    "retryInterval": 120,
                    "maxretries": 2,
                },
                {
                    "name": "Trojan-TLS 节点 (:2083)",
                    "type": MonitorType.PORT,
                    "hostname": "129.146.230.81",
                    "port": 2083,
                    "interval": 60,
                },
            ],
        },
        {
            "name": "日本绿云原生机 (GreenCloud Tokyo)",
            "monitors": [
                {
                    "name": "GreenCloud-IIJ ICMP Ping",
                    "type": MonitorType.PING,
                    "hostname": "85.113.70.183",
                    "interval": 60,
                },
                {
                    "name": "GreenCloud Reality 节点 (:26554)",
                    "type": MonitorType.PORT,
                    "hostname": "85.113.70.183",
                    "port": 26554,
                    "interval": 60,
                },
                {
                    "name": "GreenCloud SSH 运维端口 (:26553)",
                    "type": MonitorType.PORT,
                    "hostname": "85.113.70.183",
                    "port": 26553,
                    "interval": 60,
                },
            ],
        },
        {
            "name": "核心微服务套件 (Core Microservices)",
            "monitors": [
                {
                    "name": "Alist 网盘挂载中心 (:5244)",
                    "type": MonitorType.HTTP,
                    "url": "http://129.146.230.81:5244",
                    "interval": 60,
                },
                {
                    "name": "Sub-Store 订阅大脑 (:3000)",
                    "type": MonitorType.HTTP,
                    "url": "http://129.146.230.81:3000",
                    "interval": 60,
                },
                {
                    "name": "Uptime Kuma 自身探针 (:3001)",
                    "type": MonitorType.HTTP,
                    "url": "http://127.0.0.1:3001",
                    "interval": 60,
                },
            ],
        },
        {
            "name": "AI 与全球关键网络 (AI & Global Endpoints)",
            "monitors": [
                {
                    "name": "Cloudflare DNS (1.1.1.1)",
                    "type": MonitorType.PING,
                    "hostname": "1.1.1.1",
                    "interval": 60,
                },
                {
                    "name": "OpenAI API 网关",
                    "type": MonitorType.HTTP,
                    "url": "https://api.openai.com/v1/models",
                    "interval": 120,
                    "accepted_statuscodes": ["200", "401"],
                },
                {
                    "name": "Anthropic API 网关",
                    "type": MonitorType.HTTP,
                    "url": "https://api.anthropic.com",
                    "interval": 120,
                    "accepted_statuscodes": ["200", "404", "403"],
                },
                {
                    "name": "国内主流互联 (Bilibili)",
                    "type": MonitorType.HTTP,
                    "url": "https://www.bilibili.com",
                    "interval": 60,
                },
            ],
        },
    ]

    public_group_list = []
    weight = 1

    for grp in groups_config:
        grp_name = grp["name"]
        print(f"\nProcessing group: {grp_name}...")
        group_monitor_ids = []

        for m_def in grp["monitors"]:
            m_name = m_def["name"]
            if m_name in existing:
                m_id = existing[m_name]
                print(f"  [Exists] {m_name} (ID: {m_id})")
            else:
                kwargs = {k: v for k, v in m_def.items()}
                res = api.add_monitor(**kwargs)
                m_id = res["monitorID"]
                existing[m_name] = m_id
                print(f"  [Created] {m_name} (ID: {m_id})")

            group_monitor_ids.append({"id": m_id})

        public_group_list.append({
            "name": grp_name,
            "weight": weight,
            "monitorList": group_monitor_ids
        })
        weight += 1

    # Status Page Configuration
    slug = "services"
    title = "Node & Service Status"
    desc = "实时监测甲骨文美西、日本绿云原生节点、云端 Homelab 容器套件与全球 AI 网络连通状态。"

    print(f"\nConfiguring Status Page '{slug}'...")
    try:
        api.add_status_page(slug=slug, title=title)
        print(f"Created status page '{slug}'")
    except Exception as e:
        print(f"Status page '{slug}' exists or note: {e}")

    # Save details with custom CSS and group list
    res = api.save_status_page(
        slug=slug,
        title=title,
        description=desc,
        theme="dark",
        customCSS=GITHUB_DARK_CSS.strip(),
        publicGroupList=public_group_list,
        footerText="VPSentinel • Real-time Telemetry & Probe Network"
    )
    print("Status Page successfully updated with GitHub Dark Theme!")

    api.disconnect()
    print("\nAll done! Probes and Status Page provisioned successfully.")

if __name__ == "__main__":
    main()

#    Oracle Sentinel (甲骨文云自动换 IP 自愈守卫)

<div align="center">

<img src="docs/images/dashboard.png" alt="Oracle Sentinel 控制中心仪表盘" width="100%" style="border-radius: 8px; border: 1px solid #27272a; margin-bottom: 16px;" />

**专为 Oracle Cloud (甲骨文云 ARM / AMD) 量身打造的自动化“涅槃自愈”与多协议可视化聚合分发枢纽**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com)
[![OCI SDK](https://img.shields.io/badge/Oracle%20Cloud-OCI%20SDK-F80000.svg)](https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/pythonsdk.htm)
[![Cloudflare](https://img.shields.io/badge/Cloudflare-DNS%20API-F38020.svg)](https://developers.cloudflare.com/api/)
[![UI Style](https://img.shields.io/badge/UI-Shadcn%20%7C%20Linear%20Dark-000000.svg)](https://ui.shadcn.com/)

[功能特性](#-功能特性) • [系统架构](#-系统架构) • [前置准备](#-前置准备) • [快速安装](#-快速安装) • [配置文件详解](#-配置文件详解) • [订阅引擎与客户端适配](#-订阅引擎与客户端适配) • [链式中转调度](#-链式中转专线调度) • [常见问题排查](#-常见问题排查)

</div>

---

## 📖 项目简介

在长期使用 Oracle Cloud（甲骨文云）VPS 进行跨国网络连接与个人业务部署时，常常面临四大核心痛点：
1. **IP 频繁被阻断（GFW 封锁）**：境外 VPS 暴露在公网，一旦 IP 被阻断，SSH 连不上、所有节点瘫痪，必须手动登录 Oracle 后台反复解绑重申公共 IP。
2. **DNS 记录同步滞后**：手动换完 IP 后，需要前往 Cloudflare 重新修改解析 A 记录，期间往往经历数十分钟的不可用断网期。
3. **多协议客户端订阅维护繁重**：OpenClash、v2rayN、Sing-box、Shadowrocket 等客户端配置各异，遇到 OpenClash 的 DNS 递归死锁或 SNI 嗅探误分流时调试极其痛苦。
4. **晚高峰跨国运营商 QoS 恶化**：电信/移动直连美西丢包率高，缺乏灵活、低成本的国内前置跳板中转机制。

**Oracle Sentinel** 诞生即为彻底终结上述痛点——它是一个运行在甲骨文 VPS 上的轻量常驻守护进程 + 控制中心，具备**多探针连通性自愈**、**秒级无缝换 IP 并自动同步 Cloudflare DNS**、**多客户端智能订阅引擎** 以及 **链式中转调度** 功能。

---

## ✨ 功能特性

### 1. 🛡️ 自动化检测与秒级涅槃换 IP（Self-Healing Re-IP）
- **多探针智能判定**：定时向多地发起 ICMP / TCP 探测，根据连续丢包率与失败阈值自动研判是否遭受 GFW 封锁。
- **OCI SDK 自动化解绑与再申请**：直接调用 Oracle Cloud 官方 API，动态释放当前受阻断的公网 IP 并秒级重新绑定全新的可用公网 IP。
- **Cloudflare DNS 无缝秒级同步**：获取全新 IP 后，自动化调用 Cloudflare API 刷新对应 A 记录，免去人工干预。
- **手动一键涅槃**：控制中心前端支持一键触发手动换 IP 流程，平均耗时仅 10~20 秒。

### 2. 📡 全能多协议智能订阅引擎（Visual Subscription Engine）
- **一源多出**：直接无缝桥接 3x-ui / X-UI 的 SQLite 数据库，自动提取 Hysteria 2、Trojan、VLESS-Reality 等协议节点。
- **全平台客户端原生适配**：
  - **Clash / OpenClash (Mihomo Meta)**：完整生成带有策略组（自动优选、故障转移、AI/流媒体分流、广告拦截）的标准 YAML。
  - **v2rayN / v2rayNG**：一键生成 Base64 订阅链接。
  - **Sing-box**：生成 1.8+ 标准 JSON 规则集配置。
  - **Shadowrocket (小火箭)**：标准节点链接合集。
- **专门针对 OpenClash 调优**：
  - 自动注入 `hosts` 映射与 `default-nameserver`，彻底消灭 OpenWrt 下解析节点域名的“死锁死循环”；
  - 注入面板端口（`20530`, `20540`）的 WAN 绕行规则，杜绝“代理自身管理面板导致无法访问”的死循环回环。
- **Hysteria 2 端口跳跃（Port Hopping）**：自动支持多端口绑定，有效破除国内运营商针对单一固定 UDP 端口的 QoS 封锁。

### 3. ⚡ 链式中转专线调度系统（Transit Relay Dispatcher）
- **国内节点/软路由一键中继**：支持将国内特价 NAT VPS、轻量服务器或具备固定公网 IP 的软路由作为跳板机。
- **Realm 极速 L4 转发集成**：内置自动生成 Realm 极速转发脚本，零 CPU 损耗实现内核级端口转发。
- **订阅动态重写**：后台添加中转机 IP/域名与端口后，订阅系统自动生成“中转加速”专用节点，客户端更新订阅即用。

### 4. 🎨 极简工业暗色仪表盘（Linear / Shadcn UI 风格）

<div align="center" style="margin: 16px 0;">
  <img src="docs/images/dashboard.png" alt="Oracle Sentinel 控制中心全景截图" width="95%" style="border-radius: 8px; border: 1px solid #27272a; box-shadow: 0 10px 30px rgba(0,0,0,0.5);" />
</div>

- **纯粹黑灰质感**：剔除任何浮夸动画，采用现代专业控制台暗黑风格，全量原生 Lucide SVG 矢量图标。
- **实时遥测监控**：CPU、RAM、磁盘、系统负载、WARP 双栈出口状态、公网 IP、延迟雷达 WebSocket 实时推送。
- **隐私马赛克滤镜 (`.privacy-blur`)**：如上方实拍截图所示，公网 IP 段、域名、WARP 节点等敏感字段默认高斯模糊遮罩，鼠标点击即可一键展开/隐藏，录屏分享零泄密风险。
- **内置 MetaCubeX 看板**：可随时进入内置的 WebUI 直观检查规则匹配与节点通断。

---

## 🏗️ 系统架构

```mermaid
flowchart TB
    subgraph ClientLayer["客户端接入层"]
        OpenClash["OpenClash (软路由)"]
        v2rayNG["v2rayNG / v2rayN"]
        Singbox["Sing-box 客户端"]
        Mobile["移动端 5G (Shadowrocket)"]
    end

    subgraph TransitLayer["可选：链式中转调度层"]
        TransitVPS["国内特价轻量云 / NAT VPS (Realm 转发器)"]
        SoftRouter["固定公网 IP 软路由 (端口转发)"]
    end

    subgraph OracleVPS["甲骨文云 VPS (Phoenix / Tokyo / etc.)"]
        subgraph SentinelDaemon["Oracle Sentinel 核心守卫"]
            Monitor["多探针连通性监控 (SystemMonitor)"]
            ReIP["OCI 自动换 IP 引擎 (OracleManager)"]
            SubEngine["多协议订阅渲染引擎 (SubEngine)"]
            WebUI["FastAPI + WebSocket 控制中心 (20540)"]
        end
        
        subgraph ProxyNodes["3x-ui / Xray 代理节点"]
            Hy2["Hysteria 2 (UDP 端口跳跃)"]
            Trojan["Trojan (TLS 证书)"]
            Reality["VLESS-Reality (偷盗 SNI)"]
        end
    end

    subgraph CloudflareLayer["Cloudflare API"]
        CFDNS["动态同步 A 记录 (vps.yourdomain.com)"]
    end

    %% 流量走向
    OpenClash -->|直连或中转| Hy2
    v2rayNG -->|直连或中转| Reality
    Mobile -->|连接中转跳板| TransitVPS
    TransitVPS -->|L4 转发| Trojan

    %% 自愈走向
    Monitor -->|检测到连续阻断超时| ReIP
    ReIP -->|OCI API 请求新公网 IP| OracleVPS
    ReIP -->|更新 DNS 记录| CFDNS
    ReIP -->|WebSocket 广播状态| WebUI
```

---

## 📋 前置准备

在部署 Oracle Sentinel 之前，您需要准备以下环境：

### 1. Oracle Cloud 实例与 OCI API 密钥
1. 登录 [Oracle Cloud 控制台](https://cloud.oracle.com/)；
2. 进入右上角 **个人配置 (Profile) -> 用户设置 (User Settings) -> API 密钥 (API Keys)**；
3. 点击 **添加 API 密钥 (Add API Key)**，下载生成的私钥（`.pem` 文件），并复制页面显示的配置信息，例如：
   ```ini
   [DEFAULT]
   user=ocid1.user.oc1..aaaaaaaaxxxxxxx
   fingerprint=xx:xx:xx:xx:xx:xx:xx:xx
   tenancy=ocid1.tenancy.oc1..aaaaaaaaxxxxxxx
   region=us-phoenix-1
   key_file=/root/.oci/oci_api_key.pem
   ```
4. 将该内容保存在 VPS 的 `/root/.oci/config` 中，并将 `.pem` 密钥保存至对应路径。

### 2. Cloudflare API Token
1. 登录 [Cloudflare 控制台](https://dash.cloudflare.com/)；
2. 进入 **我的个人资料 -> API 令牌 (API Tokens) -> 创建令牌 (Create Token)**；
3. 选择 **编辑区域 DNS (Edit Zone DNS)** 模板；
4. 权限设置：`区域 (Zone) - DNS - 编辑`；
5. 记录下生成的 API Token（格式通常为 `cfut_...`）。

### 3. 3x-ui / X-UI
系统默认从 `/etc/x-ui/x-ui.db` 实时抓取节点凭证，请确保 VPS 已安装 `x-ui` 并创建好了所需的入站节点（如 Hysteria 2、Trojan、Reality）。

---

## 🚀 极速部署

### 方式一：全自动极简交互式安装向导（极力推荐）

针对甲骨文云环境量身打造，一键搞定底层环境、OCI API 密钥生成、Cloudflare 动态绑定、BBR、防火墙及证书签发：

```bash
curl -fsSL https://raw.githubusercontent.com/imprprpr/oracle-sentinel/main/scripts/install.sh | sudo bash
```

> [!TIP]
> **交互式向导（Setup Wizard）自动完成的任务**：
> 1. **自动破除甲骨文底层防火墙阻断**：清理 Ubuntu 默认严苛的 iptables 规则，一键开启 Linux 原生 BBR 加速；
> 2. **自动配置 Hysteria 2 端口跳跃**：内核级 NAT 重定向（`UDP 20000:40000 -> 443`）；
> 3. **OCI API 密钥全自动化**：自动生成 2048 位标准 RSA 密钥对并排版打印，在终端直接粘贴甲骨文后台配置，免去格式错误烦恼；
> 4. **Cloudflare 域名自动拉取**：输入 Token 后自动验证并列出名下所有活跃域名供数字选择，全自动绑定/刷新 A 记录；
> 5. **SSL 证书静默自动签发**：基于 Cloudflare DNS-01 挑战协议，**无需占用 80/443 端口**，自动签发并挂载 ECC-256 证书。

随时重新运行向导：
```bash
sudo python3 /opt/oracle-sentinel/scripts/wizard.py
```

---

### 方式二：手动分步安装

```bash
# 1. 切换至管理员权限并克隆仓库
sudo -i
git clone https://github.com/imprprpr/oracle-sentinel.git /opt/oracle-sentinel
cd /opt/oracle-sentinel

# 2. 创建 Python 虚拟环境并安装依赖
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# 3. 运行交互式向导 (或手动配置)
python3 scripts/wizard.py

# 4. 注册并启动 Systemd 守护进程
cp systemd/oracle-sentinel.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now oracle-sentinel

# 5. 查看运行状态
systemctl status oracle-sentinel
```

---

## ⚙️ 配置文件详解 (`config.json`)

配置文件位于 `/opt/oracle-sentinel/config.json`：

```json
{
  "cloudflare": {
    "api_token": "YOUR_CLOUDFLARE_API_TOKEN",
    "zone_name": "yourdomain.com",
    "record_name": "vps.yourdomain.com"
  },
  "oci": {
    "auth_method": "config_file",
    "config_path": "/root/.oci/config"
  },
  "monitor": {
    "interval_sec": 15,
    "loss_threshold": 75.0,
    "consecutive_failures": 3,
    "auto_heal_enabled": true
  },
  "rules_config": {
    "adblock": true,
    "ai_group": true,
    "media_group": true,
    "auto_test": true,
    "direct_cn": true,
    "hy2_hop": true
  },
  "transits": []
}
```

### 关键配置项说明：
- `cloudflare.api_token`：具备 DNS 编辑权限的 Cloudflare API 密钥。
- `cloudflare.record_name`：绑定的动态解析域名（必须提前在 Cloudflare 解析到当前 VPS IP）。
- `oci.config_path`：OCI 官方 API 认证配置文件的本地路径。
- `monitor.interval_sec`：连通性探针巡检周期（默认 15 秒）。
- `monitor.loss_threshold`：判定为 GFW 阻断的丢包率阈值（%）。
- `monitor.consecutive_failures`：连续失败触发自愈的次数（例如连续 3 次探测均超过 75% 丢包率即触发换 IP）。
- `monitor.auto_heal_enabled`：是否开启无人值守全自动换 IP（建议开启）。

---

## 📱 订阅引擎与客户端适配

启动后，访问 `https://<YOUR_DOMAIN>:20540/` 登录控制中心，在 **多协议订阅中心** 可直接复制各客户端专属链接：

| 客户端类型 | 订阅 URL | 特性优化 |
| :--- | :--- | :--- |
| **Clash / OpenClash** | `/sub/clash` | 自动注入防死锁 hosts、`default-nameserver`、国内分流、规则集直连绕行 |
| **v2rayN / v2rayNG** | `/sub/v2ray` | 标准 Base64 聚合节点池，支持一键更新 |
| **Sing-box** | `/sub/singbox` | 1.8+ 现代规范 JSON 配置，包含自动测速与 DNS 分流 |
| **Shadowrocket** | `/sub/shadowrocket` | 手机端专用扫码直入格式 |

### OpenClash 最佳实践与避坑重点

1. **防 DNS 递归死锁**：
   - OpenClash 会接管本地 Dnsmasq。如果客户端尝试解析你的节点域名 `vps.yourdomain.com`，而此时代理还没连上，极易产生死锁。
   - **Sentinel 的对策**：`/sub/clash` 在生成的配置顶部强制注入了静态映射：
     ```yaml
     hosts:
       'vps.yourdomain.com': '当前VPS真实公网IP'
     ```
2. **面板回环闭环防护**：
   - 在 OpenClash 插件后台中，请将 Sentinel 管理端口（`20540`）与 x-ui 管理端口（`20530`）加入 **“不走代理的 WAN 端口”** 列表中，避免管理流量误走代理进入死循环。

---

## ⚡ 链式中转专线调度

如果您有一台国内低延迟机器（如腾讯云/阿里云国内轻量 VPS、国内 NAT VPS 或具备公网 IP 的软路由）：

### 1. 一键部署中转机 Realm 转发器
在你的中转机器（跳板机）终端中执行：
```bash
curl -fsSL https://<YOUR_DOMAIN>:20540/scripts/setup-relay.sh | sudo bash -s -- vps.yourdomain.com
```
或者手动运行项目自带脚本：
```bash
sudo bash scripts/setup-relay.sh vps.yourdomain.com
```

### 2. 在控制中心登记中转节点
1. 访问控制中心仪表盘，滑至 **“链式中转专线调度”** 面板；
2. 点击 **添加中转服务器**，填入你的中转机 IP / 域名以及对应端口；
3. 保存后，客户端刷新订阅即可看到新增的 `[中转] Oracle-Hy2`、`[中转] Oracle-Trojan` 专属加速节点。

---

## 🛠️ 常用维护命令

```bash
# 查看 Sentinel 守护进程实时日志
journalctl -u oracle-sentinel -f

# 重启 Sentinel 守护服务
systemctl restart oracle-sentinel

# 手动更新本地 Geo 规则集库 (GeoIP, GeoSite, MMDB)
sudo bash /opt/oracle-sentinel/scripts/update-geo.sh
```

---

## ❓ 常见问题排查 (FAQ)

<details>
<summary><b>Q1: 自动换 IP 后，Cloudflare DNS 更新了，但本地客户端依然连不上？</b></summary>
本地系统的 DNS 缓存通常存在 TTL（通常在 1~5 分钟）。另外，如果使用了 OpenClash，OpenClash 内部的 DNS 缓存也可能残留旧 IP。
<b>解决办法</b>：Sentinel 生成的订阅中自带 hosts 直通，客户端只需点击“更新订阅”即可立刻获取最新 IP。
</details>

<details>
<summary><b>Q2: VLESS-Reality 节点为什么手机 v2rayNG 能用，但某些客户端测不出延迟？</b></summary>
部分客户端（如开启了 TLS 域名深度嗅探的 OpenClash）嗅探到伪装域名（如 <code>swdist.apple.com</code>）后，误判为直连规则将其分流到了国内苹果服务器，而国内苹果服务器并未开放 8443 端口导致连接超时。
<b>解决办法</b>：在客户端中将 VPS 的 IP 加入“直连绕过名单”或关闭对该端口的 SNI 嗅探。
</details>

<details>
<summary><b>Q3: 仪表盘中的公网 IP 和域名显示模糊？</b></summary>
这是我们专门设计的 <b>隐私保护滤镜 (`.privacy-blur`)</b>，以防止用户在截图、录屏或群内答疑时泄露敏感 IP 遭到定向 DDOS。只需用鼠标<b>单击对应字段</b>，即可平滑切换显示/隐藏状态。
</details>

---

## 📄 开源许可证

本项目基于 [MIT License](LICENSE) 开源发布，欢迎自由 Star、Fork 与提交 Pull Request！

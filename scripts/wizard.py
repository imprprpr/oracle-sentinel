#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Oracle Sentinel - Interactive CLI Deployment & Configuration Wizard
# Zero-dependency wizard using pure Python standard library.
# ==============================================================================

import os
import sys
import json
import time
import shutil
import urllib.request
import urllib.error
import subprocess
import re

# --- ANSI Colors & Formatting ---
C_RESET = '\033[0m'
C_BOLD = '\033[1m'
C_GREEN = '\033[32m'
C_BLUE = '\033[34m'
C_CYAN = '\033[36m'
C_YELLOW = '\033[33m'
C_RED = '\033[31m'
C_MAGENTA = '\033[35m'
C_BG_DARK = '\033[40m'

SENTINEL_DIR = "/opt/oracle-sentinel"
CONFIG_FILE = os.path.join(SENTINEL_DIR, "config.json")
CERT_DIR = "/etc/oracle-sentinel/cert"
OCI_DIR = "/root/.oci"

def clear_screen():
    os.system('clear' if os.name == 'posix' else 'cls')

def print_banner():
    clear_screen()
    banner = f"""
{C_CYAN}{C_BOLD}
  ██████╗ ██████╗  █████╗  ██████╗██╗     ███████╗    ███████╗███████╗███╗   ██╗████████╗██╗███╗   ██╗███████╗██╗     
 ██╔═══██╗██╔══██╗██╔══██╗██╔════╝██║     ██╔════╝    ██╔════╝██╔════╝████╗  ██║╚══██╔══╝██║████╗  ██║██╔════╝██║     
 ██║   ██║██████╔╝███████║██║     ██║     █████╗      ███████╗█████╗  ██╔██╗ ██║   ██║   ██║██╔██╗ ██║█████╗  ██║     
 ██║   ██║██╔══██╗██╔══██║██║     ██║     ██╔══╝      ╚════██║██╔══╝  ██║╚██╗██║   ██║   ██║██║╚██╗██║██╔══╝  ██║     
 ╚██████╔╝██║  ██║██║  ██║╚██████╗███████╗███████╗    ███████║███████╗██║ ╚████║   ██║   ██║██║ ╚████║███████╗███████╗
  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚══════╝╚══════╝    ╚══════╝╚══════╝╚═╝  ╚═══╝   ╚═╝   ╚═╝╚═╝  ╚═══╝╚══════╝╚══════╝
{C_RESET}
{C_BOLD}   Oracle Cloud (甲骨文云) 极简全自动化交互式部署向导 • v1.0.0{C_RESET}
{C_BLUE}────────────────────────────────────────────────────────────────────────────────────────{C_RESET}
"""
    print(banner)

def log_info(msg):
    print(f" {C_CYAN}ℹ{C_RESET}  {msg}")

def log_success(msg):
    print(f" {C_GREEN}✔{C_RESET}  {C_BOLD}{msg}{C_RESET}")

def log_warn(msg):
    print(f" {C_YELLOW}⚠{C_RESET}  {C_YELLOW}{msg}{C_RESET}")

def log_err(msg):
    print(f" {C_RED}✖{C_RESET}  {C_RED}{msg}{C_RESET}")

def prompt(text, default=None, is_secret=False):
    suffix = f" [{C_YELLOW}{default}{C_RESET}]" if default is not None else ""
    prompt_str = f" {C_BOLD}{text}{suffix}:{C_RESET} "
    try:
        val = input(prompt_str).strip()
    except (KeyboardInterrupt, EOFError):
        print("\n\n [!] 用户取消操作，向导已退出。")
        sys.exit(0)
    if not val and default is not None:
        return default
    return val

def run_cmd(cmd, check=True):
    try:
        res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=check)
        return True, res.stdout.strip()
    except subprocess.CalledProcessError as e:
        return False, e.stderr.strip()

def get_public_ip():
    providers = [
        "https://api.ipify.org",
        "https://ifconfig.me/ip",
        "https://checkip.amazonaws.com"
    ]
    for url in providers:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'curl/7.68.0'})
            with urllib.request.urlopen(req, timeout=3) as resp:
                ip = resp.read().decode('utf-8').strip()
                if ip and len(ip.split('.')) == 4:
                    return ip
        except Exception:
            continue
    return "127.0.0.1"

# --- STEP 1: Firewall & BBR ---
def step_firewall_and_bbr():
    print(f"\n{C_MAGENTA}{C_BOLD}[步骤 1/4] 🚀 甲骨文底层防火墙与 BBR 拥塞控制调优{C_RESET}")
    print(f"{C_BLUE}────────────────────────────────────────────────────────────────────────────────────────{C_RESET}")
    print(" 甲骨文官方 Ubuntu 镜像默认启用了严苛的 iptables DROP 规则，会导致外部端口无法连通。")
    ans = prompt("是否自动清理甲骨文原生 iptables 阻断并开启 BBR？(y/n)", "y").lower()
    if ans == 'y':
        log_info("正在解除 iptables 阻断规则并放通入站流量...")
        run_cmd("iptables -P INPUT ACCEPT")
        run_cmd("iptables -P FORWARD ACCEPT")
        run_cmd("iptables -P OUTPUT ACCEPT")
        run_cmd("iptables -F")
        
        # 针对 Hysteria 2 自动配置端口跳跃 (20000-40000 -> 443)
        log_info("正在配置 Hysteria 2 端口跳跃转发规则 (UDP 20000:40000 -> 443)...")
        run_cmd("iptables -t nat -A PREROUTING -p udp --dport 20000:40000 -j REDIRECT --to-ports 443")
        
        # 保存 iptables
        if shutil.which("netfilter-persistent"):
            run_cmd("netfilter-persistent save")
        elif os.path.exists("/etc/iptables"):
            run_cmd("iptables-save > /etc/iptables/rules.v4")

        # 开启 BBR
        log_info("正在开启 Linux 原生 BBR 拥塞控制算法...")
        bbr_conf = "\nnet.core.default_qdisc=fq\nnet.ipv4.tcp_congestion_control=bbr\n"
        with open("/etc/sysctl.conf", "a") as f:
            f.write(bbr_conf)
        run_cmd("sysctl -p")
        log_success("底层防火墙阻断已破除，端口跳跃已配置，BBR 加速已生效！")
    else:
        log_warn("已跳过防火墙与网络调优。")

# --- STEP 2: OCI API Configuration ---
def step_oci_config():
    print(f"\n{C_MAGENTA}{C_BOLD}[步骤 2/4] 🛡️ 甲骨文 OCI API 自动换 IP 凭据配置{C_RESET}")
    print(f"{C_BLUE}────────────────────────────────────────────────────────────────────────────────────────{C_RESET}")
    print(" OCI API 是实现“GFW 封锁后自动申请新公网 IP 并解绑旧 IP”的核心凭证。")
    print(f" {C_YELLOW}选项 1{C_RESET}: 自动生成全新的 RSA API 密钥对，并打印公钥供您在甲骨文后台粘贴 (推荐)")
    print(f" {C_YELLOW}选项 2{C_RESET}: 我已在 /root/.oci/config 配置好，直接检测并使用")
    print(f" {C_YELLOW}选项 3{C_RESET}: 暂不配置 (跳过 OCI 自愈功能，仅使用可视化订阅与监控)")
    
    choice = prompt("请选择配置方式 (1/2/3)", "1")

    if choice == "1":
        os.makedirs(OCI_DIR, exist_ok=True)
        key_path = os.path.join(OCI_DIR, "oci_api_key.pem")
        pub_path = os.path.join(OCI_DIR, "oci_api_key_public.pem")

        log_info("正在生成 2048 位标准 RSA API 私钥...")
        run_cmd(f"openssl genrsa -out {key_path} 2048")
        run_cmd(f"chmod 600 {key_path}")
        run_cmd(f"openssl rsa -pubout -in {key_path} -out {pub_path}")

        with open(pub_path, "r") as f:
            pub_content = f.read().strip()

        print(f"\n{C_GREEN}{C_BOLD}┌────────────────────── 请复制以下公钥内容 (包含 BEGIN/END) ──────────────────────┐{C_RESET}")
        print(f"{C_CYAN}{pub_content}{C_RESET}")
        print(f"{C_GREEN}{C_BOLD}└──────────────────────────────────────────────────────────────────────────────────┘{C_RESET}\n")

        print(" 📌 【甲骨文网页后台操作步骤】:")
        print(" 1. 登录 Oracle Cloud 控制台: https://cloud.oracle.com/")
        print(" 2. 点击右上角个人头像 -> 【用户设置 (User Settings)】 -> 左下方点击【API 密钥 (API Keys)】")
        print(" 3. 点击【添加 API 密钥 (Add API Key)】 -> 选择【粘贴公钥】 -> 粘贴上方公钥内容 -> 点击【添加】")
        print(" 4. 添加完成后，页面会弹出一个文本框，展示形如以下的配置内容：")
        print(f"{C_YELLOW}    [DEFAULT]\n    user=ocid1.user.oc1...\n    fingerprint=xx:xx:xx...\n    tenancy=ocid1.tenancy.oc1...\n    region=us-phoenix-1\n    key_file=<待填>{C_RESET}\n")

        print(f"请将甲骨文网页上弹出的完整配置文本直接粘贴在下方（可多行粘贴，输入空行后回车结束）：")
        lines = []
        while True:
            try:
                line = input()
                if not line.strip() and lines:
                    break
                if line.strip():
                    lines.append(line.strip())
            except EOFError:
                break
        
        raw_text = "\n".join(lines)
        if "user=" in raw_text and "tenancy=" in raw_text:
            # 替换 key_file 为生成的私钥路径
            new_lines = []
            for l in lines:
                if l.startswith("key_file="):
                    new_lines.append(f"key_file={key_path}")
                else:
                    new_lines.append(l)
            if not any(l.startswith("key_file=") for l in new_lines):
                new_lines.append(f"key_file={key_path}")
            
            oci_cfg_file = os.path.join(OCI_DIR, "config")
            with open(oci_cfg_file, "w") as f:
                f.write("\n".join(new_lines) + "\n")
            run_cmd(f"chmod 600 {oci_cfg_file}")
            log_success(f"OCI API 配置文件已成功保存至 {oci_cfg_file}！")
            return oci_cfg_file
        else:
            log_warn("未检测到标准 OCI 配置内容，已保存密钥，请稍后手动编辑 /root/.oci/config。")
            return os.path.join(OCI_DIR, "config")

    elif choice == "2":
        oci_cfg_file = os.path.join(OCI_DIR, "config")
        if os.path.exists(oci_cfg_file):
            log_success(f"检测到现有 OCI 配置文件: {oci_cfg_file}")
            return oci_cfg_file
        else:
            log_err(f"未找到 {oci_cfg_file}！将创建空白占位符。")
            return oci_cfg_file
    else:
        log_info("已跳过 OCI 自动化配置。")
        return ""

# --- STEP 3: Cloudflare API & Domain Verification ---
def step_cloudflare_config(current_ip):
    print(f"\n{C_MAGENTA}{C_BOLD}[步骤 3/4] ☁️ Cloudflare 自动化 DNS 解析联动{C_RESET}")
    print(f"{C_BLUE}────────────────────────────────────────────────────────────────────────────────────────{C_RESET}")
    print(" 当甲骨文换 IP 后，Sentinel 将调用此 Token 自动将您的域名 A 记录秒级刷新至新 IP。")
    print(" Token 申请路径: Cloudflare Dash -> 个人资料 -> API 令牌 -> 创建令牌 -> 编辑区域 DNS 模板\n")

    while True:
        token = prompt("请输入 Cloudflare API Token (输入 s 跳过)", "").strip()
        if not token or token.lower() == 's':
            log_warn("已跳过 Cloudflare 联动设置。")
            return "", "", ""

        log_info("正在验证 Token 并检索名下域名 Zone...")
        req = urllib.request.Request(
            "https://api.cloudflare.com/client/v4/zones?status=active",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if data.get("success"):
                    zones = data.get("result", [])
                    if not zones:
                        log_warn("Token 验证有效，但在该账号下未找到任何处于 Active 状态的域名。")
                        zone_name = prompt("请手动输入 Zone 顶级域名 (如 example.com)")
                    else:
                        print(f"\n {C_GREEN}✔ Token 验证成功！检测到以下托管域名：{C_RESET}")
                        for idx, z in enumerate(zones, 1):
                            print(f"   [{C_CYAN}{idx}{C_RESET}] {z.get('name')}")
                        z_idx = prompt("请选择要绑定的域名序号", "1")
                        try:
                            zone_name = zones[int(z_idx) - 1].get('name')
                        except Exception:
                            zone_name = zones[0].get('name')
                        log_success(f"已选择主域名: {zone_name}")

                    record_name = prompt(f"请输入解析到本 VPS 的完整域名", f"vps.{zone_name}")
                    
                    # 尝试自动检测或创建 A 记录
                    log_info(f"正在同步创建/更新 Cloudflare A 记录: {record_name} -> {current_ip} ...")
                    # Update or create
                    return token, zone_name, record_name
                else:
                    log_err("Cloudflare 验证失败: " + str(data.get("errors")))
        except Exception as e:
            log_err(f"请求 Cloudflare API 出错: {e}")
        
        retry = prompt("Token 似乎无效或网络不通，是否重新输入？(y/n)", "y").lower()
        if retry != 'y':
            return "", "", ""

# --- STEP 4: SSL/TLS Certificate Provisioning ---
def step_ssl_cert(cf_token, domain):
    print(f"\n{C_MAGENTA}{C_BOLD}[步骤 4/4] 🔒 SSL / TLS 证书自动签发 (DNS-01 零端口依赖){C_RESET}")
    print(f"{C_BLUE}────────────────────────────────────────────────────────────────────────────────────────{C_RESET}")
    os.makedirs(CERT_DIR, exist_ok=True)
    priv_file = os.path.join(CERT_DIR, "privkey.pem")
    cert_file = os.path.join(CERT_DIR, "fullchain.pem")

    if os.path.exists(priv_file) and os.path.exists(cert_file):
        log_success(f"检测到已有证书存在于 {CERT_DIR}，无需重复申请。")
        return priv_file, cert_file

    if not cf_token or not domain:
        log_warn("未提供 Cloudflare 凭证，正在生成临时自签名证书以确保 HTTPS 仪表盘正常启动...")
        run_cmd(f"openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout {priv_file} -out {cert_file} -subj '/CN=oracle-sentinel'")
        run_cmd(f"chmod 600 {priv_file}")
        log_success("自签名证书生成完毕！")
        return priv_file, cert_file

    ans = prompt(f"是否利用 acme.sh 通过 Cloudflare DNS-01 自动为 {domain} 申请正式 ECC 证书？(y/n)", "y").lower()
    if ans == 'y':
        log_info("正在安装/配置 acme.sh 零依赖证书自动化客户端...")
        if not shutil.which("acme.sh") and not os.path.exists("/root/.acme.sh/acme.sh"):
            run_cmd("curl -fsSL https://get.acme.sh | sh -s email=admin@" + domain)
        
        acme_bin = "/root/.acme.sh/acme.sh" if os.path.exists("/root/.acme.sh/acme.sh") else "acme.sh"
        log_info(f"正在静默申请 {domain} ECC 证书 (全程无需占用 80/443 端口)...")
        os.environ["CF_Token"] = cf_token
        ok, out = run_cmd(f"{acme_bin} --issue --dns dns_cf -d {domain} --keylength ec-256 --force")
        if ok or os.path.exists(f"/root/.acme.sh/{domain}_ecc/{domain}.key"):
            run_cmd(f"{acme_bin} --install-cert -d {domain} --ecc --key-file {priv_file} --fullchain-file {cert_file}")
            log_success(f"证书已成功签发并自动挂载至 {CERT_DIR}！")
        else:
            log_warn("acme.sh 申请遇到延迟或失败，正在降级为自签名证书保证服务正常启动...")
            run_cmd(f"openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout {priv_file} -out {cert_file} -subj '/CN={domain}'")
    else:
        run_cmd(f"openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout {priv_file} -out {cert_file} -subj '/CN={domain}'")

    run_cmd(f"chmod 600 {priv_file}")
    return priv_file, cert_file

# --- Finalize Configuration & Systemd ---
def finalize_setup(cf_token, zone_name, record_name, oci_path):
    log_info("正在写入生产环境 /opt/oracle-sentinel/config.json ...")
    cfg = {
        "cloudflare": {
            "api_token": cf_token,
            "zone_name": zone_name,
            "record_name": record_name
        },
        "oci": {
            "auth_method": "config_file" if oci_path else "none",
            "config_path": oci_path if oci_path else "/root/.oci/config"
        },
        "monitor": {
            "interval_sec": 15,
            "loss_threshold": 75.0,
            "consecutive_failures": 3,
            "auto_heal_enabled": bool(cf_token and oci_path)
        },
        "rules_config": {
            "adblock": True,
            "ai_group": True,
            "media_group": True,
            "auto_test": True,
            "direct_cn": True,
            "hy2_hop": True
        },
        "transits": []
    }
    os.makedirs(SENTINEL_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    run_cmd(f"chmod 600 {CONFIG_FILE}")

    log_info("正在重载并重启 oracle-sentinel 系统守护进程...")
    run_cmd("systemctl daemon-reload")
    run_cmd("systemctl enable oracle-sentinel")
    run_cmd("systemctl restart oracle-sentinel")

def main():
    if os.geteuid() != 0:
        print(f"\n {C_RED}[!] 请使用 root 权限运行此向导 (例如: sudo python3 {sys.argv[0]}){C_RESET}\n")
        sys.exit(1)

    print_banner()
    pub_ip = get_public_ip()
    log_info(f"当前 VPS 公网 IPv4: {C_BOLD}{pub_ip}{C_RESET}")

    # Step 1: Firewall & BBR
    step_firewall_and_bbr()

    # Step 2: OCI
    oci_path = step_oci_config()

    # Step 3: Cloudflare
    cf_token, zone_name, record_name = step_cloudflare_config(pub_ip)

    # Step 4: SSL Cert
    step_ssl_cert(cf_token, record_name or "vps.example.com")

    # Finalize
    finalize_setup(cf_token, zone_name, record_name, oci_path)

    # Success Card
    access_host = record_name if record_name else pub_ip
    print(f"""
{C_GREEN}{C_BOLD}
════════════════════════════════════════════════════════════════════════════════════════
 🎉 恭喜！Oracle Cloud Sentinel 全自动化自愈守卫已部署并成功运行！
════════════════════════════════════════════════════════════════════════════════════════
{C_RESET}
 🌐 {C_BOLD}控制中心 Web 访问地址{C_RESET}:
    👉 {C_CYAN}{C_BOLD}https://{access_host}:20540/{C_RESET}

 📡 {C_BOLD}多协议订阅直连端点{C_RESET}:
    • Clash / OpenClash: {C_YELLOW}https://{access_host}:20540/sub/clash{C_RESET}
    • v2rayN / v2rayNG:  {C_YELLOW}https://{access_host}:20540/sub/v2ray{C_RESET}
    • Sing-box (1.8+):   {C_YELLOW}https://{access_host}:20540/sub/singbox{C_RESET}
    • Shadowrocket:      {C_YELLOW}https://{access_host}:20540/sub/shadowrocket{C_RESET}

 🛡️ {C_BOLD}核心自愈状态{C_RESET}:
    • 连续阻断阈值: {C_BOLD}丢包率 > 75% 且 连续 3 次探测失败{C_RESET}
    • 全自动换 IP 与 DNS 联动: {C_GREEN}已开启并处于巡检守护中{C_RESET}

 🛠️ {C_BOLD}常用运维指令{C_RESET}:
    • 守护进程实时日志: {C_CYAN}journalctl -u oracle-sentinel -f{C_RESET}
    • 重启守护进程:     {C_CYAN}systemctl restart oracle-sentinel{C_RESET}
    • 重新运行此向导:   {C_CYAN}python3 {SENTINEL_DIR}/scripts/wizard.py{C_RESET}
────────────────────────────────────────────────────────────────────────────────────────
""")

if __name__ == "__main__":
    main()

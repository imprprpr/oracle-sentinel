#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VPSentinel IP Purity & Streaming/AI Unlock Audit Module
Author: Antigravity Agent
"""

import time
import socket
import logging
import re
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional
import requests

logger = logging.getLogger("IPAuditor")

def country_code_to_emoji(country_code: str) -> str:
    if not country_code or len(country_code) != 2:
        return "🌐"
    return "".join(chr(ord(c.upper()) + 127397) for c in country_code)

class IPAuditor:
    def __init__(self, cache_ttl: int = 1800):
        self.cache_ttl = cache_ttl
        self._cached_report: Optional[Dict[str, Any]] = None
        self._last_audit_time: float = 0.0
        self._is_auditing: bool = False

    def is_running(self) -> bool:
        return self._is_auditing

    def get_latest_report(self) -> Optional[Dict[str, Any]]:
        return self._cached_report

    def audit(self, force: bool = False) -> Dict[str, Any]:
        now = time.time()
        if not force and self._cached_report and (now - self._last_audit_time < self.cache_ttl):
            res = dict(self._cached_report)
            res["cached"] = True
            res["cache_age_sec"] = int(now - self._last_audit_time)
            return res

        self._is_auditing = True
        try:
            report = self._run_full_audit()
            self._cached_report = report
            self._last_audit_time = now
            return report
        finally:
            self._is_auditing = False

    def _run_full_audit(self) -> Dict[str, Any]:
        t0 = time.time()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"
        }

        # 1. Base IP Profile & Geo
        base_info = self._get_base_ip_info(headers)
        public_ip = base_info.get("ip", "")

        # 2. Parallel probing for Speed & Accuracy
        with ThreadPoolExecutor(max_workers=8) as executor:
            fut_scamalytics = executor.submit(self._check_scamalytics, public_ip, headers)
            fut_dnsbl = executor.submit(self._check_dnsbl, public_ip)
            fut_openai = executor.submit(self._check_openai, headers)
            fut_claude = executor.submit(self._check_claude, headers)
            fut_gemini = executor.submit(self._check_gemini, headers)
            fut_netflix = executor.submit(self._check_netflix, headers)
            fut_youtube = executor.submit(self._check_youtube, headers)
            fut_disney = executor.submit(self._check_disney, headers)
            fut_google_captcha = executor.submit(self._check_google_captcha, headers)
            fut_warp = executor.submit(self._check_warp)

            scamalytics_data = fut_scamalytics.result()
            dnsbl_data = fut_dnsbl.result()
            openai_status = fut_openai.result()
            claude_status = fut_claude.result()
            gemini_status = fut_gemini.result()
            netflix_status = fut_netflix.result()
            youtube_status = fut_youtube.result()
            disney_status = fut_disney.result()
            google_captcha_status = fut_google_captcha.result()
            warp_status = fut_warp.result()

        # Fraud score synthesis
        fraud_score = scamalytics_data.get("score", 0)
        risk_level = scamalytics_data.get("risk", "low")
        risk_zh = scamalytics_data.get("risk_zh", "极低风险")

        # Purity rating computation
        purity_rating = "A+"
        purity_desc = "极致纯净 (Clean)"
        if dnsbl_data.get("any_listed"):
            purity_rating = "C"
            purity_desc = "黑名单预警 (Blacklisted)"
        elif fraud_score > 60:
            purity_rating = "D"
            purity_desc = "高风控 (High Risk)"
        elif fraud_score > 30:
            purity_rating = "B"
            purity_desc = "常规机房 (Medium Risk)"
        elif base_info.get("is_datacenter"):
            purity_rating = "A"
            purity_desc = "纯净机房 (DataCenter Clean)"
        else:
            purity_rating = "A+"
            purity_desc = "极净家宽/原生 (Residential Clean)"

        report = {
            "cached": False,
            "cache_age_sec": 0,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "audit_duration_sec": round(time.time() - t0, 2),
            "purity_rating": purity_rating,
            "purity_desc": purity_desc,
            "network": {
                "ip": public_ip,
                "type": base_info.get("type", "IPv4"),
                "country": base_info.get("country", "Unknown"),
                "country_code": base_info.get("country_code", "UN"),
                "flag_emoji": base_info.get("flag_emoji", "🌐"),
                "region": base_info.get("region", ""),
                "city": base_info.get("city", ""),
                "asn": base_info.get("asn", ""),
                "asname": base_info.get("asname", ""),
                "isp": base_info.get("isp", ""),
                "org": base_info.get("org", ""),
                "is_datacenter": base_info.get("is_datacenter", True),
                "ip_type_desc": "机房托管 (DataCenter)" if base_info.get("is_datacenter", True) else "住宅宽带 (Residential / ISP)",
                "reverse_dns": base_info.get("reverse_dns", "")
            },
            "risk": {
                "scamalytics_score": fraud_score,
                "scamalytics_risk": risk_level,
                "risk_zh": risk_zh,
                "is_vpn": scamalytics_data.get("is_vpn", False),
                "is_tor": scamalytics_data.get("is_tor", False),
                "dnsbl_clean": not dnsbl_data.get("any_listed", False),
                "dnsbl_tested": dnsbl_data.get("details", []),
                "google_captcha": google_captcha_status
            },
            "unlock_matrix": {
                "ai": {
                    "openai": openai_status,
                    "claude": claude_status,
                    "gemini": gemini_status
                },
                "streaming": {
                    "netflix": netflix_status,
                    "youtube": youtube_status,
                    "disney": disney_status
                }
            },
            "warp": warp_status
        }
        return report

    def _get_base_ip_info(self, headers: Dict[str, str]) -> Dict[str, Any]:
        info = {
            "ip": "Unknown",
            "type": "IPv4",
            "country": "Unknown",
            "country_code": "US",
            "flag_emoji": "🇺🇸",
            "region": "",
            "city": "",
            "asn": "",
            "asname": "",
            "isp": "",
            "org": "",
            "is_datacenter": True,
            "reverse_dns": ""
        }
        # Try ip-api.com
        try:
            r = requests.get("http://ip-api.com/json/?fields=66846719", headers=headers, timeout=5)
            if r.status_code == 200:
                data = r.json()
                if data.get("status") == "success":
                    cc = data.get("countryCode", "US")
                    reverse_val = (data.get("reverse") or "").strip()
                    if not reverse_val and data.get("query"):
                        try:
                            reverse_val = socket.gethostbyaddr(data.get("query"))[0]
                        except Exception:
                            reverse_val = "无反向 PTR 记录 (None)"
                    info.update({
                        "ip": data.get("query", ""),
                        "country": data.get("country", ""),
                        "country_code": cc,
                        "flag_emoji": country_code_to_emoji(cc),
                        "region": data.get("regionName", ""),
                        "city": data.get("city", ""),
                        "asn": data.get("as", ""),
                        "asname": data.get("asname", ""),
                        "isp": data.get("isp", ""),
                        "org": data.get("org", ""),
                        "is_datacenter": bool(data.get("hosting", True)),
                        "reverse_dns": reverse_val or "无反向 PTR 记录 (None)"
                    })
                    return info
        except Exception as e:
            logger.warning(f"ip-api lookup error: {e}")

        # Fallback to ipwho.is
        try:
            r = requests.get("https://ipwho.is/", headers=headers, timeout=5)
            if r.status_code == 200:
                data = r.json()
                if data.get("success"):
                    cc = data.get("country_code", "US")
                    conn = data.get("connection", {})
                    info.update({
                        "ip": data.get("ip", ""),
                        "country": data.get("country", ""),
                        "country_code": cc,
                        "flag_emoji": data.get("flag", {}).get("emoji", country_code_to_emoji(cc)),
                        "region": data.get("region", ""),
                        "city": data.get("city", ""),
                        "asn": f"AS{conn.get('asn', '')}",
                        "asname": conn.get("org", ""),
                        "isp": conn.get("isp", ""),
                        "org": conn.get("org", ""),
                        "is_datacenter": True
                    })
        except Exception as e:
            logger.warning(f"ipwho.is lookup error: {e}")

        if info["ip"] and info["ip"] != "Unknown" and not info.get("reverse_dns"):
            try:
                info["reverse_dns"] = socket.gethostbyaddr(info["ip"])[0]
            except Exception:
                info["reverse_dns"] = "无反向 PTR 记录 (None)"
        if not info.get("reverse_dns"):
            info["reverse_dns"] = "无反向 PTR 记录 (None)"

        return info

    def _check_scamalytics(self, ip: str, headers: Dict[str, str]) -> Dict[str, Any]:
        res = {
            "score": 0,
            "risk": "low",
            "risk_zh": "极低风险",
            "is_vpn": False,
            "is_tor": False,
            "is_datacenter": True
        }
        if not ip or ip == "Unknown":
            return res

        # 1. Use curl to query ipinfo.check.place community bridge (handles Cloudflare cleanly)
        try:
            url = f"https://ipinfo.check.place/{ip}?db=scamalytics"
            cmd = ["curl", "-sL", "--max-time", "5", url]
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
            if p.returncode == 0 and p.stdout.strip().startswith("{"):
                data = json.loads(p.stdout)
                scam = data.get("scamalytics", {})
                score = scam.get("scamalytics_score")
                risk = scam.get("scamalytics_risk", "low").lower()
                if score is not None:
                    res["score"] = int(score)
                    res["risk"] = risk
                    risk_map = {
                        "low": "极低风险",
                        "medium": "中等风险",
                        "high": "高风险",
                        "very high": "极高风险"
                    }
                    res["risk_zh"] = risk_map.get(risk, risk.capitalize())
                    res["is_vpn"] = bool(scam.get("scamalytics_proxy", {}).get("is_vpn", False))
                    res["is_datacenter"] = bool(scam.get("scamalytics_proxy", {}).get("is_datacenter", True))
                    return res
        except Exception as e:
            logger.debug(f"check.place scamalytics lookup failed: {e}")

        # 2. Fallback Scamalytics direct scrape attempt
        try:
            scam_url = f"https://scamalytics.com/ip/{ip}"
            r = requests.get(scam_url, headers=headers, timeout=5)
            if r.status_code == 200:
                m_score = re.search(r"Fraud Score:\s*(\d+)", r.text)
                m_risk = re.search(r">\s*(Low|Medium|High|Very High)\s*Risk", r.text, re.I)
                if m_score:
                    res["score"] = int(m_score.group(1))
                if m_risk:
                    r_str = m_risk.group(1).lower()
                    res["risk"] = r_str
                    risk_map = {"low": "极低风险", "medium": "中等风险", "high": "高风险", "very high": "极高风险"}
                    res["risk_zh"] = risk_map.get(r_str, r_str.capitalize())
                return res
        except Exception as e:
            logger.debug(f"Direct scamalytics lookup failed: {e}")

        return res

    def _check_dnsbl(self, ip: str) -> Dict[str, Any]:
        result = {"any_listed": False, "details": []}
        if not ip or ip == "Unknown" or ":" in ip:
            return result

        reversed_ip = ".".join(reversed(ip.split(".")))
        blacklists = [
            ("SpamCop", "bl.spamcop.net"),
            ("DroneBL", "dnsbl.dronebl.org"),
            ("S5h", "all.s5h.net"),
            ("GBUdb Truncate", "truncate.gbudb.net")
        ]

        for name, host in blacklists:
            query = f"{reversed_ip}.{host}"
            try:
                ans = socket.gethostbyname(query)
                result["details"].append({"name": name, "status": "listed", "clean": False, "response": ans})
                result["any_listed"] = True
            except socket.gaierror:
                result["details"].append({"name": name, "status": "clean", "clean": True, "response": None})
            except Exception as e:
                result["details"].append({"name": name, "status": "clean", "clean": True, "error": str(e)})

        return result

    def _check_openai(self, headers: Dict[str, str]) -> Dict[str, Any]:
        res = {"status": "unlocked", "label": "原生解锁 / 可直连", "badge": "success"}
        try:
            r = requests.get("https://api.openai.com/v1/models", headers=headers, timeout=5)
            if r.status_code == 401:
                res = {"status": "unlocked", "label": "原生全解锁 (API & Web 直连)", "badge": "success"}
            elif r.status_code == 403:
                res = {"status": "blocked", "label": "Cloudflare 1020 拦截 (需 WARP 接管)", "badge": "danger"}
            else:
                res = {"status": "unlocked", "label": f"响应正常 (HTTP {r.status_code})", "badge": "success"}
        except Exception as e:
            res = {"status": "error", "label": f"探测超时 / 异常 ({e.__class__.__name__})", "badge": "warning"}
        return res

    def _check_claude(self, headers: Dict[str, str]) -> Dict[str, Any]:
        res = {"status": "unlocked", "label": "原生解锁", "badge": "success"}
        try:
            r = requests.get("https://claude.ai", headers=headers, timeout=5, allow_redirects=True)
            if r.status_code in (200, 301, 302):
                res = {"status": "unlocked", "label": "原生解锁 (可用网页与 API)", "badge": "success"}
            elif r.status_code == 403:
                res = {"status": "blocked", "label": "机房 IP 拦截 (建议开启 WARP 分流)", "badge": "danger"}
            else:
                res = {"status": "warning", "label": f"HTTP {r.status_code}", "badge": "warning"}
        except Exception as e:
            res = {"status": "error", "label": f"探测超时 ({e.__class__.__name__})", "badge": "warning"}
        return res

    def _check_gemini(self, headers: Dict[str, str]) -> Dict[str, Any]:
        res = {"status": "unlocked", "label": "原生解锁", "badge": "success"}
        try:
            r = requests.get("https://gemini.google.com", headers=headers, timeout=5, allow_redirects=True)
            if r.status_code == 200:
                res = {"status": "unlocked", "label": "支持区域原生直连", "badge": "success"}
            elif r.status_code in (403, 451):
                res = {"status": "blocked", "label": "区域限制 (Geo Restricted)", "badge": "danger"}
            else:
                res = {"status": "unlocked", "label": f"HTTP {r.status_code}", "badge": "success"}
        except Exception as e:
            res = {"status": "error", "label": f"探测异常 ({e.__class__.__name__})", "badge": "warning"}
        return res

    def _check_netflix(self, headers: Dict[str, str]) -> Dict[str, Any]:
        res = {"status": "unknown", "label": "检测中", "badge": "info"}
        try:
            r1 = requests.get("https://www.netflix.com/title/80018499", headers=headers, timeout=6, allow_redirects=True)
            r2 = requests.get("https://www.netflix.com/title/70143836", headers=headers, timeout=6, allow_redirects=True)

            code1, code2 = r1.status_code, r2.status_code
            if code1 == 200 and code2 == 200:
                res = {"status": "full", "label": "原生全解锁 (含非自制剧)", "badge": "success"}
            elif code1 == 200 and code2 != 200:
                res = {"status": "originals", "label": "仅自制剧解锁 (Originals Only)", "badge": "warning"}
            else:
                res = {"status": "blocked", "label": "未解锁 / 屏蔽 (需 WARP 接管)", "badge": "danger"}
        except Exception as e:
            res = {"status": "error", "label": f"探测超时 ({e.__class__.__name__})", "badge": "warning"}
        return res

    def _check_youtube(self, headers: Dict[str, str]) -> Dict[str, Any]:
        res = {"status": "unlocked", "label": "已解锁", "badge": "success", "region": "US"}
        try:
            r = requests.get("https://www.youtube.com/premium", headers=headers, timeout=6)
            if r.status_code == 200:
                m = re.search(r'"INNERTUBE_CONTEXT_GL":"([A-Z]{2})"', r.text) or re.search(r'"countryCode":"([A-Z]{2})"', r.text)
                region = m.group(1) if m else "US"
                res = {"status": "unlocked", "label": f"Premium 支持跨区订阅 ({region})", "badge": "success", "region": region}
            elif "not available" in r.text.lower():
                res = {"status": "blocked", "label": "地区不可用", "badge": "danger", "region": None}
            else:
                res = {"status": "unlocked", "label": f"HTTP {r.status_code}", "badge": "success", "region": "US"}
        except Exception as e:
            res = {"status": "error", "label": f"探测超时 ({e.__class__.__name__})", "badge": "warning", "region": None}
        return res

    def _check_disney(self, headers: Dict[str, str]) -> Dict[str, Any]:
        res = {"status": "unlocked", "label": "原生解锁", "badge": "success"}
        try:
            r = requests.get("https://www.disneyplus.com", headers=headers, timeout=6, allow_redirects=False)
            if r.status_code in (200, 301, 302):
                loc = r.headers.get("location", "")
                if "error" in loc or "unavailable" in loc:
                    res = {"status": "blocked", "label": "区域限制", "badge": "danger"}
                else:
                    res = {"status": "unlocked", "label": "原生解锁 / 可用", "badge": "success"}
            elif r.status_code == 403:
                res = {"status": "blocked", "label": "机房屏蔽 (需 WARP)", "badge": "danger"}
            else:
                res = {"status": "unlocked", "label": f"HTTP {r.status_code}", "badge": "success"}
        except Exception as e:
            res = {"status": "error", "label": f"探测超时 ({e.__class__.__name__})", "badge": "warning"}
        return res

    def _check_google_captcha(self, headers: Dict[str, str]) -> Dict[str, Any]:
        res = {"status": "clean", "label": "纯净 / 无验证码 (No Captcha)", "badge": "success"}
        try:
            r = requests.get("https://www.google.com/search?q=oracle+sentinel+ping", headers=headers, timeout=5)
            if "sorry/index" in r.text or "unusual traffic" in r.text.lower():
                res = {"status": "captcha", "label": "触发人机验证 (Unusual Traffic)", "badge": "warning"}
            else:
                res = {"status": "clean", "label": "纯净 / 无搜索验证码 (Clean)", "badge": "success"}
        except Exception as e:
            res = {"status": "unknown", "label": f"探测失败 ({e.__class__.__name__})", "badge": "info"}
        return res

    def _check_warp(self) -> Dict[str, Any]:
        res = {
            "active": False,
            "status": "off",
            "label": "未接入 WARP",
            "colo": None,
            "warp_ip": None
        }
        try:
            cmd = ["curl", "-s", "--max-time", "4", "--socks5", "127.0.0.1:40000", "https://www.cloudflare.com/cdn-cgi/trace"]
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if p.returncode == 0 and "warp=" in p.stdout:
                lines = dict(x.split("=", 1) for x in p.stdout.strip().split("\n") if "=" in x)
                warp_val = lines.get("warp", "off")
                colo = lines.get("colo", "LAX")
                ip = lines.get("ip", "")
                if warp_val in ("on", "plus"):
                    res = {
                        "active": True,
                        "status": warp_val,
                        "label": f"WARP 双栈接管中 ({colo} 节点)",
                        "colo": colo,
                        "warp_ip": ip
                    }
        except Exception as e:
            logger.debug(f"WARP check error: {e}")
        return res

auditor = IPAuditor()

if __name__ == "__main__":
    print("Testing IPAuditor...")
    report = auditor.audit(force=True)
    print(json.dumps(report, indent=2, ensure_ascii=False))

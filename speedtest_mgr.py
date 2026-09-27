#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VPSentinel Speedtest & Network Benchmark Module
Author: Antigravity Agent
"""

import time
import json
import logging
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional, List

logger = logging.getLogger("SpeedtestMgr")

BENCHMARK_TARGETS = [
    {"name": "中国电信 (上海)", "isp": "电信", "region": "华东", "host": "202.96.209.133"},
    {"name": "中国联通 (北京)", "isp": "联通", "region": "华北", "host": "123.125.81.6"},
    {"name": "中国移动 (上海)", "isp": "移动", "region": "华东", "host": "211.136.112.50"},
    {"name": "中国移动 (广州)", "isp": "移动", "region": "华南", "host": "120.196.165.24"},
    {"name": "腾讯云 BGP (全国优选)", "isp": "BGP", "region": "亚太", "host": "119.29.29.29"},
    {"name": "阿里云 BGP (全国优选)", "isp": "BGP", "region": "亚太", "host": "223.5.5.5"},
    {"name": "Cloudflare Anycast", "isp": "国际", "region": "北美", "host": "1.1.1.1"},
    {"name": "Google DNS", "isp": "国际", "region": "全球", "host": "8.8.8.8"},
]

def ping_target(target: Dict[str, str], count: int = 3) -> Dict[str, Any]:
    host = target["host"]
    res = {
        "name": target["name"],
        "isp": target["isp"],
        "region": target["region"],
        "host": host,
        "loss": 100,
        "avg_ms": None,
        "min_ms": None,
        "max_ms": None,
        "jitter_ms": None,
        "status": "unreachable",
        "badge": "danger"
    }
    try:
        cmd = ["ping", "-c", str(count), "-W", "2", host]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
        if p.returncode == 0 or "packet loss" in p.stdout:
            for line in p.stdout.splitlines():
                if "packet loss" in line or "loss" in line:
                    m = re.search(r"([\d\.]+)%\s*(?:packet\s*)?loss", line, re.I)
                    if m:
                        try:
                            res["loss"] = int(round(float(m.group(1))))
                        except Exception:
                            res["loss"] = 0
                if "rtt min/avg/max" in line or "round-trip min/avg/max" in line:
                    parts = line.split("=")[1].strip().split("/")
                    res["min_ms"] = round(float(parts[0]), 1)
                    res["avg_ms"] = round(float(parts[1]), 1)
                    res["max_ms"] = round(float(parts[2]), 1)
                    res["jitter_ms"] = round(float(parts[3].split()[0]), 1)
                    
                    avg = res["avg_ms"]
                    if res["loss"] >= 50:
                        res["status"] = "丢包严重"
                        res["badge"] = "danger"
                    elif avg < 60:
                        res["status"] = "极速"
                        res["badge"] = "success"
                    elif avg < 160:
                        res["status"] = "优良"
                        res["badge"] = "success"
                    elif avg < 230:
                        res["status"] = "正常"
                        res["badge"] = "info"
                    else:
                        res["status"] = "偏高"
                        res["badge"] = "warning"
        else:
            res["status"] = "超时 / 阻断"
            res["badge"] = "danger"
    except Exception as e:
        logger.debug(f"Ping {host} error: {e}")
        res["status"] = "探测异常"
        res["badge"] = "secondary"

    return res

def run_latency_benchmarks() -> List[Dict[str, Any]]:
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(ping_target, BENCHMARK_TARGETS))
    return results

def run_speedtest_cli() -> Dict[str, Any]:
    cmd = ["speedtest-cli", "--json", "--secure"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=50)
    if p.returncode != 0:
        raise RuntimeError(f"speedtest-cli 异常: {p.stderr.strip() or p.stdout.strip()}")
    data = json.loads(p.stdout)
    
    download_mbps = round(data.get("download", 0) / 1e6, 2)
    upload_mbps = round(data.get("upload", 0) / 1e6, 2)
    ping_ms = round(data.get("ping", 0), 1)
    server = data.get("server", {})
    client = data.get("client", {})

    return {
        "download_mbps": download_mbps,
        "upload_mbps": upload_mbps,
        "ping_ms": ping_ms,
        "server_name": server.get("name", "Unknown"),
        "server_sponsor": server.get("sponsor", "Unknown"),
        "server_country": server.get("country", "Unknown"),
        "server_distance_km": round(server.get("d", 0), 1),
        "client_ip": client.get("ip", ""),
        "client_isp": client.get("isp", ""),
        "bytes_sent_mb": round(data.get("bytes_sent", 0) / (1024 * 1024), 2),
        "bytes_received_mb": round(data.get("bytes_received", 0) / (1024 * 1024), 2),
    }

class SpeedtestManager:
    def __init__(self):
        self.is_running = False
        self.stage = "idle"  # idle, bandwidth, latency, done, error
        self.progress_msg = "空闲待命"
        self.started_at: float = 0.0
        self.last_result: Optional[Dict[str, Any]] = None
        self.history: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def get_status(self) -> Dict[str, Any]:
        return {
            "is_running": self.is_running,
            "stage": self.stage,
            "progress_msg": self.progress_msg,
            "elapsed_sec": round(time.time() - self.started_at, 1) if self.is_running else 0,
            "last_result": self.last_result,
            "history_count": len(self.history)
        }

    def start_benchmark(self, mode: str = "full") -> bool:
        with self._lock:
            if self.is_running:
                return False
            self.is_running = True
            self.started_at = time.time()
            self.stage = "starting"
            self.progress_msg = "正在初始化网络测试引擎..."

        t = threading.Thread(target=self._execute_benchmark_worker, args=(mode,), daemon=True)
        t.start()
        return True

    def _execute_benchmark_worker(self, mode: str):
        t0 = time.time()
        result: Dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "mode": mode,
            "success": False,
            "duration_sec": 0,
            "bandwidth": None,
            "three_network": [],
            "rating": "N/A",
            "rating_desc": "测试中",
            "error": None
        }

        try:
            # Step 1: Bandwidth speedtest if full mode
            if mode == "full":
                self.stage = "bandwidth"
                self.progress_msg = "正在测试就近骨干节点的上下行带宽与往返延迟..."
                try:
                    result["bandwidth"] = run_speedtest_cli()
                except Exception as e:
                    logger.warning(f"Bandwidth test failed: {e}")
                    result["bandwidth_error"] = str(e)

            # Step 2: Latency benchmarks
            self.stage = "latency"
            self.progress_msg = "正在测试国内三网骨干与国际链路延迟..."
            result["three_network"] = run_latency_benchmarks()

            # Step 3: Synthesis Rating
            dl = result.get("bandwidth", {}).get("download_mbps", 0) if result.get("bandwidth") else 0
            ul = result.get("bandwidth", {}).get("upload_mbps", 0) if result.get("bandwidth") else 0

            # Calculate china avg latency
            cn_pings = [x["avg_ms"] for x in result["three_network"] if x.get("isp") in ("电信", "联通", "移动") and x.get("avg_ms")]
            cn_avg = sum(cn_pings) / len(cn_pings) if cn_pings else 200.0

            if mode == "full":
                if dl >= 100 and cn_avg < 180:
                    result["rating"] = "A+"
                    result["rating_desc"] = "超高带宽 / 极佳跨境链路"
                elif dl >= 30 and cn_avg < 220:
                    result["rating"] = "A"
                    result["rating_desc"] = "优良跨境互联 / 流畅 4K 播放"
                elif dl >= 10:
                    result["rating"] = "B"
                    result["rating_desc"] = "常规跨境性能 / 满足日常使用"
                else:
                    result["rating"] = "C"
                    result["rating_desc"] = "受限或丢包较高"
            else:
                # ping only mode
                if cn_avg < 180:
                    result["rating"] = "A+"
                    result["rating_desc"] = "三网直连延迟极佳"
                elif cn_avg < 220:
                    result["rating"] = "A"
                    result["rating_desc"] = "跨境路由优良稳定"
                elif cn_avg < 260:
                    result["rating"] = "B"
                    result["rating_desc"] = "常规跨洋延迟"
                else:
                    result["rating"] = "C"
                    result["rating_desc"] = "网络延迟偏高"

            result["success"] = True
            result["duration_sec"] = round(time.time() - t0, 1)
            self.stage = "done"
            self.progress_msg = f"测速完成，耗时 {result['duration_sec']} 秒"

            with self._lock:
                self.last_result = result
                self.history.insert(0, {
                    "timestamp": result["timestamp"],
                    "rating": result["rating"],
                    "download_mbps": dl,
                    "upload_mbps": ul,
                    "ping_ms": result.get("bandwidth", {}).get("ping_ms", 0) if result.get("bandwidth") else 0,
                    "cn_avg_latency": round(cn_avg, 1)
                })
                if len(self.history) > 10:
                    self.history.pop()

        except Exception as e:
            logger.error(f"Speedtest worker error: {e}", exc_info=True)
            result["error"] = str(e)
            result["success"] = False
            self.stage = "error"
            self.progress_msg = f"测速失败: {str(e)}"
            with self._lock:
                self.last_result = result
        finally:
            with self._lock:
                self.is_running = False

speedtest_mgr = SpeedtestManager()

if __name__ == "__main__":
    print("Testing SpeedtestManager (mode=ping_only)...")
    speedtest_mgr._execute_benchmark_worker(mode="ping_only")
    print(json.dumps(speedtest_mgr.last_result, indent=2, ensure_ascii=False))

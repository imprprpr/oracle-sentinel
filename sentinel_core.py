#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Oracle Sentinel - Core Engine & Multi-Cloud Provider Abstraction
# ==============================================================================

import os
import sys
import time
import json
import socket
import logging
import platform
import subprocess
import requests
import psutil

# Conditional OCI import for cross-cloud compatibility
try:
    import oci
    HAS_OCI = True
except ImportError:
    HAS_OCI = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('SentinelCore')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = '/opt/oracle-sentinel/config.json' if os.path.exists('/opt/oracle-sentinel/config.json') else os.path.join(BASE_DIR, 'config.json')
METADATA_INSTANCE_URL = 'http://169.254.169.254/opc/v2/instance/'
METADATA_VNICS_URL = 'http://169.254.169.254/opc/v2/vnics/'

DEFAULT_CONFIG = {
    'provider': {
        'type': 'auto',          # 'auto', 'oracle', 'hook', 'generic'
        'hook_cmd': ''
    },
    'cloudflare': {
        'api_token': '',
        'zone_name': '',
        'record_name': ''
    },
    'oci': {
        'auth_method': 'config_file',
        'config_path': '/root/.oci/config'
    },
    'monitor': {
        'interval_sec': 15,
        'loss_threshold': 75.0,
        'consecutive_failures': 3,
        'auto_heal_enabled': True
    },
    'notifications': {
        'enabled': False,
        'telegram': {
            'enabled': False,
            'bot_token': '',
            'chat_id': ''
        },
        'discord': {
            'enabled': False,
            'webhook_url': ''
        },
        'bark': {
            'enabled': False,
            'bark_key': ''
        },
        'custom_webhook': {
            'enabled': False,
            'url': ''
        }
    },
    'rules_config': {
        'adblock': True,
        'ai_group': True,
        'media_group': True,
        'auto_test': True,
        'direct_cn': True,
        'hy2_hop': True
    },
    'transits': []
}

def get_cloud_info():
    """
    Auto-detects host virtualization, cloud provider, and CPU architecture.
    """
    arch = platform.machine()
    dmi_str = ""
    for df in ['/sys/class/dmi/id/product_name', '/sys/class/dmi/id/sys_vendor', '/sys/class/dmi/id/chassis_asset_tag']:
        if os.path.exists(df):
            try:
                with open(df, 'r', encoding='utf-8', errors='ignore') as f:
                    dmi_str += f.read() + " "
            except Exception:
                pass

    if 'OracleCloud' in dmi_str:
        return {'provider': 'Oracle Cloud', 'region': 'OCI Global', 'arch': arch}
    elif 'Amazon' in dmi_str or 'EC2' in dmi_str:
        return {'provider': 'AWS (Amazon EC2)', 'region': 'AWS', 'arch': arch}
    elif 'Alibaba' in dmi_str or 'Aliyun' in dmi_str:
        return {'provider': 'Alibaba Cloud (阿里云)', 'region': 'Aliyun', 'arch': arch}
    elif 'Tencent' in dmi_str:
        return {'provider': 'Tencent Cloud (腾讯云)', 'region': 'Tencent', 'arch': arch}
    elif 'Hetzner' in dmi_str:
        return {'provider': 'Hetzner Cloud', 'region': 'Hetzner', 'arch': arch}
    elif 'DigitalOcean' in dmi_str:
        return {'provider': 'DigitalOcean', 'region': 'DO', 'arch': arch}

    # Metadata service check
    try:
        r = requests.get(METADATA_INSTANCE_URL, headers={'Authorization': 'Bearer Oracle'}, timeout=1)
        if r.status_code == 200:
            reg = r.json().get('canonicalRegionName', 'Oracle Cloud')
            return {'provider': 'Oracle Cloud', 'region': reg, 'arch': arch}
    except Exception:
        pass

    return {'provider': 'Generic VPS / Dedicated Server', 'region': 'Global', 'arch': arch}

class ConfigManager:
    @staticmethod
    def load():
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    merged = DEFAULT_CONFIG.copy()
                    for k, v in cfg.items():
                        if isinstance(v, dict) and k in merged:
                            merged[k].update(v)
                        else:
                            merged[k] = v
                    return merged
            except Exception as e:
                logger.error(f'Error reading {CONFIG_PATH}: {e}')
        return DEFAULT_CONFIG.copy()

    @staticmethod
    def save(cfg):
        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f'Error saving {CONFIG_PATH}: {e}')
            return False

class SystemMonitor:
    def __init__(self):
        self.probes = [
            {'name': 'AliDNS', 'host': '223.5.5.5', 'port': 53},
            {'name': 'DNSPod', 'host': '119.29.29.29', 'port': 53},
            {'name': 'Baidu', 'host': 'www.baidu.com', 'port': 80},
            {'name': 'Tencent', 'host': 'www.qq.com', 'port': 80}
        ]
        self.last_net_io = psutil.net_io_counters()
        self.last_net_time = time.time()
        self.consecutive_failures = 0

    def get_public_ip(self):
        providers = [
            'https://api.ipify.org',
            'https://ifconfig.me/ip',
            'https://checkip.amazonaws.com'
        ]
        for url in providers:
            try:
                r = requests.get(url, timeout=2)
                if r.status_code == 200:
                    ip = r.text.strip()
                    if ip and len(ip.split('.')) == 4:
                        return ip
            except Exception:
                continue
        return '127.0.0.1'

    def get_warp_status(self):
        try:
            r = requests.get(
                'https://cloudflare.com/cdn-cgi/trace',
                proxies={'http': 'socks5h://127.0.0.1:40000', 'https': 'socks5h://127.0.0.1:40000'},
                timeout=2
            )
            data = dict(line.split('=', 1) for line in r.text.strip().split('\n') if '=' in line)
            return {
                'active': data.get('warp') in ('on', 'plus'),
                'ip': data.get('ip', 'N/A'),
                'loc': data.get('loc', 'N/A')
            }
        except Exception:
            return {'active': False, 'ip': 'Offline', 'loc': 'N/A'}

    def check_domestic_probes(self):
        total = len(self.probes)
        success = 0
        latencies = []

        for p in self.probes:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.5)
            t0 = time.time()
            try:
                s.connect((p['host'], p['port']))
                latencies.append((time.time() - t0) * 1000)
                success += 1
            except Exception:
                pass
            finally:
                s.close()

        loss = round((total - success) / total * 100, 1)
        avg_rtt = round(sum(latencies) / len(latencies), 1) if latencies else 0.0

        return {
            'loss_pct': loss,
            'avg_rtt_ms': avg_rtt,
            'success_probes': success,
            'total_probes': total
        }

    def check_port_listening(self, port, proto='tcp'):
        try:
            for conn in psutil.net_connections(kind='inet'):
                if conn.laddr.port == port and conn.status == (psutil.CONN_LISTEN if proto == 'tcp' else conn.status):
                    return True
        except Exception:
            pass
        return False

    def get_metrics(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        
        now = time.time()
        curr_io = psutil.net_io_counters()
        dt = max(now - self.last_net_time, 0.1)
        
        rx_bytes_sec = (curr_io.bytes_recv - self.last_net_io.bytes_recv) / dt
        tx_bytes_sec = (curr_io.bytes_sent - self.last_net_io.bytes_sent) / dt
        
        self.last_net_io = curr_io
        self.last_net_time = now

        uptime_seconds = int(time.time() - psutil.boot_time())
        days = uptime_seconds // 86400
        hours = (uptime_seconds % 86400) // 3600
        mins = (uptime_seconds % 3600) // 60
        uptime_str = f'{days}d {hours}h {mins}m' if days else f'{hours}h {mins}m'

        return {
            'cpu_pct': cpu,
            'mem_pct': mem.percent,
            'mem_used_mb': round(mem.used / (1024 * 1024), 1),
            'mem_total_mb': round(mem.total / (1024 * 1024), 1),
            'rx_speed_kb': round(rx_bytes_sec / 1024, 1),
            'tx_speed_kb': round(tx_bytes_sec / 1024, 1),
            'uptime': uptime_str
        }

    def get_full_state(self):
        cfg = ConfigManager.load()
        cloud_info = get_cloud_info()
        metrics = self.get_metrics()
        probes = self.check_domestic_probes()
        pub_ip = self.get_public_ip()
        warp = self.get_warp_status()

        nodes = [
            {
                'id': 'vless-reality',
                'name': 'Oracle-US',
                'proto': 'VLESS-Reality',
                'port': 8443,
                'sni': 'swdist.apple.com',
                'status': 'online' if self.check_port_listening(8443, 'tcp') else 'offline'
            },
            {
                'id': 'hy2',
                'name': 'Oracle-Hy2',
                'proto': 'Hysteria 2',
                'port': 443,
                'hop': '20000-40000 (iptables active)',
                'status': 'online' if self.check_port_listening(443, 'udp') else 'offline'
            },
            {
                'id': 'trojan',
                'name': 'Oracle-Trojan',
                'proto': 'Trojan-TLS',
                'port': 2083,
                'sni': cfg.get('cloudflare', {}).get('record_name', 'vps.example.com'),
                'status': 'online' if self.check_port_listening(2083, 'tcp') else 'offline'
            }
        ]

        if probes['loss_pct'] >= 80:
            health = 'critical'
        elif probes['loss_pct'] > 0:
            health = 'warning'
        else:
            health = 'healthy'

        return {
            'timestamp': int(time.time()),
            'health': health,
            'public_ip': pub_ip,
            'cloud_info': cloud_info,
            'probes': probes,
            'metrics': metrics,
            'nodes': nodes,
            'warp': warp
        }

# ==============================================================================
# Multi-Cloud Provider Abstraction
# ==============================================================================

class BaseCloudProvider:
    def change_public_ip(self) -> str:
        raise NotImplementedError("Subclasses must implement change_public_ip()")

    def get_name(self) -> str:
        return "BaseProvider"

class OracleCloudProvider(BaseCloudProvider):
    def __init__(self, config_path=None):
        self.metadata = self._get_metadata(METADATA_INSTANCE_URL)
        self.vnics_info = self._get_metadata(METADATA_VNICS_URL)
        self.compartment_id = self.metadata.get('compartmentId')
        self.instance_id = self.metadata.get('id')
        self.region = self.metadata.get('canonicalRegionName', 'us-phoenix-1')
        self.vnic_id = self.vnics_info[0].get('vnicId') if self.vnics_info else None
        self.client = None
        self.init_error = None
        
        if not HAS_OCI:
            self.init_error = "OCI Python SDK is not installed."
            return

        try:
            self.client = self._init_client(config_path)
        except Exception as e:
            self.init_error = str(e)
            logger.warning(f'Oracle Client init deferred/failed: {e}')

    def get_name(self) -> str:
        return "Oracle Cloud Infrastructure (OCI)"

    def _get_metadata(self, url):
        try:
            r = requests.get(url, headers={'Authorization': 'Bearer Oracle'}, timeout=2)
            return r.json()
        except Exception:
            return {}

    def _init_client(self, config_path):
        default_oci_cfg = os.path.expanduser('~/.oci/config')
        target_cfg = config_path or (default_oci_cfg if os.path.exists(default_oci_cfg) else None)
        
        if target_cfg and os.path.exists(target_cfg):
            try:
                config = oci.config.from_file(target_cfg)
                logger.info(f'Using OCI API Key configuration from {target_cfg}')
                return oci.core.VirtualNetworkClient(config)
            except Exception as e:
                logger.warning(f'Failed loading ~/.oci/config: {e}')
        
        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        logger.info('Using OCI Instance Principal authentication')
        return oci.core.VirtualNetworkClient(config={}, signer=signer)

    def change_public_ip(self):
        if not self.client:
            raise RuntimeError(f'OCI Client not ready: {self.init_error}')
        if not self.vnic_id:
            raise ValueError('Primary VNIC ID not detected from metadata.')

        logger.info('Querying private IPs on primary VNIC...')
        try:
            priv_ips = self.client.list_private_ips(vnic_id=self.vnic_id).data
        except Exception as e:
            if 'NotAuthorizedOrNotFound' in str(e):
                raise PermissionError(
                    'Oracle IAM Authorization failed. Please grant permission in Oracle Console: '
                    'Create Dynamic Group for this instance and add Policy: '
                    '"Allow dynamic-group <group-name> to manage public-ips in tenancy"'
                )
            raise e

        primary_priv_ip = next((ip for ip in priv_ips if ip.is_primary), None)
        if not primary_priv_ip:
            raise ValueError('Primary private IP not found on VNIC')

        # Release old public IP
        try:
            pub_ip_details = oci.core.models.GetPublicIpByPrivateIpIdDetails(private_ip_id=primary_priv_ip.id)
            pub_ip = self.client.get_public_ip_by_private_ip_id(pub_ip_details).data
            if pub_ip and pub_ip.id:
                logger.info(f'Releasing old Public IP: {pub_ip.ip_address} (OCID: {pub_ip.id})')
                self.client.delete_public_ip(pub_ip.id)
                time.sleep(2)
        except Exception as e:
            logger.warning(f'Notice on fetching old public IP: {e}')

        # Create new public IP
        logger.info('Allocating new Ephemeral Public IP from Oracle Cloud pool...')
        create_details = oci.core.models.CreatePublicIpDetails(
            compartment_id=self.compartment_id,
            lifetime='EPHEMERAL',
            private_ip_id=primary_priv_ip.id,
            display_name=f'sentinel-ephemeral-{int(time.time())}'
        )
        new_pub_ip = self.client.create_public_ip(create_details).data
        logger.info(f'Successfully assigned NEW Public IP: {new_pub_ip.ip_address}')
        return new_pub_ip.ip_address

class CustomHookProvider(BaseCloudProvider):
    def __init__(self, hook_cmd):
        self.hook_cmd = hook_cmd

    def get_name(self) -> str:
        return "Custom Script / Hook"

    def change_public_ip(self) -> str:
        if not self.hook_cmd:
            raise ValueError("No custom hook script or command configured.")
        logger.info(f"Executing custom Re-IP hook: {self.hook_cmd}")
        res = subprocess.run(self.hook_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        new_ip = res.stdout.strip()
        if not (new_ip and len(new_ip.split('.')) == 4):
            new_ip = SystemMonitor().get_public_ip()
        return new_ip

class GenericProvider(BaseCloudProvider):
    def get_name(self) -> str:
        return "Generic VPS (Monitoring & Alert Only)"

    def change_public_ip(self) -> str:
        logger.info("Generic VPS detected: Automatic IP swap not supported by cloud provider.")
        logger.info("Attempting WARP egress renewal...")
        try:
            subprocess.run("warp-cli disconnect && sleep 1 && warp-cli connect", shell=True, check=False)
        except Exception:
            pass
        return SystemMonitor().get_public_ip()

def get_cloud_provider(cfg):
    """
    Factory method returning the active Cloud Provider instance based on configuration.
    """
    p_type = cfg.get('provider', {}).get('type', 'auto')
    cloud_info = get_cloud_info()

    if p_type == 'oracle' or (p_type == 'auto' and 'Oracle' in cloud_info['provider']):
        return OracleCloudProvider(cfg.get('oci', {}).get('config_path'))
    elif p_type == 'hook':
        return CustomHookProvider(cfg.get('provider', {}).get('hook_cmd', ''))
    else:
        return GenericProvider()

# Backwards compatibility alias
OracleManager = OracleCloudProvider

# ==============================================================================
# Cloudflare DNS Manager
# ==============================================================================

class CloudflareManager:
    def __init__(self, api_token, zone_name=''):
        self.api_token = api_token.strip() if api_token else ''
        self.zone_name = zone_name.strip()
        self.headers = {
            'Authorization': f'Bearer {self.api_token}',
            'Content-Type': 'application/json'
        }

    def verify_token(self):
        if not self.api_token:
            return False, 'API Token is empty'
        try:
            r = requests.get('https://api.cloudflare.com/client/v4/user/tokens/verify', headers=self.headers, timeout=5)
            res = r.json()
            if res.get('success'):
                return True, 'Token verified successfully'
            return False, res.get('messages', [{}])[0].get('message', 'Invalid token')
        except Exception as e:
            return False, str(e)

    def list_zones(self):
        if not self.api_token:
            return False, [], 'API Token is empty'
        try:
            r = requests.get('https://api.cloudflare.com/client/v4/zones?status=active', headers=self.headers, timeout=6)
            res = r.json()
            if res.get('success'):
                zones = [{'id': z['id'], 'name': z['name']} for z in res.get('result', [])]
                return True, zones, 'Zones retrieved successfully'
            errors = res.get('errors', [{}])[0].get('message', 'Failed to retrieve zones')
            return False, [], errors
        except Exception as e:
            return False, [], str(e)

    def update_dns_record(self, record_name='', new_ip=None):
        if not self.api_token:
            raise ValueError('Cloudflare API Token not configured')
        if not new_ip:
            raise ValueError('new_ip is required')

        # Get Zone ID
        url = f'https://api.cloudflare.com/client/v4/zones?name={self.zone_name}'
        r = requests.get(url, headers=self.headers, timeout=5)
        res = r.json()
        if not res.get('success') or not res.get('result'):
            raise ValueError(f'Zone {self.zone_name} not found in Cloudflare account.')
        zone_id = res['result'][0]['id']

        # Get DNS Record ID
        dns_url = f'https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records?type=A&name={record_name}'
        r = requests.get(dns_url, headers=self.headers, timeout=5)
        res = r.json()
        if not res.get('success') or not res.get('result'):
            # Create record if not found
            logger.info(f'Record {record_name} not found, creating new A record...')
            create_url = f'https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records'
            payload = {
                'type': 'A',
                'name': record_name,
                'content': new_ip,
                'ttl': 60,
                'proxied': False
            }
            r = requests.post(create_url, headers=self.headers, json=payload, timeout=5)
            c_res = r.json()
            if not c_res.get('success'):
                raise RuntimeError(f'Failed to create A record: {c_res.get("errors")}')
            return True

        record_id = res['result'][0]['id']

        # Update A Record
        update_url = f'https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}'
        payload = {
            'type': 'A',
            'name': record_name,
            'content': new_ip,
            'ttl': 60,
            'proxied': False
        }
        r = requests.put(update_url, headers=self.headers, json=payload, timeout=5)
        u_res = r.json()
        if not u_res.get('success'):
            raise RuntimeError(f'Failed to update DNS record: {u_res.get("errors")}')
        
        logger.info(f'Cloudflare DNS updated: {record_name} -> {new_ip}')
        return True

def generate_rsa_keypair(key_dir="/root/.oci"):
    os.makedirs(key_dir, exist_ok=True)
    key_path = os.path.join(key_dir, "oci_api_key.pem")
    pub_path = os.path.join(key_dir, "oci_api_key_public.pem")

    res = subprocess.run(
        f"openssl genrsa -out {key_path} 2048 && chmod 600 {key_path} && openssl rsa -pubout -in {key_path} -out {pub_path}",
        shell=True, capture_output=True, text=True
    )
    if res.returncode != 0:
        raise RuntimeError(f"OpenSSL failed: {res.stderr}")
    
    with open(pub_path, 'r', encoding='utf-8') as f:
        pub_content = f.read().strip()
    return pub_content, key_path

def save_oci_config(raw_config_text, key_path, oci_dir="/root/.oci"):
    os.makedirs(oci_dir, exist_ok=True)
    lines = raw_config_text.strip().splitlines()
    new_lines = []
    has_key_file = False
    for l in lines:
        l_s = l.strip()
        if l_s.startswith("key_file="):
            new_lines.append(f"key_file={key_path}")
            has_key_file = True
        elif l_s:
            new_lines.append(l_s)
    if not has_key_file:
        new_lines.append(f"key_file={key_path}")
    
    cfg_file = os.path.join(oci_dir, "config")
    with open(cfg_file, 'w', encoding='utf-8') as f:
        f.write("\n".join(new_lines) + "\n")
    os.chmod(cfg_file, 0o600)
    return cfg_file

if __name__ == '__main__':
    info = get_cloud_info()
    print("Detected Cloud Environment:", info)

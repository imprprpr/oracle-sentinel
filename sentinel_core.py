#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import time
import json
import socket
import logging
import subprocess
import requests
import psutil
import oci

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('OracleSentinel')

CONFIG_PATH = '/opt/oracle-sentinel/config.json'
METADATA_INSTANCE_URL = 'http://169.254.169.254/opc/v2/instance/'
METADATA_VNICS_URL = 'http://169.254.169.254/opc/v2/vnics/'

DEFAULT_CONFIG = {
    'cloudflare': {
        'api_token': '',
        'zone_name': '',
        'record_name': ''
    },
    'oci': {
        'auth_method': 'instance_principal',
        'config_path': '/home/ubuntu/.oci/config'
    },
    'monitor': {
        'interval_sec': 10,
        'loss_threshold': 80.0,
        'consecutive_failures': 5,
        'auto_heal_enabled': False
    }
}

class ConfigManager:
    @staticmethod
    def load():
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    # Merge with default in case of missing keys
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
            logger.error(f'Error writing {CONFIG_PATH}: {e}')
            return False

class SystemMonitor:
    def __init__(self):
        self.last_net = psutil.net_io_counters()
        self.last_time = time.time()
        self.consecutive_failures = 0

    def get_public_ip(self):
        providers = [
            'https://ip.sb',
            'https://api.ipify.org',
            'https://ifconfig.me/ip'
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
                timeout=3
            )
            data = dict(line.split('=', 1) for line in r.text.strip().split('\n') if '=' in line)
            if data.get('warp') in ('on', 'plus'):
                return {'status': 'active', 'ip': data.get('ip', 'Unknown'), 'loc': data.get('loc', 'US')}
        except Exception:
            pass
        return {'status': 'inactive', 'ip': 'N/A', 'loc': 'N/A'}

    def check_port_listening(self, port, proto='tcp'):
        try:
            for conn in psutil.net_connections(kind=proto):
                if conn.laddr and conn.laddr.port == port:
                    return True
        except Exception:
            pass
        return False

    def check_domestic_probes(self):
        targets = [
            ('AliDNS', '223.5.5.5', 53),
            ('Baidu', 'www.baidu.com', 443),
            ('Tencent', 'www.qq.com', 443)
        ]
        results = []
        latencies = []
        for name, host, port in targets:
            t0 = time.time()
            try:
                s = socket.create_connection((host, port), timeout=2.5)
                dt = round((time.time() - t0) * 1000, 1)
                s.close()
                results.append({'target': name, 'status': 'ok', 'latency': dt})
                latencies.append(dt)
            except Exception as e:
                results.append({'target': name, 'status': 'fail', 'latency': None, 'error': str(e)})

        loss_pct = round(((len(targets) - len(latencies)) / len(targets)) * 100, 1)
        avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else 0
        return {
            'loss_pct': loss_pct,
            'avg_latency': avg_latency,
            'details': results
        }

    def get_metrics(self):
        now = time.time()
        dt = max(now - self.last_time, 0.1)
        cur_net = psutil.net_io_counters()

        rx_bytes_sec = max(0, int((cur_net.bytes_recv - self.last_net.bytes_recv) / dt))
        tx_bytes_sec = max(0, int((cur_net.bytes_sent - self.last_net.bytes_sent) / dt))

        self.last_net = cur_net
        self.last_time = now

        mem = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=None)

        # Uptime
        uptime_sec = int(time.time() - psutil.boot_time())
        days, rem = divmod(uptime_sec, 86400)
        hours, rem = divmod(rem, 3600)
        mins, _ = divmod(rem, 60)
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

        # Status level
        if probes['loss_pct'] >= 80:
            health = 'critical'
        elif probes['loss_pct'] > 0:
            health = 'warning'
        else:
            health = 'healthy'

        return {
            'timestamp': int(time.time()),
            'health': health,
            'current_ip': pub_ip,
            'location': 'US Phoenix (Oracle Cloud HWcl:PHX-AD-1)',
            'probes': probes,
            'metrics': metrics,
            'nodes': nodes,
            'warp': warp
        }

class OracleManager:
    def __init__(self, config_path=None):
        self.metadata = self._get_metadata(METADATA_INSTANCE_URL)
        self.vnics_info = self._get_metadata(METADATA_VNICS_URL)
        
        self.compartment_id = self.metadata.get('compartmentId')
        self.instance_id = self.metadata.get('id')
        self.region = self.metadata.get('canonicalRegionName', 'us-phoenix-1')
        self.vnic_id = self.vnics_info[0].get('vnicId') if self.vnics_info else None
        self.client = None
        self.init_error = None
        
        try:
            self.client = self._init_client(config_path)
        except Exception as e:
            self.init_error = str(e)
            logger.warning(f'Oracle Client init deferred/failed: {e}')

    def _get_metadata(self, url):
        try:
            r = requests.get(url, headers={'Authorization': 'Bearer Oracle'}, timeout=3)
            return r.json()
        except Exception as e:
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
        except oci.exceptions.ServiceError as e:
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

        # Find existing public IP
        try:
            pub_ip_details = oci.core.models.GetPublicIpByPrivateIpIdDetails(private_ip_id=primary_priv_ip.id)
            pub_ip = self.client.get_public_ip_by_private_ip_id(pub_ip_details).data
            if pub_ip and pub_ip.id:
                logger.info(f'Releasing old Public IP: {pub_ip.ip_address} (OCID: {pub_ip.id})')
                self.client.delete_public_ip(pub_ip.id)
                time.sleep(2)
        except oci.exceptions.ServiceError as e:
            if e.status != 404:
                logger.warning(f'Notice on fetching old public IP: {e}')

        # Request new ephemeral public IP
        logger.info('Allocating new Ephemeral Public IP from Oracle Cloud Phoenix pool...')
        create_details = oci.core.models.CreatePublicIpDetails(
            compartment_id=self.compartment_id,
            lifetime='EPHEMERAL',
            private_ip_id=primary_priv_ip.id,
            display_name=f'sentinel-ephemeral-{int(time.time())}'
        )
        new_pub_ip = self.client.create_public_ip(create_details).data
        logger.info(f'Successfully assigned NEW Public IP: {new_pub_ip.ip_address}')
        return new_pub_ip.ip_address

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

    def update_dns_record(self, record_name='', new_ip=None):
        if not self.api_token:
            raise ValueError('Cloudflare API Token not configured')
        if not new_ip:
            raise ValueError('new_ip is required')

        # Get Zone ID
        url = f'https://api.cloudflare.com/client/v4/zones?name={self.zone_name}'
        r = requests.get(url, headers=self.headers, timeout=5)
        res = r.json()
        if not res.get('success') or len(res.get('result', [])) == 0:
            raise ValueError(f'Cloudflare Zone not found for {self.zone_name}')
        zone_id = res['result'][0]['id']

        # Get Record ID
        url = f'https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records?name={record_name}&type=A'
        r = requests.get(url, headers=self.headers, timeout=5)
        res = r.json()
        if not res.get('success') or len(res.get('result', [])) == 0:
            raise ValueError(f'DNS record for {record_name} not found in Cloudflare')
        record_id = res['result'][0]['id']
        old_ip = res['result'][0]['content']

        # Update Record
        update_url = f'https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}'
        data = {
            'type': 'A',
            'name': record_name,
            'content': new_ip,
            'ttl': 1,
            'proxied': False
        }
        update_res = requests.put(update_url, headers=self.headers, json=data, timeout=5).json()
        if update_res.get('success'):
            logger.info(f'Cloudflare DNS updated: {old_ip} -> {new_ip}')
            return True, old_ip
        else:
            errors = update_res.get('errors', [{'message': 'Unknown error'}])
            raise RuntimeError(f'Cloudflare DNS update failed: {errors}')


#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ==============================================================================
# VPSentinel - Multi-Node Sentinel Mesh Management
# ==============================================================================

import os
import json
import time
import logging
import urllib.request
import urllib.error
import ssl
import threading

logger = logging.getLogger('MeshManager')

CONFIG_PATH = '/opt/vpsentinel/config.json' if os.path.exists('/opt/vpsentinel/config.json') else (
    '/opt/oracle-sentinel/config.json' if os.path.exists('/opt/oracle-sentinel/config.json') else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
)

class MeshManager:
    _lock = threading.Lock()
    _node_cache = {}

    @classmethod
    def load_config(cls):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f'Error reading config for mesh: {e}')
        return {}

    @classmethod
    def save_config(cls, cfg):
        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f'Error saving mesh config: {e}')
            return False

    @classmethod
    def get_nodes(cls):
        cfg = cls.load_config()
        return cfg.get('mesh_nodes', [])

    @classmethod
    def save_nodes(cls, nodes):
        cfg = cls.load_config()
        cfg['mesh_nodes'] = nodes
        return cls.save_config(cfg)

    @classmethod
    def add_node(cls, name, host, api_token='', location='Global', tag='REMOTE', enabled=True):
        nodes = cls.get_nodes()
        node_id = f"node_{int(time.time())}_{len(nodes) + 1}"
        new_node = {
            'id': node_id,
            'name': name.strip(),
            'host': host.strip().rstrip('/'),
            'api_token': api_token.strip(),
            'location': location.strip(),
            'tag': tag.strip(),
            'enabled': bool(enabled),
            'created_at': int(time.time()),
            'last_status': {
                'online': False,
                'rtt_ms': 0,
                'cpu_pct': 0,
                'mem_pct': 0,
                'pub_ip': 'N/A',
                'checked_at': 0,
                'error': 'Unprobed'
            }
        }
        nodes.append(new_node)
        cls.save_nodes(nodes)
        return new_node

    @classmethod
    def update_node(cls, node_id, update_data):
        nodes = cls.get_nodes()
        for idx, n in enumerate(nodes):
            if n.get('id') == node_id:
                for k in ['name', 'host', 'api_token', 'location', 'tag', 'enabled']:
                    if k in update_data:
                        nodes[idx][k] = update_data[k]
                cls.save_nodes(nodes)
                return nodes[idx]
        return None

    @classmethod
    def delete_node(cls, node_id):
        nodes = cls.get_nodes()
        new_nodes = [n for n in nodes if n.get('id') != node_id]
        if len(new_nodes) < len(nodes):
            cls.save_nodes(new_nodes)
            return True
        return False

    @classmethod
    def probe_remote_node(cls, node):
        host = node.get('host', '')
        if not host:
            return {'online': False, 'rtt_ms': 0, 'error': 'No host specified', 'checked_at': int(time.time())}

        if not host.startswith('http://') and not host.startswith('https://'):
            url = f"https://{host}/api/status"
        else:
            url = f"{host}/api/status"

        token = node.get('api_token', '')
        headers = {'User-Agent': 'VPSentinel-Mesh/2.4'}
        if token:
            headers['Authorization'] = f"Bearer {token}"

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
                rtt = round((time.time() - t0) * 1000, 1)
                data = json.loads(resp.read().decode('utf-8'))
                metrics = data.get('metrics', {})
                return {
                    'online': True,
                    'rtt_ms': rtt,
                    'cpu_pct': metrics.get('cpu_pct', 0),
                    'mem_pct': metrics.get('mem_pct', 0),
                    'rx_speed_kb': metrics.get('rx_speed_kb', 0),
                    'tx_speed_kb': metrics.get('tx_speed_kb', 0),
                    'pub_ip': data.get('public_ip', 'N/A'),
                    'uptime': metrics.get('uptime', 'N/A'),
                    'warp': data.get('warp', {}).get('active', False),
                    'checked_at': int(time.time()),
                    'error': None
                }
        except Exception as e:
            rtt = round((time.time() - t0) * 1000, 1)
            return {
                'online': False,
                'rtt_ms': rtt,
                'cpu_pct': 0,
                'mem_pct': 0,
                'pub_ip': 'N/A',
                'checked_at': int(time.time()),
                'error': str(e)
            }

    @classmethod
    def get_mesh_overview(cls, local_state_func=None):
        nodes = cls.get_nodes()
        result_nodes = []

        # Local node
        if callable(local_state_func):
            try:
                local_state = local_state_func()
                metrics = local_state.get('metrics', {})
                result_nodes.append({
                    'id': 'local_master',
                    'name': 'Master 控制中心 (本机)',
                    'host': local_state.get('public_ip', '127.0.0.1'),
                    'location': local_state.get('cloud', {}).get('region', 'Local'),
                    'tag': 'MASTER',
                    'enabled': True,
                    'is_local': True,
                    'last_status': {
                        'online': True,
                        'rtt_ms': 1,
                        'cpu_pct': metrics.get('cpu_pct', 0),
                        'mem_pct': metrics.get('mem_pct', 0),
                        'rx_speed_kb': metrics.get('rx_speed_kb', 0),
                        'tx_speed_kb': metrics.get('tx_speed_kb', 0),
                        'pub_ip': local_state.get('public_ip', '127.0.0.1'),
                        'uptime': metrics.get('uptime', 'N/A'),
                        'checked_at': int(time.time())
                    }
                })
            except Exception as e:
                logger.error(f'Error getting local state for mesh: {e}')

        # Remote nodes with cache
        for n in nodes:
            cached = cls._node_cache.get(n['id'], n.get('last_status', {}))
            node_copy = dict(n)
            node_copy['last_status'] = cached
            node_copy['is_local'] = False
            result_nodes.append(node_copy)

        online_count = sum(1 for n in result_nodes if n.get('last_status', {}).get('online'))
        total_count = len(result_nodes)

        return {
            'total_nodes': total_count,
            'online_nodes': online_count,
            'nodes': result_nodes,
            'health_pct': round((online_count / total_count * 100) if total_count > 0 else 100.0, 1)
        }

    @classmethod
    def refresh_all_nodes(cls):
        nodes = cls.get_nodes()
        threads = []
        for n in nodes:
            if not n.get('enabled', True):
                continue
            def _probe(target_node):
                stat = cls.probe_remote_node(target_node)
                with cls._lock:
                    cls._node_cache[target_node['id']] = stat
                    target_node['last_status'] = stat
            t = threading.Thread(target=_probe, args=(n,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=6)
        cls.save_nodes(nodes)

    @classmethod
    def start_background_poller(cls, interval_sec=60):
        def _loop():
            logger.info("Starting background Sentinel Mesh node poller...")
            while True:
                try:
                    cls.refresh_all_nodes()
                except Exception as e:
                    logger.error(f"Mesh poller error: {e}")
                time.sleep(interval_sec)

        t = threading.Thread(target=_loop, name="MeshPollerDaemon", daemon=True)
        t.start()
        return t

if __name__ == '__main__':
    print("Mesh Overview:", MeshManager.get_mesh_overview())

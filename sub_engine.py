#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import json
import base64
import sqlite3
import logging
import urllib.parse
import yaml
from transit_mgr import TransitManager
from custom_node_mgr import CustomNodeManager

logger = logging.getLogger('SubEngine')
DB_PATH = '/etc/x-ui/x-ui.db'
CONFIG_PATH = '/opt/vpsentinel/config.json' if os.path.exists('/opt/vpsentinel/config.json') else (
    '/opt/oracle-sentinel/config.json' if os.path.exists('/opt/oracle-sentinel/config.json') else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
)

DEFAULT_RULES_CONFIG = {
    'adblock': True,
    'ai_group': True,
    'media_group': True,
    'auto_test': True,
    'direct_cn': True,
    'hy2_hop': True
}

class SubEngine:
    @staticmethod
    def get_rules_config():
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    rules = cfg.get('rules_config', DEFAULT_RULES_CONFIG)
                    return {**DEFAULT_RULES_CONFIG, **rules}
            except Exception as e:
                logger.error(f'Error reading rules config: {e}')
        return DEFAULT_RULES_CONFIG.copy()

    @staticmethod
    def save_rules_config(rules):
        try:
            cfg = {}
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
            cfg['rules_config'] = rules
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f'Error saving rules config: {e}')
            return False

    @staticmethod
    def get_server_ip():
        try:
            import sentinel_core
            mon = sentinel_core.SystemMonitor()
            ip = mon.get_public_ip()
            if ip and ip != '127.0.0.1':
                return ip
        except Exception:
            pass
        try:
            import urllib.request
            ip = urllib.request.urlopen('https://api.ipify.org', timeout=3).read().decode('utf-8').strip()
            if ip and ip != '127.0.0.1':
                return ip
        except Exception:
            pass
        return '129.146.230.81'

    @staticmethod
    def get_server_domain():
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    rec = cfg.get('cloudflare', {}).get('record_name')
                    if rec:
                        return rec
            except Exception:
                pass
        return 'vps.example.com'

    @staticmethod
    def extract_nodes_from_db():
        if not os.path.exists(DB_PATH):
            logger.error(f'Database {DB_PATH} not found.')
            return []

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, tag, port, protocol, settings, stream_settings, enable FROM inbounds WHERE enable = 1;")
        rows = cursor.fetchall()
        conn.close()

        nodes = []
        domain = SubEngine.get_server_domain()
        server_ip = SubEngine.get_server_ip()

        for row in rows:
            inbound_id, tag, port, proto, st_raw, ss_raw, enabled = row
            try:
                st = json.loads(st_raw) if st_raw else {}
                ss = json.loads(ss_raw) if ss_raw else {}
            except Exception:
                continue

            clients = st.get('clients', [])
            client = clients[0] if clients else {}

            if proto == 'vless' and ss.get('security') == 'reality':
                rs = ss.get('realitySettings', {})
                rs_st = rs.get('settings', {})
                node = {
                    'name': '🇺🇸 Oracle-美西-Reality',
                    'type': 'vless',
                    'server': server_ip,
                    'port': port,
                    'uuid': client.get('id', ''),
                    'network': ss.get('network', 'tcp'),
                    'tls': True,
                    'udp': True,
                    'flow': client.get('flow', 'xtls-rprx-vision'),
                    'servername': rs.get('serverNames', ['swdist.apple.com'])[0] if rs.get('serverNames') else 'swdist.apple.com',
                    'reality-opts': {
                        'public-key': rs_st.get('publicKey', ''),
                        'short-id': rs.get('shortIds', ['cb2ebc41'])[0] if rs.get('shortIds') else ''
                    },
                    'client-fingerprint': rs_st.get('fingerprint', 'chrome')
                }
                nodes.append(('reality', node))

            elif proto == 'hysteria':
                node = {
                    'name': '🇺🇸 Oracle-美西-Hy2',
                    'type': 'hysteria2',
                    'server': server_ip,
                    'port': port,
                    'password': client.get('auth', ''),
                    'sni': ss.get('tlsSettings', {}).get('serverName', domain),
                    'skip-cert-verify': True
                }
                nodes.append(('hy2', node))

            elif proto == 'trojan':
                node = {
                    'name': '🇺🇸 Oracle-美西-Trojan',
                    'type': 'trojan',
                    'server': server_ip,
                    'port': port,
                    'password': client.get('password', ''),
                    'sni': ss.get('tlsSettings', {}).get('serverName', domain),
                    'skip-cert-verify': True,
                    'client-fingerprint': 'chrome',
                    'udp': True
                }
                nodes.append(('trojan', node))

        return nodes

    # --- 1. Clash / Mihomo YAML Generator ---
    @staticmethod
    def generate_clash_yaml(rules_override=None):
        rules_cfg = rules_override or SubEngine.get_rules_config()
        raw_nodes = SubEngine.extract_nodes_from_db()
        transits = TransitManager.get_transits()

        proxies = []
        node_names = []

        # 1. Direct Nodes
        for ntype, node_data in raw_nodes:
            n = node_data.copy()
            if ntype == 'hy2' and rules_cfg.get('hy2_hop', True):
                n['ports'] = '20000-40000'
                n['name'] = '🇺🇸 Oracle-美西-Hy2 (跳跃)'
            proxies.append(n)
            node_names.append(n['name'])

        # 2. Transit / Relay Nodes
        for t in transits:
            if not t.get('enabled', True):
                continue
            t_name = t.get('name', '中转')
            t_host = t.get('host', '')
            if not t_host:
                continue

            for ntype, base_node in raw_nodes:
                relay_node = base_node.copy()
                if ntype == 'hy2':
                    relay_node['name'] = f'[{t_name}] Hy2专线'
                    relay_node['server'] = t_host
                    relay_node['port'] = t.get('hy2_port', 20443)
                    if 'ports' in relay_node:
                        del relay_node['ports']
                    proxies.append(relay_node)
                    node_names.append(relay_node['name'])
                elif ntype == 'reality':
                    relay_node['name'] = f'[{t_name}] Reality专线'
                    relay_node['server'] = t_host
                    relay_node['port'] = t.get('reality_port', 28443)
                    proxies.append(relay_node)
                    node_names.append(relay_node['name'])
                elif ntype == 'trojan':
                    relay_node['name'] = f'[{t_name}] Trojan专线'
                    relay_node['server'] = t_host
                    relay_node['port'] = t.get('trojan_port', 22083)
                    proxies.append(relay_node)
                    node_names.append(relay_node['name'])

        # 3. Custom / External Standalone Nodes
        custom_nodes = CustomNodeManager.get_custom_nodes()
        for cn in custom_nodes:
            if not cn.get('enabled', True):
                continue
            cp = CustomNodeManager.to_clash_proxy(cn)
            if cp:
                proxies.append(cp)
                node_names.append(cp['name'])

        if not node_names:
            node_names = ['DIRECT']

        proxy_groups = []

        # Group: 🚀 节点选择
        group_select_proxies = []
        if rules_cfg.get('auto_test', True):
            group_select_proxies.append('⚡ 自动优选')
        group_select_proxies.extend(node_names)
        group_select_proxies.append('DIRECT')

        proxy_groups.append({
            'name': '🚀 节点选择',
            'type': 'select',
            'proxies': group_select_proxies
        })

        # Group: ⚡ 自动优选
        if rules_cfg.get('auto_test', True):
            proxy_groups.append({
                'name': '⚡ 自动优选',
                'type': 'url-test',
                'url': 'https://www.gstatic.com/generate_204',
                'interval': 300,
                'tolerance': 50,
                'proxies': list(node_names)
            })

        # Group: 🤖 AI 智能服务
        if rules_cfg.get('ai_group', True):
            proxy_groups.append({
                'name': '🤖 AI 智能服务',
                'type': 'select',
                'proxies': ['🚀 节点选择'] + list(node_names)
            })

        # Group: 🎬 国际流媒体
        if rules_cfg.get('media_group', True):
            proxy_groups.append({
                'name': '🎬 国际流媒体',
                'type': 'select',
                'proxies': ['🚀 节点选择'] + list(node_names)
            })

        # Group: 🛑 广告拦截
        if rules_cfg.get('adblock', True):
            proxy_groups.append({
                'name': '🛑 广告拦截',
                'type': 'select',
                'proxies': ['REJECT', 'DIRECT']
            })

        # Group: 🎯 全球直连
        proxy_groups.append({
            'name': '🎯 全球直连',
            'type': 'select',
            'proxies': ['DIRECT']
        })

        rules = [
            'IP-CIDR,127.0.0.0/8,🎯 全球直连,no-resolve',
            'IP-CIDR,172.16.0.0/12,🎯 全球直连,no-resolve',
            'IP-CIDR,192.168.0.0/16,🎯 全球直连,no-resolve',
            'IP-CIDR,10.0.0.0/8,🎯 全球直连,no-resolve',
            'IP-CIDR,100.64.0.0/10,🎯 全球直连,no-resolve',
            'IP-CIDR6,fc00::/7,🎯 全球直连,no-resolve',
            'IP-CIDR6,fe80::/10,🎯 全球直连,no-resolve',
            'IP-CIDR6,::1/128,🎯 全球直连,no-resolve'
        ]

        if rules_cfg.get('adblock', True):
            rules.extend([
                'GEOSITE,category-ads-all,🛑 广告拦截',
                'DOMAIN-KEYWORD,adservice,🛑 广告拦截'
            ])

        if rules_cfg.get('ai_group', True):
            rules.extend([
                'GEOSITE,openai,🤖 AI 智能服务',
                'GEOSITE,anthropic,🤖 AI 智能服务',
                'DOMAIN-SUFFIX,openai.com,🤖 AI 智能服务',
                'DOMAIN-SUFFIX,chatgpt.com,🤖 AI 智能服务',
                'DOMAIN-SUFFIX,oaistatic.com,🤖 AI 智能服务',
                'DOMAIN-SUFFIX,oaiusercontent.com,🤖 AI 智能服务',
                'DOMAIN-SUFFIX,anthropic.com,🤖 AI 智能服务',
                'DOMAIN-SUFFIX,claude.ai,🤖 AI 智能服务',
                'DOMAIN-SUFFIX,claudecontent.com,🤖 AI 智能服务',
                'DOMAIN-KEYWORD,openai,🤖 AI 智能服务',
                'DOMAIN-KEYWORD,anthropic,🤖 AI 智能服务',
                'DOMAIN-KEYWORD,claude,🤖 AI 智能服务'
            ])

        if rules_cfg.get('media_group', True):
            rules.extend([
                'GEOSITE,netflix,🎬 国际流媒体',
                'GEOSITE,youtube,🎬 国际流媒体',
                'GEOSITE,disney,🎬 国际流媒体',
                'GEOSITE,spotify,🎬 国际流媒体',
                'DOMAIN-SUFFIX,netflix.com,🎬 国际流媒体',
                'DOMAIN-SUFFIX,nflxext.com,🎬 国际流媒体',
                'DOMAIN-SUFFIX,nflximg.net,🎬 国际流媒体',
                'DOMAIN-SUFFIX,nflxvideo.net,🎬 国际流媒体',
                'DOMAIN-SUFFIX,youtube.com,🎬 国际流媒体',
                'DOMAIN-SUFFIX,googlevideo.com,🎬 国际流媒体',
                'DOMAIN-SUFFIX,disneyplus.com,🎬 国际流媒体',
                'DOMAIN-SUFFIX,spotify.com,🎬 国际流媒体'
            ])

        rules.extend([
            'GEOSITE,github,🚀 节点选择',
            'GEOSITE,telegram,🚀 节点选择',
            'GEOSITE,twitter,🚀 节点选择',
            'DOMAIN-SUFFIX,github.com,🚀 节点选择',
            'DOMAIN-SUFFIX,telegram.org,🚀 节点选择',
            'DOMAIN-SUFFIX,twitter.com,🚀 节点选择',
            'DOMAIN-SUFFIX,x.com,🚀 节点选择'
        ])

        if rules_cfg.get('direct_cn', True):
            rules.extend([
                'GEOSITE,cn,🎯 全球直连',
                'GEOIP,CN,🎯 全球直连'
            ])

        rules.append('MATCH,🚀 节点选择')

        server_ip = SubEngine.get_server_ip()
        domain = SubEngine.get_server_domain()
        clash_config = {
            'port': 7890,
            'socks-port': 7891,
            'mixed-port': 7892,
            'allow-lan': True,
            'mode': 'rule',
            'log-level': 'info',
            'unified-delay': True,
            'hosts': {
                domain: server_ip
            },
            'dns': {
                'enable': True,
                'listen': '0.0.0.0:1053',
                'enhanced-mode': 'fake-ip',
                'fake-ip-range': '198.18.0.1/16',
                'default-nameserver': [
                    '223.5.5.5',
                    '119.29.29.29',
                    '114.114.114.114'
                ],
                'nameserver': [
                    '223.5.5.5',
                    '119.29.29.29'
                ],
                'fallback': [
                    'https://1.1.1.1/dns-query',
                    'https://8.8.8.8/dns-query'
                ],
                'fallback-filter': {
                    'geoip': True,
                    'geoip-code': 'CN',
                    'ipcidr': [
                        '240.0.0.0/4'
                    ]
                }
            },
            'geox-url': {
                'geoip': f'https://{domain}:20540/static/geo/geoip.dat',
                'geosite': f'https://{domain}:20540/static/geo/geosite.dat',
                'mmdb': f'https://{domain}:20540/static/geo/country.mmdb'
            },
            'proxies': proxies,
            'proxy-groups': proxy_groups,
            'rules': rules
        }

        return yaml.dump(clash_config, allow_unicode=True, sort_keys=False)

    # --- 2. v2rayN / Shadowrocket / 通用 Base64 订阅 ---
    @staticmethod
    def generate_v2ray_base64():
        raw_nodes = SubEngine.extract_nodes_from_db()
        transits = TransitManager.get_transits()
        rules_cfg = SubEngine.get_rules_config()

        links = []

        # 1. Direct Nodes
        for ntype, n in raw_nodes:
            if ntype == 'reality':
                name = urllib.parse.quote('Oracle-US (Reality)')
                pbk = n['reality-opts']['public-key']
                sid = n['reality-opts']['short-id']
                sni = n['servername']
                fp = n['client-fingerprint']
                flow = n['flow']
                link = f"vless://{n['uuid']}@{n['server']}:{n['port']}?type=tcp&security=reality&pbk={pbk}&fp={fp}&sni={sni}&sid={sid}&flow={flow}#{name}"
                links.append(link)

            elif ntype == 'hy2':
                hop = rules_cfg.get('hy2_hop', True)
                name = urllib.parse.quote('Oracle-Hy2 (端口跳跃)' if hop else 'Oracle-Hy2')
                mport_param = "&mport=20000-40000" if hop else ""
                link = f"hysteria2://{n['password']}@{n['server']}:{n['port']}?sni={n['sni']}&insecure=0{mport_param}#{name}"
                links.append(link)

            elif ntype == 'trojan':
                name = urllib.parse.quote('Oracle-Trojan (TLS)')
                link = f"trojan://{n['password']}@{n['server']}:{n['port']}?security=tls&sni={n['sni']}&type=tcp#{name}"
                links.append(link)

        # 2. Transit Nodes
        for t in transits:
            if not t.get('enabled', True):
                continue
            t_name = t.get('name', '中转')
            t_host = t.get('host', '')
            if not t_host:
                continue

            for ntype, n in raw_nodes:
                if ntype == 'reality':
                    name = urllib.parse.quote(f"[{t_name}] Reality专线")
                    pbk = n['reality-opts']['public-key']
                    sid = n['reality-opts']['short-id']
                    sni = n['servername']
                    fp = n['client-fingerprint']
                    flow = n['flow']
                    port = t.get('reality_port', 28443)
                    link = f"vless://{n['uuid']}@{t_host}:{port}?type=tcp&security=reality&pbk={pbk}&fp={fp}&sni={sni}&sid={sid}&flow={flow}#{name}"
                    links.append(link)

                elif ntype == 'hy2':
                    name = urllib.parse.quote(f"[{t_name}] Hy2专线")
                    port = t.get('hy2_port', 20443)
                    link = f"hysteria2://{n['password']}@{t_host}:{port}?sni={n['sni']}&insecure=0#{name}"
                    links.append(link)

                elif ntype == 'trojan':
                    name = urllib.parse.quote(f"[{t_name}] Trojan专线")
                    port = t.get('trojan_port', 22083)
                    link = f"trojan://{n['password']}@{t_host}:{port}?security=tls&sni={n['sni']}&type=tcp#{name}"
                    links.append(link)

        # 3. Custom / External Standalone Nodes
        custom_nodes = CustomNodeManager.get_custom_nodes()
        for cn in custom_nodes:
            if not cn.get('enabled', True):
                continue
            link = CustomNodeManager.to_share_link(cn)
            if link:
                links.append(link)

        joined_text = "\n".join(links) + "\n"
        return base64.b64encode(joined_text.encode('utf-8')).decode('utf-8')

    # --- 3. Sing-box JSON Generator ---
    @staticmethod
    def generate_singbox_json():
        raw_nodes = SubEngine.extract_nodes_from_db()
        transits = TransitManager.get_transits()

        outbounds = []
        node_tags = []

        # 1. Direct Nodes
        for ntype, n in raw_nodes:
            if ntype == 'reality':
                tag = 'Oracle-US'
                outbounds.append({
                    'type': 'vless',
                    'tag': tag,
                    'server': n['server'],
                    'server_port': n['port'],
                    'uuid': n['uuid'],
                    'flow': n['flow'],
                    'network': 'tcp',
                    'tls': {
                        'enabled': True,
                        'server_name': n['servername'],
                        'reality': {
                            'enabled': True,
                            'public_key': n['reality-opts']['public-key'],
                            'short_id': n['reality-opts']['short-id']
                        },
                        'utls': {
                            'enabled': True,
                            'fingerprint': 'chrome'
                        }
                    },
                    'packet_encoding': 'xudp'
                })
                node_tags.append(tag)

            elif ntype == 'hy2':
                tag = 'Oracle-Hy2'
                outbounds.append({
                    'type': 'hysteria2',
                    'tag': tag,
                    'server': n['server'],
                    'server_port': n['port'],
                    'up_mbps': 100,
                    'down_mbps': 100,
                    'password': n['password'],
                    'tls': {
                        'enabled': True,
                        'server_name': n['sni']
                    }
                })
                node_tags.append(tag)

            elif ntype == 'trojan':
                tag = 'Oracle-Trojan'
                outbounds.append({
                    'type': 'trojan',
                    'tag': tag,
                    'server': n['server'],
                    'server_port': n['port'],
                    'password': n['password'],
                    'tls': {
                        'enabled': True,
                        'server_name': n['sni']
                    }
                })
                node_tags.append(tag)

        # 2. Transit Nodes
        for t in transits:
            if not t.get('enabled', True):
                continue
            t_name = t.get('name', '中转')
            t_host = t.get('host', '')
            if not t_host:
                continue

            for ntype, n in raw_nodes:
                if ntype == 'reality':
                    tag = f'[{t_name}] Reality专线'
                    outbounds.append({
                        'type': 'vless',
                        'tag': tag,
                        'server': t_host,
                        'server_port': t.get('reality_port', 28443),
                        'uuid': n['uuid'],
                        'flow': n['flow'],
                        'network': 'tcp',
                        'tls': {
                            'enabled': True,
                            'server_name': n['servername'],
                            'reality': {
                                'enabled': True,
                                'public_key': n['reality-opts']['public-key'],
                                'short_id': n['reality-opts']['short-id']
                            },
                            'utls': {'enabled': True, 'fingerprint': 'chrome'}
                        },
                        'packet_encoding': 'xudp'
                    })
                    node_tags.append(tag)
                elif ntype == 'hy2':
                    tag = f'[{t_name}] Hy2专线'
                    outbounds.append({
                        'type': 'hysteria2',
                        'tag': tag,
                        'server': t_host,
                        'server_port': t.get('hy2_port', 20443),
                        'up_mbps': 100,
                        'down_mbps': 100,
                        'password': n['password'],
                        'tls': {'enabled': True, 'server_name': n['sni']}
                    })
                    node_tags.append(tag)
                elif ntype == 'trojan':
                    tag = f'[{t_name}] Trojan专线'
                    outbounds.append({
                        'type': 'trojan',
                        'tag': tag,
                        'server': t_host,
                        'server_port': t.get('trojan_port', 22083),
                        'password': n['password'],
                        'tls': {'enabled': True, 'server_name': n['sni']}
                    })
                    node_tags.append(tag)

        # 3. Custom / External Standalone Nodes
        custom_nodes = CustomNodeManager.get_custom_nodes()
        for cn in custom_nodes:
            if not cn.get('enabled', True):
                continue
            sb_out = CustomNodeManager.to_singbox_outbound(cn)
            if sb_out:
                outbounds.append(sb_out)
                node_tags.append(sb_out['tag'])

        if not node_tags:
            node_tags = ['direct']

        # Select & URLTest groups
        selector_outbounds = ['urltest'] + node_tags + ['direct']
        head_groups = [
            {'type': 'selector', 'tag': 'select', 'outbounds': selector_outbounds},
            {'type': 'urltest', 'tag': 'urltest', 'outbounds': list(node_tags), 'url': 'https://www.gstatic.com/generate_204', 'interval': '5m'},
            {'type': 'direct', 'tag': 'direct'},
            {'type': 'block', 'tag': 'block'},
            {'type': 'dns', 'tag': 'dns-out'}
        ]

        all_outbounds = head_groups + outbounds

        singbox_config = {
            'dns': {
                'servers': [
                    {'tag': 'remote', 'address': 'https://1.1.1.1/dns-query', 'detour': 'select'},
                    {'tag': 'local', 'address': '223.5.5.5', 'detour': 'direct'}
                ],
                'rules': [
                    {'geosite': 'cn', 'server': 'local'},
                    {'geoip': 'cn', 'server': 'local'}
                ]
            },
            'inbounds': [
                {'type': 'mixed', 'tag': 'mixed-in', 'listen': '127.0.0.1', 'listen_port': 2080}
            ],
            'outbounds': all_outbounds,
            'route': {
                'rules': [
                    {'ip_is_private': True, 'outbound': 'direct'},
                    {'geosite': 'category-ads-all', 'outbound': 'block'},
                    {'geosite': 'openai', 'outbound': 'select'},
                    {'geosite': 'netflix', 'outbound': 'select'},
                    {'geoip': 'cn', 'outbound': 'direct'},
                    {'geosite': 'cn', 'outbound': 'direct'}
                ],
                'auto_detect_interface': True
            }
        }

        return json.dumps(singbox_config, indent=2, ensure_ascii=False)

if __name__ == '__main__':
    print("V2Ray Base64 length:", len(SubEngine.generate_v2ray_base64()))
    print("Sing-box Outbounds:", len(json.loads(SubEngine.generate_singbox_json())['outbounds']))

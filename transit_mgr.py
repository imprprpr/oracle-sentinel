#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import json
import time
import logging

logger = logging.getLogger('TransitManager')
CONFIG_PATH = '/opt/vpsentinel/config.json' if os.path.exists('/opt/vpsentinel/config.json') else (
    '/opt/oracle-sentinel/config.json' if os.path.exists('/opt/oracle-sentinel/config.json') else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
)

class TransitManager:
    @staticmethod
    def get_transits():
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    return cfg.get('transits', [])
            except Exception as e:
                logger.error(f'Failed to load transits from config: {e}')
        return []

    @staticmethod
    def save_transits(transits_list):
        try:
            cfg = {}
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
            cfg['transits'] = transits_list
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f'Failed to save transits: {e}')
            return False

    @staticmethod
    def add_transit(name, host, hy2_port=20443, reality_port=28443, trojan_port=22083):
        transits = TransitManager.get_transits()
        item = {
            'id': f'transit_{int(time.time())}',
            'name': name.strip(),
            'host': host.strip(),
            'hy2_port': int(hy2_port),
            'reality_port': int(reality_port),
            'trojan_port': int(trojan_port),
            'enabled': True,
            'created_at': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        transits.append(item)
        TransitManager.save_transits(transits)
        return item

    @staticmethod
    def delete_transit(transit_id):
        transits = TransitManager.get_transits()
        filtered = [t for t in transits if t.get('id') != transit_id]
        TransitManager.save_transits(filtered)
        return True

    @staticmethod
    def toggle_transit(transit_id, enabled):
        transits = TransitManager.get_transits()
        for t in transits:
            if t.get('id') == transit_id:
                t['enabled'] = enabled
                break
        TransitManager.save_transits(transits)
        return True

    @staticmethod
    def generate_realm_script(target_host='vps.example.com'):
        """Generates a 1-line realm installation & forwarding script for the transit server."""
        return f"""#!/bin/bash
# One-click Transit Port Forwarder via Realm
set -e
TARGET="{target_host}"
echo ">>> Installing Realm port forwarder on transit server..."
mkdir -p /opt/realm
ARCH=$(uname -m)
if [ "$ARCH" = "x86_64" ]; then
    RURL="https://github.com/zhboner/realm/releases/latest/download/realm-x86_64-unknown-linux-gnu.tar.gz"
elif [ "$ARCH" = "aarch64" ]; then
    RURL="https://github.com/zhboner/realm/releases/latest/download/realm-aarch64-unknown-linux-gnu.tar.gz"
else
    echo "Unsupported architecture: $ARCH" && exit 1
fi

curl -fsSL "$RURL" -o /tmp/realm.tar.gz
tar -xvf /tmp/realm.tar.gz -C /opt/realm/
chmod +x /opt/realm/realm

cat << 'RCFG' > /opt/realm/config.toml
[log]
level = "warn"

[[endpoints]]
listen = "0.0.0.0:20443"
remote = "$TARGET:443"

[[endpoints]]
listen = "0.0.0.0:28443"
remote = "$TARGET:8443"

[[endpoints]]
listen = "0.0.0.0:22083"
remote = "$TARGET:2083"
RCFG

sed -i "s/\\$TARGET/$TARGET/g" /opt/realm/config.toml

cat << 'RSERVICE' > /etc/systemd/system/realm.service
[Unit]
Description=Realm Port Forwarder
After=network.target

[Service]
Type=simple
User=root
ExecStart=/opt/realm/realm -c /opt/realm/config.toml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
RSERVICE

systemctl daemon-reload
systemctl enable realm
systemctl restart realm
echo ">>> Realm transit service started successfully!"
systemctl status realm --no-pager
"""

if __name__ == '__main__':
    print("TransitManager loaded.")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import json
import time
import logging
from sentinel_core import ConfigManager

logger = logging.getLogger('TransitManager')

class TransitManager:
    @staticmethod
    def get_transits():
        cfg = ConfigManager.load()
        return cfg.get('transits', [])

    @staticmethod
    def save_transits(transits_list):
        cfg = ConfigManager.load()
        cfg['transits'] = transits_list
        return ConfigManager.save(cfg)

    @staticmethod
    def add_transit(name, host, hy2_port=20443, reality_port=28443, trojan_port=22083):
        for p, label in [(hy2_port, 'hy2_port'), (reality_port, 'reality_port'), (trojan_port, 'trojan_port')]:
            p_int = int(p)
            if not (1 <= p_int <= 65535):
                raise ValueError(f"Invalid port for {label}: {p}. Port must be between 1 and 65535.")

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

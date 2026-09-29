#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VPSentinel CLI tool for managing custom standalone nodes.
Usage:
  python3 scripts/add-custom-node.py "vless://..."
  python3 scripts/add-custom-node.py "hysteria2://..."
  python3 scripts/add-custom-node.py --list
  python3 scripts/add-custom-node.py --delete <node_id>
"""

import sys
import os

# Ensure parent directory is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from custom_node_mgr import CustomNodeManager

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    arg = sys.argv[1].strip()

    if arg in ('--list', '-l'):
        nodes = CustomNodeManager.get_custom_nodes()
        if not nodes:
            print("No custom nodes configured.")
            return
        print(f"=== Custom Nodes ({len(nodes)}) ===")
        for i, n in enumerate(nodes, 1):
            status = "[ACTIVE]" if n.get('enabled', True) else "[DISABLED]"
            print(f"[{i}] ID: {n.get('id')} | Name: {n.get('name')} | Type: {n.get('type')} | Server: {n.get('server')}:{n.get('port')} | {status}")
        return

    if arg in ('--delete', '-d'):
        if len(sys.argv) < 3:
            print("Error: Missing node ID to delete.")
            sys.exit(1)
        node_id = sys.argv[2].strip()
        CustomNodeManager.delete_custom_node(node_id)
        print(f"[OK] Deleted node {node_id}")
        return

    # Treat as node share link
    link = arg
    try:
        res = CustomNodeManager.add_custom_node(link)
        print("[SUCCESS] Custom node added successfully!")
        print(f"  Name:   {res.get('name')}")
        print(f"  Type:   {res.get('type')}")
        print(f"  Server: {res.get('server')}:{res.get('port')}")
        print(f"  ID:     {res.get('id')}")
        print("\nAll subscriptions (/sub/clash, /sub/v2ray, /sub/singbox) will now automatically include this node!")
    except Exception as e:
        print(f"[ERROR] Error adding node: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()

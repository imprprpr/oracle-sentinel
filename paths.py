#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Oracle Sentinel - Central Paths Resolution Module
# ==============================================================================

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def get_config_path() -> str:
    """
    Returns the path to config.json.
    Supports VPSENTINEL_CONFIG_PATH and VPSENTINEL_HOME environment variables,
    falling back to standard system paths and local workspace directory.
    """
    env_cfg = os.environ.get('VPSENTINEL_CONFIG_PATH')
    if env_cfg:
        return env_cfg

    home = os.environ.get('VPSENTINEL_HOME')
    if home:
        return os.path.join(home, 'config.json')

    if os.path.exists('/opt/vpsentinel/config.json'):
        return '/opt/vpsentinel/config.json'
    if os.path.exists('/opt/oracle-sentinel/config.json'):
        return '/opt/oracle-sentinel/config.json'
    return os.path.join(BASE_DIR, 'config.json')


CONFIG_PATH = get_config_path()
STATIC_PATH = '/opt/vpsentinel/static' if os.path.exists('/opt/vpsentinel/static') else (
    '/opt/oracle-sentinel/static' if os.path.exists('/opt/oracle-sentinel/static') else os.path.join(BASE_DIR, 'static')
)
CERT_DIR = os.environ.get('VPSENTINEL_CERT_DIR') or os.path.join(BASE_DIR, 'cert')
TRAFFIC_DB_PATH = '/opt/vpsentinel/traffic.db' if os.path.exists('/opt/vpsentinel') else (
    '/opt/oracle-sentinel/traffic.db' if os.path.exists('/opt/oracle-sentinel') else os.path.join(BASE_DIR, 'traffic.db')
)

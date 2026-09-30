#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import time
import json
import socket
import sqlite3
import asyncio
import logging
import threading
import hmac
import secrets
import ipaddress
from typing import List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Response, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from pydantic import BaseModel, field_validator
import requests

import sentinel_core
import sub_engine
import transit_mgr
import custom_node_mgr
import notification
import ip_audit
import speedtest_mgr
import auth_mgr
import traffic_mgr
import mesh_mgr
import bot_mgr
import clean_ip_mgr
import cert_sync_mgr

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('SentinelAPI')

app = FastAPI(title='VPSentinel Control Center', docs_url=None, redoc_url=None, openapi_url=None)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_PATH = '/opt/vpsentinel/static' if os.path.exists('/opt/vpsentinel/static') else (
    '/opt/oracle-sentinel/static' if os.path.exists('/opt/oracle-sentinel/static') else os.path.join(BASE_DIR, 'static')
)
METACUBEXD_PATH = os.path.join(STATIC_PATH, 'metacubexd')
NUXT_PATH = os.path.join(METACUBEXD_PATH, '_nuxt')

monitor = sentinel_core.SystemMonitor()
cfg_mgr = sentinel_core.ConfigManager()
auth = auth_mgr.AuthManager(cfg_mgr)

# Default trusted proxy networks: loopback and Cloudflare official edge ranges
DEFAULT_TRUSTED_PROXY_NETWORKS = [
    ipaddress.ip_network('127.0.0.0/8', strict=False),
    ipaddress.ip_network('::1/128', strict=False),
    ipaddress.ip_network('173.245.48.0/20', strict=False),
    ipaddress.ip_network('103.21.244.0/22', strict=False),
    ipaddress.ip_network('103.22.200.0/22', strict=False),
    ipaddress.ip_network('103.31.4.0/22', strict=False),
    ipaddress.ip_network('141.101.64.0/18', strict=False),
    ipaddress.ip_network('108.162.192.0/18', strict=False),
    ipaddress.ip_network('190.93.240.0/20', strict=False),
    ipaddress.ip_network('188.114.96.0/20', strict=False),
    ipaddress.ip_network('197.234.240.0/22', strict=False),
    ipaddress.ip_network('198.41.128.0/17', strict=False),
    ipaddress.ip_network('162.158.0.0/15', strict=False),
    ipaddress.ip_network('104.16.0.0/13', strict=False),
    ipaddress.ip_network('104.24.0.0/14', strict=False),
    ipaddress.ip_network('172.64.0.0/13', strict=False),
    ipaddress.ip_network('131.0.72.0/22', strict=False),
    ipaddress.ip_network('2400:cb00::/32', strict=False),
    ipaddress.ip_network('2606:4700::/32', strict=False),
    ipaddress.ip_network('2803:f800::/32', strict=False),
    ipaddress.ip_network('2405:b500::/32', strict=False),
    ipaddress.ip_network('2405:8100::/32', strict=False),
    ipaddress.ip_network('2a06:98c0::/29', strict=False),
    ipaddress.ip_network('2c0f:f248::/32', strict=False)
]

def is_trusted_peer(peer_ip: str, custom_cidrs: Optional[List[str]] = None) -> bool:
    if not peer_ip:
        return False
    try:
        ip_obj = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False

    networks = list(DEFAULT_TRUSTED_PROXY_NETWORKS)
    if custom_cidrs:
        for cidr in custom_cidrs:
            try:
                networks.append(ipaddress.ip_network(cidr, strict=False))
            except ValueError:
                pass

    for net in networks:
        if ip_obj in net:
            return True
    return False

def resolve_client_ip(request: Request, custom_cidrs: Optional[List[str]] = None) -> str:
    peer_ip = request.client.host if request.client else ""
    if not is_trusted_peer(peer_ip, custom_cidrs):
        return peer_ip

    headers = getattr(request, 'headers', {})
    cf_ip = None
    xfwd = None
    if hasattr(headers, 'items'):
        for k, v in headers.items():
            kl = k.lower()
            if kl == 'cf-connecting-ip' and not cf_ip:
                cf_ip = v
            elif kl == 'x-forwarded-for' and not xfwd:
                xfwd = v
    elif hasattr(headers, 'get'):
        cf_ip = headers.get('cf-connecting-ip') or headers.get('CF-Connecting-IP')
        xfwd = headers.get('x-forwarded-for') or headers.get('X-Forwarded-For')

    if cf_ip:
        return cf_ip.strip()
    if xfwd:
        return xfwd.split(',')[0].strip()
    return peer_ip

def mask_token(token: str, head: int = 4, tail: int = 4) -> str:
    if not token:
        return ""
    if len(token) <= head + tail:
        return "****"
    return f"{token[:head]}****{token[-tail:]}"

def redact_notifications(notifications: dict) -> dict:
    if not isinstance(notifications, dict):
        return {}
    redacted = json.loads(json.dumps(notifications))
    tg = redacted.get('telegram', {})
    if isinstance(tg, dict) and tg.get('bot_token'):
        tg['bot_token'] = mask_token(tg['bot_token'])
    dc = redacted.get('discord', {})
    if isinstance(dc, dict) and dc.get('webhook_url'):
        dc['webhook_url'] = mask_token(dc['webhook_url'], head=8, tail=4)
    bark = redacted.get('bark', {})
    if isinstance(bark, dict) and bark.get('bark_key'):
        bark['bark_key'] = mask_token(bark['bark_key'])
    cw = redacted.get('custom_webhook', {})
    if isinstance(cw, dict) and cw.get('url'):
        cw['url'] = mask_token(cw['url'], head=8, tail=4)
    return redacted

class LoginRequest(BaseModel):
    username: str
    password: str

class UpdatePasswordRequest(BaseModel):
    old_password: str
    new_password: str

class SecuritySettingsRequest(BaseModel):
    auth_enabled: Optional[bool] = None
    secret_path: Optional[str] = None
    enable_host_guard: Optional[bool] = None
    regenerate_sub_token: Optional[bool] = None

@app.middleware("http")
async def security_middleware(request: Request, call_next):
    # Host Guard: Reject raw IP scans on public interface
    if not auth.check_host_guard(request):
        return Response(status_code=404, content=b"", headers={"Server": "nginx/1.22.1"})

    cfg = cfg_mgr.load()
    trusted_cidrs = cfg.get("security", {}).get("trusted_proxy_cidrs", [])
    request.state.client_ip = resolve_client_ip(request, trusted_cidrs)

    response = await call_next(request)
    response.headers["Server"] = "nginx/1.22.1"
    return response

def check_admin(request: Request):
    if not auth.is_request_authenticated(request):
        raise HTTPException(status_code=401, detail="Administrator authentication required")

def check_setup_allowed(request: Request):
    cfg = cfg_mgr.load()
    if cfg.get('initialized', False):
        check_admin(request)
        return
    client_ip = request.client.host if request.client else ""
    if client_ip in ("127.0.0.1", "::1", "localhost"):
        return
    check_admin(request)

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)

ws_manager = ConnectionManager()

# Runtime state
runtime_state = {
    'status': 'healthy', # healthy, warning, critical, healing
    'last_healed': 'Never',
    'heal_count': 0,
    'heal_in_progress': False,
    'logs': [
        {'time': time.strftime("%H:%M:%S"), 'level': 'INFO', 'msg': 'Oracle Sentinel System initialized.'},
        {'time': time.strftime("%H:%M:%S"), 'level': 'INFO', 'msg': 'Sidecar monitoring active on port 20540.'}
    ]
}

def log_event(msg: str, level='INFO'):
    entry = {'time': time.strftime("%H:%M:%S"), 'level': level, 'msg': msg}
    runtime_state['logs'].append(entry)
    if len(runtime_state['logs']) > 100:
        runtime_state['logs'].pop(0)
    logger.info(f'[{level}] {msg}')
    return entry

async def broadcast_log(msg: str, level='INFO'):
    entry = log_event(msg, level)
    await ws_manager.broadcast({'type': 'log', 'data': entry})

@app.on_event('startup')
async def startup_event():
    asyncio.create_task(background_monitor_loop())
    traffic_mgr.TrafficManager.start_background_collector(cfg_mgr.load, interval_sec=60)
    mesh_mgr.MeshManager.start_background_poller(interval_sec=60)
    cert_sync_mgr.CertSyncManager.start_background_poller(cfg_mgr.load)
    bot = bot_mgr.get_bot_instance(
        get_state_func=monitor.get_full_state,
        get_config_func=cfg_mgr.load,
        run_healing_func=run_healing_routine
    )
    bot.start()

async def background_monitor_loop():
    logger.info('Starting background probe & monitor task...')
    loop = asyncio.get_running_loop()
    while True:
        try:
            cfg = cfg_mgr.load()
            state = await loop.run_in_executor(None, monitor.get_full_state)
            
            if not runtime_state['heal_in_progress']:
                runtime_state['status'] = state['health']

            payload = {
                'type': 'telemetry',
                'state': state,
                'speedtest': speedtest_mgr.speedtest_mgr.get_status(),
                'sentinel': {
                    'status': runtime_state['status'],
                    'last_healed': runtime_state['last_healed'],
                    'heal_count': runtime_state['heal_count'],
                    'auto_heal': cfg.get('monitor', {}).get('auto_heal_enabled', False)
                }
            }
            await ws_manager.broadcast(payload)

            # Auto-healing condition check
            if cfg.get('monitor', {}).get('auto_heal_enabled', False) and not runtime_state['heal_in_progress']:
                loss_thresh = float(cfg.get('monitor', {}).get('loss_threshold', 75.0))
                consec_limit = int(cfg.get('monitor', {}).get('consecutive_failures', 3))
                auto_heal_mode = cfg.get('monitor', {}).get('auto_heal_mode', 'notify_only')
                
                # P1-9: If local uplink network is down, do not trigger false positive Re-IP
                if state['probes'].get('network_down'):
                    monitor.consecutive_failures = 0
                    await broadcast_log('Local uplink network is unreachable (network_down). Skipping Re-IP evaluation.', 'WARN')
                elif state['probes']['loss_pct'] >= loss_thresh:
                    monitor.consecutive_failures += 1
                    await broadcast_log(
                        f'GFW Block threshold exceeded: {state["probes"]["loss_pct"]}% loss '
                        f'({monitor.consecutive_failures}/{consec_limit})',
                        'WARN'
                    )
                    if monitor.consecutive_failures >= consec_limit:
                        if auto_heal_mode == 'reip_auto':
                            await broadcast_log('Triggering automated Re-IP self-healing routine!', 'WARN')
                            notification.NotificationManager.broadcast(
                                cfg,
                                title="GFW Block Detected / 节点探针阻断告警",
                                message=f"[GFW Block] Loss rate reached {state['probes']['loss_pct']}% across domestic probes.\nConsecutive failures: {monitor.consecutive_failures}/{consec_limit}.\nInitiating recovery sequence...",
                                level="WARN"
                            )
                            asyncio.create_task(run_healing_routine('AUTO'))
                        else:
                            await broadcast_log(
                                f'GFW Block confirmed ({state["probes"]["loss_pct"]}% loss). '
                                f'Mode is notify_only: skipping automated Re-IP.',
                                'WARN'
                            )
                            notification.NotificationManager.broadcast(
                                cfg,
                                title="GFW Block Alert / 探针阻断告警 (仅通知)",
                                message=f"[GFW Block] Loss rate reached {state['probes']['loss_pct']}%. Consecutive failures: {monitor.consecutive_failures}/{consec_limit}.\nMode is notify_only, manual review recommended.",
                                level="WARN"
                            )
                            monitor.consecutive_failures = 0
                else:
                    if monitor.consecutive_failures > 0:
                        monitor.consecutive_failures = 0

            interval = cfg.get('monitor', {}).get('interval_sec', 15)
            await asyncio.sleep(interval)
        except Exception as e:
            logger.error(f'Monitor loop error: {e}')
            await asyncio.sleep(5)

class SettingsModel(BaseModel):
    cf_token: Optional[str] = ''
    cf_zone: Optional[str] = ''
    cf_record: Optional[str] = ''
    auto_heal: Optional[bool] = False
    auto_heal_mode: Optional[str] = None
    reip_cooldown_hours: Optional[int] = None
    provider_type: Optional[str] = 'auto'
    provider_hook: Optional[str] = ''
    lightsail: Optional[dict] = None
    hetzner: Optional[dict] = None
    azure: Optional[dict] = None
    notifications_enabled: Optional[bool] = False
    tg_enabled: Optional[bool] = False
    tg_token: Optional[str] = ''
    tg_chat_id: Optional[str] = ''
    discord_enabled: Optional[bool] = False
    discord_webhook: Optional[str] = ''
    bark_enabled: Optional[bool] = False
    bark_key: Optional[str] = ''
    custom_webhook_enabled: Optional[bool] = False
    custom_webhook_url: Optional[str] = ''
    secret_path: Optional[str] = None
    enable_host_guard: Optional[bool] = None

@app.get('/api/status')
async def get_status(request: Request):
    if not auth.verify_subscription_access(request):
        raise HTTPException(status_code=401, detail="Authentication required")
    cfg = cfg_mgr.load()
    loop = asyncio.get_running_loop()
    state = await loop.run_in_executor(None, monitor.get_full_state)
    return {
        'state': state,
        'sentinel': {
            'status': runtime_state['status'],
            'last_healed': runtime_state['last_healed'],
            'heal_count': runtime_state['heal_count'],
            'auto_heal': cfg.get('monitor', {}).get('auto_heal_enabled', False)
        },
        'logs': runtime_state['logs'][-30:]
    }

@app.get('/api/settings')
async def get_settings(request: Request):
    check_admin(request)
    cfg = cfg_mgr.load()
    token = cfg.get('cloudflare', {}).get('api_token', '')
    masked_token = f'{token[:4]}****{token[-4:]}' if len(token) > 8 else ('' if not token else '****')
    
    # Check OCI status
    oci_mgr = sentinel_core.OracleManager(cfg.get('oci', {}).get('config_path'))
    oci_status = {
        'ready': oci_mgr.client is not None,
        'instance_id': oci_mgr.instance_id,
        'vnic_id': oci_mgr.vnic_id,
        'compartment_id': oci_mgr.compartment_id,
        'region': oci_mgr.region,
        'error': oci_mgr.init_error
    }

    notify_cfg = cfg.get('notifications', {})
    tg = notify_cfg.get('telegram', {})
    discord = notify_cfg.get('discord', {})
    bark = notify_cfg.get('bark', {})
    custom = notify_cfg.get('custom_webhook', {})
    sec_cfg = auth.get_security_config()

    ls_cfg = cfg.get('lightsail', {})
    hz_cfg = cfg.get('hetzner', {})
    az_cfg = cfg.get('azure', {})

    return {
        'provider': cfg.get('provider', {'type': 'auto', 'hook_cmd': ''}),
        'lightsail': {
            'region': ls_cfg.get('region', 'us-east-1'),
            'instance_name': ls_cfg.get('instance_name', ''),
            'access_key_id': f"{ls_cfg.get('access_key_id', '')[:4]}****" if ls_cfg.get('access_key_id') else '',
            'has_secret': bool(ls_cfg.get('secret_access_key'))
        },
        'hetzner': {
            'server_id': hz_cfg.get('server_id', ''),
            'ip_type': hz_cfg.get('ip_type', 'primary'),
            'has_token': bool(hz_cfg.get('api_token'))
        },
        'azure': {
            'subscription_id': az_cfg.get('subscription_id', ''),
            'resource_group': az_cfg.get('resource_group', ''),
            'vm_name': az_cfg.get('vm_name', ''),
            'nic_name': az_cfg.get('nic_name', ''),
            'tenant_id': az_cfg.get('tenant_id', ''),
            'client_id': f"{az_cfg.get('client_id', '')[:4]}****" if az_cfg.get('client_id') else '',
            'has_secret': bool(az_cfg.get('client_secret'))
        },
        'cloudflare': {
            'token_set': bool(token),
            'masked_token': masked_token,
            'zone_name': cfg.get('cloudflare', {}).get('zone_name', ''),
            'record_name': cfg.get('cloudflare', {}).get('record_name', '')
        },
        'oci': oci_status,
        'monitor': cfg.get('monitor', {}),
        'security': {
            'auth_enabled': sec_cfg.get('auth_enabled', True),
            'admin_username': sec_cfg.get('admin_username', 'admin'),
            'secret_path': sec_cfg.get('secret_path', '/sentinel'),
            'enable_host_guard': sec_cfg.get('enable_host_guard', True),
            'sub_token': sec_cfg.get('sub_token', '')
        },
        'notifications': {
            'enabled': notify_cfg.get('enabled', False),
            'telegram': {
                'enabled': tg.get('enabled', False),
                'bot_token': f"{tg.get('bot_token', '')[:4]}****" if tg.get('bot_token') else '',
                'chat_id': tg.get('chat_id', '')
            },
            'discord': {
                'enabled': discord.get('enabled', False),
                'webhook_url': f"{discord.get('webhook_url', '')[:25]}****" if discord.get('webhook_url') else ''
            },
            'bark': {
                'enabled': bark.get('enabled', False),
                'bark_key': f"{bark.get('bark_key', '')[:4]}****" if bark.get('bark_key') else '',
            },
            'custom_webhook': {
                'enabled': custom.get('enabled', False),
                'url': mask_token(custom.get('url', ''), head=8, tail=4) if custom.get('url') else ''
            }
        }
    }

@app.post('/api/settings')
async def update_settings(data: SettingsModel, request: Request):
    check_admin(request)
    cfg = cfg_mgr.load()
    if data.cf_token:
        cfg['cloudflare']['api_token'] = data.cf_token
    if data.cf_zone is not None:
        cfg['cloudflare']['zone_name'] = data.cf_zone
    if data.cf_record is not None:
        cfg['cloudflare']['record_name'] = data.cf_record
    if data.auto_heal is not None:
        cfg.setdefault('monitor', {})['auto_heal_enabled'] = data.auto_heal
    if data.auto_heal_mode is not None:
        cfg.setdefault('monitor', {})['auto_heal_mode'] = data.auto_heal_mode
    if data.reip_cooldown_hours is not None:
        cfg.setdefault('monitor', {})['reip_cooldown_hours'] = data.reip_cooldown_hours

    if 'provider' not in cfg:
        cfg['provider'] = {}
    if data.provider_type:
        cfg['provider']['type'] = data.provider_type
    if data.provider_hook is not None:
        cfg['provider']['hook_cmd'] = data.provider_hook

    if data.lightsail is not None:
        cur_ls = cfg.setdefault('lightsail', {})
        sec_k = data.lightsail.get('secret_access_key', '')
        if not sec_k or '****' in sec_k:
            sec_k = cur_ls.get('secret_access_key', '')
        ak_id = data.lightsail.get('access_key_id', '')
        if not ak_id or '****' in ak_id:
            ak_id = cur_ls.get('access_key_id', '')
        cfg['lightsail'] = {
            'access_key_id': ak_id,
            'secret_access_key': sec_k,
            'region': data.lightsail.get('region') or cur_ls.get('region', 'us-east-1'),
            'instance_name': data.lightsail.get('instance_name') or cur_ls.get('instance_name', '')
        }

    if data.hetzner is not None:
        cur_hz = cfg.setdefault('hetzner', {})
        tok = data.hetzner.get('api_token', '')
        if not tok or '****' in tok:
            tok = cur_hz.get('api_token', '')
        cfg['hetzner'] = {
            'api_token': tok,
            'server_id': data.hetzner.get('server_id') or cur_hz.get('server_id', ''),
            'ip_type': data.hetzner.get('ip_type') or cur_hz.get('ip_type', 'primary')
        }

    if data.azure is not None:
        cur_az = cfg.setdefault('azure', {})
        csec = data.azure.get('client_secret', '')
        if not csec or '****' in csec:
            csec = cur_az.get('client_secret', '')
        cid = data.azure.get('client_id', '')
        if not cid or '****' in cid:
            cid = cur_az.get('client_id', '')
        cfg['azure'] = {
            'subscription_id': data.azure.get('subscription_id') or cur_az.get('subscription_id', ''),
            'resource_group': data.azure.get('resource_group') or cur_az.get('resource_group', ''),
            'vm_name': data.azure.get('vm_name') or cur_az.get('vm_name', ''),
            'nic_name': data.azure.get('nic_name') or cur_az.get('nic_name', ''),
            'client_id': cid,
            'client_secret': csec,
            'tenant_id': data.azure.get('tenant_id') or cur_az.get('tenant_id', '')
        }

    sec = cfg.setdefault('security', {})
    if data.secret_path is not None:
        sec['secret_path'] = data.secret_path.strip() or '/sentinel'
    if data.enable_host_guard is not None:
        sec['enable_host_guard'] = data.enable_host_guard

    if 'notifications' not in cfg:
        cfg['notifications'] = {}
    cfg['notifications']['enabled'] = bool(data.notifications_enabled)
    
    # Preserve existing secret tokens if masked or empty is submitted
    existing_tg = cfg.get('notifications', {}).get('telegram', {})
    new_tg_token = data.tg_token
    if not new_tg_token or '****' in new_tg_token:
        new_tg_token = existing_tg.get('bot_token', '')
    
    existing_discord = cfg.get('notifications', {}).get('discord', {})
    new_discord_url = data.discord_webhook
    if not new_discord_url or '****' in new_discord_url:
        new_discord_url = existing_discord.get('webhook_url', '')

    existing_bark = cfg.get('notifications', {}).get('bark', {})
    new_bark_key = data.bark_key
    if not new_bark_key or '****' in new_bark_key:
        new_bark_key = existing_bark.get('bark_key', '')

    cfg['notifications']['telegram'] = {
        'enabled': bool(data.tg_enabled),
        'bot_token': new_tg_token or '',
        'chat_id': data.tg_chat_id or ''
    }
    cfg['notifications']['discord'] = {
        'enabled': bool(data.discord_enabled),
        'webhook_url': new_discord_url or ''
    }
    cfg['notifications']['bark'] = {
        'enabled': bool(data.bark_enabled),
        'bark_key': new_bark_key or ''
    }
    existing_custom = cfg.get('notifications', {}).get('custom_webhook', {})
    new_custom_url = data.custom_webhook_url
    if not new_custom_url or '****' in new_custom_url:
        new_custom_url = existing_custom.get('url', '')

    cfg['notifications']['custom_webhook'] = {
        'enabled': bool(data.custom_webhook_enabled),
        'url': new_custom_url or ''
    }

    cfg_mgr.save(cfg)
    await broadcast_log('System configuration updated successfully.')
    return {'status': 'ok'}

@app.post('/api/notifications/test')
async def test_notifications(request: Request, data: Optional[dict] = None):
    check_admin(request)
    cfg = cfg_mgr.load()
    if data and 'notifications' in data:
        cfg['notifications'] = data['notifications']
    
    results = notification.NotificationManager.broadcast(
        cfg,
        title="Probe Alert Test / 告警测试",
        message="Universal Sentinel notification channel test successful! All systems operational.\n全能哨兵消息推送测试成功，节点状态良好。",
        level="SUCCESS"
    )
    return {'status': 'ok', 'results': results}

@app.post('/api/settings/test-cf')
async def test_cf_token(data: dict, request: Request):
    check_admin(request)
    token = data.get('token') or cfg_mgr.load().get('cloudflare', {}).get('api_token')
    cf = sentinel_core.CloudflareManager(token)
    ok, msg = cf.verify_token()
    return {'success': ok, 'message': msg}

# --- Authentication & Security Endpoints ---

@app.post('/api/auth/login')
async def login(req: LoginRequest, request: Request, response: Response):
    client_ip = getattr(request.state, "client_ip", "") or (request.client.host if request.client else "unknown")
    ok, token_or_msg = auth.authenticate_admin(req.username, req.password, client_ip=client_ip)
    if not ok:
        raise HTTPException(status_code=401, detail=token_or_msg)
    
    # Set HttpOnly session cookie
    response.set_cookie(
        key="sentinel_session",
        value=token_or_msg,
        max_age=86400 * 30,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/"
    )
    sec = auth.get_security_config()
    return {
        "success": True,
        "token": token_or_msg,
        "sub_token": sec.get("sub_token", ""),
        "secret_path": sec.get("secret_path", "/sentinel"),
        "username": req.username,
        "must_change_password": sec.get("must_change_password", False)
    }

@app.get('/api/auth/check')
async def check_auth(request: Request):
    sec = auth.get_security_config()
    authenticated = auth.is_request_authenticated(request)
    return {
        "authenticated": authenticated,
        "auth_enabled": sec.get("auth_enabled", True),
        "username": sec.get("admin_username", "admin") if authenticated else None,
        "sub_token": sec.get("sub_token", "") if authenticated else None,
        "secret_path": sec.get("secret_path", "/sentinel"),
        "must_change_password": sec.get("must_change_password", False) if authenticated else False
    }

@app.post('/api/auth/logout')
async def logout(response: Response):
    response.delete_cookie(key="sentinel_session", path="/")
    return {"success": True}

@app.post('/api/auth/update-password')
async def update_password(req: UpdatePasswordRequest, request: Request, response: Response):
    check_admin(request)
    sec = auth.get_security_config()
    current_user = sec.get("admin_username", "admin")
    client_ip = getattr(request.state, "client_ip", "") or (request.client.host if request.client else "unknown")
    ok, _ = auth.authenticate_admin(current_user, req.old_password, client_ip=client_ip)
    if not ok:
        raise HTTPException(status_code=400, detail="原密码输入错误")
    
    if not auth.update_password(req.new_password):
        raise HTTPException(status_code=400, detail="新密码长度不能少于 6 位")
    
    _, new_token = auth.authenticate_admin(current_user, req.new_password, client_ip=client_ip)
    response.set_cookie(
        key="sentinel_session",
        value=new_token,
        max_age=86400 * 30,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/"
    )
    return {"success": True, "message": "管理员密码已更新"}

@app.post('/api/auth/update-security')
async def update_security(req: SecuritySettingsRequest, request: Request):
    check_admin(request)
    sec = auth.update_security_settings(req.model_dump(exclude_unset=True))
    return {"success": True, "security": sec}

# --- Web Onboarding / Setup Wizard Endpoints ---

class SetupSaveModel(BaseModel):
    provider_type: str = 'auto'
    provider_hook: Optional[str] = ''
    oci_config_text: Optional[str] = ''
    oci_key_path: Optional[str] = ''
    lightsail: Optional[dict] = None
    hetzner: Optional[dict] = None
    azure: Optional[dict] = None
    cf_token: Optional[str] = ''
    cf_zone: Optional[str] = ''
    cf_record: Optional[str] = ''
    auto_heal: bool = True
    provision_nodes: bool = True
    notifications: Optional[dict] = None

class ProviderTestModel(BaseModel):
    provider_type: str
    provider_hook: Optional[str] = ''
    oci_config_text: Optional[str] = ''
    oci_key_path: Optional[str] = ''
    lightsail: Optional[dict] = None
    hetzner: Optional[dict] = None
    azure: Optional[dict] = None

@app.get('/api/setup/status')
async def setup_status(request: Request):
    cfg = cfg_mgr.load()
    is_init = cfg.get('initialized', False) or bool(cfg.get('cloudflare', {}).get('api_token'))
    is_authed = auth.is_request_authenticated(request)

    # P0-1: If already initialized and unauthenticated, restrict access to configuration
    if is_init and not is_authed:
        return {
            'initialized': True
        }

    cloud_info = sentinel_core.get_cloud_info()
    pub_ip = monitor.get_public_ip()
    ls_cfg = cfg.get('lightsail', {})
    hz_cfg = cfg.get('hetzner', {})
    az_cfg = cfg.get('azure', {})
    notif_cfg = redact_notifications(cfg.get('notifications', {}))
    return {
        'initialized': is_init,
        'cloud_info': cloud_info,
        'public_ip': pub_ip,
        'config': {
            'provider': cfg.get('provider', {}),
            'lightsail': {
                'region': ls_cfg.get('region', 'us-east-1'),
                'instance_name': ls_cfg.get('instance_name', ''),
                'access_key_id': f"{ls_cfg.get('access_key_id', '')[:4]}****" if ls_cfg.get('access_key_id') else '',
                'has_secret': bool(ls_cfg.get('secret_access_key'))
            },
            'hetzner': {
                'server_id': hz_cfg.get('server_id', ''),
                'ip_type': hz_cfg.get('ip_type', 'primary'),
                'has_token': bool(hz_cfg.get('api_token'))
            },
            'azure': {
                'subscription_id': az_cfg.get('subscription_id', ''),
                'resource_group': az_cfg.get('resource_group', ''),
                'vm_name': az_cfg.get('vm_name', ''),
                'nic_name': az_cfg.get('nic_name', ''),
                'tenant_id': az_cfg.get('tenant_id', ''),
                'client_id': f"{az_cfg.get('client_id', '')[:4]}****" if az_cfg.get('client_id') else '',
                'has_secret': bool(az_cfg.get('client_secret'))
            },
            'cloudflare': {
                'zone_name': cfg.get('cloudflare', {}).get('zone_name', ''),
                'record_name': cfg.get('cloudflare', {}).get('record_name', '')
            },
            'notifications': notif_cfg
        }
    }

@app.post('/api/provider/test')
async def test_provider_endpoint(data: ProviderTestModel, request: Request):
    check_setup_allowed(request)
    ptype = data.provider_type
    try:
        if ptype == 'oracle':
            prov = sentinel_core.OracleCloudProvider(config_path=data.oci_key_path)
            ok, msg = prov.test_connection()
            return {'success': ok, 'message': msg}
        elif ptype == 'lightsail':
            ls = data.lightsail or {}
            cfg = cfg_mgr.load().get('lightsail', {})
            ak = ls.get('access_key_id') or cfg.get('access_key_id', '')
            sk = ls.get('secret_access_key') or cfg.get('secret_access_key', '')
            reg = ls.get('region') or cfg.get('region', 'us-east-1')
            inst = ls.get('instance_name') or cfg.get('instance_name', '')
            prov = sentinel_core.LightsailCloudProvider(
                access_key_id=ak,
                secret_access_key=sk,
                region=reg,
                instance_name=inst
            )
            ok, msg = prov.test_connection()
            return {'success': ok, 'message': msg}
        elif ptype == 'hetzner':
            hz = data.hetzner or {}
            cfg = cfg_mgr.load().get('hetzner', {})
            tok = hz.get('api_token') or cfg.get('api_token', '')
            sid = hz.get('server_id') or cfg.get('server_id', '')
            ipt = hz.get('ip_type') or cfg.get('ip_type', 'primary')
            prov = sentinel_core.HetznerCloudProvider(
                api_token=tok,
                server_id=sid,
                ip_type=ipt
            )
            ok, msg = prov.test_connection()
            return {'success': ok, 'message': msg}
        elif ptype == 'azure':
            az = data.azure or {}
            cfg = cfg_mgr.load().get('azure', {})
            sub = az.get('subscription_id') or cfg.get('subscription_id', '')
            rg = az.get('resource_group') or cfg.get('resource_group', '')
            vm = az.get('vm_name') or cfg.get('vm_name', '')
            nic = az.get('nic_name') or cfg.get('nic_name', '')
            cid = az.get('client_id') or cfg.get('client_id', '')
            csec = az.get('client_secret') or cfg.get('client_secret', '')
            tid = az.get('tenant_id') or cfg.get('tenant_id', '')
            prov = sentinel_core.AzureCloudProvider(
                subscription_id=sub,
                resource_group=rg,
                vm_name=vm,
                nic_name=nic,
                client_id=cid,
                client_secret=csec,
                tenant_id=tid
            )
            ok, msg = prov.test_connection()
            return {'success': ok, 'message': msg}
        elif ptype == 'hook':
            cmd = data.provider_hook or cfg_mgr.load().get('provider', {}).get('hook_cmd', '')
            prov = sentinel_core.CustomHookProvider(hook_cmd=cmd)
            ok, msg = prov.test_connection()
            return {'success': ok, 'message': msg}
        elif ptype == 'auto':
            cfg = cfg_mgr.load()
            prov = sentinel_core.get_cloud_provider(cfg)
            ok, msg = prov.test_connection()
            return {'success': ok, 'message': f'Auto-detected ({prov.get_name()}): {msg}'}
        else:
            prov = sentinel_core.GenericProvider()
            ok, msg = prov.test_connection()
            return {'success': ok, 'message': msg}
    except Exception as e:
        return {'success': False, 'message': str(e)}

@app.post('/api/setup/verify-cf')
async def verify_cf(data: dict, request: Request):
    check_setup_allowed(request)
    token = data.get('token', '').strip()
    if not token:
        return {'success': False, 'message': 'API Token 不能为空'}
    cf = sentinel_core.CloudflareManager(token)
    ok, zones, msg = cf.list_zones()
    return {'success': ok, 'zones': zones, 'message': msg}

@app.post('/api/setup/generate-key')
async def generate_key(request: Request):
    check_setup_allowed(request)
    try:
        pub_key, key_path = sentinel_core.generate_rsa_keypair()
        return {'success': True, 'public_key': pub_key, 'key_path': key_path}
    except Exception as e:
        return {'success': False, 'message': str(e)}

@app.post('/api/setup/save')
async def complete_setup(data: SetupSaveModel, request: Request):
    check_setup_allowed(request)
    cfg = cfg_mgr.load()
    cfg['initialized'] = True
    cfg['provider'] = {
        'type': data.provider_type,
        'hook_cmd': data.provider_hook or ''
    }
    if data.cf_token:
        cfg['cloudflare']['api_token'] = data.cf_token
    if data.cf_zone:
        cfg['cloudflare']['zone_name'] = data.cf_zone
    if data.cf_record:
        cfg['cloudflare']['record_name'] = data.cf_record
    
    cfg['monitor']['auto_heal_enabled'] = data.auto_heal
    
    # If OCI config provided
    if data.provider_type == 'oracle' and data.oci_config_text:
        key_path = data.oci_key_path or '/root/.oci/oci_api_key.pem'
        try:
            cfg_path = sentinel_core.save_oci_config(data.oci_config_text, key_path)
            cfg['oci']['config_path'] = cfg_path
            cfg['oci']['auth_method'] = 'config_file'
        except Exception as e:
            logger.warning(f"Error saving OCI config: {e}")

    if data.lightsail:
        cur_ls = cfg.setdefault('lightsail', {})
        sec_k = data.lightsail.get('secret_access_key', '')
        if not sec_k or '****' in sec_k:
            sec_k = cur_ls.get('secret_access_key', '')
        ak_id = data.lightsail.get('access_key_id', '')
        if not ak_id or '****' in ak_id:
            ak_id = cur_ls.get('access_key_id', '')
        cfg['lightsail'] = {
            'access_key_id': ak_id,
            'secret_access_key': sec_k,
            'region': data.lightsail.get('region') or cur_ls.get('region', 'us-east-1'),
            'instance_name': data.lightsail.get('instance_name') or cur_ls.get('instance_name', '')
        }

    if data.hetzner:
        cur_hz = cfg.setdefault('hetzner', {})
        tok = data.hetzner.get('api_token', '')
        if not tok or '****' in tok:
            tok = cur_hz.get('api_token', '')
        cfg['hetzner'] = {
            'api_token': tok,
            'server_id': data.hetzner.get('server_id') or cur_hz.get('server_id', ''),
            'ip_type': data.hetzner.get('ip_type') or cur_hz.get('ip_type', 'primary')
        }

    if data.azure:
        cur_az = cfg.setdefault('azure', {})
        csec = data.azure.get('client_secret', '')
        if not csec or '****' in csec:
            csec = cur_az.get('client_secret', '')
        cid = data.azure.get('client_id', '')
        if not cid or '****' in cid:
            cid = cur_az.get('client_id', '')
        cfg['azure'] = {
            'subscription_id': data.azure.get('subscription_id') or cur_az.get('subscription_id', ''),
            'resource_group': data.azure.get('resource_group') or cur_az.get('resource_group', ''),
            'vm_name': data.azure.get('vm_name') or cur_az.get('vm_name', ''),
            'nic_name': data.azure.get('nic_name') or cur_az.get('nic_name', ''),
            'client_id': cid,
            'client_secret': csec,
            'tenant_id': data.azure.get('tenant_id') or cur_az.get('tenant_id', '')
        }

    if data.notifications:
        cfg['notifications'] = data.notifications

    cfg_mgr.save(cfg)

    # Optionally provision 3x-ui inbounds
    if data.provision_nodes and data.cf_record:
        try:
            script_path = os.path.join(BASE_DIR, 'scripts')
            if script_path not in sys.path:
                sys.path.insert(0, script_path)
            import node_provisioner
            node_provisioner.provision_nodes(domain=data.cf_record)
        except Exception as e:
            logger.warning(f"Auto-provision nodes warning: {e}")

    await broadcast_log('Web 初始化向导配置已完成，Sentinel 引擎已全面接管自愈守护！', 'INFO')
    return {'success': True, 'message': 'Setup completed successfully'}

class QuickStartRequest(BaseModel):
    outbound_mode: str = 'edgetunnel'
    admin_password: Optional[str] = None
    pages_domain: Optional[str] = None
    pages_uuid: Optional[str] = None
    worker_domain: Optional[str] = None
    worker_uuid: Optional[str] = None

@app.post('/api/setup/quick-start')
async def quick_start_setup(data: QuickStartRequest, request: Request):
    check_setup_allowed(request)
    cfg = cfg_mgr.load()
    cfg['initialized'] = True
    cfg.setdefault('provider', {})['type'] = 'auto'
    cfg.setdefault('monitor', {})['auto_heal_enabled'] = True

    sec = cfg.setdefault('security', {})
    if data.admin_password and len(data.admin_password.strip()) >= 6:
        sec['admin_password_hash'] = auth.hash_password(data.admin_password.strip())
        sec['session_secret'] = secrets.token_hex(32)

    if not sec.get('sub_token'):
        sec['sub_token'] = secrets.token_hex(16)
    sub_token = sec['sub_token']

    if data.outbound_mode == 'edgetunnel':
        edt = cfg.setdefault('edgetunnel', {})
        edt['enabled'] = True
        if data.pages_domain:
            edt['pages_domain'] = clean_ip_mgr.sanitize_domain(data.pages_domain)
        if data.pages_uuid:
            clean_uuid = clean_ip_mgr.validate_uuid(data.pages_uuid) or data.pages_uuid.strip()
            edt['pages_uuid'] = clean_uuid
        if data.worker_domain:
            edt['worker_domain'] = clean_ip_mgr.sanitize_domain(data.worker_domain)
        if data.worker_uuid:
            clean_w_uuid = clean_ip_mgr.validate_uuid(data.worker_uuid) or data.worker_uuid.strip()
            edt['worker_uuid'] = clean_w_uuid
        clean_ip_mgr.CleanIPManager.refresh_clean_ips(active_test=False)
    else:
        cfg.setdefault('edgetunnel', {})['enabled'] = False
        try:
            script_path = os.path.join(BASE_DIR, 'scripts')
            if script_path not in sys.path:
                sys.path.insert(0, script_path)
            import node_provisioner
            node_provisioner.provision_nodes()
        except Exception as e:
            logger.warning(f"Native nodes auto-provision note: {e}")

    cfg_mgr.save(cfg)

    await broadcast_log('Web 极速向导配置已完成，系统已就绪！', 'INFO')
    return {
        'success': True,
        'message': 'Quick start setup completed successfully',
        'sub_token': sub_token,
        'urls': {
            'clash': f'/sub/clash?token={sub_token}',
            'singbox': f'/sub/singbox?token={sub_token}',
            'v2ray': f'/sub/v2ray?token={sub_token}'
        }
    }

# --- Subscription Engine Endpoints ---

@app.api_route('/sub/clash', methods=['GET', 'HEAD'])
async def get_clash_sub(request: Request):
    if not auth.verify_subscription_access(request):
        raise HTTPException(status_code=403, detail="订阅 Token 无效或未提供，拒绝访问")
    yaml_content = sub_engine.SubEngine.generate_clash_yaml()
    headers = {
        'Content-Disposition': 'inline; filename="oracle_sentinel_clash.yaml"',
        'subscription-userinfo': 'upload=1073741824; download=5368709120; total=1073741824000; expire=0',
        'profile-update-interval': '24'
    }
    return Response(content=yaml_content, media_type='text/yaml; charset=utf-8', headers=headers)

@app.api_route('/sub/v2ray', methods=['GET', 'HEAD'])
@app.api_route('/sub/base64', methods=['GET', 'HEAD'])
@app.api_route('/sub/shadowrocket', methods=['GET', 'HEAD'])
async def get_v2ray_sub(request: Request):
    if not auth.verify_subscription_access(request):
        raise HTTPException(status_code=403, detail="订阅 Token 无效或未提供，拒绝访问")
    b64_content = sub_engine.SubEngine.generate_v2ray_base64()
    headers = {
        'Content-Disposition': 'inline; filename="oracle_nodes.txt"',
        'subscription-userinfo': 'upload=1073741824; download=5368709120; total=1073741824000; expire=0',
        'profile-update-interval': '24'
    }
    return Response(content=b64_content, media_type='text/plain; charset=utf-8', headers=headers)

@app.api_route('/sub/singbox', methods=['GET', 'HEAD'])
async def get_singbox_sub(request: Request):
    if not auth.verify_subscription_access(request):
        raise HTTPException(status_code=403, detail="订阅 Token 无效或未提供，拒绝访问")
    json_content = sub_engine.SubEngine.generate_singbox_json()
    headers = {
        'Content-Disposition': 'inline; filename="singbox_config.json"',
        'profile-update-interval': '24'
    }
    return Response(content=json_content, media_type='application/json; charset=utf-8', headers=headers)

@app.get('/api/sub/rules')
async def get_sub_rules(request: Request):
    check_admin(request)
    return sub_engine.SubEngine.get_rules_config()

@app.post('/api/sub/rules')
async def set_sub_rules(rules: dict, request: Request):
    check_admin(request)
    sub_engine.SubEngine.save_rules_config(rules)
    await broadcast_log('Subscription routing rules updated successfully.')
    return {'status': 'ok', 'rules': rules}

# --- Transit / Relay Endpoints ---

class TransitCreateModel(BaseModel):
    name: str
    host: str
    hy2_port: int = 20443
    reality_port: int = 28443
    trojan_port: int = 22083

    @field_validator('hy2_port', 'reality_port', 'trojan_port')
    @classmethod
    def validate_ports(cls, v):
        if not (1 <= v <= 65535):
            raise ValueError("Port must be between 1 and 65535")
        return v

@app.get('/api/transits')
async def list_transits(request: Request):
    check_admin(request)
    return transit_mgr.TransitManager.get_transits()

@app.post('/api/transits')
async def create_transit(item: TransitCreateModel, request: Request):
    check_admin(request)
    res = transit_mgr.TransitManager.add_transit(
        name=item.name,
        host=item.host,
        hy2_port=item.hy2_port,
        reality_port=item.reality_port,
        trojan_port=item.trojan_port
    )
    await broadcast_log(f'Added new transit relay node: {item.name} ({item.host})')
    return {'status': 'ok', 'transit': res}

@app.delete('/api/transits/{transit_id}')
async def delete_transit(transit_id: str, request: Request):
    check_admin(request)
    transit_mgr.TransitManager.delete_transit(transit_id)
    await broadcast_log(f'Removed transit relay node ID: {transit_id}')
    return {'status': 'ok'}

@app.post('/api/transits/{transit_id}/toggle')
async def toggle_transit(transit_id: str, data: dict, request: Request):
    check_admin(request)
    enabled = data.get('enabled', True)
    transit_mgr.TransitManager.toggle_transit(transit_id, enabled)
    return {'status': 'ok'}

@app.get('/scripts/setup-relay.sh')
async def get_relay_script():
    domain = sub_engine.SubEngine.get_server_domain()
    script = transit_mgr.TransitManager.generate_realm_script(domain)
    return Response(content=script, media_type='text/x-shellscript')

# --- Custom Standalone Nodes Endpoints ---

@app.get('/api/custom-nodes')
async def list_custom_nodes(request: Request):
    check_admin(request)
    return custom_node_mgr.CustomNodeManager.get_custom_nodes()

@app.post('/api/custom-nodes')
async def create_custom_node(item: dict, request: Request):
    check_admin(request)
    try:
        res = custom_node_mgr.CustomNodeManager.add_custom_node(item)
        await broadcast_log(f'Added custom node: {res.get("name")} ({res.get("server")}:{res.get("port")})')
        return {'status': 'ok', 'node': res}
    except Exception as e:
        logger.error(f'Failed to add custom node: {e}')
        raise HTTPException(status_code=400, detail=str(e))

@app.delete('/api/custom-nodes/{node_id}')
async def delete_custom_node(node_id: str, request: Request):
    check_admin(request)
    custom_node_mgr.CustomNodeManager.delete_custom_node(node_id)
    await broadcast_log(f'Removed custom node ID: {node_id}')
    return {'status': 'ok'}

@app.post('/api/custom-nodes/{node_id}/toggle')
async def toggle_custom_node(node_id: str, data: dict, request: Request):
    check_admin(request)
    enabled = data.get('enabled', True)
    custom_node_mgr.CustomNodeManager.toggle_custom_node(node_id, enabled)
    return {'status': 'ok'}

# --- EdgeTunnel (EDT) Integration API ---
@app.get('/api/edt/config')
async def get_edt_config(request: Request):
    check_admin(request)
    cfg = cfg_mgr.load()
    edt = cfg.get('edgetunnel', {})
    clean_ips = clean_ip_mgr.CleanIPManager.get_clean_ips()
    return {
        'status': 'ok',
        'edgetunnel': {
            'enabled': bool(edt.get('enabled', False)),
            'pages_domain': edt.get('pages_domain', ''),
            'worker_domain': edt.get('worker_domain', ''),
            'uuid': edt.get('uuid', ''),
            'pages_uuid': edt.get('pages_uuid', ''),
            'worker_uuid': edt.get('worker_uuid', ''),
            'path': edt.get('path', '/?ed=2048'),
            'proxy_ip': edt.get('proxy_ip', ''),
            'clean_ips': clean_ips,
            'auto_refresh_clean_ips': bool(edt.get('auto_refresh_clean_ips', True)),
            'enable_fallback_group': bool(edt.get('enable_fallback_group', True))
        }
    }

@app.post('/api/edt/config')
async def save_edt_config(data: dict, request: Request):
    check_admin(request)
    cfg = cfg_mgr.load()
    if 'edgetunnel' not in cfg:
        cfg['edgetunnel'] = {}

    edt = cfg['edgetunnel']
    for k in ('enabled', 'pages_domain', 'worker_domain', 'uuid', 'pages_uuid', 'worker_uuid', 'path', 'proxy_ip', 'auto_refresh_clean_ips', 'enable_fallback_group'):
        if k in data:
            val = data[k]
            if k in ('pages_domain', 'worker_domain') and isinstance(val, str):
                val = clean_ip_mgr.sanitize_domain(val)
            edt[k] = val

    if 'clean_ips' in data and isinstance(data['clean_ips'], dict):
        clean_ip_mgr.CleanIPManager.save_clean_ips(data['clean_ips'])
    else:
        cfg_mgr.save(cfg)

    await broadcast_log('EdgeTunnel configuration updated.')
    return {'status': 'ok', 'message': 'EdgeTunnel configuration saved successfully'}

@app.post('/api/edt/refresh-clean-ips')
async def refresh_edt_clean_ips(request: Request):
    check_admin(request)
    try:
        updated = clean_ip_mgr.CleanIPManager.refresh_clean_ips(active_test=False)
        await broadcast_log('Refreshed EdgeTunnel Clean IP pools.')
        return {'status': 'ok', 'clean_ips': updated}
    except Exception as e:
        logger.error(f'Failed to refresh clean IPs: {e}')
        raise HTTPException(status_code=500, detail=str(e))

@app.get('/api/edt/status')
async def get_edt_status(request: Request):
    check_admin(request)
    endpoints = mesh_mgr.MeshManager.get_serverless_endpoints()
    results = []
    for ep in endpoints:
        probe = mesh_mgr.MeshManager.probe_serverless_endpoint(ep['domain'])
        ep_res = dict(ep)
        ep_res['last_status'] = probe
        results.append(ep_res)
    return {'status': 'ok', 'endpoints': results}

@app.get('/api/services')
async def get_services(request: Request):
    check_admin(request)
    xui_base_path = '/'
    xui_port = 20530
    db_path = '/etc/x-ui/x-ui.db'
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT value FROM settings WHERE key = 'webBasePath'")
            r = c.fetchone()
            if r and r[0]: xui_base_path = r[0].strip()
            c.execute("SELECT value FROM settings WHERE key = 'webPort'")
            r = c.fetchone()
            if r and r[0]: xui_port = int(r[0])
            conn.close()
        except Exception as e:
            logger.warning(f"Error querying x-ui.db settings: {e}")

    def is_listening(port):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.3)
            res = s.connect_ex(('127.0.0.1', port))
            s.close()
            return res == 0
        except Exception:
            return False

    services = [
        {
            "id": "kuma-status",
            "name": "Uptime Kuma 探针状态大屏",
            "category": "dashboard",
            "proto": "https",
            "port": 3001,
            "path": "/status/services",
            "badge": "16 Probes",
            "desc": "实时监测甲骨文美西核心、日本绿云原生机、云端套件与全球 AI 节点（OpenAI/Anthropic）连通率与毫秒级延迟。",
            "running": is_listening(3001)
        },
        {
            "id": "xui",
            "name": "3x-ui 核心节点面板",
            "category": "admin",
            "proto": "https",
            "port": xui_port,
            "path": xui_base_path,
            "badge": "Xray Core",
            "desc": "VLESS-Reality / Hysteria 2 / Trojan 原生节点配置、公私钥证书管理与实时流量审计。",
            "running": is_listening(xui_port)
        },
        {
            "id": "kuma-admin",
            "name": "Uptime Kuma 运维后台",
            "category": "admin",
            "proto": "https",
            "port": 3001,
            "path": "/",
            "badge": "Telemetry",
            "desc": "探针目标增删、心跳频率调整、Telegram / Discord / Bark 即时阻断告警通道配置。",
            "running": is_listening(3001)
        },
        {
            "id": "substore",
            "name": "Sub-Store 订阅大脑",
            "category": "admin",
            "proto": "https",
            "port": 3000,
            "path": "/?api=/api",
            "badge": "Subscription",
            "desc": "节点清洗过滤、多机场聚合、正则批量重命名与 Clash / Sing-box / Surge 跨平台分流规则转换。",
            "running": is_listening(3000)
        },
        {
            "id": "alist",
            "name": "Alist 全网盘挂载中心",
            "category": "admin",
            "proto": "https",
            "port": 5244,
            "path": "/",
            "badge": "WebDAV 4K",
            "desc": "聚合挂载阿里云盘、夸克、百度网盘、OneDrive，支持 4K WebDAV 原画免下载高速串流播放。",
            "running": is_listening(5244)
        }
    ]
    return {
        "status": "ok",
        "services": services,
        "xui_base_path": xui_base_path,
        "xui_port": xui_port
    }

class HealTriggerModel(BaseModel):
    force: Optional[bool] = False

# --- Healing Sequence ---

async def run_healing_routine(trigger_source='MANUAL', force=False) -> dict:
    if runtime_state['heal_in_progress']:
        return {'ok': False, 'error': 'Healing routine already in progress', 'duration_sec': 0.0, 'new_ip': '', 'dns_ok': False}

    cfg = cfg_mgr.load()
    mon_cfg = cfg.get('monitor', {})
    now = time.time()
    t_start = now

    # P1-7: Rolling 24-hour quota and cooldown checks
    reip_history = [t for t in mon_cfg.get('reip_history', []) if (now - t) < 86400]
    max_reip = int(mon_cfg.get('max_reip_per_day', 3))
    cooldown_sec = mon_cfg.get('reip_cooldown_hours', 24) * 3600
    last_reip = mon_cfg.get('last_reip_timestamp', 0)

    if not force:
        if len(reip_history) >= max_reip:
            msg = f"Daily Re-IP quota exceeded ({len(reip_history)}/{max_reip} in last 24h). Trigger aborted."
            logger.warning(msg)
            await broadcast_log(f'[WARN] {msg}', 'WARN')
            notification.NotificationManager.broadcast(
                cfg,
                title="Re-IP Quota Exceeded / 换IP已达每日上限",
                message=msg,
                level="WARN"
            )
            monitor.consecutive_failures = 0
            return {'ok': False, 'error': msg, 'duration_sec': 0.0, 'new_ip': '', 'dns_ok': False}

        if trigger_source == 'AUTO' and (now - last_reip) < cooldown_sec:
            rem_h = round((cooldown_sec - (now - last_reip)) / 3600, 1)
            msg = f"Auto Re-IP suppressed by cooldown circuit breaker. Last Re-IP cooldown has {rem_h}h remaining ({mon_cfg.get('reip_cooldown_hours', 24)}h window)."
            logger.warning(msg)
            await broadcast_log(f'[WARN] {msg}', 'WARN')
            notification.NotificationManager.broadcast(
                cfg,
                title="Re-IP Cooldown Active / 换IP保护中",
                message=msg,
                level="WARN"
            )
            monitor.consecutive_failures = 0
            return {'ok': False, 'error': msg, 'duration_sec': 0.0, 'new_ip': '', 'dns_ok': False}

    runtime_state['heal_in_progress'] = True
    runtime_state['status'] = 'healing'

    old_ip = monitor.get_public_ip()
    await broadcast_log(f'[HEAL STEP 1/5] Initiated {trigger_source} Re-IP rebirth routine (current IP: {old_ip})...', 'WARN')
    await asyncio.sleep(1)

    cf_token = cfg.get('cloudflare', {}).get('api_token')
    cf_zone = cfg.get('cloudflare', {}).get('zone_name', '')
    cf_record = cfg.get('cloudflare', {}).get('record_name', '')

    cloud_prov = sentinel_core.get_cloud_provider(cfg)
    prov_name = cloud_prov.get_name()
    loop = asyncio.get_running_loop()

    try:
        # P1-10 Pre-flight check before releasing current IP
        await broadcast_log(f'[HEAL PRE-FLIGHT] Validating credentials and connectivity for {prov_name}...')
        conn_ok, conn_msg = await loop.run_in_executor(None, cloud_prov.test_connection)
        if not conn_ok:
            err_msg = f"Pre-flight provider validation failed: {conn_msg}. Aborting IP rebirth to prevent instance isolation."
            logger.error(err_msg)
            await broadcast_log(f'[ERROR] {err_msg}', 'ERROR')
            notification.NotificationManager.broadcast(
                cfg,
                title="Healing Pre-Flight Failed / 自动修复预检失败",
                message=err_msg,
                level="ERROR"
            )
            runtime_state['status'] = 'warning'
            dt = round(time.time() - t_start, 1)
            return {'ok': False, 'error': err_msg, 'duration_sec': dt, 'new_ip': '', 'dns_ok': False}

        # Step 2: IP swap via Provider
        await broadcast_log(f'[HEAL STEP 2/5] Initiating IP rebirth via provider: {prov_name}...')
        new_ip = await loop.run_in_executor(None, cloud_prov.change_public_ip)
        await broadcast_log(f'[HEAL STEP 3/5] Fresh Public IP acquired: {new_ip}', 'INFO')
        await asyncio.sleep(1)

        # Step 3: Cloudflare DNS update
        dns_ok = False
        if cf_token and cf_record:
            await broadcast_log(f'[HEAL STEP 4/5] Updating Cloudflare DNS: {cf_record} -> {new_ip}...')
            cf_mgr = sentinel_core.CloudflareManager(cf_token, cf_zone)
            try:
                dns_res = await loop.run_in_executor(None, cf_mgr.update_dns_record, cf_record, new_ip)
                dns_ok = bool(dns_res)
                if dns_ok:
                    await broadcast_log('[OK] [HEAL STEP 4/5] Cloudflare DNS record updated successfully!')
                else:
                    await broadcast_log('[WARN] [HEAL STEP 4/5] Cloudflare DNS update returned False/empty.', 'WARN')
            except Exception as cf_err:
                logger.warning(f"Cloudflare DNS update error: {cf_err}")
                await broadcast_log(f'[WARN] [HEAL STEP 4/5] Cloudflare DNS update failed: {cf_err}', 'WARN')
        else:
            await broadcast_log('[WARN] [HEAL STEP 4/5] Cloudflare token not set; skipping DNS update.', 'WARN')

        # Step 4: Verification (P1-10)
        await broadcast_log('[HEAL STEP 5/5] Verifying edge routing, external egress IP & health state...')
        actual_ip = await loop.run_in_executor(None, monitor.get_public_ip)
        ip_matched = (actual_ip == new_ip) if actual_ip and actual_ip != '127.0.0.1' else False
        dns_required = bool(cf_token and cf_record)
        dns_matched = (not dns_required) or dns_ok

        # Update persistent history and Re-IP state in config atomically
        def _record_reip(c):
            mon = c.setdefault('monitor', {})
            hist = [t for t in mon.get('reip_history', []) if (time.time() - t) < 86400]
            hist.append(int(time.time()))
            mon['reip_history'] = hist
            mon['last_reip_timestamp'] = int(time.time())
            mon['last_reip_old_ip'] = old_ip
            mon['last_reip_new_ip'] = new_ip
            mon['dns_sync_pending'] = not dns_matched
            return True

        cfg_mgr.update(_record_reip)

        runtime_state['last_healed'] = time.strftime('%Y-%m-%d %H:%M:%S')
        runtime_state['heal_count'] += 1
        monitor.consecutive_failures = 0
        dt = round(time.time() - t_start, 1)

        is_success = ip_matched and dns_matched
        if is_success:
            runtime_state['status'] = 'healthy'
            await broadcast_log(f'[OK] Rebirth completed and verified in {dt}s! Server is now operational on IP: {new_ip}')
            notification.NotificationManager.broadcast(
                cfg,
                title="IP Swapped & Restored / 节点IP重生命名成功",
                message=f"[OK] Rebirth routine succeeded and verified!\nProvider: {prov_name}\nNew IP: {new_ip}\nCloudflare DNS: {cf_record} -> {new_ip}\nDuration: {dt}s",
                level="SUCCESS"
            )
            return {'ok': True, 'new_ip': new_ip, 'error': '', 'duration_sec': dt, 'dns_ok': dns_ok}
        else:
            runtime_state['status'] = 'warning'
            warn_msg = (
                f"[WARN] Rebirth executed in {dt}s (new IP: {new_ip}), but verification flagged issues: "
                f"egress IP match: {ip_matched} (actual {actual_ip}), DNS ok: {dns_ok}."
            )
            await broadcast_log(warn_msg, 'WARN')
            notification.NotificationManager.broadcast(
                cfg,
                title="IP Swapped with Verification Warning / 节点换IP完成但需复核",
                message=warn_msg,
                level="WARN"
            )
            return {'ok': False, 'new_ip': new_ip, 'error': warn_msg, 'duration_sec': dt, 'dns_ok': dns_ok}

    except Exception as e:
        logger.error(f'Healing routine failed: {e}', exc_info=True)
        await broadcast_log(f'[ERROR] Healing failed: {str(e)}', 'ERROR')
        runtime_state['status'] = 'warning'
        dt = round(time.time() - t_start, 1)

        notification.NotificationManager.broadcast(
            cfg,
            title="Healing Routine Failed / 自动修复失败",
            message=f"[FAILED] Rebirth routine failed for provider {prov_name}: {str(e)}",
            level="ERROR"
        )
        return {'ok': False, 'new_ip': '', 'error': str(e), 'duration_sec': dt, 'dns_ok': False}
    finally:
        runtime_state['heal_in_progress'] = False

@app.post('/api/heal/trigger')
async def trigger_healing(request: Request, body: Optional[HealTriggerModel] = None):
    check_admin(request)
    if runtime_state['heal_in_progress']:
        raise HTTPException(status_code=409, detail='Healing is already in progress')
    force = body.force if body else False
    asyncio.create_task(run_healing_routine('MANUAL', force=force))
    return {'status': 'initiated', 'message': f'Re-IP rebirth sequence started (force={force})'}

@app.get('/api/ip/audit')
async def get_ip_audit(request: Request, force: bool = False):
    if not auth.verify_subscription_access(request):
        raise HTTPException(status_code=401, detail="Authentication required")
    if force:
        check_admin(request)
    loop = asyncio.get_running_loop()
    report = await loop.run_in_executor(None, ip_audit.auditor.audit, force)
    return JSONResponse(
        content=report,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
    )

class SpeedtestRequest(BaseModel):
    mode: Optional[str] = 'full'

@app.post('/api/speedtest/run')
async def trigger_speedtest(request: Request, req: Optional[SpeedtestRequest] = None):
    check_admin(request)
    mode = req.mode if req and req.mode else 'full'
    started = speedtest_mgr.speedtest_mgr.start_benchmark(mode=mode)
    if not started:
        raise HTTPException(status_code=409, detail='已有网络测速任务正在执行中，请稍候')
    mode_name = '全带宽与三网压测' if mode == 'full' else '国内三网低延迟探测'
    await broadcast_log(f'网络测速任务已发起 ({mode_name})', 'INFO')
    return {'status': 'started', 'message': f'测速任务已启动 ({mode_name})'}

@app.get('/api/speedtest/status')
async def get_speedtest_status(request: Request):
    check_admin(request)
    return speedtest_mgr.speedtest_mgr.get_status()

@app.websocket('/ws/live')
async def websocket_endpoint(websocket: WebSocket):
    sec = auth.get_security_config()
    if sec.get("auth_enabled", True):
        token = websocket.cookies.get("sentinel_session") or websocket.query_params.get("token")
        is_session_valid = auth.verify_session_token(token)
        is_sub_valid = bool(token and hmac.compare_digest(token, sec.get("sub_token", "")))
        if not (is_session_valid or is_sub_valid):
            await websocket.close(code=1008)
            return
    await ws_manager.connect(websocket)
    try:
        cfg = cfg_mgr.load()
        loop = asyncio.get_running_loop()
        state = await loop.run_in_executor(None, monitor.get_full_state)
        await websocket.send_json({
            'type': 'initial',
            'state': state,
            'speedtest': speedtest_mgr.speedtest_mgr.get_status(),
            'sentinel': {
                'status': runtime_state['status'],
                'last_healed': runtime_state['last_healed'],
                'heal_count': runtime_state['heal_count'],
                'auto_heal': cfg.get('monitor', {}).get('auto_heal_enabled', False)
            },
            'logs': runtime_state['logs'][-30:]
        })
        while True:
            data = await websocket.receive_text()
            if data == 'ping':
                await websocket.send_text('pong')
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)

# --- Traffic Auditing & Quota Endpoints ---

@app.get('/api/traffic/stats')
async def get_traffic_stats(request: Request):
    check_admin(request)
    return traffic_mgr.TrafficManager.get_traffic_stats()

class TrafficConfigModel(BaseModel):
    monthly_limit_gb: Optional[float] = None
    alert_threshold_pct: Optional[int] = None
    reset_day: Optional[int] = None

@app.post('/api/traffic/config')
async def set_traffic_config(data: TrafficConfigModel, request: Request):
    check_admin(request)
    success = traffic_mgr.TrafficManager.set_quota_config(
        monthly_limit_gb=data.monthly_limit_gb,
        alert_threshold_pct=data.alert_threshold_pct,
        reset_day=data.reset_day
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save traffic quota config")
    await broadcast_log(f'Updated traffic billing quota: limit={data.monthly_limit_gb}GB, threshold={data.alert_threshold_pct}%, reset_day={data.reset_day}')
    return {'status': 'ok', 'config': traffic_mgr.TrafficManager.get_quota_config()}

# --- Sentinel Mesh Cluster Endpoints ---

class MeshNodeModel(BaseModel):
    name: str
    host: str
    api_token: Optional[str] = ''
    location: Optional[str] = 'Global'
    tag: Optional[str] = 'REMOTE'
    enabled: Optional[bool] = True

@app.get('/api/mesh/overview')
async def get_mesh_overview(request: Request):
    check_admin(request)
    return mesh_mgr.MeshManager.get_mesh_overview(local_state_func=monitor.get_full_state)

@app.get('/api/mesh/nodes')
async def get_mesh_nodes(request: Request):
    check_admin(request)
    return mesh_mgr.MeshManager.get_nodes()

@app.post('/api/mesh/nodes')
async def add_mesh_node(node: MeshNodeModel, request: Request):
    check_admin(request)
    created = mesh_mgr.MeshManager.add_node(
        name=node.name,
        host=node.host,
        api_token=node.api_token or '',
        location=node.location or 'Global',
        tag=node.tag or 'REMOTE',
        enabled=node.enabled if node.enabled is not None else True
    )
    def _probe_new():
        stat = mesh_mgr.MeshManager.probe_remote_node(created)
        with mesh_mgr.MeshManager._lock:
            mesh_mgr.MeshManager._node_cache[created['id']] = stat
    threading.Thread(target=_probe_new, daemon=True).start()
    await broadcast_log(f'Added new Sentinel Mesh node: {node.name} ({node.host})')
    return {'status': 'ok', 'node': created}

@app.put('/api/mesh/nodes/{node_id}')
async def update_mesh_node(node_id: str, node: MeshNodeModel, request: Request):
    check_admin(request)
    updated = mesh_mgr.MeshManager.update_node(node_id, node.dict(exclude_unset=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Node not found")
    await broadcast_log(f'Updated Sentinel Mesh node: {node_id}')
    return {'status': 'ok', 'node': updated}

@app.delete('/api/mesh/nodes/{node_id}')
async def delete_mesh_node(node_id: str, request: Request):
    check_admin(request)
    deleted = mesh_mgr.MeshManager.delete_node(node_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Node not found")
    await broadcast_log(f'Removed Sentinel Mesh node ID: {node_id}')
    return {'status': 'ok', 'deleted_id': node_id}

@app.post('/api/mesh/refresh')
async def refresh_mesh(request: Request):
    check_admin(request)
    mesh_mgr.MeshManager.refresh_all_nodes()
    return mesh_mgr.MeshManager.get_mesh_overview(local_state_func=monitor.get_full_state)

# --- Distributed Certificate Sync Endpoints ---

class CertConfigModel(BaseModel):
    enabled: Optional[bool] = None
    role: Optional[str] = None  # 'disabled', 'master', 'edge'
    master_url: Optional[str] = None
    sync_token: Optional[str] = None
    cert_dir: Optional[str] = None
    poll_interval_hours: Optional[int] = None
    auto_reload_services: Optional[List[str]] = None
    post_sync_hook: Optional[str] = None
    verify_ssl: Optional[bool] = None

class CertSyncNowModel(BaseModel):
    force: Optional[bool] = False

def verify_cert_key_access(request: Request) -> bool:
    """
    P0-2: Strict security authentication for downloading sensitive TLS private key bundles (/api/cert/bundle).
    Only allows:
    1. Active administrator authenticated session.
    2. Explicit cert_sync.sync_token Bearer header or token query param.
    Strictly forbids sub_token: subscription clients must never have access to private TLS keys.
    """
    if auth.is_request_authenticated(request):
        return True

    cfg = cfg_mgr.load()
    sync_cfg = cert_sync_mgr.CertSyncManager.get_sync_config(cfg)
    sync_token = sync_cfg.get('sync_token', '').strip()
    if not sync_token:
        return False

    req_token = ''
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        req_token = auth_header[7:].strip()
    elif "token" in request.query_params:
        req_token = request.query_params.get("token", "").strip()

    if not req_token:
        return False

    return hmac.compare_digest(req_token, sync_token)

def verify_cert_access(request: Request) -> bool:
    """Verifies that the request has permission to access certificate sync endpoints."""
    return verify_cert_key_access(request)

@app.get('/api/cert/info')
async def get_cert_info(request: Request):
    check_admin(request)
    cfg = cfg_mgr.load()
    sync_cfg = cert_sync_mgr.CertSyncManager.get_sync_config(cfg)
    cert_dir = sync_cfg.get('cert_dir')
    local_info = cert_sync_mgr.CertManager.get_local_cert_info(cert_dir)
    return {
        'status': 'ok',
        'config': sync_cfg,
        'certificate': local_info
    }

@app.get('/api/cert/status')
async def get_cert_status(request: Request):
    if not verify_cert_access(request):
        raise HTTPException(status_code=401, detail="Invalid certificate sync authorization")
    cfg = cfg_mgr.load()
    sync_cfg = cert_sync_mgr.CertSyncManager.get_sync_config(cfg)
    cert_dir = sync_cfg.get('cert_dir')
    info = cert_sync_mgr.CertManager.get_local_cert_info(cert_dir)
    if not info.get('exists'):
        return {
            'status': 'no_cert',
            'fingerprint': '',
            'domains': [],
            'issuer': 'N/A',
            'valid_to': '',
            'days_left': 0,
            'bundle_updated_at': 0
        }
    return {
        'status': 'ok',
        'fingerprint': info.get('fingerprint', ''),
        'domains': info.get('domains', []),
        'issuer': info.get('issuer', 'Unknown'),
        'valid_to': info.get('valid_to', ''),
        'days_left': info.get('days_left', 0),
        'bundle_updated_at': int(os.path.getmtime(info['fullchain_path'])) if os.path.exists(info.get('fullchain_path', '')) else 0
    }

@app.get('/api/cert/bundle')
async def get_cert_bundle(request: Request):
    if not verify_cert_key_access(request):
        raise HTTPException(status_code=401, detail="Invalid certificate sync authorization")
    cfg = cfg_mgr.load()
    sync_cfg = cert_sync_mgr.CertSyncManager.get_sync_config(cfg)
    cert_dir = sync_cfg.get('cert_dir')
    try:
        bundle = cert_sync_mgr.CertManager.read_cert_bundle(cert_dir)
        return {
            'status': 'ok',
            **bundle
        }
    except Exception as e:
        logger.error(f"Failed to read certificate bundle: {e}")
        raise HTTPException(status_code=404, detail=f"Certificate bundle not available: {e}")

@app.post('/api/cert/config')
async def save_cert_config(model: CertConfigModel, request: Request):
    check_admin(request)
    data = model.model_dump(exclude_unset=True) if hasattr(model, 'model_dump') else model.dict(exclude_unset=True)
    updated = cert_sync_mgr.CertSyncManager.update_sync_config(data)
    await broadcast_log(f"Updated certificate sync configuration (role: {updated.get('role')})")
    return {'status': 'ok', 'config': updated}

@app.post('/api/cert/sync-now')
async def trigger_cert_sync_now(model: CertSyncNowModel, request: Request):
    check_admin(request)
    cfg = cfg_mgr.load()
    sync_cfg = cert_sync_mgr.CertSyncManager.get_sync_config(cfg)
    role = sync_cfg.get('role', 'disabled')

    if role == 'edge':
        res = cert_sync_mgr.CertSyncManager.perform_edge_sync(force=bool(model.force))
        await broadcast_log(f"Edge certificate sync: {res.get('status')} - {res.get('message')}")
        return res
    elif role == 'master':
        # Master node local reload
        services = sync_cfg.get('auto_reload_services', ['x-ui', 'vpsentinel', 'nginx'])
        hook = sync_cfg.get('post_sync_hook', '')
        reload_results = cert_sync_mgr.CertSyncAgent.reload_downstream_services(services=services, hook_path=hook)
        await broadcast_log(f"Master certificate reloaded downstream services: {len(reload_results)} services")
        return {
            'success': True,
            'status': 'reloaded',
            'role': 'master',
            'message': 'Master node reloaded downstream services successfully',
            'reloaded': reload_results
        }
    else:
        return {
            'success': False,
            'status': 'disabled',
            'message': 'Certificate sync is disabled on this node. Please set role to Master or Edge.'
        }

# --- Interactive Bot Endpoints ---

@app.get('/api/bot/status')
async def get_bot_status(request: Request):
    check_admin(request)
    bot = bot_mgr.get_bot_instance(
        get_state_func=monitor.get_full_state,
        get_config_func=cfg_mgr.load,
        run_healing_func=run_healing_routine
    )
    return bot.get_status()

# Mount static folder and dedicated metacubexd app
if os.path.exists(STATIC_PATH):
    app.mount('/static', StaticFiles(directory=STATIC_PATH), name='static')
if os.path.exists(METACUBEXD_PATH):
    app.mount('/metacubexd', StaticFiles(directory=METACUBEXD_PATH, html=True), name='metacubexd')
if os.path.exists(NUXT_PATH):
    app.mount('/_nuxt', StaticFiles(directory=NUXT_PATH), name='nuxt')

@app.get('/dash')
async def dash_redirect():
    dash_index = os.path.join(METACUBEXD_PATH, 'index.html')
    if os.path.exists(dash_index):
        return FileResponse(dash_index)
    return HTMLResponse('<h1>Dashboard UI not found</h1>', status_code=404)

DECOY_HTML = """<!DOCTYPE html>
<html>
<head>
<title>Welcome to nginx!</title>
<style>
html { color-scheme: light dark; }
body { width: 35em; margin: 0 auto; font-family: Tahoma, Verdana, Arial, sans-serif; padding-top: 50px; }
</style>
</head>
<body>
<h1>Welcome to nginx!</h1>
<p>If you see this page, the nginx web server is successfully installed and
working. Further configuration is required.</p>

<p>For online documentation and support please refer to
<a href="http://nginx.org/">nginx.org</a>.<br/>
Commercial support is available at
<a href="http://nginx.com/">nginx.com</a>.</p>

<p><em>Thank you for using nginx.</em></p>
</body>
</html>"""

@app.api_route('/', methods=['GET', 'HEAD'])
async def root():
    # Public root is a stealth decoy Nginx welcome page
    return HTMLResponse(content=DECOY_HTML, status_code=200, headers={"Server": "nginx/1.22.1"})

@app.api_route('/sentinel', methods=['GET', 'HEAD'])
@app.api_route('/sentinel/', methods=['GET', 'HEAD'])
async def serve_sentinel_ui():
    index_file = os.path.join(STATIC_PATH, 'index.html')
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return HTMLResponse('<h1>Sentinel UI not found</h1>', status_code=404)

@app.api_route('/{path_slug}', methods=['GET', 'HEAD'])
@app.api_route('/{path_slug}/', methods=['GET', 'HEAD'])
async def serve_custom_path_ui(path_slug: str):
    sec = auth.get_security_config()
    configured = sec.get("secret_path", "/sentinel").strip('/')
    if path_slug == configured:
        index_file = os.path.join(STATIC_PATH, 'index.html')
        if os.path.exists(index_file):
            return FileResponse(index_file)
    return Response(status_code=404, content=b"")

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=20540)

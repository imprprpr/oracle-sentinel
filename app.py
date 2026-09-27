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
from typing import List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Response, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel, field_validator

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
        return Response(status_code=404, content=b"")

    # Cloudflare / Proxy client IP extraction
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        request.state.client_ip = cf_ip.strip()
    else:
        xfwd = request.headers.get("x-forwarded-for")
        if xfwd:
            request.state.client_ip = xfwd.split(",")[0].strip()
        else:
            request.state.client_ip = request.client.host if request.client else ""

    response = await call_next(request)
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
    bot = bot_mgr.get_bot_instance(get_state_func=monitor.get_full_state, get_config_func=cfg_mgr.load)
    bot.start()

async def background_monitor_loop():
    logger.info('Starting background probe & monitor task...')
    while True:
        try:
            cfg = cfg_mgr.load()
            state = monitor.get_full_state()
            
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
                loss_thresh = cfg.get('monitor', {}).get('loss_threshold', 80.0)
                consec_limit = cfg.get('monitor', {}).get('consecutive_failures', 5)
                
                if state['probes']['loss_pct'] >= loss_thresh:
                    monitor.consecutive_failures += 1
                    await broadcast_log(
                        f'GFW Block threshold exceeded: {state["probes"]["loss_pct"]}% loss '
                        f'({monitor.consecutive_failures}/{consec_limit})',
                        'WARN'
                    )
                    if monitor.consecutive_failures >= consec_limit:
                        await broadcast_log('Triggering automated Re-IP self-healing routine!', 'WARN')
                        notification.NotificationManager.broadcast(
                            cfg,
                            title="GFW Block Detected / 节点探针阻断告警",
                            message=f"[GFW Block] Loss rate reached {state['probes']['loss_pct']}% across domestic probes.\nConsecutive failures: {monitor.consecutive_failures}/{consec_limit}.\nInitiating recovery sequence...",
                            level="WARN"
                        )
                        asyncio.create_task(run_healing_routine('AUTO'))
                else:
                    if monitor.consecutive_failures > 0:
                        monitor.consecutive_failures = 0

            interval = cfg.get('monitor', {}).get('interval_sec', 10)
            await asyncio.sleep(interval)
        except Exception as e:
            logger.error(f'Monitor loop error: {e}')
            await asyncio.sleep(5)

class SettingsModel(BaseModel):
    cf_token: Optional[str] = ''
    cf_zone: Optional[str] = ''
    cf_record: Optional[str] = ''
    auto_heal: Optional[bool] = False
    provider_type: Optional[str] = 'auto'
    provider_hook: Optional[str] = ''
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
    state = monitor.get_full_state()
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

    return {
        'provider': cfg.get('provider', {'type': 'auto', 'hook_cmd': ''}),
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
                'bark_key': f"{bark.get('bark_key', '')[:4]}****" if bark.get('bark_key') else ''
            },
            'custom_webhook': {
                'enabled': custom.get('enabled', False),
                'url': custom.get('url', '')
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
        cfg['monitor']['auto_heal_enabled'] = data.auto_heal

    if 'provider' not in cfg:
        cfg['provider'] = {}
    if data.provider_type:
        cfg['provider']['type'] = data.provider_type
    if data.provider_hook is not None:
        cfg['provider']['hook_cmd'] = data.provider_hook

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
    cfg['notifications']['custom_webhook'] = {
        'enabled': bool(data.custom_webhook_enabled),
        'url': data.custom_webhook_url or ''
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
async def login(req: LoginRequest, response: Response):
    ok, token_or_msg = auth.authenticate_admin(req.username, req.password)
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
        "username": req.username
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
        "secret_path": sec.get("secret_path", "/sentinel")
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
    ok, _ = auth.authenticate_admin(current_user, req.old_password)
    if not ok:
        raise HTTPException(status_code=400, detail="原密码输入错误")
    
    if not auth.update_password(req.new_password):
        raise HTTPException(status_code=400, detail="新密码长度不能少于 6 位")
    
    _, new_token = auth.authenticate_admin(current_user, req.new_password)
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
    cf_token: Optional[str] = ''
    cf_zone: Optional[str] = ''
    cf_record: Optional[str] = ''
    auto_heal: bool = True
    provision_nodes: bool = True
    notifications: Optional[dict] = None

@app.get('/api/setup/status')
async def setup_status():
    cfg = cfg_mgr.load()
    is_init = cfg.get('initialized', False) or bool(cfg.get('cloudflare', {}).get('api_token'))
    cloud_info = sentinel_core.get_cloud_info()
    pub_ip = monitor.get_public_ip()
    return {
        'initialized': is_init,
        'cloud_info': cloud_info,
        'public_ip': pub_ip,
        'config': {
            'provider': cfg.get('provider', {}),
            'cloudflare': {
                'zone_name': cfg.get('cloudflare', {}).get('zone_name', ''),
                'record_name': cfg.get('cloudflare', {}).get('record_name', '')
            },
            'notifications': cfg.get('notifications', {})
        }
    }

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

    await broadcast_log('🎉 Web 初始化向导配置已完成，Sentinel 引擎已全面接管自愈守护！', 'INFO')
    return {'success': True, 'message': 'Setup completed successfully'}

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

# --- Healing Sequence ---

async def run_healing_routine(trigger_source='MANUAL'):
    if runtime_state['heal_in_progress']:
        return
    runtime_state['heal_in_progress'] = True
    runtime_state['status'] = 'healing'
    t_start = time.time()
    
    await broadcast_log(f'⚡ [HEAL STEP 1/5] Initiated {trigger_source} Re-IP rebirth routine...', 'WARN')
    await asyncio.sleep(1)

    cfg = cfg_mgr.load()
    cf_token = cfg.get('cloudflare', {}).get('api_token')
    cf_zone = cfg.get('cloudflare', {}).get('zone_name', '')
    cf_record = cfg.get('cloudflare', {}).get('record_name', '')

    cloud_prov = sentinel_core.get_cloud_provider(cfg)
    prov_name = cloud_prov.get_name()

    try:
        # Step 2: IP swap via Provider
        await broadcast_log(f'🌐 [HEAL STEP 2/5] Initiating IP rebirth via provider: {prov_name}...')
        
        loop = asyncio.get_event_loop()
        new_ip = await loop.run_in_executor(None, cloud_prov.change_public_ip)
        
        await broadcast_log(f'✨ [HEAL STEP 3/5] Fresh Public IP acquired: {new_ip}', 'INFO')
        await asyncio.sleep(1)

        # Step 3: Cloudflare DNS update
        if cf_token and cf_record:
            await broadcast_log(f'☁️ [HEAL STEP 4/5] Updating Cloudflare DNS: {cf_record} -> {new_ip}...')
            cf_mgr = sentinel_core.CloudflareManager(cf_token, cf_zone)
            await loop.run_in_executor(None, cf_mgr.update_dns_record, cf_record, new_ip)
            await broadcast_log('✅ [HEAL STEP 4/5] Cloudflare DNS record updated successfully!')
        else:
            await broadcast_log('⚠️ [HEAL STEP 4/5] Cloudflare token not set; skipping DNS update.', 'WARN')

        # Step 4: Verification
        await broadcast_log('🔄 [HEAL STEP 5/5] Verifying edge routing & resetting health state...')
        runtime_state['last_healed'] = time.strftime('%Y-%m-%d %H:%M:%S')
        runtime_state['heal_count'] += 1
        monitor.consecutive_failures = 0
        runtime_state['status'] = 'healthy'
        
        dt = round(time.time() - t_start, 1)
        await broadcast_log(f'🎉 Rebirth completed in {dt}s! Server is now operational on IP: {new_ip}')

        notification.NotificationManager.broadcast(
            cfg,
            title="IP Swapped & Restored / 节点IP重生命名成功",
            message=f"🎉 Rebirth routine succeeded!\nProvider: {prov_name}\nNew IP: {new_ip}\nCloudflare DNS: {cf_record} -> {new_ip}\nDuration: {dt}s",
            level="SUCCESS"
        )

    except Exception as e:
        logger.error(f'Healing routine failed: {e}', exc_info=True)
        await broadcast_log(f'❌ Healing failed: {str(e)}', 'ERROR')
        runtime_state['status'] = 'warning'

        notification.NotificationManager.broadcast(
            cfg,
            title="Healing Routine Failed / 自动修复失败",
            message=f"❌ Rebirth routine failed for provider {prov_name}: {str(e)}",
            level="ERROR"
        )
    finally:
        runtime_state['heal_in_progress'] = False

@app.post('/api/heal/trigger')
async def trigger_healing(request: Request):
    check_admin(request)
    if runtime_state['heal_in_progress']:
        raise HTTPException(status_code=409, detail='Healing is already in progress')
    asyncio.create_task(run_healing_routine('MANUAL'))
    return {'status': 'initiated', 'message': 'Re-IP rebirth sequence started'}

@app.get('/api/ip/audit')
async def get_ip_audit(request: Request, force: bool = False):
    if force:
        check_admin(request)
    loop = asyncio.get_running_loop()
    report = await loop.run_in_executor(None, ip_audit.auditor.audit, force)
    return report

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
        state = monitor.get_full_state()
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

# --- Interactive Bot Endpoints ---

@app.get('/api/bot/status')
async def get_bot_status(request: Request):
    check_admin(request)
    bot = bot_mgr.get_bot_instance(get_state_func=monitor.get_full_state, get_config_func=cfg_mgr.load)
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

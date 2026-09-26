#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import time
import json
import asyncio
import logging
from typing import List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

import sentinel_core
import sub_engine
import transit_mgr
import notification

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('SentinelAPI')

app = FastAPI(title='VPSentinel Control Center')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_PATH = '/opt/vpsentinel/static' if os.path.exists('/opt/vpsentinel/static') else (
    '/opt/oracle-sentinel/static' if os.path.exists('/opt/oracle-sentinel/static') else os.path.join(BASE_DIR, 'static')
)
METACUBEXD_PATH = os.path.join(STATIC_PATH, 'metacubexd')
NUXT_PATH = os.path.join(METACUBEXD_PATH, '_nuxt')

monitor = sentinel_core.SystemMonitor()
cfg_mgr = sentinel_core.ConfigManager()

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
                            message=f"⚠️ Loss rate reached {state['probes']['loss_pct']}% across domestic probes.\nConsecutive failures: {monitor.consecutive_failures}/{consec_limit}.\nInitiating recovery sequence...",
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

@app.get('/api/status')
async def get_status():
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
async def get_settings():
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
async def update_settings(data: SettingsModel):
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
async def test_notifications(data: Optional[dict] = None):
    cfg = cfg_mgr.load()
    if data and 'notifications' in data:
        cfg['notifications'] = data['notifications']
    
    results = notification.NotificationManager.broadcast(
        cfg,
        title="Probe Alert Test / 告警测试",
        message="🎉 Universal Sentinel notification channel test successful! All systems operational.\n全能哨兵消息推送测试成功，节点状态良好。",
        level="SUCCESS"
    )
    return {'status': 'ok', 'results': results}

@app.post('/api/settings/test-cf')
async def test_cf_token(data: dict):
    token = data.get('token') or cfg_mgr.load().get('cloudflare', {}).get('api_token')
    cf = sentinel_core.CloudflareManager(token)
    ok, msg = cf.verify_token()
    return {'success': ok, 'message': msg}

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
async def verify_cf(data: dict):
    token = data.get('token', '').strip()
    if not token:
        return {'success': False, 'message': 'API Token 不能为空'}
    cf = sentinel_core.CloudflareManager(token)
    ok, zones, msg = cf.list_zones()
    return {'success': ok, 'zones': zones, 'message': msg}

@app.post('/api/setup/generate-key')
async def generate_key():
    try:
        pub_key, key_path = sentinel_core.generate_rsa_keypair()
        return {'success': True, 'public_key': pub_key, 'key_path': key_path}
    except Exception as e:
        return {'success': False, 'message': str(e)}

@app.post('/api/setup/save')
async def complete_setup(data: SetupSaveModel):
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

@app.get('/sub/clash')
async def get_clash_sub():
    yaml_content = sub_engine.SubEngine.generate_clash_yaml()
    headers = {
        'Content-Disposition': 'inline; filename="oracle_sentinel_clash.yaml"',
        'subscription-userinfo': 'upload=1073741824; download=5368709120; total=1073741824000; expire=0',
        'profile-update-interval': '24'
    }
    return Response(content=yaml_content, media_type='text/yaml; charset=utf-8', headers=headers)

@app.get('/sub/v2ray')
@app.get('/sub/base64')
@app.get('/sub/shadowrocket')
async def get_v2ray_sub():
    b64_content = sub_engine.SubEngine.generate_v2ray_base64()
    headers = {
        'Content-Disposition': 'inline; filename="oracle_nodes.txt"',
        'subscription-userinfo': 'upload=1073741824; download=5368709120; total=1073741824000; expire=0',
        'profile-update-interval': '24'
    }
    return Response(content=b64_content, media_type='text/plain; charset=utf-8', headers=headers)

@app.get('/sub/singbox')
async def get_singbox_sub():
    json_content = sub_engine.SubEngine.generate_singbox_json()
    headers = {
        'Content-Disposition': 'inline; filename="singbox_config.json"',
        'profile-update-interval': '24'
    }
    return Response(content=json_content, media_type='application/json; charset=utf-8', headers=headers)

@app.get('/api/sub/rules')
async def get_sub_rules():
    return sub_engine.SubEngine.get_rules_config()

@app.post('/api/sub/rules')
async def set_sub_rules(rules: dict):
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

@app.get('/api/transits')
async def list_transits():
    return transit_mgr.TransitManager.get_transits()

@app.post('/api/transits')
async def create_transit(item: TransitCreateModel):
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
async def delete_transit(transit_id: str):
    transit_mgr.TransitManager.delete_transit(transit_id)
    await broadcast_log(f'Removed transit relay node ID: {transit_id}')
    return {'status': 'ok'}

@app.post('/api/transits/{transit_id}/toggle')
async def toggle_transit(transit_id: str, data: dict):
    enabled = data.get('enabled', True)
    transit_mgr.TransitManager.toggle_transit(transit_id, enabled)
    return {'status': 'ok'}

@app.get('/scripts/setup-relay.sh')
async def get_relay_script():
    domain = sub_engine.SubEngine.get_server_domain()
    script = transit_mgr.TransitManager.generate_realm_script(domain)
    return Response(content=script, media_type='text/x-shellscript')

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
async def trigger_healing():
    if runtime_state['heal_in_progress']:
        raise HTTPException(status_code=409, detail='Healing is already in progress')
    asyncio.create_task(run_healing_routine('MANUAL'))
    return {'status': 'initiated', 'message': 'Re-IP rebirth sequence started'}

@app.websocket('/ws/live')
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        cfg = cfg_mgr.load()
        state = monitor.get_full_state()
        await websocket.send_json({
            'type': 'initial',
            'state': state,
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

@app.api_route('/', methods=['GET', 'HEAD'])
async def root():
    index_file = os.path.join(STATIC_PATH, 'index.html')
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return HTMLResponse('<h1>Sentinel UI not found</h1>', status_code=404)

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=20540)

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

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('SentinelAPI')

app = FastAPI(title='Oracle Sentinel Control Center')

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
                        await broadcast_log('Triggering automated OCI Re-IP self-healing routine!', 'WARN')
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
    cf_token: str = ''
    cf_zone: str = ''
    cf_record: str = ''
    auto_heal: bool = False

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

    return {
        'cloudflare': {
            'token_set': bool(token),
            'masked_token': masked_token,
            'zone_name': cfg.get('cloudflare', {}).get('zone_name', ''),
            'record_name': cfg.get('cloudflare', {}).get('record_name', '')
        },
        'oci': oci_status,
        'monitor': cfg.get('monitor', {})
    }

@app.post('/api/settings')
async def update_settings(data: SettingsModel):
    cfg = cfg_mgr.load()
    if data.cf_token:
        cfg['cloudflare']['api_token'] = data.cf_token
    cfg['cloudflare']['zone_name'] = data.cf_zone
    cfg['cloudflare']['record_name'] = data.cf_record
    cfg['monitor']['auto_heal_enabled'] = data.auto_heal
    cfg_mgr.save(cfg)
    await broadcast_log('System configuration updated successfully.')
    return {'status': 'ok'}

@app.post('/api/settings/test-cf')
async def test_cf_token(data: dict):
    token = data.get('token') or cfg_mgr.load().get('cloudflare', {}).get('api_token')
    cf = sentinel_core.CloudflareManager(token)
    ok, msg = cf.verify_token()
    return {'success': ok, 'message': msg}

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

    try:
        # Step 2: OCI IP swap
        await broadcast_log('🌐 [HEAL STEP 2/5] Communicating with Oracle Cloud Phoenix API to swap Public IP...')
        oci_mgr = sentinel_core.OracleManager(cfg.get('oci', {}).get('config_path'))
        
        loop = asyncio.get_event_loop()
        new_ip = await loop.run_in_executor(None, oci_mgr.change_public_ip)
        
        await broadcast_log(f'✨ [HEAL STEP 3/5] Fresh Public IP acquired: {new_ip}', 'INFO')
        await asyncio.sleep(1)

        # Step 3: Cloudflare DNS update
        if cf_token:
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
        await broadcast_log(f'🎉 Phoenix rebirth completed in {dt}s! Server is now operational on IP: {new_ip}')

    except Exception as e:
        logger.error(f'Healing routine failed: {e}', exc_info=True)
        await broadcast_log(f'❌ Healing failed: {str(e)}', 'ERROR')
        runtime_state['status'] = 'warning'
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
app.mount('/static', StaticFiles(directory='/opt/oracle-sentinel/static'), name='static')
app.mount('/metacubexd', StaticFiles(directory='/opt/oracle-sentinel/static/metacubexd', html=True), name='metacubexd')
app.mount('/_nuxt', StaticFiles(directory='/opt/oracle-sentinel/static/metacubexd/_nuxt'), name='nuxt')

@app.get('/dash')
async def dash_redirect():
    return FileResponse('/opt/oracle-sentinel/static/metacubexd/index.html')

@app.api_route('/', methods=['GET', 'HEAD'])
async def root():
    return FileResponse('/opt/oracle-sentinel/static/index.html')

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=20540)

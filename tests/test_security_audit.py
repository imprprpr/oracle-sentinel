import os
import json
import time
import threading
import unittest
from starlette.testclient import TestClient

import app
import sentinel_core
import auth_mgr
import sub_engine
import mesh_mgr

class TestSecurityAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orig_config = sentinel_core.ConfigManager.load()
        test_cfg = json.loads(json.dumps(cls.orig_config))
        test_cfg["initialized"] = True
        test_cfg["security"] = {
            "auth_enabled": True,
            "admin_username": "admin",
            "admin_password_hash": app.auth.hash_password(auth_mgr.DEFAULT_ADMIN_PASS),
            "session_secret": "test_security_session_secret_12345",
            "secret_path": "/sentinel",
            "sub_token": "test_security_sub_token_123",
            "enable_host_guard": True,
            "allowed_hosts": ["vps.example.com"]
        }
        test_cfg["cloudflare"] = {
            "api_token": "",
            "zone_name": "",
            "record_name": "vps.example.com"
        }
        sentinel_core.ConfigManager.save(test_cfg)
        cls.sec_cfg = test_cfg["security"]
        cls.sub_token = "test_security_sub_token_123"
        cls.admin_token = app.auth.create_session_token("admin")
        cls.client = TestClient(app.app, base_url='https://vps.example.com')

    @classmethod
    def tearDownClass(cls):
        sentinel_core.ConfigManager.save(cls.orig_config)

    def test_unauthenticated_sensitive_endpoints_return_401(self):
        endpoints = [
            '/api/custom-nodes',
            '/api/mesh/nodes',
            '/api/mesh/overview',
            '/api/services',
            '/api/sub/rules',
            '/api/transits',
            '/api/traffic/stats',
            '/api/speedtest/status',
            '/api/status'
        ]
        for ep in endpoints:
            res = self.client.get(ep)
            self.assertEqual(
                res.status_code,
                401,
                f"Endpoint {ep} should return 401 for unauthenticated request, got {res.status_code}"
            )

    def test_authenticated_endpoints_succeed(self):
        if not self.admin_token:
            self.skipTest("No admin token available")

        cookies = {"sentinel_session": self.admin_token}
        res_custom = self.client.get('/api/custom-nodes', cookies=cookies)
        self.assertEqual(res_custom.status_code, 200)

        res_transits = self.client.get('/api/transits', cookies=cookies)
        self.assertEqual(res_transits.status_code, 200)

        res_sub_rules = self.client.get('/api/sub/rules', cookies=cookies)
        self.assertEqual(res_sub_rules.status_code, 200)

        res_mesh_nodes = self.client.get('/api/mesh/nodes', cookies=cookies)
        self.assertEqual(res_mesh_nodes.status_code, 200)

        res_traffic = self.client.get('/api/traffic/stats', cookies=cookies)
        self.assertEqual(res_traffic.status_code, 200)

    def test_setup_endpoints_require_auth_for_external_clients(self):
        # Simulate an external client IP
        client_external = TestClient(
            app.app,
            base_url='https://vps.example.com',
            client=('203.0.113.10', 54321)
        )
        res_cf = client_external.post('/api/setup/verify-cf', json={'token': 'test'})
        self.assertEqual(res_cf.status_code, 401)

        res_key = client_external.post('/api/setup/generate-key')
        self.assertEqual(res_key.status_code, 401)

        res_save = client_external.post('/api/setup/save', json={'provider_type': 'auto'})
        self.assertEqual(res_save.status_code, 401)

    def test_atomic_config_storage_concurrency(self):
        errors = []

        def worker(thread_idx):
            for i in range(10):
                val = f"test_val_{thread_idx}_{i}"
                ok = sentinel_core.ConfigManager.update_key(f"test_concurrency_{thread_idx}", val)
                if not ok:
                    errors.append(f"Write failure in thread {thread_idx} loop {i}")
                cfg = sentinel_core.ConfigManager.load()
                if not isinstance(cfg, dict):
                    errors.append(f"Read corrupted in thread {thread_idx} loop {i}")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(errors), 0, f"Concurrent config write errors: {errors}")

    def test_host_guard_ip_and_auth_bypass(self):
        class DummyRequest:
            def __init__(self, host, cookies=None, headers=None, client_ip="203.0.113.5"):
                self.headers = headers or {"host": host}
                self.cookies = cookies or {}
                self.query_params = {}
                self.client = type("Client", (), {"host": client_ip})()

        # Unauthenticated raw IP probe should be rejected
        req_raw_ip = DummyRequest(host="129.146.230.81")
        self.assertFalse(app.auth.check_host_guard(req_raw_ip))

        # Authenticated raw IP probe with admin cookie should be allowed
        req_auth_ip = DummyRequest(
            host="129.146.230.81",
            cookies={"sentinel_session": self.admin_token}
        )
        self.assertTrue(app.auth.check_host_guard(req_auth_ip))

        # Authenticated raw IP probe with Bearer token should be allowed
        req_bearer_ip = DummyRequest(
            host="129.146.230.81",
            headers={"host": "129.146.230.81", "authorization": f"Bearer {self.sub_token}"}
        )
        self.assertTrue(app.auth.check_host_guard(req_bearer_ip))

    def test_mesh_proxy_aggregation_in_subscriptions(self):
        mock_mesh_nodes = [
            {
                "id": "node_test_mesh",
                "name": "Tokyo-Test",
                "host": "tokyo.test.com:20540",
                "enabled": True,
                "proxy_nodes": [
                    {
                        "type": "vless",
                        "name": "[Tokyo-Test] VLESS-Reality",
                        "server": "140.238.10.10",
                        "port": 8443,
                        "uuid": "00000000-0000-0000-0000-000000000001",
                        "network": "tcp",
                        "tls": True,
                        "flow": "xtls-rprx-vision",
                        "servername": "swdist.apple.com",
                        "reality-opts": {
                            "public-key": "abcdef123456",
                            "short-id": "1234"
                        },
                        "raw_link": "vless://00000000-0000-0000-0000-000000000001@140.238.10.10:8443?security=reality&sni=swdist.apple.com&pbk=abcdef123456&sid=1234&type=tcp&flow=xtls-rprx-vision#[Tokyo-Test] VLESS-Reality"
                    }
                ]
            }
        ]

        original_get_nodes = mesh_mgr.MeshManager.get_nodes
        try:
            mesh_mgr.MeshManager.get_nodes = classmethod(lambda cls: mock_mesh_nodes)

            # Test Clash output contains mesh proxy
            clash_yaml = sub_engine.SubEngine.generate_clash_yaml()
            self.assertIn("[Tokyo-Test] VLESS-Reality", clash_yaml)

            # Test Sing-box output contains mesh proxy
            singbox_json = sub_engine.SubEngine.generate_singbox_json()
            self.assertIn("[Tokyo-Test] VLESS-Reality", singbox_json)

            # Test Base64 output contains mesh proxy link
            b64_output = sub_engine.SubEngine.generate_v2ray_base64()
            import base64
            decoded = base64.b64decode(b64_output).decode('utf-8')
            self.assertIn("[Tokyo-Test] VLESS-Reality", decoded)
        finally:
            mesh_mgr.MeshManager.get_nodes = original_get_nodes

if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for Web Setup Quick Start endpoint and Host Guard uninitialized state.
Strictly Zero Emojis.
"""

import json
import unittest
from starlette.testclient import TestClient

import sentinel_core
import auth_mgr
import clean_ip_mgr
import app


class TestQuickSetup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orig_config = sentinel_core.ConfigManager.load()
        cls.client = TestClient(app.app, base_url="https://vps.example.com")

    @classmethod
    def tearDownClass(cls):
        sentinel_core.ConfigManager.save(cls.orig_config)

    def setUp(self):
        # Reset configuration for each test to a clean state
        test_cfg = json.loads(json.dumps(self.orig_config))
        test_cfg["initialized"] = False
        test_cfg["security"] = {
            "auth_enabled": True,
            "admin_username": "admin",
            "admin_password_hash": app.auth.hash_password("mNq7gQGr"),
            "session_secret": "quick_setup_session_secret_12345",
            "secret_path": "/sentinel",
            "sub_token": "quick_test_sub_token_999",
            "enable_host_guard": True,
            "allowed_hosts": []
        }
        test_cfg["cloudflare"] = {
            "api_token": "",
            "zone_name": "",
            "record_name": ""
        }
        test_cfg["edgetunnel"] = {
            "enabled": False,
            "pages_domain": "",
            "pages_uuid": "",
            "worker_domain": "",
            "worker_uuid": ""
        }
        sentinel_core.ConfigManager.save(test_cfg)
        self.admin_token = app.auth.create_session_token("admin")

    def test_uuid_validation_helper(self):
        valid_uuid = "e7b0a880-9765-4f40-8b17-7e61e05d0e2e"
        self.assertEqual(clean_ip_mgr.validate_uuid(valid_uuid), valid_uuid)
        self.assertEqual(clean_ip_mgr.CleanIPManager.validate_uuid(valid_uuid.upper()), valid_uuid)
        self.assertEqual(clean_ip_mgr.validate_uuid("invalid-uuid"), "")
        self.assertEqual(clean_ip_mgr.validate_uuid(""), "")
        self.assertEqual(clean_ip_mgr.validate_uuid(None), "")

    def test_host_guard_uninitialized_allows_raw_ip(self):
        class DummyRequest:
            def __init__(self, host, cookies=None, headers=None, client_ip="203.0.113.10"):
                self.headers = headers or {"host": host}
                self.cookies = cookies or {}
                self.query_params = {}
                self.client = type("Client", (), {"host": client_ip})()

        # When uninitialized and allowed_hosts is empty, raw IP is permitted for setup
        req = DummyRequest(host="129.146.230.81")
        self.assertTrue(app.auth.check_host_guard(req))

    def test_quick_start_edgetunnel_mode(self):
        payload = {
            "outbound_mode": "edgetunnel",
            "admin_password": "NewSecretPass123",
            "pages_domain": "https://my-pages.pages.dev/",
            "pages_uuid": "e7b0a880-9765-4f40-8b17-7e61e05d0e2e",
            "worker_domain": "my-worker.workers.dev",
            "worker_uuid": "b2c3d4e5-6789-4012-9abc-def012345678"
        }
        cookies = {"sentinel_session": self.admin_token}
        res = self.client.post("/api/setup/quick-start", json=payload, cookies=cookies)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("sub_token"), "quick_test_sub_token_999")
        self.assertIn("/sub/clash?token=quick_test_sub_token_999", data.get("urls", {}).get("clash", ""))
        self.assertIn("/sub/singbox?token=quick_test_sub_token_999", data.get("urls", {}).get("singbox", ""))
        self.assertIn("/sub/v2ray?token=quick_test_sub_token_999", data.get("urls", {}).get("v2ray", ""))

        # Verify config was persisted
        cfg = sentinel_core.ConfigManager.load()
        self.assertTrue(cfg.get("initialized"))
        edt = cfg.get("edgetunnel", {})
        self.assertTrue(edt.get("enabled"))
        self.assertEqual(edt.get("pages_domain"), "my-pages.pages.dev")
        self.assertEqual(edt.get("pages_uuid"), "e7b0a880-9765-4f40-8b17-7e61e05d0e2e")
        self.assertEqual(edt.get("worker_domain"), "my-worker.workers.dev")
        self.assertEqual(edt.get("worker_uuid"), "b2c3d4e5-6789-4012-9abc-def012345678")

        # Verify admin password was updated
        self.assertTrue(app.auth.verify_password("NewSecretPass123", cfg["security"]["admin_password_hash"]))

    def test_quick_start_native_mode(self):
        payload = {
            "outbound_mode": "native",
            "admin_password": "NativePass987"
        }
        cookies = {"sentinel_session": self.admin_token}
        res = self.client.post("/api/setup/quick-start", json=payload, cookies=cookies)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))

        cfg = sentinel_core.ConfigManager.load()
        self.assertTrue(cfg.get("initialized"))
        self.assertFalse(cfg.get("edgetunnel", {}).get("enabled"))
        self.assertTrue(app.auth.verify_password("NativePass987", cfg["security"]["admin_password_hash"]))

    def test_host_guard_locks_after_initialized_with_domain(self):
        # Configure domain and mark initialized
        cfg = sentinel_core.ConfigManager.load()
        cfg["initialized"] = True
        cfg["security"]["allowed_hosts"] = ["mysentinel.com"]
        sentinel_core.ConfigManager.save(cfg)

        class DummyRequest:
            def __init__(self, host, cookies=None, headers=None, client_ip="203.0.113.10"):
                self.headers = headers or {"host": host}
                self.cookies = cookies or {}
                self.query_params = {}
                self.client = type("Client", (), {"host": client_ip})()

        # Raw IP without authentication should now be rejected by Host Guard
        req_raw_ip = DummyRequest(host="129.146.230.81")
        self.assertFalse(app.auth.check_host_guard(req_raw_ip))

        # Allowed domain should be accepted
        req_domain = DummyRequest(host="mysentinel.com")
        self.assertTrue(app.auth.check_host_guard(req_domain))


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Oracle Sentinel - Decoupling Phase 0 & Phase 1 Test Suite
# Tests paths convergence, ServiceManager abstraction, BaseDnsProvider hierarchy,
# and verifies R14 config isolation. Strictly zero emojis.
# ==============================================================================

import os
import sys
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    import tests.sandbox  # noqa: F401
except ImportError:
    import sandbox  # noqa: F401

import paths
import service_mgr
import sentinel_core


class TestPathsConvergence(unittest.TestCase):
    def test_paths_default_exports(self):
        self.assertTrue(os.path.isdir(paths.BASE_DIR))
        self.assertIn('static', paths.STATIC_PATH)
        self.assertIn('config.json', paths.CONFIG_PATH)
        self.assertIn('traffic.db', paths.TRAFFIC_DB_PATH)

    def test_vpsentinel_config_path_env_override(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            custom_cfg = os.path.join(tmp_dir, 'custom_override.json')
            with patch.dict(os.environ, {'VPSENTINEL_CONFIG_PATH': custom_cfg}):
                self.assertEqual(paths.get_config_path(), custom_cfg)
                self.assertEqual(sentinel_core.get_active_config_path(), custom_cfg)

    def test_vpsentinel_home_env_override(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            orig_cfg = os.environ.get('VPSENTINEL_CONFIG_PATH')
            try:
                with patch.dict(os.environ, {'VPSENTINEL_HOME': tmp_dir}, clear=False):
                    os.environ.pop('VPSENTINEL_CONFIG_PATH', None)
                    expected_cfg = os.path.join(tmp_dir, 'config.json')
                    self.assertEqual(paths.get_config_path(), expected_cfg)
            finally:
                if orig_cfg is not None:
                    os.environ['VPSENTINEL_CONFIG_PATH'] = orig_cfg


class TestServiceManagerAbstraction(unittest.TestCase):
    def test_noop_service_manager(self):
        mgr = service_mgr.NoopServiceManager()
        ok_rel, msg_rel = mgr.reload('x-ui')
        self.assertTrue(ok_rel)
        self.assertIn('Simulated reload', msg_rel)

        ok_rst, msg_rst = mgr.restart('vpsentinel')
        self.assertTrue(ok_rst)
        self.assertIn('Simulated restart', msg_rst)

        self.assertTrue(mgr.is_active('any_service'))

    @patch('subprocess.run')
    def test_systemd_service_manager(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = 'Reloading done'
        mock_proc.stderr = ''
        mock_run.return_value = mock_proc

        mgr = service_mgr.SystemdServiceManager()
        ok, msg = mgr.reload('x-ui')
        self.assertTrue(ok)
        self.assertIn('Reloading done', msg)
        self.assertIn('systemctl reload x-ui', mock_run.call_args[0][0])

        mock_proc.returncode = 1
        mock_proc.stdout = ''
        mock_proc.stderr = 'Unit not found'
        ok_fail, msg_fail = mgr.restart('bad_service')
        self.assertFalse(ok_fail)
        self.assertIn('Unit not found', msg_fail)

    def test_service_manager_factory_and_injection(self):
        orig_mgr = service_mgr._global_service_manager
        try:
            custom_mock = MagicMock(spec=service_mgr.BaseServiceManager)
            service_mgr.set_service_manager(custom_mock)
            self.assertEqual(service_mgr.get_service_manager(), custom_mock)

            service_mgr.set_service_manager(None)
            mgr = service_mgr.get_service_manager()
            self.assertIsInstance(mgr, (service_mgr.SystemdServiceManager, service_mgr.NoopServiceManager))
        finally:
            service_mgr.set_service_manager(orig_mgr)


class TestDnsProviderAbstraction(unittest.TestCase):
    def test_cloudflare_dns_provider_inheritance_and_alias(self):
        prov = sentinel_core.CloudflareDnsProvider(api_token='test_token', zone_name='example.com')
        self.assertIsInstance(prov, sentinel_core.BaseDnsProvider)
        self.assertEqual(prov.get_name(), 'Cloudflare DNS')
        self.assertEqual(sentinel_core.CloudflareManager, sentinel_core.CloudflareDnsProvider)

    def test_get_dns_provider_legacy_cloudflare_config(self):
        cfg = {
            'cloudflare': {
                'api_token': 'legacy_cf_token_123',
                'zone_name': 'legacy.com'
            }
        }
        prov = sentinel_core.get_dns_provider(cfg)
        self.assertIsInstance(prov, sentinel_core.CloudflareDnsProvider)
        self.assertEqual(prov.api_token, 'legacy_cf_token_123')
        self.assertEqual(prov.zone_name, 'legacy.com')

    def test_get_dns_provider_new_dns_config(self):
        cfg = {
            'dns': {
                'type': 'cloudflare',
                'api_token': 'new_cf_token_456',
                'zone_name': 'newzone.com'
            }
        }
        prov = sentinel_core.get_dns_provider(cfg)
        self.assertIsInstance(prov, sentinel_core.CloudflareDnsProvider)
        self.assertEqual(prov.api_token, 'new_cf_token_456')
        self.assertEqual(prov.zone_name, 'newzone.com')

    def test_get_dns_provider_unknown_fallback_to_cloudflare(self):
        cfg = {
            'dns': {
                'type': 'unknown_provider_xyz',
                'api_token': 'fallback_token'
            }
        }
        prov = sentinel_core.get_dns_provider(cfg, zone_name='override.com')
        self.assertIsInstance(prov, sentinel_core.CloudflareDnsProvider)
        self.assertEqual(prov.api_token, 'fallback_token')
        self.assertEqual(prov.zone_name, 'override.com')

    @patch('requests.get')
    def test_cloudflare_provider_verify_token(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'success': True}
        mock_get.return_value = mock_resp

        prov = sentinel_core.CloudflareDnsProvider('valid_token')
        ok, msg = prov.verify_token()
        self.assertTrue(ok)
        self.assertIn('successfully', msg)
        self.assertEqual(mock_get.call_count, 1)

    @patch('requests.get')
    def test_cloudflare_provider_list_zones(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'success': True,
            'result': [{'id': 'zone1', 'name': 'example.com'}]
        }
        mock_get.return_value = mock_resp

        prov = sentinel_core.CloudflareDnsProvider('valid_token')
        ok, zones, msg = prov.list_zones()
        self.assertTrue(ok)
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0]['name'], 'example.com')


class TestR14ConfigIsolation(unittest.TestCase):
    def test_root_config_json_not_modified_by_sandbox(self):
        real_cfg_path = os.path.join(BASE_DIR, 'config.json')
        if not os.path.exists(real_cfg_path):
            self.skipTest('Real config.json not present in BASE_DIR')

        st_before = os.stat(real_cfg_path)
        mtime_before = st_before.st_mtime_ns

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_cfg = os.path.join(tmp_dir, 'config.json')
            with patch.dict(os.environ, {'VPSENTINEL_CONFIG_PATH': tmp_cfg}):
                sentinel_core.ConfigManager.save({'isolated_key': 'sandboxed_value'})
                loaded = sentinel_core.ConfigManager.load()
                self.assertEqual(loaded.get('isolated_key'), 'sandboxed_value')

        st_after = os.stat(real_cfg_path)
        mtime_after = st_after.st_mtime_ns
        self.assertEqual(mtime_before, mtime_after)


if __name__ == '__main__':
    unittest.main()

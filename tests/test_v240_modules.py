import os
import sys
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    import tests.sandbox  # noqa: F401
except ImportError:
    import sandbox  # noqa: F401

import traffic_mgr
import mesh_mgr
import bot_mgr

class TestV240Modules(unittest.TestCase):
    def test_traffic_billing_cycle_dates(self):
        start_date, next_reset, days_rem = traffic_mgr.TrafficManager.get_billing_cycle_dates(reset_day=1)
        self.assertTrue(len(start_date) == 10)
        self.assertTrue(len(next_reset) == 10)
        self.assertGreaterEqual(days_rem, 0)
        self.assertLessEqual(days_rem, 31)

    def test_traffic_quota_config(self):
        traffic_mgr.TrafficManager.init_db()
        cfg = traffic_mgr.TrafficManager.get_quota_config()
        self.assertIn('monthly_limit_gb', cfg)
        self.assertIn('alert_threshold_pct', cfg)
        self.assertIn('reset_day', cfg)

    def test_mesh_overview_structure(self):
        overview = mesh_mgr.MeshManager.get_mesh_overview(local_state_func=lambda: {'public_ip': '1.2.3.4'})
        self.assertIn('total_nodes', overview)
        self.assertIn('online_nodes', overview)
        self.assertIn('health_pct', overview)
        self.assertIn('nodes', overview)
        self.assertGreaterEqual(overview['total_nodes'], 1)

    def test_bot_main_keyboard(self):
        bot = bot_mgr.get_bot_instance()
        kb = bot.get_main_keyboard()
        self.assertIn('inline_keyboard', kb)
        buttons = [btn['text'] for row in kb['inline_keyboard'] for btn in row]
        self.assertIn('运行状态', buttons)
        self.assertIn('集群概览', buttons)
        self.assertIn('三网测速', buttons)
        self.assertIn('订阅导出', buttons)
        self.assertIn('触发换 IP', buttons)

if __name__ == '__main__':
    unittest.main()

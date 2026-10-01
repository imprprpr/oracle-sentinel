import os
import sys
import unittest
import base64
import json
import yaml

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    import tests.sandbox  # noqa: F401
except ImportError:
    import sandbox  # noqa: F401

import custom_node_mgr
import sub_engine

class TestCustomNodes(unittest.TestCase):
    def setUp(self):
        self.japan_link = (
            "vless://fe4a207f-8fc6-4371-9dec-ff5f4b6e8e49@158.51.111.141:53446"
            "?encryption=none&flow=xtls-rprx-vision&security=reality&sni=swdist.apple.com"
            "&fp=chrome&pbk=sxZBWUr_VD0FVLTRA9ItNpwq52Lt8bz2l4UpfNS4Vgc&sid=6f6717d02ba01689&type=tcp"
            "#JP-%E6%97%A5%E6%9C%AC%E5%8E%9F%E7%94%9F%E5%A4%A7%E5%8F%A3%E5%AD%90"
        )
        self.hy2_link = "hysteria2://myauth@1.2.3.4:20443?sni=my.domain.com&insecure=1&mport=20000-40000#HK-Hy2"
        self.trojan_link = "trojan://mypass@5.6.7.8:22083?sni=tr.domain.com#SG-Trojan"
        self.ss_link = "ss://YWVzLTEyOC1nY206cGFzc3dvcmQ=@9.10.11.12:8388#US-SS"

    def test_parse_vless_reality(self):
        node = custom_node_mgr.CustomNodeManager.parse_link(self.japan_link)
        self.assertEqual(node['type'], 'vless')
        self.assertEqual(node['name'], 'JP-日本原生大口子')
        self.assertEqual(node['server'], '158.51.111.141')
        self.assertEqual(node['port'], 53446)
        self.assertEqual(node['uuid'], 'fe4a207f-8fc6-4371-9dec-ff5f4b6e8e49')
        self.assertEqual(node['reality-opts']['public-key'], 'sxZBWUr_VD0FVLTRA9ItNpwq52Lt8bz2l4UpfNS4Vgc')
        self.assertEqual(node['reality-opts']['short-id'], '6f6717d02ba01689')

    def test_clash_conversion(self):
        node = custom_node_mgr.CustomNodeManager.parse_link(self.japan_link)
        clash_proxy = custom_node_mgr.CustomNodeManager.to_clash_proxy(node)
        self.assertEqual(clash_proxy['name'], 'JP-日本原生大口子')
        self.assertEqual(clash_proxy['type'], 'vless')
        self.assertEqual(clash_proxy['server'], '158.51.111.141')
        self.assertEqual(clash_proxy['port'], 53446)
        self.assertEqual(clash_proxy['reality-opts']['public-key'], 'sxZBWUr_VD0FVLTRA9ItNpwq52Lt8bz2l4UpfNS4Vgc')

    def test_singbox_conversion(self):
        node = custom_node_mgr.CustomNodeManager.parse_link(self.japan_link)
        sb_out = custom_node_mgr.CustomNodeManager.to_singbox_outbound(node)
        self.assertEqual(sb_out['tag'], 'JP-日本原生大口子')
        self.assertEqual(sb_out['type'], 'vless')
        self.assertEqual(sb_out['server'], '158.51.111.141')
        self.assertEqual(sb_out['server_port'], 53446)
        self.assertTrue(sb_out['tls']['reality']['enabled'])

    def test_sub_engine_integration(self):
        node = custom_node_mgr.CustomNodeManager.parse_link(self.japan_link)
        custom_node_mgr.CustomNodeManager.get_custom_nodes = staticmethod(lambda: [node])

        # Clash YAML test
        clash_yaml = sub_engine.SubEngine.generate_clash_yaml()
        cfg = yaml.safe_load(clash_yaml)
        names = [p['name'] for p in cfg['proxies']]
        self.assertIn('JP-日本原生大口子', names)
        native_group = next((g for g in cfg['proxy-groups'] if g['name'] in ('原生节点 (VPS)', '节点选择')), None)
        self.assertIsNotNone(native_group)
        self.assertIn('JP-日本原生大口子', native_group['proxies'])

        # v2ray Base64 test
        b64 = sub_engine.SubEngine.generate_v2ray_base64()
        decoded = base64.b64decode(b64).decode()
        self.assertIn('158.51.111.141:53446', decoded)

        # Sing-box JSON test
        sb_json = sub_engine.SubEngine.generate_singbox_json()
        sb_cfg = json.loads(sb_json)
        tags = [o.get('tag') for o in sb_cfg['outbounds']]
        self.assertIn('JP-日本原生大口子', tags)

if __name__ == '__main__':
    unittest.main()

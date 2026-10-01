# -*- coding: utf-8 -*-
# ==============================================================================
# Oracle Sentinel - Test Suite Global Sandbox Fixture (R14 Isolation)
# Ensures test executions never modify the real repository config.json.
# Strictly zero emojis.
# ==============================================================================

import os
import shutil
import tempfile
import atexit

_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_real_cfg = os.path.join(_repo_root, 'config.json')

if 'VPSENTINEL_CONFIG_PATH' not in os.environ:
    _sandbox_dir = tempfile.mkdtemp(prefix='sentinel_test_sandbox_')
    _sandbox_cfg = os.path.join(_sandbox_dir, 'config.json')
    if os.path.exists(_real_cfg):
        shutil.copy2(_real_cfg, _sandbox_cfg)
    else:
        with open(_sandbox_cfg, 'w', encoding='utf-8') as f:
            f.write('{}')
    os.environ['VPSENTINEL_CONFIG_PATH'] = _sandbox_cfg

    def _cleanup():
        shutil.rmtree(_sandbox_dir, ignore_errors=True)

    atexit.register(_cleanup)

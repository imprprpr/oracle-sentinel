#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Oracle Sentinel - Service Management Abstraction
# Decouples systemd from container and lightweight Linux environments
# ==============================================================================

import os
import shutil
import logging
import subprocess
from typing import Tuple

logger = logging.getLogger('ServiceManager')


class BaseServiceManager:
    """
    Abstract interface for managing system services (e.g. x-ui, vpsentinel, realm).
    """
    def reload(self, service_name: str) -> Tuple[bool, str]:
        raise NotImplementedError

    def restart(self, service_name: str) -> Tuple[bool, str]:
        raise NotImplementedError

    def is_active(self, service_name: str) -> bool:
        raise NotImplementedError


class SystemdServiceManager(BaseServiceManager):
    """
    Standard service manager using systemctl commands.
    """
    def reload(self, service_name: str) -> Tuple[bool, str]:
        cmd = f"systemctl reload {service_name} 2>/dev/null || systemctl restart {service_name} 2>/dev/null"
        try:
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            ok = (res.returncode == 0)
            msg = res.stdout.strip() or res.stderr.strip() or ("Reloaded successfully" if ok else "Reload failed")
            return ok, msg
        except Exception as e:
            return False, str(e)

    def restart(self, service_name: str) -> Tuple[bool, str]:
        cmd = f"systemctl restart {service_name} 2>/dev/null"
        try:
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            ok = (res.returncode == 0)
            msg = res.stdout.strip() or res.stderr.strip() or ("Restarted successfully" if ok else "Restart failed")
            return ok, msg
        except Exception as e:
            return False, str(e)

    def is_active(self, service_name: str) -> bool:
        try:
            res = subprocess.run(f"systemctl is-active --quiet {service_name}", shell=True)
            return res.returncode == 0
        except Exception:
            return False


class NoopServiceManager(BaseServiceManager):
    """
    Fallback service manager for Docker containers or non-systemd environments.
    Logs actions without executing failing systemctl commands.
    """
    def reload(self, service_name: str) -> Tuple[bool, str]:
        logger.info(f"Container/No-systemd mode: simulated service reload for '{service_name}'")
        return True, f"Simulated reload for {service_name}"

    def restart(self, service_name: str) -> Tuple[bool, str]:
        logger.info(f"Container/No-systemd mode: simulated service restart for '{service_name}'")
        return True, f"Simulated restart for {service_name}"

    def is_active(self, service_name: str) -> bool:
        return True


_global_service_manager = None


def is_systemd_available() -> bool:
    """
    Checks if systemd is actively running and systemctl executable is present.
    """
    return os.path.exists('/run/systemd/system') and (shutil.which('systemctl') is not None)


def get_service_manager() -> BaseServiceManager:
    """
    Returns the appropriate service manager instance based on host environment.
    """
    if _global_service_manager is not None:
        return _global_service_manager

    if is_systemd_available():
        return SystemdServiceManager()
    return NoopServiceManager()


def set_service_manager(mgr: BaseServiceManager):
    """
    Allows injecting a custom or mock service manager during testing or custom deployment.
    """
    global _global_service_manager
    _global_service_manager = mgr

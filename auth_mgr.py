#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VPSentinel Authentication, Session & Host Guard Module
Author: Antigravity Agent
"""

import os
import time
import hmac
import hashlib
import secrets
import base64
import logging
import ipaddress
from typing import Optional, Dict, Any, Tuple
try:
    from fastapi import Request, Response, HTTPException
except ImportError:
    Request = Any
    Response = Any
    HTTPException = Exception

logger = logging.getLogger("AuthMgr")

DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASS = "mNq7gQGr"
DEFAULT_SAFE_PATH = "/sentinel"
SESSION_TTL_SEC = 86400 * 30  # 30 days session validity

class AuthManager:
    def __init__(self, cfg_mgr):
        self.cfg_mgr = cfg_mgr
        self._ensure_security_config()

    def _ensure_security_config(self):
        """Initializes default security settings in config.json if not present."""
        cfg = self.cfg_mgr.load()
        sec = cfg.setdefault("security", {})
        changed = False

        if "auth_enabled" not in sec:
            sec["auth_enabled"] = True
            changed = True

        if "admin_username" not in sec:
            sec["admin_username"] = DEFAULT_ADMIN_USER
            changed = True

        if "admin_password_hash" not in sec or not sec["admin_password_hash"]:
            sec["admin_password_hash"] = self.hash_password(DEFAULT_ADMIN_PASS)
            changed = True

        if "session_secret" not in sec or not sec["session_secret"]:
            sec["session_secret"] = secrets.token_hex(32)
            changed = True

        if "sub_token" not in sec or not sec["sub_token"]:
            sec["sub_token"] = secrets.token_hex(16)
            changed = True

        if "secret_path" not in sec:
            sec["secret_path"] = DEFAULT_SAFE_PATH
            changed = True

        if "enable_host_guard" not in sec:
            sec["enable_host_guard"] = True
            changed = True

        if "allowed_hosts" not in sec:
            # Auto populate domain if known
            cf_record = cfg.get("cloudflare", {}).get("record_name", "").strip()
            sec["allowed_hosts"] = [cf_record] if cf_record else []
            changed = True

        if changed:
            self.cfg_mgr.save(cfg)
            logger.info("Security configuration initialized successfully.")

    def get_security_config(self) -> Dict[str, Any]:
        cfg = self.cfg_mgr.load()
        return cfg.get("security", {})

    @staticmethod
    def hash_password(password: str, salt: Optional[str] = None) -> str:
        if not salt:
            salt = secrets.token_hex(16)
        key = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
        return f"{salt}:{key}"

    @classmethod
    def verify_password(cls, password: str, stored_hash: str) -> bool:
        if not stored_hash or ":" not in stored_hash:
            return False
        try:
            salt, expected_key = stored_hash.split(":", 1)
            calculated_key = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
            return hmac.compare_digest(expected_key, calculated_key)
        except Exception:
            return False

    def authenticate_admin(self, username: str, password: str) -> Tuple[bool, str]:
        sec = self.get_security_config()
        expected_user = sec.get("admin_username", DEFAULT_ADMIN_USER)
        expected_hash = sec.get("admin_password_hash", "")

        if username != expected_user:
            return False, "用户名或密码错误"

        if not self.verify_password(password, expected_hash):
            return False, "用户名或密码错误"

        # Generate HMAC session token
        token = self.create_session_token(username)
        return True, token

    def create_session_token(self, username: str) -> str:
        sec = self.get_security_config()
        secret_key = sec.get("session_secret", "sentinel_secret").encode("utf-8")
        timestamp = str(int(time.time()))
        payload = f"{username}:{timestamp}"
        signature = hmac.new(secret_key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        raw = f"{payload}:{signature}"
        return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")

    def verify_session_token(self, token: Optional[str]) -> bool:
        if not token:
            return False
        sec = self.get_security_config()
        if not sec.get("auth_enabled", True):
            return True

        try:
            raw = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
            parts = raw.split(":")
            if len(parts) != 3:
                return False
            username, timestamp_str, signature = parts
            timestamp = int(timestamp_str)
            now = int(time.time())

            if now - timestamp > SESSION_TTL_SEC:
                return False  # Expired

            secret_key = sec.get("session_secret", "sentinel_secret").encode("utf-8")
            expected_payload = f"{username}:{timestamp_str}"
            expected_sig = hmac.new(secret_key, expected_payload.encode("utf-8"), hashlib.sha256).hexdigest()
            return hmac.compare_digest(signature, expected_sig)
        except Exception:
            return False

    def is_request_authenticated(self, request: Request) -> bool:
        sec = self.get_security_config()
        if not sec.get("auth_enabled", True):
            return True

        # 1. Check Cookie
        cookie_token = request.cookies.get("sentinel_session")
        if self.verify_session_token(cookie_token):
            return True

        # 2. Check Authorization Header (Bearer <token>)
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
            if self.verify_session_token(token):
                return True

        # 3. Check Query parameter
        query_token = request.query_params.get("session_token")
        if self.verify_session_token(query_token):
            return True

        return False

    def verify_subscription_access(self, request: Request) -> bool:
        """Verifies if request has permission to download Clash/Singbox sub."""
        sec = self.get_security_config()
        if not sec.get("auth_enabled", True):
            return True

        # If admin is logged in
        if self.is_request_authenticated(request):
            return True

        # Check sub_token query parameter or path
        expected_sub_token = sec.get("sub_token", "")
        if not expected_sub_token:
            return True

        token_param = request.query_params.get("token", "")
        if token_param and hmac.compare_digest(token_param, expected_sub_token):
            return True

        # Also support sub_token passed via Bearer
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            b_token = auth_header[7:].strip()
            if hmac.compare_digest(b_token, expected_sub_token):
                return True

        return False

    def check_host_guard(self, request: Request) -> bool:
        """
        Validates request Host header.
        Rejects raw IP scans (e.g. https://129.146.230.81:20540).
        """
        sec = self.get_security_config()
        if not sec.get("enable_host_guard", True):
            return True

        raw_host = request.headers.get("host", "").strip()
        if not raw_host:
            return False

        # Extract hostname part without port
        hostname = raw_host.split(":")[0].strip().lower()

        # Local loopback & local probes always allowed
        if hostname in ("127.0.0.1", "localhost", "::1"):
            return True

        # Build allowed list
        cfg = self.cfg_mgr.load()
        cf_record = cfg.get("cloudflare", {}).get("record_name", "").strip().lower()
        allowed = [h.strip().lower() for h in sec.get("allowed_hosts", []) if h.strip()]
        if cf_record and cf_record not in allowed:
            allowed.append(cf_record)

        # Check if hostname matches any allowed host
        if hostname in allowed:
            return True

        # If it's a raw IP address that wasn't explicitly whitelisted, reject!
        try:
            ipaddress.ip_address(hostname)
            # It IS a raw IP address (e.g. 129.146.230.81) -> BLOCK!
            logger.warning(f"Host Guard blocked direct IP probe: Host='{raw_host}' from Client='{request.client.host if request.client else 'unknown'}'")
            return False
        except ValueError:
            # It is a domain name. If allowed_hosts list is empty, allow it; otherwise require match.
            if not allowed:
                return True
            return False

    def update_password(self, new_password: str) -> bool:
        if not new_password or len(new_password) < 6:
            return False
        cfg = self.cfg_mgr.load()
        sec = cfg.setdefault("security", {})
        sec["admin_password_hash"] = self.hash_password(new_password)
        # Invalidate existing sessions by rotating session secret
        sec["session_secret"] = secrets.token_hex(32)
        self.cfg_mgr.save(cfg)
        logger.info("Admin password updated successfully.")
        return True

    def update_security_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        cfg = self.cfg_mgr.load()
        sec = cfg.setdefault("security", {})
        for k in ["auth_enabled", "secret_path", "enable_host_guard", "allowed_hosts"]:
            if k in settings:
                sec[k] = settings[k]
        if settings.get("regenerate_sub_token"):
            sec["sub_token"] = secrets.token_hex(16)
        self.cfg_mgr.save(cfg)
        return sec

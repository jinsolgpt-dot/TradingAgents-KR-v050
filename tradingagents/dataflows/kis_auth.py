# Adapted from TradingAgents-KR ce0aa456419800c29325516f984fc55a9a8f14dd (Apache-2.0).
"""Read-only KIS authentication; credentials and tokens are never written to disk."""
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import requests

from .errors import VendorNotConfiguredError, VendorRateLimitError

KST = timezone(timedelta(hours=9))

class KISAuthError(RuntimeError):
    pass

@dataclass
class KISToken:
    access_token: str = field(repr=False)
    expires_at: datetime

    @property
    def is_valid(self):
        return datetime.now(KST) < self.expires_at - timedelta(minutes=10)

class KISAuthManager:
    def __init__(self, app_key=None, app_secret=None, base_url=None):
        self.app_key = app_key or os.getenv("KIS_APP_KEY", "")
        self.app_secret = app_secret or os.getenv("KIS_APP_SECRET", "")
        self.base_url = base_url or "https://openapi.koreainvestment.com:9443"
        if self.base_url not in ("https://openapi.koreainvestment.com:9443", "https://openapivts.koreainvestment.com:29443"):
            raise ValueError("KIS base_url must be an official KIS HTTPS endpoint")
        self._token = None
        self._lock = threading.Lock()

    def issue_token(self):
        if not self.app_key or not self.app_secret:
            raise VendorNotConfiguredError("Set KIS_APP_KEY and KIS_APP_SECRET")
        try:
            response = requests.post(self.base_url + "/oauth2/tokenP", json={
                "grant_type": "client_credentials", "appkey": self.app_key,
                "appsecret": self.app_secret}, timeout=20)
            if response.status_code == 429:
                raise VendorRateLimitError("KIS authentication rate limit")
            response.raise_for_status()
            data = response.json()
            expiry = datetime.strptime(data["access_token_token_expired"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
            return KISToken(data["access_token"], expiry)
        except (requests.RequestException, ValueError, KeyError):
            raise KISAuthError("KIS token request failed; verify credentials and availability") from None

    def get_token(self, force_refresh=False):
        with self._lock:
            if force_refresh or self._token is None or not self._token.is_valid:
                self._token = self.issue_token()
            return self._token.access_token

    def build_headers(self, tr_id=None, extra_headers=None, force_refresh=False):
        headers = {"content-type": "application/json; charset=utf-8",
                   "authorization": "Bearer " + self.get_token(force_refresh),
                   "appkey": self.app_key, "appsecret": self.app_secret, "custtype": "P"}
        if tr_id:
            headers["tr_id"] = tr_id
        if extra_headers:
            headers.update(extra_headers)
        return headers

_default_manager = None
_manager_lock = threading.Lock()

def get_kis_auth_manager():
    global _default_manager
    with _manager_lock:
        if _default_manager is None:
            _default_manager = KISAuthManager()
        return _default_manager

"""Unified Microsoft Graph API client with retry and session pooling."""

import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

GRAPH_URL = "https://graph.microsoft.com/v1.0"
GRAPH_BETA_URL = "https://graph.microsoft.com/beta"
TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"


class MicrosoftGraphClient:
    """Graph API client using client_credentials flow with retry adapter."""

    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = TOKEN_URL_TEMPLATE.format(tenant_id=tenant_id)
        self._token: str | None = None
        self._token_expiry: float = 0

        # Session with retry
        self._session = requests.Session()
        retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
        self._session.mount("https://", adapter)

    def _acquire_token(self):
        resp = self._session.post(self.token_url, data={
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": GRAPH_SCOPE,
        }, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"Token request failed ({resp.status_code}): {resp.text}")
        data = resp.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + data.get("expires_in", 3600) - 300

    def _headers(self) -> dict:
        if not self._token or time.time() >= self._token_expiry:
            self._acquire_token()
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", 30)
        resp = self._session.request(method, url, headers=self._headers(), **kwargs)
        if resp.status_code >= 400:
            raise RuntimeError(f"Graph API {method} {url} -> {resp.status_code}: {resp.text}")
        return resp

    def get(self, path: str, beta: bool = False) -> requests.Response:
        base = GRAPH_BETA_URL if beta else GRAPH_URL
        return self._request("GET", f"{base}{path}")

    def post(self, path: str, json_data: dict = None, beta: bool = False) -> requests.Response:
        base = GRAPH_BETA_URL if beta else GRAPH_URL
        return self._request("POST", f"{base}{path}", json=json_data)

    def patch(self, path: str, json_data: dict = None, beta: bool = False) -> requests.Response:
        base = GRAPH_BETA_URL if beta else GRAPH_URL
        return self._request("PATCH", f"{base}{path}", json=json_data)

    def delete(self, path: str, beta: bool = False) -> requests.Response:
        base = GRAPH_BETA_URL if beta else GRAPH_URL
        return self._request("DELETE", f"{base}{path}")

    def raw_request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make a request that doesn't auto-raise on error status."""
        kwargs.setdefault("timeout", 30)
        return self._session.request(method, url, headers=self._headers(), **kwargs)

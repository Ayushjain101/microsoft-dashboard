import time
import requests
from config import GRAPH_URL, GRAPH_BETA_URL, TOKEN_URL_TEMPLATE, GRAPH_SCOPE


class GraphClient:
    """Microsoft Graph API client using client_credentials flow."""

    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = TOKEN_URL_TEMPLATE.format(tenant_id=tenant_id)
        self._token = None
        self._token_expiry = 0

    def _acquire_token(self):
        resp = requests.post(self.token_url, data={
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": GRAPH_SCOPE,
        })
        if resp.status_code != 200:
            raise RuntimeError(f"Token request failed ({resp.status_code}): {resp.text}")
        data = resp.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + data.get("expires_in", 3600) - 300  # 5 min buffer

    def _headers(self) -> dict:
        if not self._token or time.time() >= self._token_expiry:
            self._acquire_token()
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        resp = requests.request(method, url, headers=self._headers(), **kwargs)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Graph API {method} {url} → {resp.status_code}: {resp.text}"
            )
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
        return requests.request(method, url, headers=self._headers(), **kwargs)

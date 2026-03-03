import requests
from config import CLOUDFLARE_API_URL, CLOUDFLARE_API_KEY, CLOUDFLARE_EMAIL


class CloudflareClient:
    """Cloudflare DNS API client using Global API Key auth."""

    def __init__(self, api_key: str = None, email: str = None):
        self.api_key = api_key or CLOUDFLARE_API_KEY
        self.email = email or CLOUDFLARE_EMAIL
        self._zone_cache = {}

    def _headers(self) -> dict:
        return {
            "X-Auth-Key": self.api_key,
            "X-Auth-Email": self.email,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{CLOUDFLARE_API_URL}{path}"
        resp = requests.request(method, url, headers=self._headers(), **kwargs)
        data = resp.json()
        if not data.get("success", False):
            errors = data.get("errors", [])
            raise RuntimeError(f"Cloudflare {method} {path} failed: {errors}")
        return data

    def get_zone_id(self, domain: str) -> str:
        """Get zone ID for a domain."""
        if domain in self._zone_cache:
            return self._zone_cache[domain]
        data = self._request("GET", f"/zones?name={domain}")
        results = data.get("result", [])
        if not results:
            raise RuntimeError(f"Zone not found for domain: {domain}")
        zone_id = results[0]["id"]
        self._zone_cache[domain] = zone_id
        return zone_id

    def list_dns_records(self, domain: str, type: str = None, name: str = None) -> list:
        """List DNS records for a zone."""
        zone_id = self.get_zone_id(domain)
        params = {}
        if type:
            params["type"] = type
        if name:
            params["name"] = name
        data = self._request("GET", f"/zones/{zone_id}/dns_records", params=params)
        return data.get("result", [])

    def create_dns_record(self, domain: str, record_type: str, name: str,
                          content: str, ttl: int = 3600, priority: int = None,
                          proxied: bool = False) -> dict:
        """Create a DNS record."""
        zone_id = self.get_zone_id(domain)
        payload = {
            "type": record_type,
            "name": name,
            "content": content,
            "ttl": ttl,
            "proxied": proxied,
        }
        if priority is not None:
            payload["priority"] = priority
        data = self._request("POST", f"/zones/{zone_id}/dns_records", json=payload)
        return data.get("result", {})

    def upsert_dns_record(self, domain: str, record_type: str, name: str,
                          content: str, ttl: int = 3600, priority: int = None,
                          proxied: bool = False) -> dict:
        """Create or update a DNS record. If a record of the same type+name
        exists, update it; otherwise create it."""
        existing = self.list_dns_records(domain, type=record_type, name=name)
        zone_id = self.get_zone_id(domain)
        payload = {
            "type": record_type,
            "name": name,
            "content": content,
            "ttl": ttl,
            "proxied": proxied,
        }
        if priority is not None:
            payload["priority"] = priority

        if existing:
            record_id = existing[0]["id"]
            data = self._request("PUT", f"/zones/{zone_id}/dns_records/{record_id}",
                                 json=payload)
        else:
            data = self._request("POST", f"/zones/{zone_id}/dns_records", json=payload)
        return data.get("result", {})

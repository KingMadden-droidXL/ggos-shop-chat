"""Apollo API client: retries + rate-limit handling.

Reads APOLLO_API_KEY from the environment. No key is stored in the repo.
"""
import os
import time

import requests


class ApolloClient:
    def __init__(self, api_key=None, base_url=None):
        self.base_url = base_url or os.getenv(
            "APOLLO_BASE_URL", "https://api.apollo.io/api/v1"
        )
        self.api_key = api_key or os.getenv("APOLLO_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "APOLLO_API_KEY is not set — add it to .env (never commit it)."
            )
        self.headers = {"Content-Type": "application/json", "x-api-key": self.api_key}

    def _request(self, method, endpoint, **kwargs):
        url = f"{self.base_url}/{endpoint}"
        for attempt in range(3):
            r = requests.request(method, url, headers=self.headers, timeout=30, **kwargs)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()

    def get(self, endpoint, params=None):
        return self._request("GET", endpoint, params=params)

    def post(self, endpoint, payload=None):
        return self._request("POST", endpoint, json=payload or {})

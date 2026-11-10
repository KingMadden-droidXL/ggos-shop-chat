"""Standalone Shopify Admin API client for GGOS.

Gangster-elegant, god-mode as far as the gates allow — and the gates
do not move. This client can READ the whole house: shop, products,
orders, counts. It can WRITE exactly one way, and only when two
locks are both open at the same time:

  1. GGOS_SHOPIFY_WRITE_ENABLED=1 in the environment, AND
  2. approved=True passed to that one call.

No lock, no write. No auto-publish, no auto-send, no spend, no
token in the code, no token in a log. The token is the owner's
shpat_ Admin API token, read from SHOPIFY_ADMIN_TOKEN (or
SHOPIFY_TOKEN) in the environment, and it is never printed.

Env:
  SHOPIFY_SHOP_DOMAIN   e.g. w1q4is-1q.myshopify.com (NoLoveAppeal575)
  SHOPIFY_ADMIN_TOKEN   shpat_... — set it, never commit it, never paste it
  GGOS_SHOPIFY_WRITE_ENABLED   "1" to arm writes; default off
"""
import os
import time

import requests

API_VERSION = "2025-10"


class ShopifyWriteDisabledError(RuntimeError):
    """Raised when a write is attempted without both gates open."""


class ShopifyClient:
    def __init__(self, shop_domain=None, admin_token=None, api_version=None):
        self.shop_domain = shop_domain or os.getenv("SHOPIFY_SHOP_DOMAIN")
        if not self.shop_domain:
            raise RuntimeError(
                "SHOPIFY_SHOP_DOMAIN is not set — e.g. w1q4is-1q.myshopify.com."
            )
        self.admin_token = admin_token or os.getenv(
            "SHOPIFY_ADMIN_TOKEN"
        ) or os.getenv("SHOPIFY_TOKEN")
        if not self.admin_token:
            raise RuntimeError(
                "SHOPIFY_ADMIN_TOKEN is not set — add the shpat_ token to "
                "the environment (never commit it, never paste it in chat)."
            )
        self.api_version = api_version or API_VERSION
        self.base_url = (
            f"https://{self.shop_domain}/admin/api/{self.api_version}"
        )
        self.headers = {
            "X-Shopify-Access-Token": self.admin_token,
            "Content-Type": "application/json",
        }

    # -- the one road in ---------------------------------------------------

    def _request(self, method, endpoint, **kwargs):
        url = f"{self.base_url}/{endpoint}"
        for attempt in range(3):
            r = requests.request(
                method, url, headers=self.headers, timeout=30, **kwargs
            )
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()

    def get(self, endpoint, params=None):
        return self._request("GET", endpoint, params=params)

    # -- reads: the house, wide open to look at ---------------------------

    def get_shop(self):
        """The shop itself: name, domain, plan, currency. Read-only."""
        return self.get("shop.json")["shop"]

    def get_product_count(self):
        return self.get("products/count.json")["count"]

    def get_order_count(self):
        return self.get("orders/count.json")["count"]

    def list_products(self, limit=50, page_info=None):
        """One page of products, newest first. Read-only.

        Returns (products, next_page_info). Pass next_page_info back
        in to walk the whole catalogue, one page at a time.
        """
        params = {"limit": limit}
        if page_info:
            params["page_info"] = page_info
        data = self.get("products.json", params=params)
        link = data.get("_link_header", "")
        nxt = None
        if 'rel="next"' in link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    nxt = part.split("page_info=")[-1].split(">")[0].strip()
        return data.get("products", []), nxt

    def list_all_products(self, limit=50, max_pages=20):
        """Every product, paginated. Read-only. Stops at max_pages so
        a runaway catalogue can never loop forever."""
        products, page_info, pages = [], None, 0
        while pages < max_pages:
            batch, page_info = self.list_products(limit=limit, page_info=page_info)
            products.extend(batch)
            pages += 1
            if not page_info or not batch:
                break
        return products

    def get_product(self, product_id):
        return self.get(f"products/{product_id}.json")["product"]

    def list_orders(self, limit=50, status="any"):
        """Recent orders. Read-only. status='any' includes them all."""
        data = self.get("orders.json", params={"limit": limit, "status": status})
        return data.get("orders", [])

    # -- writes: two locks, both at once, or nothing moves ----------------

    @staticmethod
    def _write_gate(approved):
        if os.environ.get("GGOS_SHOPIFY_WRITE_ENABLED", "0") != "1":
            raise ShopifyWriteDisabledError(
                "Shopify writes are disabled. "
                "Set GGOS_SHOPIFY_WRITE_ENABLED=1 to arm them."
            )
        if not approved:
            raise ShopifyWriteDisabledError(
                "Shopify writes require approved=True on this exact call. "
                "No blanket approval, no silent push."
            )

    def create_product(self, product, *, approved=False):
        """Create ONE product, draft status only, and only with both
        gates open. `product` is the Shopify product dict
        (title, body_html, vendor, product_type, variants, images).
        Returns the created product as Shopify reports it.

        Nothing here ever publishes live on its own: the product is
        created as a draft, and the owner still says the word.
        """
        self._write_gate(approved)
        payload = {"product": {**product, "status": "draft"}}
        return self._request("POST", "products.json", json=payload)["product"]

"""Tests for the standalone Shopify client + godmode sweep.

No network, no live store, no token. requests is mocked; the sweep
runs against a fake client. The gates are the point: reads are free,
writes need both locks, and god mode never applies anything.
"""
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from integrations.shopify import ShopifyClient, ShopifyWriteDisabledError


def _client():
    return ShopifyClient(
        shop_domain="w1q4is-1q.myshopify.com", admin_token="shpat_test"
    )


def _fake_response(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    return resp


class TestShopifyClient(unittest.TestCase):
    def test_missing_domain_raises(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SHOPIFY_SHOP_DOMAIN", None)
            with self.assertRaises(RuntimeError):
                ShopifyClient(admin_token="shpat_test")

    def test_missing_token_raises(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SHOPIFY_ADMIN_TOKEN", None)
            os.environ.pop("SHOPIFY_TOKEN", None)
            with self.assertRaises(RuntimeError):
                ShopifyClient(shop_domain="w1q4is-1q.myshopify.com")

    def test_token_never_leaks_into_url(self):
        # The token belongs in the auth header only — never in the URL.
        client = _client()
        with patch("integrations.shopify.shopify_client.requests.request") as req:
            req.return_value = _fake_response({"shop": {"name": "NoLoveAppeal575"}})
            client.get_shop()
            url = req.call_args.args[1]
            self.assertNotIn("shpat_test", url)
            self.assertEqual(
                req.call_args.kwargs["headers"]["X-Shopify-Access-Token"],
                "shpat_test",
            )

    def test_reads_parse_shop_products_orders(self):
        client = _client()
        calls = {
            "shop.json": {"shop": {"name": "NoLoveAppeal575", "domain": "x.myshopify.com"}},
            "products/count.json": {"count": 2},
            "orders/count.json": {"count": 0},
            "products.json": {"products": [{"title": "Still Here Tee"}]},
            "orders.json": {"orders": []},
        }
        with patch("integrations.shopify.shopify_client.requests.request") as req:
            def side_effect(method, url, **kw):
                for key, payload in calls.items():
                    if url.endswith(key):
                        return _fake_response(payload)
                raise AssertionError(url)
            req.side_effect = side_effect
            self.assertEqual(client.get_shop()["name"], "NoLoveAppeal575")
            self.assertEqual(client.get_product_count(), 2)
            self.assertEqual(client.get_order_count(), 0)
            self.assertEqual(client.list_all_products(), [{"title": "Still Here Tee"}])
            self.assertEqual(client.list_orders(), [])

    def test_write_blocked_without_env_gate(self):
        client = _client()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GGOS_SHOPIFY_WRITE_ENABLED", None)
            with self.assertRaises(ShopifyWriteDisabledError):
                client.create_product({"title": "X"}, approved=True)

    def test_write_blocked_without_per_call_approval(self):
        client = _client()
        with patch.dict(os.environ, {"GGOS_SHOPIFY_WRITE_ENABLED": "1"}):
            with self.assertRaises(ShopifyWriteDisabledError):
                client.create_product({"title": "X"})

    def test_write_goes_out_draft_only_when_both_gates_open(self):
        client = _client()
        with patch.dict(os.environ, {"GGOS_SHOPIFY_WRITE_ENABLED": "1"}):
            with patch("integrations.shopify.shopify_client.requests.request") as req:
                req.return_value = _fake_response(
                    {"product": {"id": 1, "title": "X", "status": "draft"}}
                )
                out = client.create_product({"title": "X"}, approved=True)
                self.assertEqual(out["status"], "draft")
                sent = req.call_args.kwargs["json"]["product"]
                self.assertEqual(sent["status"], "draft")


class TestGodmodeSweep(unittest.TestCase):
    def test_sweep_is_read_only_and_never_approved(self):
        from services.shopify_godmode import godmode_sweep

        fake = MagicMock()
        fake.get_shop.return_value = {"name": "NoLoveAppeal575", "domain": "x.myshopify.com"}
        fake.get_product_count.return_value = 1
        fake.get_order_count.return_value = 0
        fake.list_all_products.return_value = [{"title": "Still Here Tee", "handle": "still-here", "status": "active"}]
        fake.list_orders.return_value = []

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "report.json")
            report = godmode_sweep(client=fake, out_path=out)
            self.assertEqual(report["mode"], "godmode-read-only")
            self.assertFalse(report["applied"])
            self.assertFalse(report["change_package"]["approved"])
            self.assertFalse(report["change_package"]["applied"])
            self.assertEqual(report["change_package"]["agents_run"], 36)
            self.assertTrue(os.path.exists(out))
            saved = json.load(open(out))
            self.assertEqual(saved["shop"]["name"], "NoLoveAppeal575")


if __name__ == "__main__":
    unittest.main()

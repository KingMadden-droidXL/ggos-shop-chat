"""Tests for the godmode gateway wiring (api/godmode.py + wired page).

No network, no live store, no token. The sweep runs against a fake
client; the token-not-set state is checked with the env cleared. The
live page is never written by these tests — the wired page is checked
against it, and since the Nov 7 swap the live page is the wired copy.
"""
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIVE_PAGE = Path.home() / "workspace" / "user" / "files" / "gangstergodos.html"
WIRED_PAGE = PROJECT_ROOT / "gangstergodos-wired.html"


def _fake_client():
    fake = MagicMock()
    fake.get_shop.return_value = {
        "name": "NoLoveAppeal575", "domain": "x.myshopify.com"}
    fake.get_product_count.return_value = 1
    fake.get_order_count.return_value = 0
    fake.list_all_products.return_value = [
        {"title": "Still Here Tee", "handle": "still-here", "status": "active"}]
    fake.list_orders.return_value = []
    return fake


def _clear_shopify_env():
    """Context manager that removes every Shopify env var."""
    return patch.dict(os.environ, {}, clear=True)


class TestGodmodeReport(unittest.TestCase):
    def test_token_not_set_when_env_empty(self):
        from api.godmode import run_godmode_report

        with _clear_shopify_env():
            envelope = run_godmode_report()
        self.assertEqual(envelope["status"], "token_not_set")
        self.assertIsNone(envelope["report"])
        self.assertFalse(envelope["applied"])
        self.assertIn("SHOPIFY_ADMIN_TOKEN", envelope["message"])
        # No numbers anywhere in the envelope — nothing was read.
        self.assertNotIn("counts", json.dumps(envelope))
        self.assertNotIn("products_seen", json.dumps(envelope))

    def test_token_not_set_when_domain_missing_but_token_present(self):
        from api.godmode import run_godmode_report

        env = {"SHOPIFY_ADMIN_TOKEN": "shpat_test", "PATH": os.environ.get("PATH", "")}
        with patch.dict(os.environ, env, clear=True):
            envelope = run_godmode_report()
        self.assertEqual(envelope["status"], "token_not_set")
        self.assertIsNone(envelope["report"])

    def test_ok_with_fake_client_and_receipt_written(self):
        from api.godmode import run_godmode_report

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "report.json")
            envelope = run_godmode_report(client=_fake_client(), out_path=out)
            self.assertEqual(envelope["status"], "ok")
            self.assertFalse(envelope["applied"])
            report = envelope["report"]
            self.assertEqual(report["mode"], "godmode-read-only")
            self.assertFalse(report["applied"])
            self.assertFalse(report["change_package"]["approved"])
            self.assertFalse(report["change_package"]["applied"])
            self.assertEqual(report["change_package"]["agents_run"], 36)
            self.assertEqual(report["counts"], {"products": 1, "orders": 0})
            self.assertEqual(report["shop"]["name"], "NoLoveAppeal575")
            saved = json.load(open(out))
            self.assertEqual(saved["shop"]["name"], "NoLoveAppeal575")
            self.assertFalse(saved["change_package"]["approved"])

    def test_fake_client_never_writes_a_receipt_by_default(self):
        from api.godmode import run_godmode_report

        with tempfile.TemporaryDirectory() as tmp:
            with patch("api.godmode.DEFAULT_RECEIPT", Path(tmp) / "nope.json"):
                envelope = run_godmode_report(client=_fake_client())
        self.assertEqual(envelope["status"], "ok")
        self.assertFalse((Path(tmp) / "nope.json").exists())


class TestGodmodeRoute(unittest.TestCase):
    def test_route_registered(self):
        from ggos.app import app

        paths = {r.path for r in app.routes}
        self.assertIn("/godmode/sweep", paths)


class TestWiredPage(unittest.TestCase):
    def test_wired_page_keeps_hashes_prices_cashapp_and_roster(self):
        live = LIVE_PAGE.read_text(encoding="utf-8")
        wired = WIRED_PAGE.read_text(encoding="utf-8")
        hashes = re.findall(r'"[0-9a-f]{64}"', live)
        self.assertEqual(len(hashes), 2)
        for h in hashes:
            self.assertIn(h, wired)
        for call in ("pay(99)", "pay(499)", "pay(999)"):
            self.assertIn(call, wired)
        self.assertIn("https://cash.app/$Manifestingmoney10", wired)
        names = sorted(re.findall(r'name:"([^"]+)"', live))
        self.assertEqual(len(names), 36)
        self.assertEqual(names, sorted(re.findall(r'name:"([^"]+)"', wired)))
        self.assertNotIn("shpat_", wired)

    def test_wired_page_calls_the_sweep_and_shows_token_state(self):
        wired = WIRED_PAGE.read_text(encoding="utf-8")
        self.assertIn("/godmode/sweep", wired)
        self.assertIn("RUN SHOPIFY SWEEP", wired)
        self.assertIn("token not set in env", wired.lower())
        self.assertNotIn("isn't wired into this page yet", wired)

    def test_live_page_is_wired(self):
        live = LIVE_PAGE.read_text(encoding="utf-8")
        self.assertIn("/godmode/sweep", live)
        self.assertIn("RUN SHOPIFY SWEEP", live)
        self.assertNotIn("isn't wired into this page yet", live)


if __name__ == "__main__":
    unittest.main()

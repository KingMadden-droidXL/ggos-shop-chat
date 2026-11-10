"""Tests for the $0 shop chat (ggos/shop_chat.py + POST /shop/chat).

No LLM, no network, no live store, no token. Answers are checked
against the knowledge file generated from the live store — the file is
the fixture, so tests assert on prices the store actually lists.
"""
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

from ggos import shop_chat  # noqa: E402


class TestShopChatAnswers(unittest.TestCase):
    def test_knowledge_file_is_live_only(self):
        data = shop_chat.load_knowledge()
        self.assertGreater(len(data["products"]), 0)
        titles = [p["title"] for p in data["products"]]
        self.assertNotIn("AI Money Duo", titles)
        contested = [p for p in data["products"] if p.get("contested")]
        self.assertEqual([p["title"] for p in contested], ["Heartless 575"])

    def test_bipolar_bear_hoodie_price(self):
        out = shop_chat.answer("How much is the Bipolar Bear Hoodie?")
        self.assertIn("$39.99", out["reply"])
        self.assertTrue(any("polar-bear-hoodie" in link["url"]
                            for link in out["links"]))
        self.assertFalse(out["handoff"])

    def test_trustless_hoodie_sizes(self):
        out = shop_chat.answer("What sizes does the Trustless hoodie come in?")
        for size in ("S", "M", "L", "XL"):
            self.assertIn(size, out["reply"])

    def test_discount_code(self):
        out = shop_chat.answer("Do you have a discount code?")
        self.assertIn("STAYCOLD10", out["reply"])
        self.assertIn("10%", out["reply"])

    def test_shipping(self):
        out = shop_chat.answer("How long does shipping take?")
        self.assertIn("made to order", out["reply"].lower())
        self.assertIn("Hobbs", out["reply"])

    def test_master_key_price(self):
        out = shop_chat.answer("How much is the Master Key?")
        self.assertIn("$37", out["reply"])

    def test_book_is_fourteen_pages(self):
        out = shop_chat.answer("Tell me about the book")
        self.assertIn("$17", out["reply"])
        self.assertIn("14 pages", out["reply"])

    def test_contested_heartless_tee_gets_check_with_gavin(self):
        out = shop_chat.answer("How much is Heartless 575?")
        self.assertIn("$26.99", out["reply"])
        self.assertIn("reworked", out["reply"])
        self.assertTrue(out["handoff"])

    def test_unknown_question_hands_off_without_inventing(self):
        out = shop_chat.answer("Do you sell hats with feathers?")
        self.assertTrue(out["handoff"])
        self.assertNotIn("$", out["reply"])
        self.assertIn("gavinmadden52@gmail.com", out["reply"])

    def test_duo_is_never_mentioned(self):
        out = shop_chat.answer("What bundles do you have?")
        self.assertNotIn("Duo", out["reply"])
        self.assertNotIn("$47", out["reply"])

    def test_empty_message_gets_a_prompt(self):
        out = shop_chat.answer("   ")
        self.assertIn("ask me", out["reply"])

    def test_rate_limit_blocks_the_21st_call(self):
        key = "test-rate-limit-key"
        shop_chat._hits.pop(key, None)
        for _ in range(20):
            self.assertTrue(shop_chat.check_rate_limit(key))
        self.assertFalse(shop_chat.check_rate_limit(key))
        shop_chat._hits.pop(key, None)


class TestShopChatEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from ggos.app import app
        cls.client = TestClient(app)

    def test_post_chat_answers(self):
        res = self.client.post(
            "/shop/chat", json={"message": "How much is the Bipolar Bear Hoodie?"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("$39.99", res.json()["reply"])

    def test_post_chat_empty_message(self):
        res = self.client.post("/shop/chat", json={"message": ""})
        self.assertEqual(res.status_code, 200)
        self.assertIn("ask me", res.json()["reply"])

    def test_post_chat_rejects_non_string_message(self):
        res = self.client.post("/shop/chat", json={"message": 42})
        self.assertEqual(res.status_code, 400)

    def test_health_still_ok(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])


if __name__ == "__main__":
    unittest.main()

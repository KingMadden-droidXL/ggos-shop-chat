"""Tests: webhooks write events into gangster_god.db.

Uses a temp DB via GGOS_DB_PATH. No network calls.
"""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("APOLLO_API_KEY", "test-key-dummy")

from fastapi.testclient import TestClient

from api.webhooks import apollo as apollo_mod
from api.webhooks import gumroad as gumroad_mod


def _rows(db_path, sql="SELECT event_type, source FROM events ORDER BY id"):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


class TestWebhookDbLogging(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test_god.db"
        os.environ["GGOS_DB_PATH"] = str(self.db_path)

    def tearDown(self):
        os.environ.pop("GGOS_DB_PATH", None)
        self.tmp.cleanup()

    def test_apollo_reply_writes_one_event_row(self):
        client = TestClient(apollo_mod.app)
        r = client.post(
            "/api/webhooks/apollo",
            json={"id": "evt_1", "type": "email_replied", "contact_id": "c_1"},
        )
        self.assertEqual(r.status_code, 200)
        rows = _rows(self.db_path)
        self.assertEqual(rows, [("email_replied", "apollo")])
        conn = sqlite3.connect(str(self.db_path))
        data = json.loads(
            conn.execute("SELECT data FROM events").fetchone()[0]
        )
        conn.close()
        self.assertEqual(data["contact_id"], "c_1")

    def test_duplicate_delivery_is_idempotent(self):
        client = TestClient(apollo_mod.app)
        payload = {"id": "evt_9", "type": "interested"}
        client.post("/api/webhooks/apollo", json=payload)
        client.post("/api/webhooks/apollo", json=payload)
        rows = _rows(self.db_path)
        self.assertEqual(len(rows), 1)

    def test_gumroad_sale_writes_sale_and_queued_pitch_rows(self):
        client = TestClient(gumroad_mod.app)
        r = client.post(
            "/api/webhooks/gumroad",
            data={
                "sale_id": "sale_7",
                "email": "buyer@example.com",
                "product_name": "AI Compliance Shield",
                "price": "49.00",
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["queued"]["status"], "AWAITING_APPROVAL")
        rows = _rows(self.db_path)
        self.assertEqual(
            rows,
            [
                ("compliance_shield_purchased", "gumroad"),
                ("ascension_pitch_queued", "ascension.OS"),
            ],
        )

    def test_logging_failure_does_not_break_the_webhook(self):
        # Point at a directory, not a file: sqlite connect fails.
        os.environ["GGOS_DB_PATH"] = self.tmp.name
        client = TestClient(apollo_mod.app, raise_server_exceptions=False)
        r = client.post("/api/webhooks/apollo", json={"type": "email_opened"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True})


if __name__ == "__main__":
    unittest.main()

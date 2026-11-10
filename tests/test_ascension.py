"""Tests for ascension.OS + the Gumroad purchase webhook + boot modes.

No network calls: the Apollo sequences gate returns PENDING_APPROVAL
without touching the network, and the Gumroad handler only queues a
draft.

DB ISOLATION: webhook tests point GGOS_DB_PATH at a temp file. Without
this, TestClient posts log events into the REAL gangster_god.db —
that happened once (Nov 3) and polluted it with test rows.
"""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("APOLLO_API_KEY", "test-key-dummy")

from fastapi.testclient import TestClient

from api.webhooks import gumroad as gumroad_mod
from boot import select_modes
from integrations.apollo.apollo_sequences import ApolloSequences
from kernel.config import ASCENSION_SEQUENCES
from services.ascension import on_compliance_shield_purchase


def _hot_buyer():
    return {
        "id": "c_hot",
        "email": "jane@acme.ai",
        "first_name": "Jane",
        "name": "Jane Doe",
        "title": "CEO",
        "city": "Clovis",
        "organization": {
            "name": "Acme AI",
            "industry": "Artificial Intelligence",
            "estimated_num_employees": 25,
            "technologies": ["python"],
        },
    }


def _sparse_buyer():
    return {"id": "sale_1", "email": "buyer@example.com", "first_name": "Pat"}


class TestAscensionRouting(unittest.TestCase):
    def test_hot_buyer_gets_3500_dfy_pitch(self):
        result = on_compliance_shield_purchase(_hot_buyer())
        self.assertEqual(result["tier"], "HOT")
        self.assertEqual(result["score"], 80)
        self.assertEqual(result["offer"]["price"], "$3,500 one-time")
        self.assertEqual(
            result["offer"]["sequence_id"],
            ASCENSION_SEQUENCES["high_ticket_3500"],
        )
        self.assertEqual(result["status"], "AWAITING_APPROVAL")

    def test_warm_buyer_gets_497_retainer_pitch(self):
        result = on_compliance_shield_purchase(_sparse_buyer())
        self.assertEqual(result["tier"], "WARM")
        self.assertEqual(result["offer"]["price"], "$1,500 setup + $497/mo")
        self.assertEqual(
            result["offer"]["sequence_id"], ASCENSION_SEQUENCES["retainer_497"]
        )
        self.assertEqual(result["status"], "AWAITING_APPROVAL")

    def test_pitch_never_auto_sends_through_the_gate(self):
        seq = ApolloSequences()
        result = on_compliance_shield_purchase(_hot_buyer(), sequences=seq)
        self.assertEqual(result["sequence_result"]["status"], "PENDING_APPROVAL")
        self.assertEqual(result["status"], "AWAITING_APPROVAL")

    def test_no_pitch_claims_missed_calls_are_an_ftc_violation(self):
        for buyer in (_hot_buyer(), _sparse_buyer()):
            pitch = on_compliance_shield_purchase(buyer)["offer"]["pitch"].lower()
            self.assertNotIn("non-compliant", pitch)
            self.assertNotIn("noncompliant", pitch)
            self.assertLessEqual(len(pitch.split()), 80)


class TestGumroadWebhook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["GGOS_DB_PATH"] = str(Path(self.tmp.name) / "test_god.db")

    def tearDown(self):
        os.environ.pop("GGOS_DB_PATH", None)
        self.tmp.cleanup()

    def test_sale_queues_retainer_pitch_without_sending(self):
        client = TestClient(gumroad_mod.app)
        r = client.post(
            "/api/webhooks/gumroad",
            data={
                "sale_id": "sale_1",
                "email": "buyer@example.com",
                "product_name": "AI Compliance Shield",
                "price": "49.00",
            },
        )
        self.assertEqual(r.status_code, 200)
        queued = r.json()["queued"]
        self.assertEqual(queued["status"], "AWAITING_APPROVAL")
        self.assertEqual(queued["tier"], "WARM")
        self.assertEqual(queued["offer"]["price"], "$1,500 setup + $497/mo")


class TestBootModes(unittest.TestCase):
    def test_no_modes_means_all_five(self):
        self.assertEqual(len(select_modes(None)), 5)

    def test_single_mode_week_one(self):
        self.assertEqual(select_modes(["system_4_niche_agent"]), ["system_4_niche_agent"])

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            select_modes(["system_9_nope"])


if __name__ == "__main__":
    unittest.main()

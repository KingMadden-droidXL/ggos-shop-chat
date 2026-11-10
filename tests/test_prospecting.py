"""Tests for prospecting.OS — the 5-mode Apollo hunter.

No network calls: ApolloClient init only needs a dummy key in the
environment; every test below either stubs the HTTP layer or never
reaches it.
"""
import hashlib
import hmac
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("APOLLO_API_KEY", "test-key-dummy")

from fastapi.testclient import TestClient

from api.webhooks import apollo as webhook_mod
from integrations.apollo.apollo_client import ApolloClient
from integrations.apollo.apollo_enrichment import ApolloEnrichment, CreditGovernor
from integrations.apollo.apollo_sequences import ApolloSequences
from kernel.config import ICP_MODES
from services.intelligence import score_prospect_multi
from services.prospecting import ProspectingOS


def _perfect_person():
    return {
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


class TestScoring(unittest.TestCase):
    def test_perfect_prospect_scores_80_and_is_hot_reachable(self):
        icp = ICP_MODES["system_4_niche_agent"]
        score, breakdown, _ = score_prospect_multi(_perfect_person(), icp)
        self.assertEqual(score, 80)
        self.assertEqual(breakdown["decision_maker"], 25)
        self.assertEqual(breakdown["industry"], 20)
        self.assertEqual(breakdown["size"], 15)
        self.assertEqual(breakdown["tech"], 15)
        self.assertEqual(breakdown["local"], 5)

    def test_growth_and_buying_signals_push_to_100(self):
        person = _perfect_person()
        person["organization"]["is_hiring"] = True
        person["_buying_signal"] = True
        score, _, _ = score_prospect_multi(person, ICP_MODES["system_4_niche_agent"])
        self.assertEqual(score, 100)

    def test_empty_prospect_scores_zero(self):
        score, breakdown, _ = score_prospect_multi(
            {}, ICP_MODES["system_4_niche_agent"]
        )
        self.assertEqual(score, 0)
        self.assertEqual(breakdown, {})

    def test_director_gets_15_not_25(self):
        person = _perfect_person()
        person["title"] = "Compliance Director"
        score, breakdown, _ = score_prospect_multi(
            person, ICP_MODES["system_4_niche_agent"]
        )
        self.assertEqual(breakdown["decision_maker"], 15)


class TestGovernor(unittest.TestCase):
    def test_below_threshold_blocked(self):
        gov = CreditGovernor(limit=100)
        self.assertFalse(gov.can_enrich(40))

    def test_limit_blocks_at_100(self):
        gov = CreditGovernor(limit=2)
        self.assertTrue(gov.can_enrich(80))
        gov.consume(2)
        self.assertFalse(gov.can_enrich(80))

    def test_consume_counts_once(self):
        gov = CreditGovernor(limit=100)
        gov.consume(1)
        self.assertEqual(gov.used, 1)

    def test_prospecting_and_enrichment_share_one_governor(self):
        os.environ["APOLLO_API_KEY"] = "test-key-dummy"
        gov = CreditGovernor(limit=100)
        hunting = ProspectingOS(governor=gov)
        self.assertIs(hunting.governor, gov)
        self.assertIs(hunting.enrichment.governor, gov)


class TestEnrichmentSkips(unittest.TestCase):
    def test_enrich_skips_without_burning_a_credit(self):
        gov = CreditGovernor(limit=100)
        enrich = ApolloEnrichment(governor=gov)
        result = enrich.enrich_person({"email": "a@b.com"}, 40)
        self.assertTrue(result["skipped"])
        self.assertEqual(gov.used, 0)


class TestSequencesApprovalGate(unittest.TestCase):
    def test_no_approval_means_pending_not_sent(self):
        seq = ApolloSequences()
        result = seq.add_to_sequence("c_1", "SEQ_COMPLIANCE_SHIELD_01")
        self.assertEqual(result["status"], "PENDING_APPROVAL")


class TestClientRequiresKey(unittest.TestCase):
    def test_missing_key_raises_clear_error(self):
        old = os.environ.pop("APOLLO_API_KEY", None)
        try:
            with self.assertRaises(RuntimeError):
                ApolloClient()
        finally:
            if old is not None:
                os.environ["APOLLO_API_KEY"] = old


class TestConfig(unittest.TestCase):
    def test_five_modes_each_with_offer_and_sequence(self):
        self.assertEqual(len(ICP_MODES), 5)
        for key, icp in ICP_MODES.items():
            self.assertIn("offer", icp, key)
            self.assertIn("titles", icp, key)
            self.assertTrue(icp["apollo_sequence_id"].startswith("SEQ_"), key)


class TestOutreachTemplates(unittest.TestCase):
    def test_all_five_modes_have_a_template_under_80_words(self):
        os.environ["APOLLO_API_KEY"] = "test-key-dummy"
        hunting = ProspectingOS()
        person = _perfect_person()
        for mode_key, icp in ICP_MODES.items():
            text = hunting.generate_peer_outreach(person, icp, mode_key)
            self.assertTrue(text, mode_key)
            self.assertLessEqual(len(text.split()), 80, mode_key)

    def test_no_template_invents_stats_about_the_prospect(self):
        os.environ["APOLLO_API_KEY"] = "test-key-dummy"
        hunting = ProspectingOS()
        person = _perfect_person()
        banned = ("30%", "most shops", "most founders", "most local")
        for mode_key, icp in ICP_MODES.items():
            text = hunting.generate_peer_outreach(person, icp, mode_key).lower()
            for phrase in banned:
                self.assertNotIn(phrase, text, mode_key)


class TestWebhookSignature(unittest.TestCase):
    def setUp(self):
        # Point the DB logger at a temp file — without this, these posts
        # log events into the REAL gangster_god.db (happened Nov 3).
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["GGOS_DB_PATH"] = str(Path(self.tmp.name) / "test_god.db")

    def tearDown(self):
        os.environ.pop("GGOS_DB_PATH", None)
        self.tmp.cleanup()

    def test_valid_signature_passes(self):
        body = b'{"type": "email_replied"}'
        sig = hmac.new(b"whsec_test", body, hashlib.sha256).hexdigest()
        self.assertTrue(webhook_mod._signature_valid(body, sig, "whsec_test"))

    def test_wrong_signature_fails(self):
        body = b'{"type": "email_replied"}'
        self.assertFalse(webhook_mod._signature_valid(body, "deadbeef", "whsec_test"))

    def test_no_secret_allows_request(self):
        os.environ.pop("APOLLO_WEBHOOK_SECRET", None)
        client = TestClient(webhook_mod.app)
        r = client.post("/api/webhooks/apollo", json={"type": "email_replied"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True})

    def test_health_endpoint_is_read_only_proof(self):
        client = TestClient(webhook_mod.app)
        r = client.get("/api/webhooks/apollo")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")
        self.assertNotIn("secret", str(r.json()).lower())

    def test_secret_with_bad_signature_rejected(self):
        os.environ["APOLLO_WEBHOOK_SECRET"] = "whsec_test"
        try:
            client = TestClient(webhook_mod.app, raise_server_exceptions=False)
            r = client.post(
                "/api/webhooks/apollo",
                json={"type": "email_replied"},
                headers={"X-Apollo-Signature": "deadbeef"},
            )
            self.assertEqual(r.status_code, 401)
        finally:
            os.environ.pop("APOLLO_WEBHOOK_SECRET", None)

    def test_secret_with_good_signature_accepted(self):
        os.environ["APOLLO_WEBHOOK_SECRET"] = "whsec_test"
        try:
            body = b'{"type": "email_replied"}'
            sig = hmac.new(b"whsec_test", body, hashlib.sha256).hexdigest()
            client = TestClient(webhook_mod.app)
            r = client.post(
                "/api/webhooks/apollo",
                content=body,
                headers={
                    "X-Apollo-Signature": sig,
                    "Content-Type": "application/json",
                },
            )
            self.assertEqual(r.status_code, 200)
        finally:
            os.environ.pop("APOLLO_WEBHOOK_SECRET", None)


if __name__ == "__main__":
    unittest.main()

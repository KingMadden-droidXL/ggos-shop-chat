"""Tests for the 36-agent swarm.

Fixture products are a small, real subset of the Oct 28 Shopify
snapshot found in the workspace: two duplicate Wave 2 pairs, one
Teddy product with no description/SKU, and the live Still Here tee.
Prices, handles, and SKUs below are copied from that snapshot, not
invented, so the duplicate / SKU / image checks are tested on real
shapes, not on a story about them.
"""
import tempfile
import unittest
from pathlib import Path

from ggos import agents, database as db


def _product(pid, title, handle, status, price, variants, description="", media=None, tags=None, inv=0):
    return {
        "id": pid, "title": title, "handle": handle, "status": status,
        "description": description, "featuredMedia": media, "tags": tags or [],
        "totalInventory": inv,
        "priceRangeV2": {"minVariantPrice": {"amount": str(price), "currencyCode": "USD"}},
        "variants": {"edges": [{"node": v} for v in variants]},
    }


def _variant(title, sku, price):
    return {"title": title, "sku": sku, "price": str(price), "inventoryQuantity": 0}


FIXTURE = [
    _product("gid://shopify/Product/15447888036147",
             "Heartless 575 Oversized Heavyweight Hoodie",
             "heartless-575-oversized-heavyweight-hoodie", "DRAFT", "54.99",
             [_variant("S", "NLA-H575OH-S", "54.99"), _variant("XL", "NLA-H575OH-XL", "54.99")],
             description="Heavyweight black hoodie", tags=["Wave 2"]),
    _product("gid://shopify/Product/15447892033843",
             "Heartless 575 Oversized Heavyweight Hoodie",
             "heartless-575-oversized-heavyweight-hoodie-1", "DRAFT", "54.99",
             [_variant("S", "NLA-H575OH-S", "54.99"), _variant("2XL", "NLA-H575OH-2XL", "57.99")],
             description="Heavyweight black hoodie", tags=["Wave 2"]),
    _product("gid://shopify/Product/15447888396595",
             "No Love / Still Here Manifesto Tee",
             "no-love-still-here-manifesto-tee", "DRAFT", "29.99",
             [_variant("S", "NLA-NLS H-S", "29.99")],
             description="NO LOVE. STILL HERE.", tags=["Wave 2"]),
    _product("gid://shopify/Product/15447892164915",
             "No Love / Still Here Manifesto Tee",
             "no-love-still-here-manifesto-tee-1", "DRAFT", "29.99",
             [_variant("S", "NLA-NLSH-S", "29.99")],
             description="NO LOVE. STILL HERE.", tags=["Wave 2"]),
    _product("gid://shopify/Product/15408024551731",
             "Teddy Tee — Deep Purple", "teddy-tee-deep-purple", "ACTIVE", "31.75",
             [_variant("S", None, "31.75")], description=""),
    _product("gid://shopify/Product/15447895310643",
             "No Love. Still Here. Tee", "no-love-still-here-tee", "ACTIVE", "26.99",
             [_variant("S", "NLA-NLSH-S", "26.99")],
             description="Black tee. NO LOVE. STILL HERE.",
             media={"preview": {"image": {"url": "https://example.invalid/tee.jpg"}}}),
]


class TestRoster(unittest.TestCase):
    def test_exactly_36_unique_agents(self):
        roster = agents.list_agents()
        self.assertEqual(len(roster), 36)
        self.assertEqual(len({r["name"] for r in roster}), 36)

    def test_original_five_present(self):
        names = {r["name"] for r in agents.list_agents()}
        for expected in ("Analyst", "CatalogAgent", "CreativeDirector",
                         "ManufacturingLead", "GrowthMarketer"):
            self.assertIn(expected, names)

    def test_no_agent_claims_shopify_writes(self):
        for cls in agents.AGENT_CLASSES:
            self.assertFalse(cls.writes_to_shopify, cls.name)


class TestChecks(unittest.TestCase):
    def test_analyst_finds_two_duplicate_groups(self):
        result = agents.Analyst().run(FIXTURE)
        self.assertEqual(result["counts"]["duplicate_groups"], 2)

    def test_sku_auditor_finds_missing_spaced_and_duplicate(self):
        result = agents.SkuAuditor().run(FIXTURE)
        self.assertGreaterEqual(result["counts"]["missing_sku_variants"], 1)
        self.assertGreaterEqual(result["counts"]["spaced_skus"], 1)
        # NLA-NLSH-S appears on both a Manifesto draft and the live tee.
        self.assertGreaterEqual(result["counts"]["duplicate_skus"], 1)

    def test_image_auditor_counts_image_less(self):
        result = agents.ImageAuditor().run(FIXTURE)
        self.assertEqual(result["counts"]["no_image"], 5)

    def test_description_auditor_finds_teddy_empty(self):
        result = agents.DescriptionAuditor().run(FIXTURE)
        self.assertEqual(result["counts"]["empty_descriptions"], 1)

    def test_price_ladder_flags_wave2_tee_gap(self):
        result = agents.PriceLadder().run(FIXTURE)
        self.assertIn("gap $3.00", " ".join(result["findings"]))

    def test_handle_auditor_finds_minus_one(self):
        result = agents.HandleAuditor().run(FIXTURE)
        self.assertEqual(result["counts"]["minus_one_handles"], 2)

    def test_cost_margin_never_invents_a_margin(self):
        result = agents.CostMargin().run(FIXTURE)
        self.assertIn("Margin cannot be computed until unit costs arrive", result["blocked"])


class TestSwarmAndGate(unittest.TestCase):
    def test_swarm_runs_36_and_stays_unapproved_unapplied(self):
        package = agents.run_swarm(FIXTURE)
        self.assertEqual(package["agents_run"], 36)
        self.assertFalse(package["approved"])
        self.assertFalse(package["applied"])

    def test_apply_blocked_without_approval(self):
        with self.assertRaises(PermissionError):
            agents.apply_package({"approved": False}, approved=False)

    def test_apply_never_writes_even_when_approved(self):
        # By design: approved packages go through Muse in chat, not code.
        with self.assertRaises(NotImplementedError):
            agents.apply_package({"approved": True}, approved=True)

    def test_swarm_persists_agent_runs_to_local_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "swarm.db"
            agents.run_swarm(FIXTURE, db_path=db_path)
            conn = db.get_connection(db_path)
            try:
                runs = db.get_agent_runs(conn, limit=100)
            finally:
                conn.close()
            self.assertEqual(len(runs), 36)
            self.assertTrue(all(r["status"] == "done" for r in runs))

    def test_swarm_does_not_assume_orders_are_zero(self):
        result = agents.OrderWatch().run(FIXTURE)
        self.assertIn("UNVERIFIED, not zero", " ".join(result["findings"]))


if __name__ == "__main__":
    unittest.main()

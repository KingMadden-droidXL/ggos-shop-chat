import tempfile
import unittest
from pathlib import Path

from ggos import database as db
from ggos.intelligence import IntelligenceModule
from ggos.money_engine import record_transaction


def _fake_fetch(url):
    """Fixed chart payloads, labelled as test fixtures — never production data."""
    if "bitcoin" in url:
        return {"prices": [[0, 100.0], [1, 110.0], [2, 90.0]]}
    if "ethereum" in url:
        return {"prices": [[0, 200.0], [1, 200.0], [2, 200.0]]}
    raise AssertionError(f"unexpected url in test fetcher: {url}")


class TestIntelligenceScoring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        db.init_db(self.db_path)
        self.intel = IntelligenceModule(db_path=self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_scan_computes_from_chart_data(self):
        intel = IntelligenceModule(db_path=self.db_path, fetch_json=_fake_fetch)
        signals = intel.scan_market_signals()
        self.assertEqual([s["coin_id"] for s in signals], ["bitcoin", "ethereum"])
        btc = signals[0]
        # 100 -> 90 is a -10% move; dispersion = pstdev/mean = 0.08165.
        self.assertEqual(btc["price_usd"], 90.0)
        self.assertEqual(btc["change_24h_pct"], -10.0)
        self.assertEqual(btc["raw_alpha"], 10.0)
        self.assertAlmostEqual(btc["volatility"], 0.08165, places=5)
        self.assertEqual(btc["prices_count"], 3)
        self.assertEqual(signals[1]["raw_alpha"], 0.0)
        self.assertEqual(signals[1]["volatility"], 0.0)

    def test_scan_raises_on_api_failure_no_fake_fallback(self):
        def _boom(url):
            raise RuntimeError("CoinGecko rate limited (HTTP 429)")

        intel = IntelligenceModule(db_path=self.db_path, fetch_json=_boom)
        with self.assertRaises(RuntimeError):
            intel.scan_market_signals()

    def test_scan_rejects_bad_coin_id(self):
        intel = IntelligenceModule(db_path=self.db_path, fetch_json=_fake_fetch)
        with self.assertRaises(ValueError):
            intel.scan_market_signals(["../etc/passwd"])

    def test_live_cycle_persists_scanned_signals_as_holds(self):
        intel = IntelligenceModule(db_path=self.db_path, fetch_json=_fake_fetch)
        summary = intel.process_intelligence_cycle(live=True)
        self.assertTrue(summary["live_scan"])
        self.assertEqual(summary["total_signals_scanned"], 2)
        self.assertEqual(summary["executable_decisions"], 0)
        self.assertTrue(
            all(d["action"] == "HOLD" for d in summary["decisions"])
        )
        self.assertEqual(summary["decisions"][0]["coin_id"], "bitcoin")
        self.assertEqual(summary["decisions"][0]["price_usd"], 90.0)
        self.assertEqual(summary["paper_predictions_recorded"], 2)
        self.assertEqual(summary["paper_summary"]["pending"], 2)
        self.assertEqual(summary["paper_summary"]["evaluated"], 0)
        with self.assertRaises(ValueError):
            intel.process_intelligence_cycle(
                signals=[{"source": "x", "raw_alpha": 1.0, "volatility": 0.5}],
                live=True,
            )

    def test_score_math_and_hold_only(self):
        # (9.0 * 0.7) / (1 + 0.5) = 4.2 — high score still HOLDs:
        # no causal model exists and nothing here approves execution.
        decision = self.intel.compute_decision_score(
            {"source": "manual", "raw_alpha": 9.0, "volatility": 0.5}
        )
        self.assertEqual(decision["composite_score"], 4.2)
        self.assertEqual(decision["risk_score"], 0.5)
        self.assertEqual(decision["action"], "HOLD")
        self.assertEqual(decision["causal_status"], "NOT_EVALUATED")

    def test_score_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            self.intel.compute_decision_score(
                {"source": "", "raw_alpha": 1.0, "volatility": 0.5}
            )
        with self.assertRaises(ValueError):
            self.intel.compute_decision_score(
                {"source": "x", "raw_alpha": 1.0, "volatility": 1.5}
            )
        with self.assertRaises(TypeError):
            self.intel.compute_decision_score(
                {"source": "x", "raw_alpha": "high", "volatility": 0.5}
            )
        with self.assertRaises(ValueError):
            self.intel.compute_decision_score({"source": "x", "volatility": 0.5})

    def test_cycle_with_no_signals_invents_nothing(self):
        summary = self.intel.process_intelligence_cycle()
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["total_signals_scanned"], 0)
        self.assertEqual(summary["executable_decisions"], 0)
        self.assertEqual(summary["decisions"], [])

        conn = db.get_connection(self.db_path)
        try:
            runs = db.get_agent_runs(conn, agent_name="IntelligenceModule")
            n_decisions = conn.execute(
                "SELECT COUNT(*) AS c FROM decisions"
            ).fetchone()["c"]
        finally:
            conn.close()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "done")
        self.assertEqual(n_decisions, 0)

    def test_cycle_persists_supplied_signals_as_unapproved_holds(self):
        conn = db.get_connection(self.db_path)
        try:
            db.insert_event(conn, "seed", description="seed event")
            record_transaction(
                conn, source="seed", external_id="1", amount_cents=5000,
                direction="in",
            )
        finally:
            conn.close()

        summary = self.intel.process_intelligence_cycle(
            signals=[
                {"source": "manual", "raw_alpha": 9.0, "volatility": 0.5},
                {"source": "manual", "raw_alpha": 1.0, "volatility": 0.9},
            ]
        )
        self.assertEqual(summary["total_signals_scanned"], 2)
        self.assertEqual(summary["executable_decisions"], 0)
        self.assertEqual(summary["state"]["events_24h"], 1)
        self.assertEqual(summary["state"]["balance_cents"], 5000)

        conn = db.get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM decisions ORDER BY id"
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["action"], "HOLD")
            self.assertEqual(row["approved"], 0)
            self.assertEqual(row["executed"], 0)
        self.assertEqual(
            [d["id"] for d in summary["decisions"]],
            [r["id"] for r in rows],
        )

    def test_cycle_fails_on_schema_mismatch(self):
        raw = Path(self.tmp.name) / "empty.db"
        raw.touch()
        intel = IntelligenceModule(db_path=raw)
        with self.assertRaises(RuntimeError):
            intel.process_intelligence_cycle(
                signals=[{"source": "x", "raw_alpha": 1.0, "volatility": 0.5}]
            )


if __name__ == "__main__":
    unittest.main()

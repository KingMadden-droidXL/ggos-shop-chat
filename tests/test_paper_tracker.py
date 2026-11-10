import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ggos import database as db
from ggos import paper_tracker

NOW = datetime(2026, 10, 28, 18, 0, tzinfo=timezone.utc)


def _record(conn, coin="bitcoin", scanned_at=None, price=100.0, change=10.0,
            score=6.0, raw=10.0, vol=0.08, horizon=24.0):
    if scanned_at is None:
        scanned_at = NOW.isoformat()
    elif not isinstance(scanned_at, str):
        scanned_at = scanned_at.isoformat()
    return paper_tracker.record_prediction(
        conn,
        coin_id=coin,
        scanned_at=scanned_at,
        price_usd=price,
        change_24h_pct=change,
        composite_score=score,
        raw_alpha=raw,
        volatility=vol,
        horizon_hours=horizon,
    )


class TestPaperTracker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        db.init_db(self.db_path)
        self.conn = db.get_connection(self.db_path)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_record_is_idempotent_for_same_coin_time_horizon(self):
        first = _record(self.conn)
        second = _record(self.conn)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(paper_tracker.list_predictions(self.conn)), 1)

    def test_record_rejects_bad_values(self):
        with self.assertRaises(ValueError):
            _record(self.conn, price=0)
        with self.assertRaises(ValueError):
            _record(self.conn, horizon=-1)

    def test_evaluate_only_due_predictions_with_real_math(self):
        due = _record(self.conn, scanned_at=NOW - timedelta(hours=25))
        not_due = _record(
            self.conn, coin="ethereum", scanned_at=NOW, price=200.0, change=-5.0
        )
        evaluated = paper_tracker.evaluate_due_predictions(
            self.conn, price_fetcher=lambda coin: 110.0, now=NOW
        )
        self.assertEqual([r["id"] for r in evaluated], [due["id"]])
        self.assertEqual(evaluated[0]["eval_price_usd"], 110.0)
        self.assertAlmostEqual(evaluated[0]["forward_return_pct"], 10.0)
        rows = {r["id"]: r for r in paper_tracker.list_predictions(self.conn)}
        self.assertIsNone(rows[not_due["id"]]["evaluated_at"])

    def test_evaluate_fetches_each_coin_once_and_fails_cleanly(self):
        _record(self.conn, scanned_at=NOW - timedelta(hours=25))
        _record(
            self.conn, scanned_at=(NOW - timedelta(hours=26)).isoformat(),
            horizon=24.0,
        )
        calls = []

        def _bad_fetch(coin):
            calls.append(coin)
            raise RuntimeError("price API down")

        with self.assertRaises(RuntimeError):
            paper_tracker.evaluate_due_predictions(
                self.conn, price_fetcher=_bad_fetch, now=NOW
            )
        self.assertEqual(calls, ["bitcoin"])
        rows = paper_tracker.list_predictions(self.conn)
        self.assertTrue(all(r["evaluated_at"] is None for r in rows))

    def test_summary_counts_momentum_only_from_evaluated(self):
        # Past up, forward up; past down, forward down: momentum 1.0.
        _record(self.conn, scanned_at=NOW - timedelta(hours=25), change=10.0)
        _record(
            self.conn, coin="ethereum", scanned_at=NOW - timedelta(hours=25),
            price=200.0, change=-5.0, raw=5.0,
        )
        paper_tracker.evaluate_due_predictions(
            self.conn,
            price_fetcher=lambda coin: 110.0 if coin == "bitcoin" else 180.0,
            now=NOW,
        )
        summary = paper_tracker.paper_summary(self.conn)
        self.assertEqual(summary["evaluated"], 2)
        self.assertEqual(summary["pending"], 0)
        self.assertFalse(summary["enough_data_for_a_claim"])
        self.assertEqual(summary["momentum_same_direction_rate"], 1.0)
        self.assertAlmostEqual(summary["mean_forward_return_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from ggos import database as db
from ggos.money_engine import (
    get_balance_cents,
    record_transaction,
    transaction_exists,
)


class TestMoneyDedup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        db.init_db(self.db_path)
        self.conn = db.get_connection(self.db_path)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_duplicate_insert_is_idempotent(self):
        r1 = record_transaction(
            self.conn, source="test", external_id="tx1", amount_cents=2500,
            direction="in", description="first",
        )
        r2 = record_transaction(
            self.conn, source="test", external_id="tx1", amount_cents=2500,
            direction="in", description="duplicate",
        )
        self.assertTrue(r1["inserted"])
        self.assertFalse(r2["inserted"])
        self.assertEqual(r1["id"], r2["id"])
        self.assertTrue(transaction_exists(self.conn, "test", "tx1"))
        # counted exactly once
        self.assertEqual(get_balance_cents(self.conn), 2500)

    def test_balance_in_minus_out(self):
        record_transaction(
            self.conn, source="t", external_id="a", amount_cents=1000,
            direction="in",
        )
        record_transaction(
            self.conn, source="t", external_id="b", amount_cents=400,
            direction="out",
        )
        self.assertEqual(get_balance_cents(self.conn), 600)

    def test_source_and_external_id_required(self):
        with self.assertRaises(ValueError):
            record_transaction(
                self.conn, source="", external_id="x", amount_cents=1,
                direction="in",
            )


if __name__ == "__main__":
    unittest.main()

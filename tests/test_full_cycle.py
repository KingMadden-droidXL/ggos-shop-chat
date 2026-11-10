import tempfile
import unittest
from pathlib import Path

from ggos import database as db
from ggos.boss import BossAgent


class TestFullCycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        db.init_db(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cycle_writes_real_rows(self):
        agent = BossAgent(db_path=self.db_path)
        summary = agent.run_full_cycle()
        self.assertTrue(summary["ok"])
        self.assertIn("run_id", summary)

        conn = db.get_connection(self.db_path)
        try:
            runs = db.get_agent_runs(conn)
            n_events = conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"]
        finally:
            conn.close()

        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "done")
        self.assertGreater(n_events, 0)

    def test_cycle_fails_cleanly_on_schema_mismatch(self):
        # point at a db with no schema at all: verify_state must say not-ok
        raw = Path(self.tmp.name) / "empty.db"
        raw.touch()
        agent = BossAgent(db_path=raw)
        state = agent.verify_state()
        self.assertFalse(state["ok"])
        with self.assertRaises(RuntimeError):
            agent.run_full_cycle()

    def test_stubs_raise_instead_of_faking(self):
        agent = BossAgent(db_path=self.db_path)
        with self.assertRaises(NotImplementedError):
            agent.scan_market_signals()
        with self.assertRaises(NotImplementedError):
            agent.transform_content("hello")


if __name__ == "__main__":
    unittest.main()

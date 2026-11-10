import tempfile
import unittest
from pathlib import Path

from ggos import database as db


class TestSchema(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_is_idempotent(self):
        v1 = db.init_db(self.db_path)
        v2 = db.init_db(self.db_path)
        self.assertEqual(v1, db.SCHEMA_VERSION)
        self.assertEqual(v2, db.SCHEMA_VERSION)

    def test_tables_exist(self):
        db.init_db(self.db_path)
        conn = db.get_connection(self.db_path)
        try:
            tables = {
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        finally:
            conn.close()
        for t in [
            "schema_version",
            "events",
            "money",
            "decisions",
            "telemetry",
            "agents",
            "agent_runs",
            "knowledge",
            "memory",
        ]:
            self.assertIn(t, tables)

    def test_creates_exactly_the_file_we_pointed_at(self):
        db.init_db(self.db_path)
        self.assertTrue(self.db_path.exists())
        # and nothing extra landed next to it
        self.assertEqual(
            [p.name for p in Path(self.tmp.name).glob("*.db")], ["test.db"]
        )


if __name__ == "__main__":
    unittest.main()

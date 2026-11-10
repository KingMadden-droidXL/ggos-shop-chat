import tempfile
import unittest
from pathlib import Path

from ggos import database as db


class TestMigrationV1toV2(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_v1_database_upgrades_to_v2(self):
        # simulate a database left behind by the first repair: schema at v1
        conn = db.get_connection(self.db_path)
        try:
            conn.executescript(db.MIGRATIONS[1])
            conn.execute("INSERT INTO schema_version (version) VALUES (1)")
            conn.commit()
        finally:
            conn.close()

        version = db.init_db(self.db_path)
        self.assertEqual(version, db.SCHEMA_VERSION)

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
        for t in ["tasks", "sops", "prompt_runs", "paper_predictions"]:
            self.assertIn(t, tables)

    def test_v2_database_upgrades_to_v3(self):
        conn = db.get_connection(self.db_path)
        try:
            conn.executescript(db.MIGRATIONS[1])
            conn.executescript(db.MIGRATIONS[2])
            conn.execute("INSERT INTO schema_version (version) VALUES (1)")
            conn.execute("INSERT INTO schema_version (version) VALUES (2)")
            conn.commit()
        finally:
            conn.close()

        self.assertEqual(db.init_db(self.db_path), 3)
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
        self.assertIn("paper_predictions", tables)

    def test_fresh_init_goes_straight_to_v3(self):
        self.assertEqual(db.init_db(self.db_path), db.SCHEMA_VERSION)
        self.assertEqual(db.SCHEMA_VERSION, 3)


class TestTasks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        db.init_db(self.db_path)
        self.conn = db.get_connection(self.db_path)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_task_lifecycle(self):
        task = db.create_task(self.conn, module="ExecutionModule",
                              payload={"action": "review"})
        self.assertEqual(task["status"], "pending")

        task = db.update_task_status(self.conn, task["id"], "in_progress")
        self.assertEqual(task["status"], "in_progress")

        task = db.update_task_status(self.conn, task["id"], "completed")
        self.assertEqual(task["status"], "completed")

        pending = db.list_tasks(self.conn, status="pending")
        self.assertEqual(pending, [])

    def test_invalid_status_rejected(self):
        with self.assertRaises(ValueError):
            db.create_task(self.conn, module="x", status="AUTO_EXECUTE")

    def test_missing_task_returns_none(self):
        self.assertIsNone(db.get_task(self.conn, 9999))
        self.assertIsNone(db.update_task_status(self.conn, 9999, "completed"))


class TestSops(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        db.init_db(self.db_path)
        self.conn = db.get_connection(self.db_path)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_sop_round_trip(self):
        sop = db.create_sop(
            self.conn,
            title="High traffic response",
            trigger_event="HIGH_TRAFFIC_ALERT",
            steps=["check dashboard", "scale workers", "notify owner"],
        )
        self.assertEqual(sop["title"], "High traffic response")

        found = db.list_sops(self.conn, trigger_event="HIGH_TRAFFIC_ALERT")
        self.assertEqual(len(found), 1)
        import json

        self.assertEqual(json.loads(found[0]["steps_json"]),
                         ["check dashboard", "scale workers", "notify owner"])


class TestPromptRuns(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        db.init_db(self.db_path)
        self.conn = db.get_connection(self.db_path)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_prompt_run_records_real_io(self):
        run = db.save_prompt_run(
            self.conn,
            pipeline_type="CONTENT_TRANSFORMATION_4X",
            input_raw="raw notes here",
            outputs={"summary": "actual model output here"},
        )
        self.assertEqual(run["pipeline_type"], "CONTENT_TRANSFORMATION_4X")

        runs = db.list_prompt_runs(self.conn, pipeline_type="CONTENT_TRANSFORMATION_4X")
        self.assertEqual(len(runs), 1)
        import json

        self.assertEqual(json.loads(runs[0]["outputs_json"]),
                         {"summary": "actual model output here"})


class TestNewRoutesRegistered(unittest.TestCase):
    def test_routes_exist(self):
        from ggos.app import app

        paths = {r.path for r in app.routes}
        for p in ["/tasks", "/tasks/{task_id}", "/sops", "/prompt-runs"]:
            self.assertIn(p, paths)


if __name__ == "__main__":
    unittest.main()

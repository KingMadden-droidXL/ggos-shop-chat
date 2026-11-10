"""Tests for the Turso/libSQL database path.

The libsql client is exercised against a LOCAL file (GGOS_USE_LIBSQL=1),
which proves the client API usage (connect / executescript / execute /
commit / lastrowid / cursor.description) that the remote Turso path
uses too. The remote path itself is UNTESTED — no Turso credentials
exist yet — and is marked as such in ggos/database.py.
"""
import os
import tempfile
import unittest
from pathlib import Path

from ggos import database as db


class TestLibsqlLocalPath(unittest.TestCase):
    def setUp(self):
        self._saved = {
            k: os.environ.get(k) for k in ("GGOS_USE_LIBSQL", "TURSO_DATABASE_URL")
        }
        os.environ["GGOS_USE_LIBSQL"] = "1"
        os.environ.pop("TURSO_DATABASE_URL", None)
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "libsql-test.db"

    def tearDown(self):
        self.tmp.cleanup()
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_init_db_migrates_to_latest_via_libsql(self):
        version = db.init_db(self.db_path)
        self.assertEqual(version, 3)

    def test_insert_event_and_idempotent_duplicate(self):
        db.init_db(self.db_path)
        conn = db.get_connection(self.db_path)
        try:
            first = db.insert_event(
                conn, "email_replied", source="apollo", external_id="evt_1",
                data='{"contact_id": "c_1"}',
            )
            self.assertTrue(first["inserted"])
            dup = db.insert_event(
                conn, "email_replied", source="apollo", external_id="evt_1",
                data='{"contact_id": "c_1"}',
            )
            self.assertFalse(dup["inserted"])
            self.assertEqual(dup["id"], first["id"])
            events = db.recent_events(conn)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["event_type"], "email_replied")
            self.assertEqual(events[0]["source"], "apollo")
        finally:
            conn.close()

    def test_task_round_trip_via_libsql(self):
        db.init_db(self.db_path)
        conn = db.get_connection(self.db_path)
        try:
            task = db.create_task(conn, "prospecting", {"mode": "system_4"})
            self.assertEqual(task["module"], "prospecting")
            self.assertEqual(task["status"], "pending")
            updated = db.update_task_status(conn, task["id"], "completed")
            self.assertEqual(updated["status"], "completed")
            self.assertEqual(len(db.list_tasks(conn)), 1)
        finally:
            conn.close()


class TestDefaultStillSqlite(unittest.TestCase):
    def test_default_connection_is_sqlite3_with_row_factory(self):
        saved = {
            k: os.environ.get(k) for k in ("GGOS_USE_LIBSQL", "TURSO_DATABASE_URL")
        }
        os.environ.pop("GGOS_USE_LIBSQL", None)
        os.environ.pop("TURSO_DATABASE_URL", None)
        try:
            import sqlite3

            with tempfile.TemporaryDirectory() as d:
                conn = db.get_connection(Path(d) / "x.db")
                try:
                    self.assertIsInstance(conn, sqlite3.Connection)
                    self.assertIsNotNone(conn.row_factory)
                finally:
                    conn.close()
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_is_turso_reads_env(self):
        saved = os.environ.get("TURSO_DATABASE_URL")
        try:
            os.environ.pop("TURSO_DATABASE_URL", None)
            self.assertFalse(db.is_turso())
            os.environ["TURSO_DATABASE_URL"] = "libsql://example.turso.io"
            self.assertTrue(db.is_turso())
        finally:
            if saved is None:
                os.environ.pop("TURSO_DATABASE_URL", None)
            else:
                os.environ["TURSO_DATABASE_URL"] = saved


if __name__ == "__main__":
    unittest.main()

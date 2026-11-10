"""Tests for the version handshake (ggos/versions.py + /v1/version).

The pasted bridge.py this replaces imported a swarm_v2 module that does
not exist and built a second Flask server. The fix wires the handshake
into the real FastAPI app: GET /v1/version serves the envelope, and
POST /swarm/trigger answers 426 to a declared client older than the
minimum instead of running it. No LLM, no network, no live store.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestSatisfies(unittest.TestCase):
    def test_spec_ranges(self):
        from ggos import versions

        self.assertTrue(versions.satisfies("0.1.0", ">=0.1.0"))
        self.assertTrue(versions.satisfies("0.1.5", ">=0.1.0 <0.2.0"))
        self.assertFalse(versions.satisfies("0.0.9", ">=0.1.0"))
        self.assertFalse(versions.satisfies("0.2.0", ">=0.1.0 <0.2.0"))
        self.assertTrue(versions.satisfies("0.1.0", "==0.1.0"))
        self.assertTrue(versions.satisfies("1.0", ">=0.1.0"))

    def test_client_too_old(self):
        from ggos import versions

        self.assertIsNone(versions.client_too_old(None))
        self.assertIsNone(versions.client_too_old("0.1.0"))
        self.assertIsNone(versions.client_too_old("0.2.0"))
        self.assertIsNotNone(versions.client_too_old("0.0.9"))


class TestVersionEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from ggos.app import app
        cls.client = TestClient(app)

    def test_version_envelope(self):
        from ggos import versions
        from ggos import database as db

        res = self.client.get("/v1/version")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["app_version"], versions.APP_VERSION)
        self.assertEqual(body["schema_version"], db.SCHEMA_VERSION)
        self.assertEqual(
            body["min_client_version"], versions.MIN_CLIENT_VERSION)
        self.assertEqual(body["components"], versions.COMPONENTS)

    def test_health_carries_app_version(self):
        from ggos import versions

        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])
        self.assertEqual(res.json()["app_version"], versions.APP_VERSION)

    def test_versions_json_matches_module(self):
        from ggos import versions

        with open(PROJECT_ROOT / "versions.json") as f:
            on_disk = json.load(f)
        self.assertEqual(on_disk, versions.version_envelope())


class TestTriggerHandshake(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from ggos.app import app
        self.client = TestClient(app)
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        from ggos import database as db
        db.init_db(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def _token(self):
        import ggos.app as app_mod
        return patch.object(app_mod.config, "API_TOKEN", "test-token")

    def _db(self):
        import ggos.app as app_mod
        return patch.object(app_mod.config, "DB_PATH", self.db_path)

    def test_old_client_gets_426(self):
        with self._token():
            res = self.client.post(
                "/swarm/trigger",
                json={"client_version": "0.0.9"},
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(res.status_code, 426)
        body = res.json()["detail"]
        self.assertEqual(body["error"], "client_too_old")
        self.assertIn("app_version", body)
        self.assertIn("min_client_version", body)

    def test_current_client_runs(self):
        with self._token(), self._db():
            res = self.client.post(
                "/swarm/trigger",
                json={"client_version": "0.1.0"},
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])

    def test_undeclared_client_still_runs(self):
        with self._token(), self._db():
            res = self.client.post(
                "/swarm/trigger",
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])


if __name__ == "__main__":
    unittest.main()

import os
import unittest

from ggos import notifier
from ggos.notifier import OutboundDisabledError


class TestGates(unittest.TestCase):
    def test_dispatch_disabled_by_default(self):
        os.environ.pop("GGOS_OUTBOUND_ENABLED", None)
        with self.assertRaises(OutboundDisabledError):
            notifier.dispatch_webhook("https://example.com/hook", {}, approved=True)

    def test_dispatch_requires_per_call_approval(self):
        os.environ["GGOS_OUTBOUND_ENABLED"] = "1"
        try:
            with self.assertRaises(OutboundDisabledError):
                notifier.dispatch_webhook("https://example.com/hook", {})
        finally:
            os.environ.pop("GGOS_OUTBOUND_ENABLED", None)

    def test_trigger_refuses_without_configured_token(self):
        from fastapi import HTTPException

        from ggos import app as appmod

        old = appmod.config.API_TOKEN
        appmod.config.API_TOKEN = ""
        try:
            with self.assertRaises(HTTPException) as ctx:
                appmod.require_token("Bearer anything")
            self.assertEqual(ctx.exception.status_code, 503)
        finally:
            appmod.config.API_TOKEN = old

    def test_trigger_rejects_wrong_token(self):
        from fastapi import HTTPException

        from ggos import app as appmod

        old = appmod.config.API_TOKEN
        appmod.config.API_TOKEN = "real-token"
        try:
            with self.assertRaises(HTTPException) as ctx:
                appmod.require_token("Bearer wrong-token")
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertTrue(appmod.require_token("Bearer real-token"))
        finally:
            appmod.config.API_TOKEN = old


if __name__ == "__main__":
    unittest.main()

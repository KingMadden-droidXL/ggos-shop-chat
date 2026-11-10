"""Read-only godmode endpoint logic for the GangsterGodOS gateway page.

The gateway page (gangstergodos.html) is a static front door: 36 agent
names, pay buttons, an unlock gate. It cannot talk to Shopify itself.
This module is the one wire between the unlocked page and the real
sweep in services/shopify_godmode.py.

Rules, same as the sweep itself:
  - Read-only. The change package in the report is always
    approved=False and applied=False. Nothing is pushed, sent, or spent.
  - The Shopify token comes only from the environment
    (SHOPIFY_ADMIN_TOKEN, fallback SHOPIFY_TOKEN) plus
    SHOPIFY_SHOP_DOMAIN. It is never read from chat, code, or a file.
  - When the token is not set, the answer is a plain
    status="token_not_set" state with no numbers at all, never a fake
    success and never invented counts.
"""
import os
from pathlib import Path

from services.shopify_godmode import godmode_sweep

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECEIPT = PROJECT_ROOT / "data" / "shopify-godmode-report.json"


def _token_configured():
    return bool(
        (os.getenv("SHOPIFY_ADMIN_TOKEN") or os.getenv("SHOPIFY_TOKEN"))
        and os.getenv("SHOPIFY_SHOP_DOMAIN")
    )


def run_godmode_report(client=None, out_path=None):
    """Run one read-only sweep and return a status envelope.

    client: a ShopifyClient (or a fake with the same read methods) for
        tests. When None, a live client is built from the environment.
    out_path: where to write the report receipt. For a live run it
        defaults to data/shopify-godmode-report.json (or
        GGOS_GODMODE_REPORT when set). Pass a path explicitly in tests,
        or leave it unset with a fake client to skip writing.
    """
    if client is None and not _token_configured():
        return {
            "status": "token_not_set",
            "report": None,
            "applied": False,
            "message": (
                "Shopify token not set in env. Set SHOPIFY_SHOP_DOMAIN and "
                "SHOPIFY_ADMIN_TOKEN in the server environment (never in "
                "chat, never in code), restart the API, and run the sweep again."
            ),
        }
    if out_path is None and client is None:
        out_path = str(os.getenv("GGOS_GODMODE_REPORT", str(DEFAULT_RECEIPT)))
    try:
        report = godmode_sweep(client=client, out_path=out_path)
    except RuntimeError as exc:
        # ShopifyClient raises RuntimeError when domain/token are missing.
        return {
            "status": "token_not_set",
            "report": None,
            "applied": False,
            "message": str(exc),
        }
    return {
        "status": "ok",
        "report": report,
        "applied": False,
        "message": (
            "Read-only sweep. Nothing was written to Shopify, nothing "
            "was sent, nothing was spent. The change package is a draft "
            "until the owner approves it in chat."
        ),
    }

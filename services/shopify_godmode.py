"""God mode, as far as god mode goes — and not one step past the gates.

One command reads the whole house, runs the 36-agent swarm over the
live snapshot, and hands back a change package that is ALWAYS
approved=False and applied=False. That is the ceiling. God mode here
means total sight, not total action: every product seen, every order
counted, every gap named, nothing pushed, nothing sent, nothing
spent. The push still happens in chat with Muse, after the owner
approves the exact changes, word for word.

    python -m services.shopify_godmode            # needs SHOPIFY_SHOP_DOMAIN + SHOPIFY_ADMIN_TOKEN
    python -m services.shopify_godmode --out data/shopify-godmode-report.json

The report is the receipt. If it is not in the report, it did not happen.
"""
import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ggos.agents import run_swarm  # noqa: E402
from integrations.shopify import ShopifyClient  # noqa: E402


def godmode_sweep(client=None, out_path=None):
    """Run the full read-only sweep. Returns the report dict.

    Reads only. The swarm's change package inside the report is
    always approved=False, applied=False.
    """
    client = client or ShopifyClient()
    shop = client.get_shop()
    products = client.list_all_products()
    orders = client.list_orders(limit=50)
    counts = {
        "products": client.get_product_count(),
        "orders": client.get_order_count(),
    }

    context = {
        "products": products,
        "orders": orders,
        "context_source": "shopify-admin-api-live",
        "shop": {"name": shop.get("name"), "domain": shop.get("domain")},
    }
    package = run_swarm(context)

    report = {
        "mode": "godmode-read-only",
        "shop": {"name": shop.get("name"), "domain": shop.get("domain")},
        "counts": counts,
        "products_seen": len(products),
        "orders_seen": len(orders),
        "change_package": package,
        "applied": False,
        "note": (
            "God mode ends here: sight, not action. Nothing was written "
            "to Shopify, nothing was sent, nothing was spent. The change "
            "package is a draft until the owner approves it in chat."
        ),
    }
    if out_path:
        Path(out_path).write_text(json.dumps(report, indent=2))
    return report


def _elegant_summary(report):
    pkg = report["change_package"]
    proposed = pkg.get("proposed_changes", []) if isinstance(pkg, dict) else []
    blocked = pkg.get("blocked", []) if isinstance(pkg, dict) else []
    lines = [
        "The house, in full. Velvet over concrete.",
        f"Shop: {report['shop']['name']} ({report['shop']['domain']})",
        f"Products on the books: {report['counts']['products']} "
        f"({report['products_seen']} seen). "
        f"Orders on the books: {report['counts']['orders']} "
        f"({report['orders_seen']} seen).",
        f"Swarm: {pkg.get('agents_run')} agents, "
        f"{len(proposed)} proposed changes, {len(blocked)} blocked. "
        f"Approved: {pkg.get('approved')}. Applied: {pkg.get('applied')}.",
        "Nothing pushed. Nothing sent. Nothing spent. "
        "The draft waits for your word.",
    ]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="GGOS Shopify godmode sweep (read-only)")
    parser.add_argument("--out", default=None, help="Write the report JSON here")
    args = parser.parse_args(argv)
    out = args.out or os.environ.get(
        "GGOS_GODMODE_REPORT",
        str(PROJECT_ROOT / "data" / "shopify-godmode-report.json"),
    )
    report = godmode_sweep(out_path=out)
    print(_elegant_summary(report))
    print(f"Receipt written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
